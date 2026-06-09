from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Document:
    content: str
    metadata: dict = field(default_factory=dict)
    doc_id: str = ""

    def __post_init__(self):
        if not self.doc_id:
            self.doc_id = hashlib.md5(self.content.encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {"content": self.content, "metadata": self.metadata, "doc_id": self.doc_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Document:
        return cls(content=data["content"], metadata=data.get("metadata", {}), doc_id=data.get("doc_id", ""))


# ---------------------------------------------------------------------------
# Text chunking utilities
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    separators: list[str] | None = None,
) -> list[str]:
    """Split text into overlapping chunks using hierarchical separators.

    Tries to split on paragraph boundaries first, then sentences, then words.
    """
    if len(text) <= chunk_size:
        return [text]

    separators = separators or ["\n\n", "\n", ". ", " "]
    return _recursive_split(text, chunk_size, chunk_overlap, separators)


def _recursive_split(text: str, chunk_size: int, overlap: int, separators: list[str]) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    separator = separators[0]
    remaining_separators = separators[1:]

    segments = text.split(separator)
    chunks: list[str] = []
    current_chunk = ""

    for segment in segments:
        candidate = (current_chunk + separator + segment) if current_chunk else segment
        if len(candidate) <= chunk_size:
            current_chunk = candidate
        else:
            if current_chunk:
                chunks.append(current_chunk)
            if len(segment) > chunk_size and remaining_separators:
                sub_chunks = _recursive_split(segment, chunk_size, overlap, remaining_separators)
                chunks.extend(sub_chunks)
                current_chunk = ""
            else:
                current_chunk = segment

    if current_chunk:
        chunks.append(current_chunk)

    if overlap > 0 and len(chunks) > 1:
        chunks = _apply_overlap(chunks, overlap)

    return chunks


def _apply_overlap(chunks: list[str], overlap: int) -> list[str]:
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-overlap:]
        result.append(prev_tail + chunks[i])
    return result


# ---------------------------------------------------------------------------
# TF-IDF vector scoring
# ---------------------------------------------------------------------------

_TOKENIZE_RE = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    return _TOKENIZE_RE.findall(text.lower())


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    counts = Counter(tokens)
    total = len(tokens)
    if total == 0:
        return {}
    return {word: count / total for word, count in counts.items()}


def _compute_idf(corpus_tfs: list[dict[str, float]]) -> dict[str, float]:
    num_docs = len(corpus_tfs)
    if num_docs == 0:
        return {}
    doc_freq: Counter[str] = Counter()
    for tf in corpus_tfs:
        doc_freq.update(tf.keys())
    return {word: math.log((num_docs + 1) / (df + 1)) + 1.0 for word, df in doc_freq.items()}


def _tfidf_vector(tf: dict[str, float], idf: dict[str, float]) -> dict[str, float]:
    return {word: tf_val * idf.get(word, 1.0) for word, tf_val in tf.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    common_keys = set(vec_a) & set(vec_b)
    if not common_keys:
        return 0.0
    dot = sum(vec_a[k] * vec_b[k] for k in common_keys)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------

class SimpleVectorStore:
    """TF-IDF based vector store with optional JSON persistence.

    Uses TF-IDF cosine similarity for semantic-aware retrieval.
    No external dependencies required. For production, swap with
    chromadb/pinecone/weaviate.
    """

    def __init__(self, persist_path: str | Path | None = None):
        self._docs: dict[str, Document] = {}
        self._doc_tfs: dict[str, dict[str, float]] = {}
        self._idf: dict[str, float] = {}
        self._idf_dirty = True
        self._persist_path = Path(persist_path).expanduser() if persist_path else None
        if self._persist_path:
            self._load()

    def add(self, doc: Document) -> None:
        self._docs[doc.doc_id] = doc
        tokens = _tokenize(doc.content)
        self._doc_tfs[doc.doc_id] = _compute_tf(tokens)
        self._idf_dirty = True
        self._auto_save()

    def add_text(self, text: str, metadata: dict | None = None) -> str:
        doc = Document(content=text, metadata=metadata or {})
        self.add(doc)
        return doc.doc_id

    def search(self, query: str, top_k: int = 3) -> list[Document]:
        if not self._docs:
            return []

        self._rebuild_idf()

        query_tokens = _tokenize(query)
        query_tf = _compute_tf(query_tokens)
        query_vec = _tfidf_vector(query_tf, self._idf)

        scored: list[tuple[float, Document]] = []
        for doc_id, doc in self._docs.items():
            doc_vec = _tfidf_vector(self._doc_tfs[doc_id], self._idf)
            score = _cosine_similarity(query_vec, doc_vec)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]

    def delete(self, doc_id: str) -> None:
        self._docs.pop(doc_id, None)
        self._doc_tfs.pop(doc_id, None)
        self._idf_dirty = True
        self._auto_save()

    def clear(self) -> None:
        self._docs.clear()
        self._doc_tfs.clear()
        self._idf.clear()
        self._idf_dirty = True
        self._auto_save()

    @property
    def size(self) -> int:
        return len(self._docs)

    def _rebuild_idf(self) -> None:
        if not self._idf_dirty:
            return
        self._idf = _compute_idf(list(self._doc_tfs.values()))
        self._idf_dirty = False

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path).expanduser() if path else self._persist_path
        if not target:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        data = [doc.to_dict() for doc in self._docs.values()]
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _load(self) -> None:
        if not self._persist_path or not self._persist_path.exists():
            return
        raw = json.loads(self._persist_path.read_text())
        for item in raw:
            doc = Document.from_dict(item)
            self._docs[doc.doc_id] = doc
            self._doc_tfs[doc.doc_id] = _compute_tf(_tokenize(doc.content))
        self._idf_dirty = True

    def _auto_save(self) -> None:
        if self._persist_path:
            self.save()


class RAGMixin:
    """Adds retrieval-augmented generation to Executor."""

    def __init__(self, store: SimpleVectorStore | None = None):
        self.store = store or SimpleVectorStore()

    def retrieve_context(self, query: str, top_k: int = 3) -> str:
        docs = self.store.search(query, top_k=top_k)
        if not docs:
            return ""
        context_parts = [f"[{i+1}] {doc.content}" for i, doc in enumerate(docs)]
        return "Relevant information:\n" + "\n".join(context_parts)

    def ingest(self, text: str, metadata: dict | None = None) -> str:
        return self.store.add_text(text, metadata)

    def ingest_many(self, texts: list[str]) -> int:
        for t in texts:
            self.store.add_text(t)
        return len(texts)

    def ingest_chunked(
        self,
        text: str,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        metadata: dict | None = None,
    ) -> list[str]:
        """Ingest a long text by splitting into overlapping chunks."""
        chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        doc_ids: list[str] = []
        base_meta = metadata or {}
        for idx, chunk in enumerate(chunks):
            chunk_meta = {**base_meta, "_chunk_index": idx, "_total_chunks": len(chunks)}
            doc_id = self.store.add_text(chunk, chunk_meta)
            doc_ids.append(doc_id)
        return doc_ids
