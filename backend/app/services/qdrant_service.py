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
    """Service for interacting with Qdrant vector database."""
    
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
            logger.info(f"Connected to Qdrant at {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")
        return cls._client
    
    @classmethod
    async def ensure_collection(cls) -> bool:
        """Ensure collection exists, create if not."""
        client = cls.get_client()
        
        try:
            collections = client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if settings.QDRANT_COLLECTION not in collection_names:
                logger.info(f"Creating collection {settings.QDRANT_COLLECTION}")
                client.create_collection(
                    collection_name=settings.QDRANT_COLLECTION,
                    vectors_config=models.VectorParams(
                        size=settings.EMBEDDING_DIM,
                        distance=models.Distance.COSINE,
                    ),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to ensure collection: {e}")
            return False
    
    @classmethod
    async def search_similar(
        cls,
        query_vector: List[float],
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        document_filter: Optional[List[str]] = None,
        system_filter: Optional[List[str]] = None,
    ) -> List[RAGContext]:
        """
        Search for similar document chunks.
        
        Args:
            query_vector: Query embedding vector
            top_k: Number of results to return
            score_threshold: Minimum similarity score
            document_filter: Filter by document IDs
            system_filter: Filter by system types
            
        Returns:
            List of retrieved contexts with metadata
        """
        client = cls.get_client()
        
        if top_k is None:
            top_k = settings.RAG_TOP_K
        if score_threshold is None:
            score_threshold = settings.RAG_SCORE_THRESHOLD
        
        # Build filter conditions
        filter_conditions = []
        if document_filter:
            filter_conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=document_filter)
                )
            )
        if system_filter:
            filter_conditions.append(
                models.FieldCondition(
                    key="system",
                    match=models.MatchAny(any=system_filter)
                )
            )
        
        query_filter = None
        if filter_conditions:
            query_filter = models.Filter(
                must=filter_conditions
            )
        
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
            
            # Convert to RAGContext objects
            contexts = []
            for result in response.points:
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
            
            logger.info(f"Found {len(contexts)} similar chunks")
            return contexts
            
        except UnexpectedResponse as e:
            logger.error(f"Qdrant search failed: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error during search: {e}")
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
            
            logger.info(f"Upserted {len(chunks)} chunks to Qdrant")
            return True
            
        except Exception as e:
            logger.error(f"Failed to upsert chunks: {e}")
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
            
            logger.info(f"Deleted chunks for document {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete document chunks: {e}")
            return False
