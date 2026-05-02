#!/usr/bin/env python3
"""Candidate 2 backend tests: chat feedback + quality-loop foundation."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.security import get_current_user_id, get_jwt_payload  # noqa: E402
from app.main import app  # noqa: E402
from app.models.chat import ChatQueryResponse  # noqa: E402
from app.models.database import get_db  # noqa: E402
import app.services.chat_service as chat_service_module  # noqa: E402


TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CHAT_READ_SCOPE = "chat.read"
FEEDBACK_ENDPOINT = "/api/v1/chat/feedback"


class FakeResult:
    def __init__(self, rows: Any = None):
        if rows is None:
            self._rows: list[Any] = []
        elif isinstance(rows, list):
            self._rows = rows
        else:
            self._rows = [rows]

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeAsyncSession:
    def __init__(self):
        self.conversations: dict[str, dict[str, Any]] = {}
        self.chat_messages: dict[str, dict[str, Any]] = {}
        self.answer_feedback_events: list[dict[str, Any]] = []
        self.answer_quality_snapshots: dict[str, dict[str, Any]] = {}

    async def execute(self, statement, params=None):
        sql = str(statement).lower()
        params = params or {}

        handlers = (
            self._handle_answer_context_query,
            self._handle_feedback_insert,
            self._handle_snapshot_aggregate_query,
            self._handle_snapshot_streak_query,
            self._handle_snapshot_upsert,
            self._handle_metrics_aggregate_query,
            self._handle_metrics_flagged_query,
            self._handle_metrics_reasons_query,
        )

        for handler in handlers:
            result = handler(sql, params)
            if result is not None:
                return result

        raise AssertionError(f"Unexpected SQL in test double: {statement}")

    def _handle_answer_context_query(self, sql: str, params: dict[str, Any]) -> FakeResult | None:
        if "from chat_messages m" not in sql or "join conversations c" not in sql:
            return None

        message = self.chat_messages.get(str(params["answer_message_id"]))
        if not message:
            return FakeResult(None)
        conversation = self.conversations.get(str(message["conversation_id"]))
        if not conversation:
            return FakeResult(None)
        return FakeResult(
            {
                "answer_message_id": message["id"],
                "role": message["role"],
                "conversation_id": message["conversation_id"],
                "conversation_user_id": conversation["user_id"],
            }
        )

    def _handle_feedback_insert(self, sql: str, params: dict[str, Any]) -> FakeResult | None:
        if "insert into answer_feedback_events" not in sql:
            return None

        event = {
            "id": str(params["id"]),
            "answer_message_id": str(params["answer_message_id"]),
            "conversation_id": str(params["conversation_id"]),
            "source_message_id": str(params["source_message_id"]) if params.get("source_message_id") else None,
            "actor_user_id": str(params["actor_user_id"]),
            "sentiment": params["sentiment"],
            "reason_code": params.get("reason_code"),
            "comment": params.get("comment"),
            "system_scope": params.get("system_scope"),
            "area_scope": params.get("area_scope"),
            "created_at": datetime.now(timezone.utc),
        }
        self.answer_feedback_events.append(event)
        return FakeResult(None)

    def _handle_snapshot_aggregate_query(self, sql: str, params: dict[str, Any]) -> FakeResult | None:
        if (
            "from answer_feedback_events" not in sql
            or "where answer_message_id = :answer_message_id" not in sql
            or "max(created_at)" not in sql
        ):
            return None

        answer_id = str(params["answer_message_id"])
        events = [e for e in self.answer_feedback_events if e["answer_message_id"] == answer_id]
        return FakeResult(
            {
                "feedback_count": len(events),
                "positive_count": sum(1 for e in events if e["sentiment"] == "up"),
                "negative_count": sum(1 for e in events if e["sentiment"] == "down"),
                "last_feedback_at": max((e["created_at"] for e in events), default=None),
            }
        )

    def _handle_snapshot_streak_query(self, sql: str, params: dict[str, Any]) -> FakeResult | None:
        if "with ordered as" not in sql or "negative_streak" not in sql:
            return None

        answer_id = str(params["answer_message_id"])
        events = [e for e in self.answer_feedback_events if e["answer_message_id"] == answer_id]
        events.sort(key=lambda e: (e["created_at"], e["id"]), reverse=True)
        streak = 0
        for event in events:
            if event["sentiment"] != "down":
                break
            streak += 1
        return FakeResult({"negative_streak": streak})

    def _handle_snapshot_upsert(self, sql: str, params: dict[str, Any]) -> FakeResult | None:
        if "insert into answer_quality_snapshots" not in sql:
            return None

        key = str(params["answer_message_id"])
        self.answer_quality_snapshots[key] = {
            "answer_message_id": key,
            "conversation_id": str(params["conversation_id"]),
            "system_scope": params.get("system_scope"),
            "area_scope": params.get("area_scope"),
            "feedback_count": int(params["feedback_count"]),
            "positive_count": int(params["positive_count"]),
            "negative_count": int(params["negative_count"]),
            "negative_streak": int(params["negative_streak"]),
            "quality_score": float(params["quality_score"]),
            "is_flagged": bool(params["is_flagged"]),
            "last_feedback_at": params.get("last_feedback_at"),
            "updated_at": datetime.now(timezone.utc),
        }
        return FakeResult(None)

    def _handle_metrics_aggregate_query(self, sql: str, params: dict[str, Any]) -> FakeResult | None:
        if "from answer_feedback_events" not in sql or "count(*)::int as total_feedback_events" not in sql:
            return None

        filtered = self._filter_feedback_for_metrics(params)
        return FakeResult(
            {
                "total_feedback_events": len(filtered),
                "positive_feedback_events": sum(1 for e in filtered if e["sentiment"] == "up"),
                "negative_feedback_events": sum(1 for e in filtered if e["sentiment"] == "down"),
            }
        )

    def _handle_metrics_flagged_query(self, sql: str, params: dict[str, Any]) -> FakeResult | None:
        if "from answer_quality_snapshots" not in sql or "count(*)::int as flagged_answers" not in sql:
            return None

        window_days = int(params["window_days"])
        system_scope = params.get("system_scope")
        area_scope = params.get("area_scope")
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        filtered = [
            s
            for s in self.answer_quality_snapshots.values()
            if bool(s.get("is_flagged"))
            and (s.get("last_feedback_at") is not None and s["last_feedback_at"] >= cutoff)
            and (system_scope is None or (s.get("system_scope") or "").lower() == str(system_scope).lower())
            and (area_scope is None or (s.get("area_scope") or "").lower() == str(area_scope).lower())
        ]
        return FakeResult({"flagged_answers": len(filtered)})

    def _handle_metrics_reasons_query(self, sql: str, params: dict[str, Any]) -> FakeResult | None:
        if "group by reason_code" not in sql:
            return None

        filtered = [e for e in self._filter_feedback_for_metrics(params) if e.get("reason_code")]
        counts: dict[str, int] = {}
        for event in filtered:
            code = str(event["reason_code"])
            counts[code] = counts.get(code, 0) + 1

        rows = [
            {"reason_code": code, "count": count}
            for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        return FakeResult(rows)

    def _filter_feedback_for_metrics(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        window_days = int(params["window_days"])
        system_scope = params.get("system_scope")
        area_scope = params.get("area_scope")
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

        return [
            e
            for e in self.answer_feedback_events
            if e["created_at"] >= cutoff
            and (system_scope is None or (e.get("system_scope") or "").lower() == str(system_scope).lower())
            and (area_scope is None or (e.get("area_scope") or "").lower() == str(area_scope).lower())
        ]

    async def commit(self):
        return None


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture
def client(fake_db: FakeAsyncSession):
    async def override_get_db():
        yield fake_db

    async def override_get_current_user_id():
        return TEST_USER_ID

    async def override_get_jwt_payload():
        return {"sub": str(TEST_USER_ID), "role": "plantig_user", "scope": [CHAT_READ_SCOPE]}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = override_get_current_user_id
    app.dependency_overrides[get_jwt_payload] = override_get_jwt_payload

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def seeded_chat(fake_db: FakeAsyncSession) -> dict[str, str]:
    conversation_id = str(uuid.uuid4())
    answer_message_id = str(uuid.uuid4())
    user_message_id = str(uuid.uuid4())

    fake_db.conversations[conversation_id] = {
        "id": conversation_id,
        "user_id": str(TEST_USER_ID),
    }
    fake_db.chat_messages[answer_message_id] = {
        "id": answer_message_id,
        "conversation_id": conversation_id,
        "role": "assistant",
        "content": "Assistant answer",
    }
    fake_db.chat_messages[user_message_id] = {
        "id": user_message_id,
        "conversation_id": conversation_id,
        "role": "user",
        "content": "User question",
    }
    return {
        "conversation_id": conversation_id,
        "answer_message_id": answer_message_id,
        "user_message_id": user_message_id,
    }


def test_submit_feedback_success_and_snapshot_update(client: TestClient, fake_db: FakeAsyncSession, seeded_chat: dict[str, str]):
    response = client.post(
        FEEDBACK_ENDPOINT,
        json={
            "answer_message_id": seeded_chat["answer_message_id"],
            "conversation_id": seeded_chat["conversation_id"],
            "sentiment": "down",
            "reason_code": "missing_citation",
            "comment": "Need stronger citation grounding.",
            "system_scope": "Liquefaction",
            "area_scope": "Liquefaction",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer_message_id"] == seeded_chat["answer_message_id"]
    assert payload["snapshot"]["feedback_count"] == 1
    assert payload["snapshot"]["negative_count"] == 1
    assert payload["snapshot"]["positive_count"] == 0
    assert payload["snapshot"]["is_flagged"] is False
    assert len(fake_db.answer_feedback_events) == 1


def test_submit_feedback_validation_failure_for_non_assistant_target(
    client: TestClient,
    seeded_chat: dict[str, str],
):
    response = client.post(
        FEEDBACK_ENDPOINT,
        json={
            "answer_message_id": seeded_chat["user_message_id"],
            "conversation_id": seeded_chat["conversation_id"],
            "sentiment": "up",
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "INVALID_FEEDBACK_TARGET"


def test_feedback_metrics_summary_basics(client: TestClient, fake_db: FakeAsyncSession, seeded_chat: dict[str, str]):
    second_answer_id = str(uuid.uuid4())
    fake_db.chat_messages[second_answer_id] = {
        "id": second_answer_id,
        "conversation_id": seeded_chat["conversation_id"],
        "role": "assistant",
        "content": "Another assistant answer",
    }

    for _ in range(3):
        submit_response = client.post(
            FEEDBACK_ENDPOINT,
            json={
                "answer_message_id": seeded_chat["answer_message_id"],
                "conversation_id": seeded_chat["conversation_id"],
                "sentiment": "down",
                "reason_code": "incorrect",
                "system_scope": "Liquefaction",
                "area_scope": "Liquefaction",
            },
        )
        assert submit_response.status_code == 200

    up_response = client.post(
        FEEDBACK_ENDPOINT,
        json={
            "answer_message_id": second_answer_id,
            "conversation_id": seeded_chat["conversation_id"],
            "sentiment": "up",
            "reason_code": "helpful",
            "system_scope": "Liquefaction",
            "area_scope": "Liquefaction",
        },
    )
    assert up_response.status_code == 200

    async def override_reviewer_payload():
        return {"sub": str(TEST_USER_ID), "role": "plantig_reviewer", "scope": [CHAT_READ_SCOPE]}

    app.dependency_overrides[get_jwt_payload] = override_reviewer_payload
    try:
        metrics_response = client.get(
            "/api/v1/chat/feedback/metrics",
            params={"window_days": 30, "system_scope": "Liquefaction", "area_scope": "Liquefaction"},
        )
    finally:
        # restore default user role for any later tests
        async def override_user_payload():
            return {"sub": str(TEST_USER_ID), "role": "plantig_user", "scope": [CHAT_READ_SCOPE]}

        app.dependency_overrides[get_jwt_payload] = override_user_payload

    assert metrics_response.status_code == 200
    payload = metrics_response.json()
    assert payload["total_feedback_events"] == 4
    assert payload["positive_feedback_events"] == 1
    assert payload["negative_feedback_events"] == 3
    assert payload["flagged_answers"] == 1
    assert any(item["reason_code"] == "incorrect" and item["count"] == 3 for item in payload["reason_breakdown"])


def test_feedback_metrics_summary_with_null_scopes(
    client: TestClient,
    fake_db: FakeAsyncSession,
    seeded_chat: dict[str, str],
):
    second_answer_id = str(uuid.uuid4())
    fake_db.chat_messages[second_answer_id] = {
        "id": second_answer_id,
        "conversation_id": seeded_chat["conversation_id"],
        "role": "assistant",
        "content": "Scoped and unscoped answer",
    }

    down_response = client.post(
        FEEDBACK_ENDPOINT,
        json={
            "answer_message_id": seeded_chat["answer_message_id"],
            "conversation_id": seeded_chat["conversation_id"],
            "sentiment": "down",
            "reason_code": "incorrect",
        },
    )
    assert down_response.status_code == 200

    up_response = client.post(
        FEEDBACK_ENDPOINT,
        json={
            "answer_message_id": second_answer_id,
            "conversation_id": seeded_chat["conversation_id"],
            "sentiment": "up",
            "reason_code": "helpful",
            "system_scope": "Liquefaction",
            "area_scope": "Liquefaction",
        },
    )
    assert up_response.status_code == 200

    async def override_reviewer_payload():
        return {"sub": str(TEST_USER_ID), "role": "plantig_reviewer", "scope": [CHAT_READ_SCOPE]}

    app.dependency_overrides[get_jwt_payload] = override_reviewer_payload
    try:
        metrics_response = client.get(
            "/api/v1/chat/feedback/metrics",
            params={"window_days": 30},
        )
    finally:
        async def override_user_payload():
            return {"sub": str(TEST_USER_ID), "role": "plantig_user", "scope": [CHAT_READ_SCOPE]}

        app.dependency_overrides[get_jwt_payload] = override_user_payload

    assert metrics_response.status_code == 200
    payload = metrics_response.json()
    assert payload["total_feedback_events"] == 2
    assert payload["positive_feedback_events"] == 1
    assert payload["negative_feedback_events"] == 1
    assert payload["flagged_answers"] == 0
    assert any(item["reason_code"] == "incorrect" and item["count"] == 1 for item in payload["reason_breakdown"])
    assert any(item["reason_code"] == "helpful" and item["count"] == 1 for item in payload["reason_breakdown"])


def test_chat_query_contract_remains_compatible(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_process_query(**_kwargs):
        return ChatQueryResponse(
            message_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            content="Compatibility response",
            citations=[],
            timestamp=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(chat_service_module.ChatService, "process_query", fake_process_query)

    response = client.post("/api/v1/chat/query", json={"query": "Compatibility check"})
    assert response.status_code == 200
    assert response.json()["content"] == "Compatibility response"
