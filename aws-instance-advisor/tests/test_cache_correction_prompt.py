from __future__ import annotations
import os
from unittest.mock import MagicMock, patch
import pytest

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("BASE_URL", "https://example.com/v1")
os.environ.setdefault("MODEL_NAME", "test-model")
os.environ.setdefault("VANTAGE_API_KEY", "test-key")

from app.agent.nodes._recommendation_utils import (
    allowed_cache_pairs,
    cache_correction_prompt,
    invalid_cache_pairs,
)
from app.models.schemas import (
    CacheCandidate,
    CacheEngine,
    CacheRecommendation,
)


def _make_candidates():
    """Build a realistic set of cache candidates with multiple engines."""
    return [
        CacheCandidate(instance_type="cache.t3.small", family="Standard", engine=CacheEngine.REDIS, vcpu=2, memory_gib=1.37),
        CacheCandidate(instance_type="cache.t3.medium", family="Standard", engine=CacheEngine.REDIS, vcpu=2, memory_gib=3.09),
        CacheCandidate(instance_type="cache.m5.large", family="Standard", engine=CacheEngine.MEMCACHED, vcpu=2, memory_gib=6.38),
        CacheCandidate(instance_type="cache.r5.large", family="Memory optimized", engine=CacheEngine.VALKEY, vcpu=2, memory_gib=13.07),
    ]


def test_cache_correction_prompt_enumerates_all_valid_pairs():
    """
    The retry prompt sent after a cache-pair validation failure must
    explicitly list every valid (instance_type, engine) pair from the
    candidate set -- not just a generic rejection message.
    """
    candidates = _make_candidates()
    pairs = [(c.instance_type, c.engine) for c in candidates]

    retry_prompt = cache_correction_prompt(
        "base prompt text",
        invalid_descriptions=["'cache.t3.micro' with engine 'redis'"],
        allowed_pairs=pairs,
    )

    # Must contain every valid pair from the candidate set
    for c in candidates:
        assert c.instance_type in retry_prompt, (
            f"Valid pair {c.instance_type} missing from retry prompt"
        )
        assert c.engine.value in retry_prompt, (
            f"Engine {c.engine.value} missing from retry prompt"
        )

    # Must contain the original base prompt (correction is additive)
    assert "base prompt text" in retry_prompt

    # Must mention that the previous choice was invalid
    assert "not a valid" in retry_prompt.lower()

    # Must contain the directive to choose from the list
    assert "MUST choose" in retry_prompt


def test_invalid_cache_pair_detected():
    """An invalid (instance_type, engine) pair is caught by invalid_cache_pairs."""
    candidates = _make_candidates()
    pairs = allowed_cache_pairs(candidates)

    # Valid pair: cache.t3.small + REDIS exists in candidates
    good = CacheRecommendation(
        needed=True,
        recommended_instance="cache.t3.small",
        engine=CacheEngine.REDIS,
        why="test",
        confidence="high",
    )
    assert invalid_cache_pairs(good, pairs) == []

    # Invalid pair: cache.t3.small + MEMCACHED does NOT exist in candidates
    bad = CacheRecommendation(
        needed=True,
        recommended_instance="cache.t3.small",
        engine=CacheEngine.MEMCACHED,
        why="test",
        confidence="high",
    )
    result = invalid_cache_pairs(bad, pairs)
    assert len(result) > 0
    assert "cache.t3.small" in result[0]


def test_allowed_cache_pairs_builds_correct_set():
    """allowed_cache_pairs returns the right set of (instance_type, engine) tuples."""
    candidates = _make_candidates()
    pairs = allowed_cache_pairs(candidates)
    assert len(pairs) == len(candidates)
    assert ("cache.t3.small", CacheEngine.REDIS) in pairs
    assert ("cache.m5.large", CacheEngine.MEMCACHED) in pairs
    assert ("cache.r5.large", CacheEngine.VALKEY) in pairs
    # Invalid combo should NOT be in the set
    assert ("cache.t3.small", CacheEngine.MEMCACHED) not in pairs
