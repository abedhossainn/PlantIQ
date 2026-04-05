"""
Embedding Service - Generate embeddings for RAG queries.

Uses sentence-transformers for text embedding generation.
"""
import logging
from typing import List, Optional
from sentence_transformers import SentenceTransformer

from ..core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating text embeddings.
    
    Role:
    - Convert text chunks and user queries into fixed-size numerical vectors
    - Enables semantic similarity search in Qdrant (cosine distance)
    
    Model:
    - Uses sentence-transformers (SBERT or similar)
    - Produces embeddings of configurable dimension (default 384 or 768)
    - Singleton instance reused for all embedding operations (memory efficient)
    
    Design Notes:
    - Embeddings are deterministic (same text always produces same vector)
    - Batch embedding is more efficient than query-by-query (GPU amortization)
    - Published chunks are re-embedded when documents are updated (replacement semantics)
    """
    
    # Singleton embedding model instance (loaded on first use)
    _model: Optional[SentenceTransformer] = None
    
    @classmethod
    def get_model(cls) -> SentenceTransformer:
        """Get or load embedding model singleton."""
        if cls._model is None:
            logger.info("Loading embedding model: %s", settings.EMBEDDING_MODEL)
            cls._model = SentenceTransformer(settings.EMBEDDING_MODEL)
            logger.info("Embedding model loaded successfully")
        return cls._model
    
    @classmethod
    async def embed_query(cls, query: str) -> List[float]:
        """
        Generate embedding for a single query string.
        
        Used for chat queries before vector search. Produces embedding compatible
        with Qdrant collection (same model, dimension, normalization).
        
        Args:
            query: User query text
            
        Returns:
            Embedding vector as list of floats (length = EMBEDDING_DIM)
        """
        model = cls.get_model()
        
        try:
            # Generate embedding
            embedding = model.encode(query, convert_to_numpy=True)
            
            # Convert to list
            return embedding.tolist()
            
        except Exception as exc:
            logger.error("Failed to generate embedding: %s", exc)
            raise
    
    @classmethod
    async def embed_batch(cls, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts (vectorized operation).
        
        Used during document publishing to batch-embed all optimized chunks.
        More efficient than per-text queries (GPU batching + amortized model load).
        
        Args:
            texts: List of text strings (chunks or documents)
            
        Returns:
            List of embedding vectors
        """
        model = cls.get_model()
        
        try:
            # Generate embeddings in batch
            embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            
            # Convert to list of lists
            return [emb.tolist() for emb in embeddings]
            
        except Exception as exc:
            logger.error("Failed to generate batch embeddings: %s", exc)
            raise
