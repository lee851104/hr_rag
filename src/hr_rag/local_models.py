"""本機encoder獨立程序：可回收記憶體，也能真正中止逾時推論。"""

import multiprocessing
import os

from hr_rag.providers import ProviderError


class ProcessModel:
    def __init__(self, target, args=(), *, startup_timeout=180, request_timeout=180):
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=target, args=(child, *args), daemon=True)
        self.request_timeout = request_timeout
        self.process.start()
        child.close()
        try:
            if self._receive(startup_timeout) != {"ready": True}:
                raise ProviderError("unavailable")
        except Exception:
            self.close()
            raise

    def _receive(self, timeout):
        try:
            if not self.connection.poll(timeout):
                self.close()
                raise ProviderError("timeout")
            return self.connection.recv()
        except (EOFError, OSError):
            self.close()
            raise ProviderError("unavailable") from None

    def call(self, data):
        try:
            self.connection.send(data)
            response = self._receive(self.request_timeout)
        except (EOFError, OSError):
            self.close()
            raise ProviderError("unavailable") from None
        if "error" in response:
            raise ProviderError(response["error"])
        return response["result"]

    def close(self):
        self.connection.close()
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=3)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=3)


def encoder_worker(connection, role, path, threads):
    """只讀取已下載的固定模型，不允許推論時連網或遠端程式碼。"""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    try:
        import torch
        from sentence_transformers import CrossEncoder, SentenceTransformer

        torch.set_num_threads(threads)
        if role == "embedding":
            model = SentenceTransformer(
                path, device="cpu", local_files_only=True, trust_remote_code=False
            )
        else:
            model = CrossEncoder(
                path,
                device="cpu",
                max_length=512,
                local_files_only=True,
                trust_remote_code=False,
            )
        connection.send({"ready": True})
    except Exception:
        connection.send({"error": "unavailable"})
        return
    while True:
        try:
            request = connection.recv()
        except EOFError:
            return
        try:
            texts = request["texts"]
            if role == "embedding":
                lengths = [len(model.tokenizer.encode(text)) for text in texts]
                if max(lengths) > model.max_seq_length:
                    connection.send({"error": "budget"})
                    continue
                result = model.encode(
                    texts,
                    batch_size=2,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )
            else:
                pairs = [(request["query"], text) for text in texts]
                if any(len(model.tokenizer.encode(q, text)) > 512 for q, text in pairs):
                    connection.send({"error": "budget"})
                    continue
                result = model.predict(pairs, batch_size=2, show_progress_bar=False)
            connection.send({"result": result.tolist()})
        except Exception:
            connection.send({"error": "unavailable"})


class LocalEncoder(ProcessModel):
    def __init__(self, role, path, settings):
        if role not in ("embedding", "reranker"):
            raise ValueError("不支援的encoder角色")
        super().__init__(
            encoder_worker,
            (role, str(path), settings.threads),
            startup_timeout=settings.timeout_seconds,
            request_timeout=settings.timeout_seconds,
        )

    def embed(self, texts):
        return self.call({"texts": texts})

    def rerank(self, query, texts):
        return self.call({"query": query, "texts": texts})
