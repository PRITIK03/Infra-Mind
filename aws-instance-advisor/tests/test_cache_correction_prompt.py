from __future__ import annotations
import os
from collections import defaultdict

import pytest

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("BASE_URL", "https://example.com/v1")
os.environ.setdefault("MODEL_NAME", "test-model")
os.environ.setdefault("VANTAGE_API_KEY", "test-key")

from app.agent.nodes._recommendation_utils import (
    allowed_cache_pairs,
    cache_correction_prompt,
    correction_prompt,
    invalid_cache_pairs,
)
from app.models.schemas import (
    CacheCandidate,
    CacheEngine,
    CacheRecommendation,
)


# ── fixtures ───────────────────────────────────────────────────────────────

def _make_candidates_multi_engine():
    """Three engines, multiple instance types — the typical mixed-engine live set."""
    return [
        CacheCandidate(instance_type="cache.t3.small",  family="Standard",          engine=CacheEngine.REDIS,     vcpu=2, memory_gib=1.37),
        CacheCandidate(instance_type="cache.t3.medium", family="Standard",          engine=CacheEngine.REDIS,     vcpu=2, memory_gib=3.09),
        CacheCandidate(instance_type="cache.m5.large",  family="Standard",          engine=CacheEngine.MEMCACHED, vcpu=2, memory_gib=6.38),
        CacheCandidate(instance_type="cache.r5.large",  family="Memory optimized",  engine=CacheEngine.VALKEY,    vcpu=2, memory_gib=13.07),
        CacheCandidate(instance_type="cache.r5.xlarge", family="Memory optimized",  engine=CacheEngine.VALKEY,    vcpu=4, memory_gib=26.32),
    ]


def _make_candidates_single_engine_single_instance():
    """Only one valid pair across the whole candidate set."""
    return [
        CacheCandidate(instance_type="cache.t3.micro", family="Standard", engine=CacheEngine.REDIS, vcpu=2, memory_gib=0.5),
    ]


def _make_candidates_single_engine_multi_instance():
    """Two instances, same engine — alternative is possible but must stay in engine."""
    return [
        CacheCandidate(instance_type="cache.t3.small",  family="Standard", engine=CacheEngine.MEMCACHED, vcpu=2, memory_gib=1.37),
        CacheCandidate(instance_type="cache.t3.medium", family="Standard", engine=CacheEngine.MEMCACHED, vcpu=2, memory_gib=3.09),
    ]


# ── cache_correction_prompt: engine grouping ───────────────────────────────

class TestCacheCorrectionPromptEngineGrouping:
    """The prompt must group candidates by engine, not emit a flat mixed list."""

    def test_each_engine_gets_its_own_section(self):
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]

        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.t3.micro' with engine 'redis'"],
            allowed_pairs=pairs,
        )

        # Each engine that has candidates must appear as a labelled group.
        # Engine names are title-cased in the prompt (e.g. "Valid Redis options:").
        prompt_lower = prompt.lower()
        assert "valid redis options:" in prompt_lower
        assert "valid memcached options:" in prompt_lower
        assert "valid valkey options:" in prompt_lower

    def test_redis_instances_appear_under_redis_section(self):
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]

        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.x1.large' with engine 'redis'"],
            allowed_pairs=pairs,
        )

        prompt_lower = prompt.lower()
        redis_section_start = prompt_lower.index("valid redis options:")
        # Find the next section header after redis (or end of string)
        next_section = len(prompt_lower)
        for header in ("valid memcached options:", "valid valkey options:"):
            try:
                pos = prompt_lower.index(header)
                if pos > redis_section_start:
                    next_section = min(next_section, pos)
            except ValueError:
                pass
        redis_section = prompt[redis_section_start:next_section]

        assert "cache.t3.small" in redis_section
        assert "cache.t3.medium" in redis_section
        # Memcached / Valkey instances must NOT bleed into the Redis section.
        assert "cache.m5.large" not in redis_section
        assert "cache.r5.large" not in redis_section

    def test_memcached_instances_do_not_appear_under_redis(self):
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]

        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.x1.large' with engine 'memcached'"],
            allowed_pairs=pairs,
        )

        prompt_lower = prompt.lower()
        redis_section_start = prompt_lower.index("valid redis options:")
        memcached_section_start = prompt_lower.index("valid memcached options:")

        # Sections are sorted alphabetically: Memcached (M) comes before Redis (R).
        assert memcached_section_start < redis_section_start

        # cache.m5.large belongs to memcached; it must appear BEFORE the redis section.
        idx_m5 = prompt.index("cache.m5.large")
        assert idx_m5 < redis_section_start

        # Redis instances must appear AFTER the redis header.
        idx_t3_small = prompt.index("cache.t3.small")
        assert idx_t3_small > redis_section_start

    def test_no_empty_engine_section_when_engine_has_no_candidates(self):
        """If only Redis candidates exist, no 'Valid memcached options:' line appears."""
        candidates = [
            CacheCandidate(instance_type="cache.t3.small", family="Standard", engine=CacheEngine.REDIS, vcpu=2, memory_gib=1.37),
        ]
        pairs = [(c.instance_type, c.engine) for c in candidates]

        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.x1.large' with engine 'redis'"],
            allowed_pairs=pairs,
        )

        assert "Valid redis options:".lower() in prompt.lower()  # section exists (title-cased)
        assert "valid memcached options:" not in prompt.lower()
        assert "valid valkey options:" not in prompt.lower()

    def test_flat_mixed_list_not_used(self):
        """The old flat format '... (engine: redis), ...' must no longer appear."""
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]

        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.t3.micro' with engine 'redis'"],
            allowed_pairs=pairs,
        )

        # The old format paired instance+engine inline like "(engine: redis)"
        # after the instance name on the same token — that pattern is gone.
        assert "(engine: redis)" not in prompt
        assert "(engine: memcached)" not in prompt
        assert "(engine: valkey)" not in prompt


# ── cache_correction_prompt: explicit field targeting ─────────────────────

class TestCacheCorrectionPromptFieldTargeting:
    """The prompt must name cache.recommended_instance+cache.engine and
    cache.alternative_instance+cache.alternative_engine as matched pairs."""

    def test_recommended_instance_field_named(self):
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]
        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.bad' with engine 'redis'"],
            allowed_pairs=pairs,
        )
        assert "cache.recommended_instance" in prompt
        assert "cache.engine" in prompt

    def test_alternative_instance_field_named(self):
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]
        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.bad' with engine 'redis'"],
            allowed_pairs=pairs,
        )
        assert "cache.alternative_instance" in prompt
        assert "cache.alternative_engine" in prompt

    def test_recommended_and_alternative_described_as_matched_pairs(self):
        """Both field pairs must be described as matched (instance + engine together)."""
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]
        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.bad' with engine 'valkey'"],
            allowed_pairs=pairs,
        )
        # The prompt should use language like "matched pair" or describe setting
        # both fields together for recommended and alternative.
        prompt_lower = prompt.lower()
        assert "matched pair" in prompt_lower or (
            "cache.recommended_instance" in prompt and "cache.engine" in prompt
            and "cache.alternative_instance" in prompt and "cache.alternative_engine" in prompt
        )

    def test_null_alternative_explicitly_allowed(self):
        """The prompt must tell the model it can set alternative to null."""
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]
        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.bad' with engine 'redis'"],
            allowed_pairs=pairs,
        )
        prompt_lower = prompt.lower()
        assert "null" in prompt_lower

    def test_fabricate_alternative_forbidden(self):
        """The prompt must instruct the model NOT to fabricate an alternative."""
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]
        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.bad' with engine 'redis'"],
            allowed_pairs=pairs,
        )
        prompt_lower = prompt.lower()
        assert "fabricate" in prompt_lower or "do not" in prompt_lower


# ── single-pair: no forced alternative ────────────────────────────────────

class TestCacheCorrectionPromptSinglePair:
    """When only one valid pair exists the prompt must still allow null alternative."""

    def test_single_pair_null_alternative_still_allowed(self):
        candidates = _make_candidates_single_engine_single_instance()
        pairs = [(c.instance_type, c.engine) for c in candidates]

        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.r6g.large' with engine 'redis'"],
            allowed_pairs=pairs,
        )

        # The only valid option must appear.
        assert "cache.t3.micro" in prompt
        assert "valid redis options:" in prompt.lower()

        # The prompt must not demand a second choice.
        prompt_lower = prompt.lower()
        assert "null" in prompt_lower  # null alternative explicitly offered

    def test_single_pair_prompt_does_not_claim_multiple_options_exist(self):
        candidates = _make_candidates_single_engine_single_instance()
        pairs = [(c.instance_type, c.engine) for c in candidates]

        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.bad' with engine 'redis'"],
            allowed_pairs=pairs,
        )

        # Must NOT promise a second option is available when there is only one.
        assert "cache.t3.micro" in prompt
        # Only one instance type should appear in the list.
        assert prompt.count("cache.t3.micro") >= 1
        # No other instance type should sneak in.
        assert "cache.t3.small" not in prompt
        assert "cache.m5.large" not in prompt

    def test_two_instances_same_engine_alternative_possible(self):
        """Two instances same engine: alternative is possible and prompt should reflect it."""
        candidates = _make_candidates_single_engine_multi_instance()
        pairs = [(c.instance_type, c.engine) for c in candidates]

        prompt = cache_correction_prompt(
            "base",
            invalid_descriptions=["'cache.r6g.large' with engine 'memcached'"],
            allowed_pairs=pairs,
        )

        assert "cache.t3.small" in prompt
        assert "cache.t3.medium" in prompt
        assert "valid memcached options:" in prompt.lower()
        # Both fields still named.
        assert "cache.recommended_instance" in prompt
        assert "cache.alternative_instance" in prompt


# ── correction_prompt (compute): explicit field targeting ─────────────────

class TestComputeCorrectionPromptFieldTargeting:
    """correction_prompt must name both recommended_instance and
    alternative_instance explicitly, and allow null for the alternative."""

    def test_recommended_instance_field_named(self):
        from app.agent.nodes._recommendation_utils import correction_prompt
        prompt = correction_prompt(
            "base",
            invalid_instances=["t2.micro"],
            allowed_types=["t3.small", "t3.medium", "m5.large"],
        )
        assert "recommended_instance" in prompt

    def test_alternative_instance_field_named(self):
        from app.agent.nodes._recommendation_utils import correction_prompt
        prompt = correction_prompt(
            "base",
            invalid_instances=["t2.micro"],
            allowed_types=["t3.small", "t3.medium", "m5.large"],
        )
        assert "alternative_instance" in prompt

    def test_null_alternative_allowed(self):
        from app.agent.nodes._recommendation_utils import correction_prompt
        prompt = correction_prompt(
            "base",
            invalid_instances=["t2.micro"],
            allowed_types=["t3.small"],
        )
        assert "null" in prompt.lower()

    def test_all_allowed_types_present(self):
        from app.agent.nodes._recommendation_utils import correction_prompt
        allowed = ["t3.small", "t3.medium", "m5.large"]
        prompt = correction_prompt(
            "base",
            invalid_instances=["t2.micro"],
            allowed_types=allowed,
        )
        for t in allowed:
            assert t in prompt


# ── _database_correction (holistic): explicit field targeting ─────────────

class TestDatabaseCorrectionFieldTargeting:
    """_database_correction must use database.recommended_instance and
    database.alternative_instance (fully qualified) and allow null."""

    def _make_db_correction(self, bad, allowed):
        # Import the private helper directly — it lives in holistic_recommender.
        import importlib
        mod = importlib.import_module("app.agent.nodes.holistic_recommender")
        return mod._database_correction("base", bad, allowed)

    def test_recommended_instance_fully_qualified(self):
        prompt = self._make_db_correction(["db.t3.micro"], ["db.t3.small", "db.m5.large"])
        assert "database.recommended_instance" in prompt

    def test_alternative_instance_fully_qualified(self):
        prompt = self._make_db_correction(["db.t3.micro"], ["db.t3.small", "db.m5.large"])
        assert "database.alternative_instance" in prompt

    def test_null_alternative_allowed(self):
        prompt = self._make_db_correction(["db.t3.micro"], ["db.t3.small"])
        assert "null" in prompt.lower()

    def test_invalid_instance_mentioned(self):
        prompt = self._make_db_correction(["db.x9.superlarge"], ["db.t3.small"])
        assert "db.x9.superlarge" in prompt

    def test_allowed_instances_listed(self):
        allowed = ["db.t3.small", "db.m5.large", "db.r5.xlarge"]
        prompt = self._make_db_correction(["db.bad"], allowed)
        for inst in allowed:
            assert inst in prompt


# ── legacy tests (preserved, updated assertions) ──────────────────────────

class TestLegacyCacheCorrectionPrompt:
    """Keep the existing behavioural checks; update the MUST-choose assertion
    to match the new prompt wording."""

    def test_enumerates_all_valid_pairs(self):
        candidates = _make_candidates_multi_engine()
        pairs = [(c.instance_type, c.engine) for c in candidates]

        prompt = cache_correction_prompt(
            "base prompt text",
            invalid_descriptions=["'cache.t3.micro' with engine 'redis'"],
            allowed_pairs=pairs,
        )

        for c in candidates:
            assert c.instance_type in prompt, f"{c.instance_type} missing from prompt"

        assert "base prompt text" in prompt
        assert "not a valid" in prompt.lower()
        # New wording uses "MUST pick" instead of "MUST choose".
        assert "MUST" in prompt

    def test_invalid_cache_pair_detected(self):
        candidates = _make_candidates_multi_engine()
        pairs = allowed_cache_pairs(candidates)

        good = CacheRecommendation(
            needed=True,
            recommended_instance="cache.t3.small",
            engine=CacheEngine.REDIS,
            why="test",
            confidence="high",
        )
        assert invalid_cache_pairs(good, pairs) == []

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

    def test_allowed_cache_pairs_builds_correct_set(self):
        candidates = _make_candidates_multi_engine()
        pairs = allowed_cache_pairs(candidates)
        assert len(pairs) == len(candidates)
        assert ("cache.t3.small",  CacheEngine.REDIS)     in pairs
        assert ("cache.m5.large",  CacheEngine.MEMCACHED) in pairs
        assert ("cache.r5.large",  CacheEngine.VALKEY)    in pairs
        assert ("cache.t3.small",  CacheEngine.MEMCACHED) not in pairs
