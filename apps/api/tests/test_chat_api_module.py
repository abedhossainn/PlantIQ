"""Unit tests for app.api.chat module."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import app.api.chat as chat_api


@pytest.mark.asyncio
async def test_error_detail_includes_extra_fields():
    detail = chat_api._error_detail("E_CODE", "boom", {"x": 1})
    assert detail == {"code": "E_CODE", "message": "boom", "x": 1}


@pytest.mark.asyncio
async def test_chat_query_success(monkeypatch):
    expected = {"answer": "ok"}

    async def _fake_process_query(**_kwargs):
        return expected

    monkeypatch.setattr(chat_api.ChatService, "process_query", _fake_process_query)

    out = await chat_api.chat_query(
        request=object(),
        current_user_id="u1",
        jwt_payload={"role": "user"},
        db=object(),
    )
    assert out == expected


@pytest.mark.asyncio
async def test_chat_query_scope_access_denied_maps_403(monkeypatch):
    async def _fake_process_query(**_kwargs):
        raise chat_api.ScopeAccessDenied({"code": "SCOPE_ACCESS_DENIED"})

    monkeypatch.setattr(chat_api.ChatService, "process_query", _fake_process_query)

    with pytest.raises(HTTPException) as exc:
        await chat_api.chat_query(object(), "u1", {"role": "user"}, object())

    assert exc.value.status_code == 403
    assert exc.value.detail == {"code": "SCOPE_ACCESS_DENIED"}


@pytest.mark.asyncio
async def test_chat_query_llm_unavailable_maps_503(monkeypatch):
    async def _fake_process_query(**_kwargs):
        raise chat_api.LLMUnavailableError("down")

    monkeypatch.setattr(chat_api.ChatService, "process_query", _fake_process_query)

    with pytest.raises(HTTPException) as exc:
        await chat_api.chat_query(object(), "u1", {"role": "user"}, object())

    assert exc.value.status_code == 503
    assert "Chat generation unavailable" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_chat_query_generic_exception_maps_500(monkeypatch):
    async def _fake_process_query(**_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(chat_api.ChatService, "process_query", _fake_process_query)

    with pytest.raises(HTTPException) as exc:
        await chat_api.chat_query(object(), "u1", {"role": "user"}, object())

    assert exc.value.status_code == 500
    assert "Failed to process query" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_chat_query_stream_scope_denied_maps_403(monkeypatch):
    async def _fake_preflight(**_kwargs):
        raise chat_api.ScopeAccessDenied({"code": "SCOPE_ACCESS_DENIED"})

    monkeypatch.setattr(chat_api.ChatService, "preflight_scope_check", _fake_preflight)

    with pytest.raises(HTTPException) as exc:
        await chat_api.chat_query_stream(object(), "u1", {"role": "user"}, object())

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_chat_query_stream_builds_sse_response(monkeypatch):
    async def _fake_preflight(**_kwargs):
        return None

    async def _fake_stream(**_kwargs):
        yield {"event": "token", "content": "A"}
        yield {"event": "token", "content": "B"}

    def _fake_encode(event):
        return f"encoded:{event['content']}"

    def _fake_create(gen):
        return gen

    monkeypatch.setattr(chat_api.ChatService, "preflight_scope_check", _fake_preflight)
    monkeypatch.setattr(chat_api.ChatService, "process_query_stream", _fake_stream)
    monkeypatch.setattr(chat_api, "encode_sse_event", _fake_encode)
    monkeypatch.setattr(chat_api, "create_sse_response", _fake_create)

    out = await chat_api.chat_query_stream(object(), "u1", {"role": "user"}, object())
    collected = []
    async for item in out:
        collected.append(item)
    assert collected == ["encoded:A", "encoded:B"]


@pytest.mark.asyncio
async def test_submit_chat_feedback_success(monkeypatch):
    expected = {"accepted": True}

    async def _fake_submit_feedback(**_kwargs):
        return expected

    monkeypatch.setattr(chat_api.AnswerFeedbackService, "submit_feedback", _fake_submit_feedback)

    out = await chat_api.submit_chat_feedback(object(), "u1", {"role": "user"}, object())
    assert out == expected


@pytest.mark.asyncio
async def test_submit_chat_feedback_service_error_maps_status(monkeypatch):
    async def _fake_submit_feedback(**_kwargs):
        raise chat_api.FeedbackServiceError(status_code=422, code="BAD", message="invalid")

    monkeypatch.setattr(chat_api.AnswerFeedbackService, "submit_feedback", _fake_submit_feedback)

    with pytest.raises(HTTPException) as exc:
        await chat_api.submit_chat_feedback(object(), "u1", {"role": "user"}, object())

    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "BAD", "message": "invalid"}


@pytest.mark.asyncio
async def test_submit_chat_feedback_generic_error_maps_500(monkeypatch):
    async def _fake_submit_feedback(**_kwargs):
        raise RuntimeError("oops")

    monkeypatch.setattr(chat_api.AnswerFeedbackService, "submit_feedback", _fake_submit_feedback)

    with pytest.raises(HTTPException) as exc:
        await chat_api.submit_chat_feedback(object(), "u1", {"role": "user"}, object())

    assert exc.value.status_code == 500
    assert exc.value.detail["code"] == "FEEDBACK_SUBMISSION_FAILED"


@pytest.mark.asyncio
async def test_get_feedback_metrics_role_denied_maps_403():
    with pytest.raises(HTTPException) as exc:
        await chat_api.get_chat_feedback_metrics(
            window_days=30,
            system_scope=None,
            area_scope=None,
            jwt_payload={"role": "user"},
            db=object(),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "METRICS_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_get_feedback_metrics_success_for_admin(monkeypatch):
    expected = {"summary": 1}

    async def _fake_metrics(**_kwargs):
        return expected

    monkeypatch.setattr(chat_api.AnswerFeedbackService, "get_metrics_summary", _fake_metrics)

    out = await chat_api.get_chat_feedback_metrics(
        window_days=30,
        system_scope="LNG",
        area_scope="OPS",
        jwt_payload={"role": "admin"},
        db=object(),
    )
    assert out == expected


@pytest.mark.asyncio
async def test_get_feedback_metrics_generic_error_maps_500(monkeypatch):
    async def _fake_metrics(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(chat_api.AnswerFeedbackService, "get_metrics_summary", _fake_metrics)

    with pytest.raises(HTTPException) as exc:
        await chat_api.get_chat_feedback_metrics(
            window_days=30,
            system_scope=None,
            area_scope=None,
            jwt_payload={"role": "reviewer"},
            db=object(),
        )
    assert exc.value.status_code == 500
    assert exc.value.detail["code"] == "METRICS_QUERY_FAILED"