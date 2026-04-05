"""Conversation service - standalone functions for conversation lifecycle management."""
import json
import logging
import uuid
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.chat import Citation

logger = logging.getLogger(__name__)

# Maximum length for auto-generated conversation titles.
_CONVERSATION_TITLE_MAX_LENGTH = 80


class _ConversationScope(dict):
    """Internal helper payload for persisted conversation scope."""


@dataclass(slots=True)
class _PreparedChatTurn:
    """Shared chat turn state prepared before LLM generation."""

    conversation_id: str
    contexts: list


def build_conversation_scope(
    workspace: Optional[str],
    document_type_filters: Optional[List[str]],
    preferred_document_types: Optional[List[str]],
    include_shared_documents: bool,
) -> _ConversationScope:
    """Create a normalized conversation-scope payload for persistence."""
    return _ConversationScope(
        workspace=workspace,
        document_type_filters=list(document_type_filters) if document_type_filters else None,
        preferred_document_types=list(preferred_document_types) if preferred_document_types else None,
        include_shared_documents=include_shared_documents,
    )


def generate_conversation_title(query: str) -> str:
    """Generate a stable conversation title from the first user query."""
    cleaned = " ".join((query or "").split())
    if not cleaned:
        return "New Conversation"

    if len(cleaned) <= _CONVERSATION_TITLE_MAX_LENGTH:
        return cleaned

    return cleaned[: _CONVERSATION_TITLE_MAX_LENGTH - 3].rstrip() + "..."


async def get_or_create_conversation(
    conversation_id: Optional[str],
    user_id: str,
    db: AsyncSession,
    conversation_scope: Optional[_ConversationScope] = None,
    initial_title: Optional[str] = None,
) -> str:
    """Get existing conversation or create new one."""
    if conversation_id:
        # Verify conversation exists and belongs to user
        result = await db.execute(
            text("SELECT id FROM conversations WHERE id = :conv_id AND user_id = :user_id"),
            {"conv_id": conversation_id, "user_id": user_id},
        )
        if result.fetchone():
            await persist_conversation_scope(
                conversation_id=conversation_id,
                user_id=user_id,
                db=db,
                conversation_scope=conversation_scope,
            )
            return conversation_id

    # Create new conversation
    new_id = str(uuid.uuid4())
    conversation_scope = conversation_scope or build_conversation_scope(
        workspace=None,
        document_type_filters=None,
        preferred_document_types=None,
        include_shared_documents=settings.CHAT_INCLUDE_SHARED_DEFAULT,
    )
    await db.execute(
        text(
            """
            INSERT INTO conversations (
                id,
                user_id,
                title,
                workspace,
                document_type_filters,
                preferred_document_types,
                include_shared_documents,
                created_at,
                updated_at
            ) VALUES (
                :id,
                :user_id,
                :title,
                :workspace,
                :document_type_filters,
                :preferred_document_types,
                :include_shared_documents,
                NOW(),
                NOW()
            )
            """
        ),
        {
            "id": new_id,
            "user_id": user_id,
            "title": initial_title or "New Conversation",
            "workspace": conversation_scope.get("workspace"),
            "document_type_filters": conversation_scope.get("document_type_filters"),
            "preferred_document_types": conversation_scope.get("preferred_document_types"),
            "include_shared_documents": conversation_scope.get("include_shared_documents"),
        },
    )
    await db.commit()

    logger.info("Created new conversation %s", new_id)
    return new_id


async def persist_conversation_scope(
    conversation_id: str,
    user_id: str,
    db: AsyncSession,
    conversation_scope: Optional[_ConversationScope],
) -> None:
    """Persist the current chat scope onto the conversation record."""
    if not conversation_scope:
        return

    await db.execute(
        text(
            """
            UPDATE conversations
            SET
                workspace = :workspace,
                document_type_filters = :document_type_filters,
                preferred_document_types = :preferred_document_types,
                include_shared_documents = :include_shared_documents,
                updated_at = NOW()
            WHERE id = :conv_id AND user_id = :user_id
            """
        ),
        {
            "conv_id": conversation_id,
            "user_id": user_id,
            "workspace": conversation_scope.get("workspace"),
            "document_type_filters": conversation_scope.get("document_type_filters"),
            "preferred_document_types": conversation_scope.get("preferred_document_types"),
            "include_shared_documents": conversation_scope.get("include_shared_documents"),
        },
    )
    await db.commit()


async def get_persisted_conversation_scope(
    conversation_id: Optional[str],
    user_id: str,
    db: AsyncSession,
) -> Optional[dict]:
    """Load persisted scope for an existing conversation owned by the current user."""
    if not conversation_id:
        return None

    result = await db.execute(
        text(
            """
            SELECT workspace, document_type_filters, preferred_document_types, include_shared_documents
            FROM conversations
            WHERE id = :conv_id AND user_id = :user_id
            """
        ),
        {"conv_id": conversation_id, "user_id": user_id},
    )
    row = result.first()
    mapping = coerce_result_mapping(row)
    if not mapping:
        return None

    return {
        "workspace": mapping.get("workspace"),
        "document_type_filters": mapping.get("document_type_filters"),
        "preferred_document_types": mapping.get("preferred_document_types"),
        "include_shared_documents": mapping.get("include_shared_documents"),
    }


def coerce_result_mapping(row: object) -> Optional[dict]:
    """Normalize SQLAlchemy row-like results into a dictionary when possible."""
    if row is None:
        return None
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    if isinstance(row, dict):
        return row
    return None


async def save_message(
    conversation_id: str,
    role: str,
    content: str,
    citations: Optional[List[Citation]],
    db: AsyncSession,
    message_id: Optional[str] = None,
) -> str:
    """Save message to database."""
    message_id = message_id or str(uuid.uuid4())

    # Serialize citations to JSON string (asyncpg requires a JSON string for JSONB columns)
    citations_json: Optional[str] = None
    if citations:
        citations_json = json.dumps([c.model_dump(mode="json") for c in citations])

    await db.execute(
        text("""
            INSERT INTO chat_messages (id, conversation_id, role, content, citations, timestamp)
            VALUES (:id, :conv_id, :role, :content, CAST(:citations AS jsonb), NOW())
        """),
        {
            "id": message_id,
            "conv_id": conversation_id,
            "role": role,
            "content": content,
            "citations": citations_json,
        },
    )
    await db.commit()
    return message_id
