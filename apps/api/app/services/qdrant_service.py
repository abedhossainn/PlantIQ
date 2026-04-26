"""
Qdrant Client Service - Vector database operations for RAG.

Handles document chunk storage, retrieval, and similarity search.
"""
import logging
from typing import List, Optional, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from ..core.config import settings
from ..models.chat import RAGContext

logger = logging.getLogger(__name__)


class QdrantService:
    """Service for interacting with Qdrant vector database.
    
    Core Operations:
    - Storage and retrieval of document chunks as embedding vectors
    - Similarity search with multi-layered filtering (workspace, document type, shared access)
    - Chunk lifecycle management (upsert on publish, delete on document removal)
    
    Design Patterns:
    - Singleton client: one Qdrant client instance reused for all operations
    - Payload architecture: each vector's payload contains metadata (doc_id, page, workspace, doc_type)
      enabling complex filtering without full collection scans
    - Scope-aware search: filters applied at query time before similarity computation
    
    Distance Metric:
    - Uses cosine similarity (values 0–1) for embedding comparisons
    - Threshold tuning in ChatService applies relaxed strategy if initial results sparse
    """
    
    # Singleton client instance (created on first use, reused for all connections)
    _client: Optional[QdrantClient] = None
    
    @classmethod
    def get_client(cls) -> QdrantClient:
        """Get or create Qdrant client singleton."""
        if cls._client is None:
            cls._client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                timeout=settings.QDRANT_TIMEOUT,
            )
            logger.info("Connected to Qdrant at %s:%s", settings.QDRANT_HOST, settings.QDRANT_PORT)
        return cls._client
    
    @classmethod
    async def ensure_collection(cls) -> bool:
        """Ensure collection exists, create if not."""
        client = cls.get_client()
        
        try:
            collections = client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if settings.QDRANT_COLLECTION not in collection_names:
                logger.info("Creating collection %s", settings.QDRANT_COLLECTION)
                client.create_collection(
                    collection_name=settings.QDRANT_COLLECTION,
                    vectors_config=models.VectorParams(
                        size=settings.EMBEDDING_DIM,
                        distance=models.Distance.COSINE,
                    ),
                )
            return True
        except Exception as exc:
            logger.error("Failed to ensure collection: %s", exc)
            return False
    
    @classmethod
    def _resolve_search_params(
        cls,
        top_k: Optional[int],
        score_threshold: Optional[float],
    ) -> tuple[int, float]:
        resolved_top_k = top_k if top_k is not None else settings.RAG_TOP_K
        resolved_score_threshold = (
            score_threshold if score_threshold is not None else settings.RAG_SCORE_THRESHOLD
        )
        return resolved_top_k, resolved_score_threshold

    @classmethod
    def _clean_values(cls, values: Optional[List[str]]) -> List[str]:
        return [value.strip() for value in (values or []) if value and value.strip()]

    @classmethod
    def _workspace_aliases(cls, value: str) -> List[str]:
        trimmed = value.strip()
        if not trimmed:
            return []
        variants = {
            trimmed,
            trimmed.lower(),
            trimmed.upper(),
            trimmed.title(),
        }
        return [variant for variant in variants if variant]

    @classmethod
    def _build_filter_conditions(
        cls,
        document_filter: Optional[List[str]],
        system_filter: Optional[List[str]],
        document_type_filter: Optional[List[str]],
    ) -> list[models.FieldCondition]:
        filter_conditions: list[models.FieldCondition] = []

        if document_filter:
            filter_conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=document_filter),
                )
            )
        if system_filter:
            filter_conditions.append(
                models.FieldCondition(
                    key="system",
                    match=models.MatchAny(any=system_filter),
                )
            )

        normalized_document_types = cls._clean_values(document_type_filter)
        if normalized_document_types:
            filter_conditions.append(
                models.FieldCondition(
                    key="document_type",
                    match=models.MatchAny(any=normalized_document_types),
                )
            )

        return filter_conditions

    @classmethod
    def _build_workspace_conditions(
        cls,
        workspace_filter: Optional[str],
        include_shared_documents: bool,
    ) -> list[models.FieldCondition]:
        workspace_conditions: list[models.FieldCondition] = []
        if not workspace_filter or not workspace_filter.strip():
            return workspace_conditions

        workspace_aliases = cls._workspace_aliases(workspace_filter)
        if workspace_aliases:
            workspace_conditions.extend(
                [
                    models.FieldCondition(
                        key="workspace",
                        match=models.MatchAny(any=workspace_aliases),
                    ),
                    models.FieldCondition(
                        key="system",
                        match=models.MatchAny(any=workspace_aliases),
                    ),
                ]
            )

        if include_shared_documents:
            workspace_conditions.extend(
                [
                    models.FieldCondition(
                        key="is_shared",
                        match=models.MatchValue(value=True),
                    ),
                    models.FieldCondition(
                        key="workspace",
                        match=models.MatchAny(any=["shared", "global", "cross-functional"]),
                    ),
                ]
            )

        return workspace_conditions

    @classmethod
    def _build_query_filter(
        cls,
        filter_conditions: list[models.FieldCondition],
        workspace_conditions: list[models.FieldCondition],
    ) -> Optional[models.Filter]:
        if not filter_conditions and not workspace_conditions:
            return None
        return models.Filter(
            must=filter_conditions or None,
            should=workspace_conditions or None,
        )

    @classmethod
    def _to_rag_contexts(cls, points: list[Any]) -> List[RAGContext]:
        contexts: list[RAGContext] = []
        for result in points:
            payload = result.payload
            contexts.append(
                RAGContext(
                    chunk_id=str(result.id),
                    content=payload.get("content", ""),
                    document_id=payload.get("document_id"),
                    document_title=payload.get("document_title", "Unknown"),
                    metadata=payload,
                    score=result.score,
                )
            )
        return contexts

    @classmethod
    async def search_similar(
        cls,
        query_vector: List[float],
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        document_filter: Optional[List[str]] = None,
        system_filter: Optional[List[str]] = None,
        document_type_filter: Optional[List[str]] = None,
        workspace_filter: Optional[str] = None,
        include_shared_documents: bool = True,
    ) -> List[RAGContext]:
        """
        Search for similar document chunks.
        
        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return
            score_threshold: Minimum similarity score
            document_filter: Filter by document IDs
            system_filter: Filter by system types
            document_type_filter: Filter by document types
            workspace_filter: Default workspace scope (usually system/area)
            include_shared_documents: Whether to include globally shared docs
            
        Returns:
            List of retrieved contexts with metadata
        """
        client = cls.get_client()
        top_k, score_threshold = cls._resolve_search_params(top_k, score_threshold)

        filter_conditions = cls._build_filter_conditions(
            document_filter=document_filter,
            system_filter=system_filter,
            document_type_filter=document_type_filter,
        )
        workspace_conditions = cls._build_workspace_conditions(
            workspace_filter=workspace_filter,
            include_shared_documents=include_shared_documents,
        )
        query_filter = cls._build_query_filter(filter_conditions, workspace_conditions)
        
        try:
            # Perform vector search (qdrant-client >= 1.10 uses query_points)
            response = client.query_points(
                collection_name=settings.QDRANT_COLLECTION,
                query=query_vector,
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=query_filter,
                with_payload=True,
            )

            contexts = cls._to_rag_contexts(response.points)
            
            logger.info("Found %s similar chunks", len(contexts))
            return contexts
            
        except UnexpectedResponse as exc:
            logger.error("Qdrant search failed: %s", exc)
            return []
        except Exception as exc:
            logger.error("Unexpected error during search: %s", exc)
            return []
    
    @classmethod
    async def upsert_chunks(
        cls,
        chunks: List[Dict[str, Any]],
    ) -> bool:
        """
        Upsert document chunks to collection.
        
        Args:
            chunks: List of chunks with id, vector, and payload
            
        Returns:
            Success status
        """
        client = cls.get_client()
        
        try:
            points = [
                models.PointStruct(
                    id=chunk["id"],
                    vector=chunk["vector"],
                    payload=chunk["payload"],
                )
                for chunk in chunks
            ]
            
            client.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=points,
                wait=True,
            )
            
            logger.info("Upserted %s chunks to Qdrant", len(chunks))
            return True
            
        except Exception as exc:
            logger.error("Failed to upsert chunks: %s", exc)
            return False
    
    @classmethod
    async def delete_document_chunks(
        cls,
        document_id: str,
    ) -> bool:
        """
        Delete all chunks for a document.
        
        Args:
            document_id: Document UUID
            
        Returns:
            Success status
        """
        client = cls.get_client()
        
        try:
            client.delete(
                collection_name=settings.QDRANT_COLLECTION,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchValue(value=document_id)
                            )
                        ]
                    )
                )
            )
            
            logger.info("Deleted chunks for document %s", document_id)
            return True
            
        except Exception as exc:
            logger.error("Failed to delete document chunks: %s", exc)
            return False
