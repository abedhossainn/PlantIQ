"""User scope governance and enforcement utilities.

Phase A (Candidate 1) introduces backend-authoritative scope enforcement using
system/area policy only. Client-provided scope values are treated as advisory
and validated against user policy before retrieval/upload operations proceed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chat import RAGContext

logger = logging.getLogger(__name__)

_DENIAL_ERROR_CODE = "SCOPE_ACCESS_DENIED"
_SHARED_SCOPE_TOKENS = {"shared", "global", "cross-functional"}
_ACTION_UPLOAD = "ingestion.upload"
_ACTION_CHAT = "chat.retrieve"


class ScopeAccessDenied(Exception):
    """Raised when request scope violates user scope policy."""

    def __init__(self, detail: dict[str, Any]):
        self.detail = detail
        super().__init__(detail.get("message") or "Scope access denied")


@dataclass(slots=True)
class ScopePolicy:
    """Normalized scope policy for one user."""

    systems: set[str]
    areas: set[str]


@dataclass(slots=True)
class EffectiveScope:
    """Effective scope after policy enforcement."""

    workspace: Optional[str]
    system_filters: Optional[list[str]]
    allow_shared_documents: bool
    policy: ScopePolicy


def _normalize_scope(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def _normalize_scope_list(values: Optional[Iterable[str]]) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        cleaned = _normalize_scope(value)
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _is_admin_role(claims: dict[str, Any]) -> bool:
    role = str(claims.get("role") or "")
    return role in {"admin", "plantig_admin"}


def _build_denial_detail(
    *,
    reason_code: str,
    message: str,
    requested_scope: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "code": _DENIAL_ERROR_CODE,
        "reason_code": reason_code,
        "message": message,
        "requested_scope": requested_scope or {},
    }


async def load_user_scope_policy(db: AsyncSession, user_id: UUID) -> ScopePolicy:
    """Load active system/area scope policy rows for a user."""
    result = await db.execute(
        text(
            """
            SELECT system_scope, area_scope
            FROM user_scope_policies
            WHERE user_id = :user_id AND is_active = TRUE
            """
        ),
        {"user_id": str(user_id)},
    )

    systems: set[str] = set()
    areas: set[str] = set()
    for row in result.mappings().all():
        if not row:
            continue
        normalized_system = _normalize_scope(row.get("system_scope"))
        normalized_area = _normalize_scope(row.get("area_scope"))
        if normalized_system:
            systems.add(normalized_system)
        if normalized_area:
            areas.add(normalized_area)

    return ScopePolicy(systems=systems, areas=areas)


async def audit_scope_denial(
    *,
    db: AsyncSession,
    user_id: UUID,
    action: str,
    endpoint: str,
    reason_code: str,
    message: str,
    requested_system: Optional[str] = None,
    requested_area: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Persist audit entry for denied scope access attempts."""
    try:
        await db.execute(
            text(
                """
                INSERT INTO access_audit_logs (
                    user_id,
                    action,
                    endpoint,
                    requested_system,
                    requested_area,
                    reason_code,
                    message,
                    metadata,
                    created_at
                )
                VALUES (
                    :user_id,
                    :action,
                    :endpoint,
                    :requested_system,
                    :requested_area,
                    :reason_code,
                    :message,
                    CAST(:metadata AS jsonb),
                    NOW()
                )
                """
            ),
            {
                "user_id": str(user_id),
                "action": action,
                "endpoint": endpoint,
                "requested_system": requested_system,
                "requested_area": requested_area,
                "reason_code": reason_code,
                "message": message,
                "metadata": json.dumps(metadata or {}),
            },
        )
        await db.commit()
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("Failed to persist access audit denial: %s", exc)


async def enforce_upload_scope(
    *,
    db: AsyncSession,
    user_id: UUID,
    claims: dict[str, Any],
    system: Optional[str],
    endpoint: str,
) -> None:
    """Authorize upload system/area scope for current user."""
    if _is_admin_role(claims):
        return

    policy = await load_user_scope_policy(db, user_id)
    requested_system = _normalize_scope(system)

    if not policy.systems and not policy.areas:
        reason = "SCOPE_POLICY_NOT_CONFIGURED"
        message = "No scope policy configured for this user."
        await _deny_with_audit(
            db=db,
            user_id=user_id,
            action=_ACTION_UPLOAD,
            endpoint=endpoint,
            reason_code=reason,
            message=message,
            requested_scope={"system": system},
            requested_system=system,
            metadata={"system": system},
        )

    if not requested_system:
        reason = "SYSTEM_SCOPE_REQUIRED"
        message = "Document upload requires a system value within your authorized scope."
        await _deny_with_audit(
            db=db,
            user_id=user_id,
            action=_ACTION_UPLOAD,
            endpoint=endpoint,
            reason_code=reason,
            message=message,
            requested_scope={"system": system},
            metadata={"system": system},
        )

    allowed_union = policy.systems | policy.areas
    if requested_system in allowed_union:
        return

    reason = "SYSTEM_SCOPE_DENIED"
    message = f"System '{system}' is outside your authorized scope policy."
    await _deny_with_audit(
        db=db,
        user_id=user_id,
        action=_ACTION_UPLOAD,
        endpoint=endpoint,
        reason_code=reason,
        message=message,
        requested_scope={"system": system},
        requested_system=system,
        metadata={"system": system, "authorized_systems": sorted(policy.systems)},
    )


async def enforce_chat_scope(
    *,
    db: AsyncSession,
    user_id: UUID,
    claims: dict[str, Any],
    workspace: Optional[str],
    system_filters: Optional[list[str]],
    endpoint: str,
) -> EffectiveScope:
    """Authorize and resolve effective chat retrieval scope."""
    if _is_admin_role(claims):
        normalized_system_filters = _normalize_scope_list(system_filters)
        return EffectiveScope(
            workspace=workspace,
            system_filters=normalized_system_filters or None,
            allow_shared_documents=True,
            policy=ScopePolicy(systems=set(), areas=set()),
        )

    policy = await load_user_scope_policy(db, user_id)
    if not policy.systems and not policy.areas:
        reason = "SCOPE_POLICY_NOT_CONFIGURED"
        message = "No scope policy configured for this user."
        await _deny_with_audit(
            db=db,
            user_id=user_id,
            action=_ACTION_CHAT,
            endpoint=endpoint,
            reason_code=reason,
            message=message,
            requested_scope={"workspace": workspace, "system_filters": system_filters or []},
            requested_system=",".join(system_filters or []),
            requested_area=workspace,
            metadata={"workspace": workspace, "system_filters": system_filters or []},
        )

    normalized_workspace = _normalize_scope(workspace)
    await _validate_workspace_scope(
        db=db,
        user_id=user_id,
        endpoint=endpoint,
        workspace=workspace,
        normalized_workspace=normalized_workspace,
        policy=policy,
    )

    normalized_system_filters = await _resolve_system_filters(
        db=db,
        user_id=user_id,
        endpoint=endpoint,
        workspace=workspace,
        system_filters=system_filters,
        policy=policy,
    )

    allow_shared_documents = bool((policy.systems | policy.areas) & _SHARED_SCOPE_TOKENS)
    return EffectiveScope(
        workspace=workspace,
        system_filters=normalized_system_filters or None,
        allow_shared_documents=allow_shared_documents,
        policy=policy,
    )


def filter_contexts_to_scope(
    contexts: list[RAGContext],
    *,
    policy: ScopePolicy,
    allow_shared_documents: bool,
) -> list[RAGContext]:
    """Defense-in-depth filter to ensure out-of-scope contexts never reach citations."""
    if not contexts:
        return contexts

    # Admin/empty policy path: policy empty implies bypass (handled by caller).
    if not policy.systems and not policy.areas:
        return contexts

    return [
        context
        for context in contexts
        if _context_in_scope(
            context=context,
            policy=policy,
            allow_shared_documents=allow_shared_documents,
        )
    ]


async def _deny_with_audit(
    *,
    db: AsyncSession,
    user_id: UUID,
    action: str,
    endpoint: str,
    reason_code: str,
    message: str,
    requested_scope: dict[str, Any],
    requested_system: Optional[str] = None,
    requested_area: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    await audit_scope_denial(
        db=db,
        user_id=user_id,
        action=action,
        endpoint=endpoint,
        reason_code=reason_code,
        message=message,
        requested_system=requested_system,
        requested_area=requested_area,
        metadata=metadata,
    )
    raise ScopeAccessDenied(
        _build_denial_detail(
            reason_code=reason_code,
            message=message,
            requested_scope=requested_scope,
        )
    )


async def _validate_workspace_scope(
    *,
    db: AsyncSession,
    user_id: UUID,
    endpoint: str,
    workspace: Optional[str],
    normalized_workspace: Optional[str],
    policy: ScopePolicy,
) -> None:
    if not normalized_workspace:
        return
    if normalized_workspace in (policy.areas | policy.systems):
        return

    await _deny_with_audit(
        db=db,
        user_id=user_id,
        action=_ACTION_CHAT,
        endpoint=endpoint,
        reason_code="AREA_SCOPE_DENIED",
        message=f"Area/workspace '{workspace}' is outside your authorized scope policy.",
        requested_scope={"workspace": workspace},
        requested_area=workspace,
        metadata={"workspace": workspace, "authorized_areas": sorted(policy.areas)},
    )


async def _resolve_system_filters(
    *,
    db: AsyncSession,
    user_id: UUID,
    endpoint: str,
    workspace: Optional[str],
    system_filters: Optional[list[str]],
    policy: ScopePolicy,
) -> Optional[list[str]]:
    normalized_system_filters = _normalize_scope_list(system_filters)
    if not normalized_system_filters:
        return sorted(policy.systems) if policy.systems else None

    unauthorized = [
        value for value in normalized_system_filters if value not in (policy.systems | policy.areas)
    ]
    if not unauthorized:
        return normalized_system_filters

    await _deny_with_audit(
        db=db,
        user_id=user_id,
        action=_ACTION_CHAT,
        endpoint=endpoint,
        reason_code="SYSTEM_SCOPE_DENIED",
        message="One or more requested system filters are outside your authorized scope policy.",
        requested_scope={"workspace": workspace, "system_filters": system_filters or []},
        requested_system=",".join(system_filters or []),
        requested_area=workspace,
        metadata={"unauthorized_systems": unauthorized, "requested_systems": system_filters or []},
    )


def _context_in_scope(
    *,
    context: RAGContext,
    policy: ScopePolicy,
    allow_shared_documents: bool,
) -> bool:
    metadata = context.metadata or {}
    allowed_union = policy.systems | policy.areas

    context_system = _normalize_scope(str(metadata.get("system") or ""))
    context_workspace = _normalize_scope(str(metadata.get("workspace") or ""))
    if context_system and context_system in allowed_union:
        return True
    if context_workspace and context_workspace in allowed_union:
        return True

    if not allow_shared_documents:
        return False

    is_shared = bool(metadata.get("is_shared"))
    return bool(
        is_shared
        or context_workspace in _SHARED_SCOPE_TOKENS
        or context_system in _SHARED_SCOPE_TOKENS
    )