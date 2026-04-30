"""Unit tests for app.api.websocket module."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocketDisconnect

import app.api.websocket as ws_api


class _FakeWS:
    def __init__(self, recv_values=None):
        self.sent = []
        self.closed = []
        self._recv_values = list(recv_values or [])

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=None, reason=None):
        self.closed.append({"code": code, "reason": reason})

    async def receive_text(self):
        if not self._recv_values:
            raise WebSocketDisconnect()
        value = self._recv_values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class _FakeResult:
    def __init__(self, found: bool):
        self._found = found

    def fetchone(self):
        return object() if self._found else None


class _FakeSession:
    def __init__(self, *, doc_found=True, conv_found=True, fail=False):
        self.doc_found = doc_found
        self.conv_found = conv_found
        self.fail = fail

    async def execute(self, query, params=None):
        if self.fail:
            raise RuntimeError("db error")
        q = str(query)
        if "SELECT id FROM documents" in q:
            return _FakeResult(self.doc_found)
        if "SELECT id FROM conversations" in q:
            return _FakeResult(self.conv_found)
        return _FakeResult(False)


class _FakeSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _session_local_factory(session):
    def _factory():
        return _FakeSessionCtx(session)

    return _factory


@pytest.mark.asyncio
async def test_send_ws_error_and_connected_helpers():
    ws = _FakeWS()
    await ws_api._send_ws_error(ws, "boom", operation="query")
    await ws_api._send_ws_connected(ws, channel="chat:1", message="ok")

    assert ws.sent[0]["type"] == "error"
    assert ws.sent[0]["operation"] == "query"
    assert ws.sent[1]["type"] == "connected"
    assert ws.sent[1]["channel"] == "chat:1"


@pytest.mark.asyncio
async def test_receive_or_heartbeat_timeout_sends_heartbeat(monkeypatch):
    ws = _FakeWS()

    async def slow_receive():
        await asyncio.sleep(0.02)
        return "ignored"

    ws.receive_text = slow_receive
    monkeypatch.setattr("app.api.websocket.settings.WS_HEARTBEAT_INTERVAL", 0.001)

    out = await ws_api._receive_or_heartbeat(ws)
    assert out is None
    assert ws.sent[-1] == {"type": "heartbeat"}


def test_parse_json_message_or_none():
    assert ws_api._parse_json_message_or_none('{"type":"ping"}') == {"type": "ping"}
    assert ws_api._parse_json_message_or_none("not-json") is None


@pytest.mark.asyncio
async def test_authorize_pipeline_socket_invalid_token(monkeypatch):
    ws = _FakeWS()
    monkeypatch.setattr(ws_api, "verify_ws_token", AsyncMock(return_value=None))

    out = await ws_api._authorize_pipeline_socket(ws, "doc1", "tok")
    assert out is None
    assert ws.closed and ws.closed[0]["code"] == 403


@pytest.mark.asyncio
async def test_authorize_pipeline_socket_forbidden_non_admin(monkeypatch):
    ws = _FakeWS()
    monkeypatch.setattr(ws_api, "verify_ws_token", AsyncMock(return_value=(uuid.uuid4(), "user")))

    out = await ws_api._authorize_pipeline_socket(ws, "doc1", "tok")
    assert out is None
    assert "admin access" in ws.closed[0]["reason"]


@pytest.mark.asyncio
async def test_authorize_pipeline_socket_no_document_access(monkeypatch):
    ws = _FakeWS()
    user_id = uuid.uuid4()
    monkeypatch.setattr(ws_api, "verify_ws_token", AsyncMock(return_value=(user_id, "admin")))
    monkeypatch.setattr(ws_api, "check_document_access", AsyncMock(return_value=False))

    out = await ws_api._authorize_pipeline_socket(ws, "doc1", "tok")
    assert out is None
    assert "No access" in ws.closed[0]["reason"]


@pytest.mark.asyncio
async def test_authorize_pipeline_socket_success(monkeypatch):
    ws = _FakeWS()
    user_id = uuid.uuid4()
    monkeypatch.setattr(ws_api, "verify_ws_token", AsyncMock(return_value=(user_id, "plantig_admin")))
    monkeypatch.setattr(ws_api, "check_document_access", AsyncMock(return_value=True))

    out = await ws_api._authorize_pipeline_socket(ws, "doc1", "tok")
    assert out == (user_id, "plantig_admin")


@pytest.mark.asyncio
async def test_authorize_chat_socket_invalid_and_no_access(monkeypatch):
    ws1 = _FakeWS()
    monkeypatch.setattr(ws_api, "verify_ws_token", AsyncMock(return_value=None))
    out1 = await ws_api._authorize_chat_socket(ws1, "c1", "tok")
    assert out1 is None

    ws2 = _FakeWS()
    uid = uuid.uuid4()
    monkeypatch.setattr(ws_api, "verify_ws_token", AsyncMock(return_value=(uid, "user")))
    monkeypatch.setattr(ws_api, "check_conversation_access", AsyncMock(return_value=False))
    out2 = await ws_api._authorize_chat_socket(ws2, "c1", "tok")
    assert out2 is None


@pytest.mark.asyncio
async def test_handle_chat_ws_message_ping_query_cancel():
    ws = _FakeWS()

    await ws_api._handle_chat_ws_message(ws, "conv1", {"type": "ping"})
    await ws_api._handle_chat_ws_message(ws, "conv1", {"type": "query", "content": "Hello"})
    await ws_api._handle_chat_ws_message(ws, "conv1", {"type": "cancel"})

    assert ws.sent[0] == {"type": "pong"}
    assert ws.sent[1]["type"] == "error" and ws.sent[1]["operation"] == "query"
    assert ws.sent[2]["type"] == "error" and ws.sent[2]["operation"] == "cancel"


@pytest.mark.asyncio
async def test_check_document_access_success_and_error(monkeypatch):
    uid = uuid.uuid4()

    monkeypatch.setattr(ws_api, "AsyncSessionLocal", _session_local_factory(_FakeSession(doc_found=True)))
    ok = await ws_api.check_document_access("doc-1", uid, "plantig_admin")
    assert ok is True

    monkeypatch.setattr(ws_api, "AsyncSessionLocal", _session_local_factory(_FakeSession(fail=True)))
    bad = await ws_api.check_document_access("doc-1", uid, "admin")
    assert bad is False


@pytest.mark.asyncio
async def test_check_conversation_access_success_and_error(monkeypatch):
    uid = uuid.uuid4()

    monkeypatch.setattr(ws_api, "AsyncSessionLocal", _session_local_factory(_FakeSession(conv_found=True)))
    ok = await ws_api.check_conversation_access("conv-1", uid)
    assert ok is True

    monkeypatch.setattr(ws_api, "AsyncSessionLocal", _session_local_factory(_FakeSession(fail=True)))
    bad = await ws_api.check_conversation_access("conv-1", uid)
    assert bad is False


@pytest.mark.asyncio
async def test_pipeline_status_websocket_happy_disconnect_flow(monkeypatch):
    ws = _FakeWS()
    manager = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock())

    monkeypatch.setattr(ws_api, "_authorize_pipeline_socket", AsyncMock(return_value=(uuid.uuid4(), "admin")))
    monkeypatch.setattr(ws_api, "get_connection_manager", lambda: manager)
    monkeypatch.setattr(ws_api, "_run_pipeline_ws_loop", AsyncMock(side_effect=WebSocketDisconnect()))

    await ws_api.pipeline_status_websocket(ws, "doc-1", token="tok")

    manager.connect.assert_awaited_once()
    manager.disconnect.assert_awaited_once()
    assert any(msg.get("type") == "connected" for msg in ws.sent)


@pytest.mark.asyncio
async def test_chat_streaming_websocket_happy_disconnect_flow(monkeypatch):
    ws = _FakeWS()
    manager = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock())

    monkeypatch.setattr(ws_api, "_authorize_chat_socket", AsyncMock(return_value=(uuid.uuid4(), "user")))
    monkeypatch.setattr(ws_api, "get_connection_manager", lambda: manager)
    monkeypatch.setattr(ws_api, "_run_chat_ws_loop", AsyncMock(side_effect=WebSocketDisconnect()))

    await ws_api.chat_streaming_websocket(ws, "conv-1", token="tok")

    manager.connect.assert_awaited_once()
    manager.disconnect.assert_awaited_once()
    assert any(msg.get("type") == "connected" for msg in ws.sent)
