"""明確執行才下載6份官方全文及4份沿革；不讀任何憑證。"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "data/raw/official-2026-10-18"
SOURCES = {
    "O01": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=N0030001",
    "O02": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=N0030002",
    "O03": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=N0030006",
    "O04": "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=N0030014",
    "O05": "https://www.mol.gov.tw/1607/28690/2282/2284/2292/81186/post",
    "O06": "https://www.mol.gov.tw/1607/28690/2282/2284/2292/81173/post",
}


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    metadata_path = DESTINATION / "sources.json"
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.exists()
        else {}
    )
    urls = dict(SOURCES)
    urls.update(
        {
            f"{key}-history": url.replace("LawAll.aspx", "LawHistory.aspx")
            for key, url in SOURCES.items()
            if key in {"O01", "O02", "O03", "O04"}
        }
    )
    with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
        for key, url in urls.items():
            path = DESTINATION / f"{key}.html"
            if path.exists():
                if (
                    key not in metadata
                    or hashlib.sha256(path.read_bytes()).hexdigest()
                    != metadata[key]["sha256"]
                ):
                    raise ValueError("existing_snapshot_requires_review")
                print(key, "preserved", flush=True)
                continue
            response = client.get(url)
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("unexpected_content_type")
            path.write_bytes(response.content)
            metadata[key] = {
                "source_url": url,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "bytes": len(response.content),
            }
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(key, len(response.content), "saved", flush=True)


if __name__ == "__main__":
    main()
