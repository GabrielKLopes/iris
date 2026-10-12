from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Protocol

import numpy as np

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
DEFAULT_DIMENSIONS = 768


class Embedder(Protocol):
    dimensions: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class FastEmbedder:
    def __init__(self, cache_dir: Path, model: str = DEFAULT_MODEL, dimensions: int = DEFAULT_DIMENSIONS):
        self.cache_dir = cache_dir
        self.model_name = model
        self.dimensions = dimensions
        self._model = None
        self._failed: Exception | None = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._failed is not None:
                raise RuntimeError(f"Embedding model unavailable: {self._failed}")
            if self._model is None:
                from fastembed import TextEmbedding

                self.cache_dir.mkdir(parents=True, exist_ok=True)
                logging.info("Loading embedding model %s", self.model_name)
                try:
                    self._model = TextEmbedding(self.model_name, cache_dir=str(self.cache_dir))
                except Exception as exc:
                    self._failed = exc
                    raise
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.array(list(self._load().embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1, norms)
