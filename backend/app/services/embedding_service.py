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
    """Service for generating text embeddings."""
    
    _model: Optional[SentenceTransformer] = None
    
    @classmethod
    def get_model(cls) -> SentenceTransformer:
        """Get or load embedding model singleton."""
        if cls._model is None:
            logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
            cls._model = SentenceTransformer(settings.EMBEDDING_MODEL)
            logger.info("Embedding model loaded successfully")
        return cls._model
    
    @classmethod
    async def embed_query(cls, query: str) -> List[float]:
        """
        Generate embedding for a query string.
        
        Args:
            query: Query text
            
        Returns:
            Embedding vector as list of floats
        """
        model = cls.get_model()
        
        try:
            # Generate embedding
            embedding = model.encode(query, convert_to_numpy=True)
            
            # Convert to list
            return embedding.tolist()
            
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise
    
    @classmethod
    async def embed_batch(cls, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of text strings
            
        Returns:
            List of embedding vectors
        """
        model = cls.get_model()
        
        try:
            # Generate embeddings in batch
            embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            
            # Convert to list of lists
            return [emb.tolist() for emb in embeddings]
            
        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            raise
