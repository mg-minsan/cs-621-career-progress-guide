"""Deterministic, dependency-light text embedding model.

Phase 3 (semantic retrieval) needs a model that converts a query and every
document into vectors that can be compared with cosine similarity. The model is
chosen and pinned here so that query and document embeddings are always built
by the *same* model and configuration; an index recorded under a different
model/configuration is rejected rather than mixed.

Chosen model: ``hash-ngram-v1``, a feature-hashed character-ngram embedder.

Why this model
--------------

* Deterministic and offline. ``zlib.crc32`` is stable across processes and
  platforms (unlike Python's built-in ``hash``, which is randomised by
  ``PYTHONHASHSEED``), so the same text always produces the same vector and an
  index can be rebuilt byte-for-byte.
* No token limit. Features are hashed into a fixed vector, so long documents
  are not truncated; the "bounded representation" guarantee lives in the text
  construction step (``core.search_documents`` keeps roles to descriptions,
  tasks and skill titles and courses to titles, descriptions and outcomes),
  not in a silent truncation inside the model.
* Subword coverage. Whole tokens plus character 3/4/5-grams let related forms
  ("programming" vs "programmer", "analytics" vs "analytical") share features,
  which is a modest, well-understood step beyond exact keyword matching.
* No training, download or heavyweight dependency: NumPy is the only runtime
  requirement, matching the plan's "local vector files and NumPy ranking"
  starting point.

Limitations: this is not a trained neural language model. It captures lexical
and subword similarity, not deep paraphrase; the hybrid retriever therefore
keeps BM25 keyword retrieval fused alongside it rather than replacing it.
Scores are relevance signals only, never readiness or suitability.
"""
from __future__ import annotations

import re
import zlib

import numpy as np


MODEL_ID = "hash-ngram-v1"

# Every field here participates in the model identity. Changing any of these
# changes the vector space and invalidates existing indexes.
MODEL_CONFIG = {
    "dim": 1024,                # power of two; bucket index is value & (dim-1)
    "char_ngrams": [3, 4, 5],   # subword feature sizes, plus the whole token
    "token_pattern": r"[a-z0-9]+",
    "hash": "zlib.crc32",       # deterministic across processes
    "weighting": "term_frequency",  # sign-folded TF, then L2 normalised
    "normalize": "l2",
}


_TOKEN = re.compile(MODEL_CONFIG["token_pattern"])
_DIM = int(MODEL_CONFIG["dim"])
if _DIM & (_DIM - 1):
    raise ValueError("MODEL_CONFIG dim must be a power of two")
_DIM_MASK = _DIM - 1
_NGRAMS = tuple(MODEL_CONFIG["char_ngrams"])


def _features(token: str) -> list[str]:
    """The whole token plus every character n-gram of the configured sizes."""
    features = [token]
    for n in _NGRAMS:
        if len(token) >= n:
            features.extend(token[i:i + n] for i in range(len(token) - n + 1))
    return features


def _signed_bucket(feature: str) -> tuple[int, int]:
    """Map a feature to a bucket index and a sign (the hashing trick)."""
    value = zlib.crc32(feature.encode("utf-8"))
    return value & _DIM_MASK, 1 if (value >> 30) & 1 else -1


def embed_text(text: str) -> np.ndarray:
    """Embed one text string into an L2-normalised float32 vector.

    Empty or featureless text yields a zero vector; callers should treat a zero
    vector as "nothing to compare" rather than a meaningful embedding.
    """
    vector = np.zeros(_DIM, dtype=np.float32)
    if not text:
        return vector
    for token in _TOKEN.findall(text.lower()):
        for feature in _features(token):
            bucket, sign = _signed_bucket(feature)
            vector[bucket] += sign
    norm = float(np.linalg.norm(vector))
    if norm:
        vector /= norm
    return vector


def encode_texts(texts) -> np.ndarray:
    """Embed an iterable of strings into an (n, dim) float32 matrix."""
    return np.stack([embed_text(text) for text in texts]).astype(np.float32)


def cosine_similarity(query_vector: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Dot-product similarity against L2-normalised document vectors.

    Both the query and the document matrix must come from ``encode_texts`` /
    ``embed_text`` so the vectors are normalised; the result is cosine
    similarity in [0, 1] for non-negative feature accumulations.
    """
    return matrix @ query_vector


def model_signature() -> dict:
    """The identity of the current model, serialised into every index."""
    return {"model_id": MODEL_ID, "model_config": MODEL_CONFIG}


def is_compatible_model(signature: dict) -> bool:
    """True when a stored signature matches the model this process embeds with."""
    return (signature.get("model_id") == MODEL_ID
            and signature.get("model_config") == MODEL_CONFIG)
