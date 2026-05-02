"""Answer feedback persistence and lightweight quality-loop aggregation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chat import (
	ChatFeedbackReasonMetric,
	ChatFeedbackSubmitRequest,
	ChatFeedbackSubmitResponse,
	ChatQualityMetricsResponse,
	ChatQualitySnapshot,
)

NEGATIVE_STREAK_FLAG_THRESHOLD = 3
TOTAL_NEGATIVE_FLAG_THRESHOLD = 5


class FeedbackServiceError(Exception):
	"""Domain-level error for feedback API contracts."""

	def __init__(self, *, status_code: int, code: str, message: str):
		super().__init__(message)
		self.status_code = status_code
		self.code = code
		self.message = message


@dataclass(slots=True)
class _AnswerContext:
	answer_message_id: str
	conversation_id: str
	conversation_user_id: str
	role: str


@dataclass(slots=True)
class _SnapshotStats:
	feedback_count: int
	positive_count: int
	negative_count: int
	negative_streak: int
	quality_score: float
	is_flagged: bool
	last_feedback_at: datetime


def _coerce_mapping(row: object) -> Optional[dict[str, Any]]:
	if row is None:
		return None
	if hasattr(row, "_mapping"):
		return dict(row._mapping)
	if isinstance(row, dict):
		return row
	return None


class AnswerFeedbackService:
	"""Service for answer-feedback events and lightweight quality metrics."""

	@classmethod
	async def submit_feedback(
		cls,
		*,
		request: ChatFeedbackSubmitRequest,
		user_id: str,
		user_claims: dict,
		db: AsyncSession,
	) -> ChatFeedbackSubmitResponse:
		"""Persist an append-only feedback event and refresh the quality snapshot."""
		answer_context = await cls._load_answer_context(
			answer_message_id=str(request.answer_message_id),
			db=db,
		)
		cls._validate_feedback_request(
			request=request,
			answer_context=answer_context,
			user_id=user_id,
			user_claims=user_claims,
		)

		event_id = str(uuid.uuid4())
		await db.execute(
			text(
				"""
				INSERT INTO answer_feedback_events (
					id,
					answer_message_id,
					conversation_id,
					source_message_id,
					actor_user_id,
					sentiment,
					reason_code,
					comment,
					system_scope,
					area_scope,
					created_at
				) VALUES (
					:id,
					:answer_message_id,
					:conversation_id,
					:source_message_id,
					:actor_user_id,
					:sentiment,
					:reason_code,
					:comment,
					:system_scope,
					:area_scope,
					NOW()
				)
				"""
			),
			{
				"id": event_id,
				"answer_message_id": answer_context.answer_message_id,
				"conversation_id": answer_context.conversation_id,
				"source_message_id": str(request.source_message_id) if request.source_message_id else None,
				"actor_user_id": str(user_id),
				"sentiment": request.sentiment,
				"reason_code": request.reason_code,
				"comment": request.comment,
				"system_scope": request.system_scope,
				"area_scope": request.area_scope,
			},
		)

		stats = await cls._compute_snapshot_stats(
			answer_message_id=answer_context.answer_message_id,
			db=db,
		)

		await db.execute(
			text(
				"""
				INSERT INTO answer_quality_snapshots (
					answer_message_id,
					conversation_id,
					system_scope,
					area_scope,
					feedback_count,
					positive_count,
					negative_count,
					negative_streak,
					quality_score,
					is_flagged,
					last_feedback_at,
					updated_at
				) VALUES (
					:answer_message_id,
					:conversation_id,
					:system_scope,
					:area_scope,
					:feedback_count,
					:positive_count,
					:negative_count,
					:negative_streak,
					:quality_score,
					:is_flagged,
					:last_feedback_at,
					NOW()
				)
				ON CONFLICT (answer_message_id)
				DO UPDATE SET
					conversation_id = EXCLUDED.conversation_id,
					system_scope = COALESCE(EXCLUDED.system_scope, answer_quality_snapshots.system_scope),
					area_scope = COALESCE(EXCLUDED.area_scope, answer_quality_snapshots.area_scope),
					feedback_count = EXCLUDED.feedback_count,
					positive_count = EXCLUDED.positive_count,
					negative_count = EXCLUDED.negative_count,
					negative_streak = EXCLUDED.negative_streak,
					quality_score = EXCLUDED.quality_score,
					is_flagged = EXCLUDED.is_flagged,
					last_feedback_at = EXCLUDED.last_feedback_at,
					updated_at = NOW()
				"""
			),
			{
				"answer_message_id": answer_context.answer_message_id,
				"conversation_id": answer_context.conversation_id,
				"system_scope": request.system_scope,
				"area_scope": request.area_scope,
				"feedback_count": stats.feedback_count,
				"positive_count": stats.positive_count,
				"negative_count": stats.negative_count,
				"negative_streak": stats.negative_streak,
				"quality_score": stats.quality_score,
				"is_flagged": stats.is_flagged,
				"last_feedback_at": stats.last_feedback_at,
			},
		)
		await db.commit()

		return ChatFeedbackSubmitResponse(
			event_id=event_id,
			answer_message_id=answer_context.answer_message_id,
			conversation_id=answer_context.conversation_id,
			timestamp=stats.last_feedback_at,
			snapshot=ChatQualitySnapshot(
				answer_message_id=answer_context.answer_message_id,
				conversation_id=answer_context.conversation_id,
				feedback_count=stats.feedback_count,
				positive_count=stats.positive_count,
				negative_count=stats.negative_count,
				negative_streak=stats.negative_streak,
				quality_score=stats.quality_score,
				is_flagged=stats.is_flagged,
				last_feedback_at=stats.last_feedback_at,
			),
		)

	@classmethod
	async def get_metrics_summary(
		cls,
		*,
		window_days: int,
		system_scope: Optional[str],
		area_scope: Optional[str],
		db: AsyncSession,
	) -> ChatQualityMetricsResponse:
		"""Return lightweight feedback metrics for admin/QA monitoring."""
		params = {
			"window_days": int(window_days),
			"system_scope": system_scope,
			"area_scope": area_scope,
		}

		aggregate_result = await db.execute(
			text(
				"""
				SELECT
					COUNT(*)::int AS total_feedback_events,
					COUNT(*) FILTER (WHERE sentiment = 'up')::int AS positive_feedback_events,
					COUNT(*) FILTER (WHERE sentiment = 'down')::int AS negative_feedback_events
				FROM answer_feedback_events
				WHERE created_at >= NOW() - (CAST(:window_days AS INTEGER) * INTERVAL '1 day')
				  AND (CAST(:system_scope AS TEXT) IS NULL OR LOWER(system_scope) = LOWER(CAST(:system_scope AS TEXT)))
				  AND (CAST(:area_scope AS TEXT) IS NULL OR LOWER(area_scope) = LOWER(CAST(:area_scope AS TEXT)))
				"""
			),
			params,
		)
		aggregate_row = _coerce_mapping(aggregate_result.first()) or {}

		flagged_result = await db.execute(
			text(
				"""
				SELECT COUNT(*)::int AS flagged_answers
				FROM answer_quality_snapshots
				WHERE is_flagged = TRUE
				  AND last_feedback_at >= NOW() - (CAST(:window_days AS INTEGER) * INTERVAL '1 day')
				  AND (CAST(:system_scope AS TEXT) IS NULL OR LOWER(system_scope) = LOWER(CAST(:system_scope AS TEXT)))
				  AND (CAST(:area_scope AS TEXT) IS NULL OR LOWER(area_scope) = LOWER(CAST(:area_scope AS TEXT)))
				"""
			),
			params,
		)
		flagged_row = _coerce_mapping(flagged_result.first()) or {}

		reasons_result = await db.execute(
			text(
				"""
				SELECT reason_code, COUNT(*)::int AS count
				FROM answer_feedback_events
				WHERE created_at >= NOW() - (CAST(:window_days AS INTEGER) * INTERVAL '1 day')
				  AND reason_code IS NOT NULL
				  AND reason_code <> ''
				  AND (CAST(:system_scope AS TEXT) IS NULL OR LOWER(system_scope) = LOWER(CAST(:system_scope AS TEXT)))
				  AND (CAST(:area_scope AS TEXT) IS NULL OR LOWER(area_scope) = LOWER(CAST(:area_scope AS TEXT)))
				GROUP BY reason_code
				ORDER BY count DESC, reason_code ASC
				"""
			),
			params,
		)

		reason_breakdown = []
		for row in reasons_result.fetchall():
			mapping = _coerce_mapping(row) or {}
			code = mapping.get("reason_code")
			count = int(mapping.get("count") or 0)
			if code:
				reason_breakdown.append(ChatFeedbackReasonMetric(reason_code=code, count=count))

		return ChatQualityMetricsResponse(
			window_days=window_days,
			total_feedback_events=int(aggregate_row.get("total_feedback_events") or 0),
			positive_feedback_events=int(aggregate_row.get("positive_feedback_events") or 0),
			negative_feedback_events=int(aggregate_row.get("negative_feedback_events") or 0),
			flagged_answers=int(flagged_row.get("flagged_answers") or 0),
			reason_breakdown=reason_breakdown,
		)

	@classmethod
	async def _load_answer_context(
		cls,
		*,
		answer_message_id: str,
		db: AsyncSession,
	) -> _AnswerContext:
		result = await db.execute(
			text(
				"""
				SELECT
					m.id AS answer_message_id,
					m.role AS role,
					m.conversation_id AS conversation_id,
					c.user_id AS conversation_user_id
				FROM chat_messages m
				JOIN conversations c ON c.id = m.conversation_id
				WHERE m.id = :answer_message_id
				"""
			),
			{"answer_message_id": answer_message_id},
		)
		row = _coerce_mapping(result.first())
		if not row:
			raise FeedbackServiceError(
				status_code=404,
				code="ANSWER_MESSAGE_NOT_FOUND",
				message="Answer message was not found.",
			)

		return _AnswerContext(
			answer_message_id=str(row["answer_message_id"]),
			role=str(row["role"]),
			conversation_id=str(row["conversation_id"]),
			conversation_user_id=str(row["conversation_user_id"]),
		)

	@classmethod
	def _validate_feedback_request(
		cls,
		*,
		request: ChatFeedbackSubmitRequest,
		answer_context: _AnswerContext,
		user_id: str,
		user_claims: dict,
	) -> None:
		user_role = str(user_claims.get("role") or "")
		is_admin_or_reviewer = user_role in {
			"admin",
			"reviewer",
			"plantig_admin",
			"plantig_reviewer",
		}

		if answer_context.role != "assistant":
			raise FeedbackServiceError(
				status_code=400,
				code="INVALID_FEEDBACK_TARGET",
				message="Feedback can only target assistant answer messages.",
			)

		if request.conversation_id and str(request.conversation_id) != answer_context.conversation_id:
			raise FeedbackServiceError(
				status_code=400,
				code="CONVERSATION_MISMATCH",
				message="Provided conversation_id does not match the answer message context.",
			)

		if not is_admin_or_reviewer and answer_context.conversation_user_id != str(user_id):
			raise FeedbackServiceError(
				status_code=403,
				code="FEEDBACK_ACCESS_DENIED",
				message="You can only submit feedback for your own conversation answers.",
			)

	@classmethod
	async def _compute_snapshot_stats(
		cls,
		*,
		answer_message_id: str,
		db: AsyncSession,
	) -> _SnapshotStats:
		aggregate_result = await db.execute(
			text(
				"""
				SELECT
					COUNT(*)::int AS feedback_count,
					COUNT(*) FILTER (WHERE sentiment = 'up')::int AS positive_count,
					COUNT(*) FILTER (WHERE sentiment = 'down')::int AS negative_count,
					MAX(created_at) AS last_feedback_at
				FROM answer_feedback_events
				WHERE answer_message_id = :answer_message_id
				"""
			),
			{"answer_message_id": answer_message_id},
		)
		aggregate = _coerce_mapping(aggregate_result.first()) or {}

		streak_result = await db.execute(
			text(
				"""
				WITH ordered AS (
					SELECT
						sentiment,
						ROW_NUMBER() OVER (ORDER BY created_at DESC, id DESC) AS rn
					FROM answer_feedback_events
					WHERE answer_message_id = :answer_message_id
				),
				first_non_negative AS (
					SELECT MIN(rn) AS stop_rank
					FROM ordered
					WHERE sentiment <> 'down'
				)
				SELECT COUNT(*)::int AS negative_streak
				FROM ordered
				WHERE sentiment = 'down'
				  AND rn < COALESCE((SELECT stop_rank FROM first_non_negative), 2147483647)
				"""
			),
			{"answer_message_id": answer_message_id},
		)
		streak_mapping = _coerce_mapping(streak_result.first()) or {}

		feedback_count = int(aggregate.get("feedback_count") or 0)
		positive_count = int(aggregate.get("positive_count") or 0)
		negative_count = int(aggregate.get("negative_count") or 0)
		negative_streak = int(streak_mapping.get("negative_streak") or 0)

		quality_score = 0.0
		if feedback_count > 0:
			quality_score = (positive_count - negative_count) / feedback_count

		is_flagged = (
			negative_streak >= NEGATIVE_STREAK_FLAG_THRESHOLD
			or negative_count >= TOTAL_NEGATIVE_FLAG_THRESHOLD
		)

		return _SnapshotStats(
			feedback_count=feedback_count,
			positive_count=positive_count,
			negative_count=negative_count,
			negative_streak=negative_streak,
			quality_score=quality_score,
			is_flagged=is_flagged,
			last_feedback_at=aggregate.get("last_feedback_at") or datetime.now(timezone.utc),
		)
