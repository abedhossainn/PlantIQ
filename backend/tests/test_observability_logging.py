#!/usr/bin/env python3
"""Unit tests for logging observability helpers."""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import app.main as main_module


def test_redact_query_string_masks_sensitive_keys(monkeypatch):
    monkeypatch.setattr(main_module, "LOG_REDACTION_ENABLED", True)
    monkeypatch.setattr(main_module, "SENSITIVE_QUERY_KEYS", {"token", "password"})

    raw = "q=lng+operations&token=abc123&password=secret&limit=10"
    redacted = main_module._redact_query_string(raw)

    assert "token=%5BREDACTED%5D" in redacted
    assert "password=%5BREDACTED%5D" in redacted
    assert "q=lng+operations" in redacted
    assert "limit=10" in redacted
    assert "abc123" not in redacted
    assert "secret" not in redacted


def test_redact_query_string_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(main_module, "LOG_REDACTION_ENABLED", True)
    monkeypatch.setattr(main_module, "SENSITIVE_QUERY_KEYS", {"access_token"})

    raw = "Access_Token=topsecret&foo=bar"
    redacted = main_module._redact_query_string(raw)

    assert "Access_Token=%5BREDACTED%5D" in redacted
    assert "foo=bar" in redacted
    assert "topsecret" not in redacted


def test_redact_query_string_can_be_disabled(monkeypatch):
    monkeypatch.setattr(main_module, "LOG_REDACTION_ENABLED", False)
    monkeypatch.setattr(main_module, "SENSITIVE_QUERY_KEYS", {"token"})

    raw = "token=abc123&mode=debug"
    output = main_module._redact_query_string(raw)

    assert output == raw
