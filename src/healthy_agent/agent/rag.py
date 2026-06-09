from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class Document:
    content: str
    metadata: dict = field(default_factory=dict)
    doc_id: str = ""

    def __post_init__(self):
        if not self.doc_id:
            self.doc_id = hashlib.md5(self.content.encode()).hexdigest()[:12]


class SimpleVectorStore:
    """In-memory keyword-based retrieval. No external dependencies.
    For production, swap with chromadb/pinecone/weaviate."""

    def __init__(self):
        self._docs: dict[str, Document] = {}

    def add(self, doc: Document) -> None:
        self._docs[doc.doc_id] = doc

    def add_text(self, text: str, metadata: dict | None = None) -> str:
        doc = Document(content=text, metadata=metadata or {})
        self._docs[doc.doc_id] = doc
        return doc.doc_id

    def search(self, query: str, top_k: int = 3) -> list[Document]:
        query_words = set(query.lower().split())
        scored = []
        for doc in self._docs.values():
            doc_words = set(doc.content.lower().split())
            overlap = len(query_words & doc_words)
            if overlap > 0:
                scored.append((overlap, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]

    def delete(self, doc_id: str) -> None:
        self._docs.pop(doc_id, None)

    def clear(self) -> None:
        self._docs.clear()

    @property
    def size(self) -> int:
        return len(self._docs)


class RAGMixin:
    """Adds retrieval-augmented generation to AgentLoop."""

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
