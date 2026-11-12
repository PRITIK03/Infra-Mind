"""Allowlist the fields published under a repository job's share capability."""

import math
import re
from typing import Any


_INSTANCE = re.compile(r"(?:db\.|cache\.)?[a-z][a-z0-9-]{0,16}\.[a-z0-9-]{1,16}", re.ASCII)
_DATABASE_ENGINES = frozenset({"PostgreSQL", "MySQL", "MariaDB", "Oracle", "SQL Server", "Aurora PostgreSQL", "Aurora MySQL"})
_CACHE_ENGINES = frozenset({"Redis", "Valkey", "Memcached"})
_BALANCERS = frozenset({"Application Load Balancer", "Network Load Balancer", "ALB", "NLB"})


def repository_share_result(result: dict[str, Any]) -> dict[str, Any] | None:
    original = result.get("system_design_recommendation")
    if not isinstance(original, dict):
        return None
    shared: dict[str, Any] = {
        "architecture_summary": "Selected AWS resources and estimated costs from the completed analysis.",
    }
    for tier in ("compute", "database", "cache", "load_balancer"):
        source = original.get(tier)
        if not isinstance(source, dict):
            return None
        public: dict[str, Any] = {"why": "See the selected resources for this tier."}
        if tier != "compute":
            public["needed"] = source.get("needed") is True
        if tier != "load_balancer":
            instance = source.get("recommended_instance")
            if isinstance(instance, str) and _INSTANCE.fullmatch(instance):
                public["recommended_instance"] = instance
            elif tier == "compute":
                public["recommended_instance"] = "Not available"
            public["assumptions"] = []
            confidence = source.get("confidence")
            public["confidence"] = confidence if confidence in ("low", "medium", "high") else "low"
        if tier == "database" and isinstance(source.get("engine_suggestion"), str) and source["engine_suggestion"] in _DATABASE_ENGINES:
            public["engine_suggestion"] = source["engine_suggestion"]
        if tier == "cache" and isinstance(source.get("engine"), str) and source["engine"] in _CACHE_ENGINES:
            public["engine"] = source["engine"]
        if tier == "load_balancer" and isinstance(source.get("load_balancer_type"), str) and source["load_balancer_type"] in _BALANCERS:
            public["load_balancer_type"] = source["load_balancer_type"]
        shared[tier] = public
    if isinstance(cost := original.get("estimated_cost"), dict):
        shared["estimated_cost"] = {
            key: value
            for key in ("compute_monthly_low", "compute_monthly_high", "database_monthly",
                        "cache_monthly", "total_monthly_low", "total_monthly_high")
            if type(value := cost.get(key)) in (float, int) and 0 <= value <= 10**12 and math.isfinite(value)
        }
    return {"system_design_recommendation": shared}
