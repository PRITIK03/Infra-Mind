from __future__ import annotations
import os
from unittest.mock import MagicMock, patch
import pytest
from openai import RateLimitError

os.environ.setdefault("API_KEY", "primary-test-key")
os.environ.setdefault("BASE_URL", "https://example.com/v1")
os.environ.setdefault("MODEL_NAME", "test-model")
os.environ.setdefault("VANTAGE_API_KEY", "vantage-test-key")

from app.llm.client import get_chat_model
from app.llm.retry import MAX_RATE_LIMIT_ATTEMPTS, RateLimitExhaustedError, _call_with_failover


def _rle():
    r = MagicMock()
    r.status_code = 429
    r.headers = {}
    r.json.return_value = {"error": {"message": "rate limited"}}
    body = {"error": {"message": "x", "type": "requests", "code": "rate_limit_exceeded"}}
    return RateLimitError(message="rate limited", response=r, body=body)


def test_three_key_exhaustion_cycles_all_three_keys(monkeypatch):
    monkeypatch.setenv("API_KEY",   "primary-key")
    monkeypatch.setenv("API_KEY_2", "secondary-key")
    monkeypatch.setenv("API_KEY_3", "tertiary-key")
    get_chat_model.cache_clear()
    used_keys = []
    def _track(model):
        used_keys.append(model.openai_api_key.get_secret_value())
        raise _rle()
    with patch("app.llm.retry.time.sleep"):
        with pytest.raises(RateLimitExhaustedError):
            _call_with_failover(_track)
    assert len(used_keys) == MAX_RATE_LIMIT_ATTEMPTS
    cycle = ["primary-key", "secondary-key", "tertiary-key"]
    for i, k in enumerate(used_keys):
        assert k == cycle[i % 3]


def test_three_key_total_attempts_is_still_capped(monkeypatch):
    monkeypatch.setenv("API_KEY",   "primary-key")
    monkeypatch.setenv("API_KEY_2", "secondary-key")
    monkeypatch.setenv("API_KEY_3", "tertiary-key")
    get_chat_model.cache_clear()
    n = 0
    def _always_fails(model):
        nonlocal n
        n += 1
        raise _rle()
    with patch("app.llm.retry.time.sleep"):
        with pytest.raises(RateLimitExhaustedError):
            _call_with_failover(_always_fails)
    assert n == MAX_RATE_LIMIT_ATTEMPTS == 6


def test_three_key_succeeds_on_tertiary_slot(monkeypatch):
    monkeypatch.setenv("API_KEY",   "primary-key")
    monkeypatch.setenv("API_KEY_2", "secondary-key")
    monkeypatch.setenv("API_KEY_3", "tertiary-key")
    get_chat_model.cache_clear()
    att = 0
    def _fail_twice(model):
        nonlocal att
        att += 1
        if att < 3:
            raise _rle()
        return "tertiary-success"
    with patch("app.llm.retry.time.sleep") as sl:
        result = _call_with_failover(_fail_twice)
    assert result == "tertiary-success"
    assert att == 3
    assert sl.call_count == 2


def test_tertiary_absent_uses_two_key_schedule(monkeypatch):
    monkeypatch.setenv("API_KEY",   "primary-key")
    monkeypatch.setenv("API_KEY_2", "secondary-key")
    monkeypatch.delenv("API_KEY_3", raising=False)
    get_chat_model.cache_clear()
    used_keys = []
    def _track(model):
        used_keys.append(model.openai_api_key.get_secret_value())
        raise _rle()
    with patch("app.llm.retry.time.sleep"):
        with pytest.raises(RateLimitExhaustedError):
            _call_with_failover(_track)
    assert len(used_keys) == MAX_RATE_LIMIT_ATTEMPTS
    for i, k in enumerate(used_keys):
        exp = "primary-key" if i % 2 == 0 else "secondary-key"
        assert k == exp


def test_only_primary_key_configured(monkeypatch):
    monkeypatch.setenv("API_KEY", "only-primary")
    monkeypatch.delenv("API_KEY_2", raising=False)
    monkeypatch.delenv("API_KEY_3", raising=False)
    get_chat_model.cache_clear()
    used_keys = []
    def _track(model):
        used_keys.append(model.openai_api_key.get_secret_value())
        raise _rle()
    with patch("app.llm.retry.time.sleep"):
        with pytest.raises(RateLimitExhaustedError):
            _call_with_failover(_track)
    assert len(used_keys) == MAX_RATE_LIMIT_ATTEMPTS
    assert all(k == "only-primary" for k in used_keys)
