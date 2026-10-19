"""本機示範帳號與SQLite session；每次驗證重讀伺服器角色。"""

import argparse
import getpass
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from hr_rag.contracts import Principal
from hr_rag.settings import PROJECT_ROOT

ROLES = ("employee", "manager", "hr")
SESSION_SECONDS = 8 * 60 * 60


class AuthenticationError(Exception):
    def __init__(self):
        super().__init__("authentication_required")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    return "scrypt$16384$8$1$" + salt.hex() + "$" + key.hex()


def password_matches(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or len(password) > 256:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", "16384", "8", "1"):
            return False
        key = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt), n=16384, r=8, p=1
        )
        return hmac.compare_digest(key.hex(), expected)
    except ValueError:
        return False


class AuthStore:
    def __init__(self, path: Path | None = None):
        # HR_RAG_AUTH_PATH只供本機隔離示範；不經HTTP設定。
        self.path = Path(
            path
            or os.environ.get("HR_RAG_AUTH_PATH")
            or PROJECT_ROOT / ".runtime/auth.sqlite3"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('employee','manager','hr')),
                    password_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    csrf_hash TEXT NOT NULL, expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS challenges (
                    token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL
                );
            """)
            for role in ROLES:
                if not db.execute(
                    "SELECT 1 FROM users WHERE user_id=?", (role,)
                ).fetchone():
                    # 初始停用，隨機值不保存；使用者本機設定密碼後才啟用。
                    db.execute(
                        "INSERT INTO users VALUES (?,?,?,0)",
                        (role, role, password_hash(secrets.token_urlsafe(32))),
                    )
        self._dummy_hash = password_hash(secrets.token_urlsafe(32))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def set_password(self, user_id: str, password: str):
        """僅受信任本機管理入口；不是HTTP API。"""
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise ValueError("password_length_12_to_256_required")
        encoded = password_hash(password)
        with self.connect() as db:
            if (
                db.execute(
                    "UPDATE users SET password_hash=?,enabled=1 WHERE user_id=?",
                    (encoded, user_id),
                ).rowcount
                != 1
            ):
                raise ValueError("unknown_demo_account")
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def set_role(self, user_id: str, role: str):
        """受信任本機管理；請求無法呼叫或傳入角色。"""
        if role not in ROLES:
            raise ValueError("invalid_role")
        with self.connect() as db:
            if (
                db.execute(
                    "UPDATE users SET role=? WHERE user_id=?", (role, user_id)
                ).rowcount
                != 1
            ):
                raise ValueError("unknown_demo_account")

    def login(self, user_id: str, password: str) -> tuple[str, str]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM users WHERE user_id=?", (user_id,)
            ).fetchone()
            valid = password_matches(
                password, row["password_hash"] if row else self._dummy_hash
            )
            if not valid or row is None or not row["enabled"]:
                raise AuthenticationError()
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (time.time(),))
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?)",
                (digest(token), user_id, digest(csrf), time.time() + SESSION_SECONDS),
            )
        return token, csrf

    def authenticate(self, session_id: str) -> Principal:
        if not session_id or len(session_id) > 128:
            raise AuthenticationError()
        with self.connect() as db:
            row = db.execute(
                "SELECT u.user_id,u.role FROM sessions s JOIN users u USING(user_id) "
                "WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1",
                (digest(session_id), time.time()),
            ).fetchone()
        if row is None:
            raise AuthenticationError()
        return Principal(user_id=row["user_id"], role=row["role"])

    def valid_csrf(self, session_id: str, csrf: str) -> bool:
        if not csrf or len(csrf) > 128:
            return False
        with self.connect() as db:
            row = db.execute(
                "SELECT csrf_hash FROM sessions WHERE token_hash=? AND expires_at>?",
                (digest(session_id), time.time()),
            ).fetchone()
        return bool(row and hmac.compare_digest(row["csrf_hash"], digest(csrf)))

    def logout(self, session_id: str):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(session_id),))

    def challenge(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM challenges WHERE expires_at<=?", (time.time(),))
            db.execute(
                "INSERT INTO challenges VALUES (?,?)",
                (digest(token), time.time() + 600),
            )
        return token

    def consume_challenge(self, cookie: str, form: str) -> bool:
        if (
            not cookie
            or len(cookie) > 128
            or len(form) > 128
            or not hmac.compare_digest(cookie.encode("utf-8"), form.encode("utf-8"))
        ):
            return False
        with self.connect() as db:
            return (
                db.execute(
                    "DELETE FROM challenges WHERE token_hash=? AND expires_at>?",
                    (digest(cookie), time.time()),
                ).rowcount
                == 1
            )


def authenticate(session_id: str) -> Principal:
    return AuthStore().authenticate(session_id)


def main():
    parser = argparse.ArgumentParser(
        description="本機設定示範帳號密碼；不接受命令列明文密碼"
    )
    parser.add_argument("command", choices=["init", "set-password"])
    parser.add_argument("--user", choices=ROLES)
    args = parser.parse_args()
    if args.command == "set-password" and args.user is None:
        parser.error("set-password 需要 --user")
    store = AuthStore()
    users = ROLES if args.command == "init" else (args.user,)
    for user in users:
        first = getpass.getpass(f"{user} 新密碼（12–256字元）：")
        second = getpass.getpass("再次輸入：")
        if not hmac.compare_digest(first.encode(), second.encode()):
            raise SystemExit("密碼不同；未變更此帳號。")
        try:
            store.set_password(user, first)
        except ValueError:
            raise SystemExit("密碼長度需12–256字元；未變更此帳號。") from None
        print(f"{user} 已設定；舊session已失效。")


if __name__ == "__main__":
    main()
