import threading
import time
import uuid
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from aos.config import get_settings
from aos.memory.embeddings import Embedder, get_embedder
from aos.schemas.memory import MemoryItem, StoredMemory

_client = None
_client_lock = threading.Lock()


def chroma_client() -> Any:
    global _client
    with _client_lock:
        if _client is None:
            settings = get_settings()
            chroma_settings = ChromaSettings(anonymized_telemetry=False)
            if settings.storage_mode == "memory":
                _client = chromadb.EphemeralClient(settings=chroma_settings)
            else:
                _client = chromadb.HttpClient(
                    host=settings.chroma_host, port=settings.chroma_port, settings=chroma_settings
                )
        return _client


def reset_chroma() -> None:
    global _client
    with _client_lock:
        _client = None


class LongTermMemory:
    """Semantic memory per user, stored in ChromaDB with our own embeddings."""

    def __init__(self, client: Any = None, embedder: Embedder | None = None) -> None:
        settings = get_settings()
        self._embedder = embedder or get_embedder()
        self._collection = (client or chroma_client()).get_or_create_collection(
            settings.chroma_collection,
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )
        self._settings = settings

    def add(
        self,
        user_id: str,
        item: MemoryItem,
        source_run_id: str | None = None,
        *,
        dedupe: bool = True,
    ) -> tuple[StoredMemory, bool]:
        """Store an item, or strengthen a near-identical one. Returns (memory, merged)."""
        [vector] = self._embedder.embed([item.text])
        match = self._nearest(user_id, vector, item.kind) if dedupe else None
        if match and match.similarity >= self._settings.memory_dedupe_similarity:
            importance = min(1.0, max(match.importance, item.importance) + 0.05)
            self.update(match.id, importance=importance, last_accessed_at=time.time())
            return match.model_copy(update={"importance": importance}), True

        now = time.time()
        memory = StoredMemory(
            **item.model_dump(),
            id=uuid.uuid4().hex,
            user_id=user_id,
            created_at=now,
            last_accessed_at=now,
            source_run_id=source_run_id,
        )
        self._collection.add(
            ids=[memory.id],
            embeddings=[vector],
            documents=[memory.text],
            metadatas=[_metadata(memory)],
        )
        return memory, False

    @property
    def min_similarity(self) -> float:
        configured = self._settings.memory_min_similarity
        return configured if configured is not None else self._embedder.min_similarity

    @property
    def consolidate_similarity(self) -> float:
        configured = self._settings.memory_consolidate_similarity
        return configured if configured is not None else self._embedder.consolidate_similarity

    def search(
        self,
        user_id: str,
        query: str,
        *,
        kinds: list[str] | None = None,
        k: int = 4,
        min_similarity: float = 0.0,
        include_consolidated: bool = False,
    ) -> list[StoredMemory]:
        [vector] = self._embedder.embed([query])
        return self._query(user_id, vector, kinds, k, min_similarity, include_consolidated)

    def get(self, memory_id: str) -> StoredMemory | None:
        found = self._collection.get(ids=[memory_id], include=["documents", "metadatas"])
        memories = _rows(found)
        return memories[0] if memories else None

    def list_user(self, user_id: str, kind: str | None = None) -> list[StoredMemory]:
        found = self._collection.get(
            where=_where(user_id, [kind] if kind else None, include_consolidated=True),
            include=["documents", "metadatas"],
        )
        return _rows(found)

    def vectors(self, memory_ids: list[str]) -> dict[str, list[float]]:
        if not memory_ids:
            return {}
        found = self._collection.get(ids=memory_ids, include=["embeddings"])
        return {mid: list(vec) for mid, vec in zip(found["ids"], found["embeddings"], strict=True)}

    def user_ids(self) -> list[str]:
        found = self._collection.get(include=["metadatas"])
        return sorted({meta["user_id"] for meta in found["metadatas"] or []})

    def update(self, memory_id: str, **fields: Any) -> None:
        current = self.get(memory_id)
        if current is None:
            return
        updated = current.model_copy(update=fields)
        self._collection.update(ids=[memory_id], metadatas=[_metadata(updated)])

    def touch(self, memory_ids: list[str]) -> None:
        now = time.time()
        for memory_id in memory_ids:
            current = self.get(memory_id)
            if current is not None:
                self.update(memory_id, access_count=current.access_count + 1, last_accessed_at=now)

    def delete(self, memory_ids: list[str]) -> None:
        if memory_ids:
            self._collection.delete(ids=memory_ids)

    def delete_user(self, user_id: str) -> int:
        ids = [m.id for m in self.list_user(user_id)]
        self.delete(ids)
        return len(ids)

    def _nearest(self, user_id: str, vector: list[float], kind: str) -> StoredMemory | None:
        found = self._query(user_id, vector, [kind], 1, 0.0, include_consolidated=False)
        return found[0] if found else None

    def _query(
        self,
        user_id: str,
        vector: list[float],
        kinds: list[str] | None,
        k: int,
        min_similarity: float,
        include_consolidated: bool,
    ) -> list[StoredMemory]:
        where = _where(user_id, kinds, include_consolidated)
        if not self._collection.get(where=where, limit=1)["ids"]:
            return []
        found = self._collection.query(
            query_embeddings=[vector],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        memories = []
        for memory_id, text, meta, distance in zip(
            found["ids"][0],
            found["documents"][0],
            found["metadatas"][0],
            found["distances"][0],
            strict=True,
        ):
            similarity = 1.0 - float(distance)
            if similarity >= min_similarity:
                memories.append(_memory(memory_id, text, meta, similarity))
        return memories


def _where(user_id: str, kinds: list[str] | None, include_consolidated: bool) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = [{"user_id": user_id}]
    if kinds:
        clauses.append({"kind": {"$in": kinds}})
    if not include_consolidated:
        clauses.append({"consolidated_into": ""})
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _metadata(memory: StoredMemory) -> dict[str, Any]:
    # Chroma metadata accepts only scalars, so lists and None become strings.
    return {
        "user_id": memory.user_id,
        "kind": memory.kind,
        "outcome": memory.outcome,
        "importance": memory.importance,
        "tags": ",".join(memory.tags),
        "access_count": memory.access_count,
        "created_at": memory.created_at,
        "last_accessed_at": memory.last_accessed_at,
        "source_run_id": memory.source_run_id or "",
        "consolidated_into": memory.consolidated_into or "",
    }


def _memory(
    memory_id: str, text: str, meta: dict[str, Any], similarity: float | None = None
) -> StoredMemory:
    return StoredMemory(
        id=memory_id,
        text=text,
        user_id=meta["user_id"],
        kind=meta["kind"],
        outcome=meta["outcome"],
        importance=meta["importance"],
        tags=[tag for tag in meta["tags"].split(",") if tag],
        access_count=meta["access_count"],
        created_at=meta["created_at"],
        last_accessed_at=meta["last_accessed_at"],
        source_run_id=meta["source_run_id"] or None,
        consolidated_into=meta["consolidated_into"] or None,
        similarity=similarity,
    )


def _rows(found: dict[str, Any]) -> list[StoredMemory]:
    return [
        _memory(memory_id, text, meta)
        for memory_id, text, meta in zip(
            found["ids"], found["documents"], found["metadatas"], strict=True
        )
    ]
