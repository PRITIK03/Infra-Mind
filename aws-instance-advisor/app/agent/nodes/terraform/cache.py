"""
Cache resource builder (ElastiCache Cluster / Replication Group) and engine mappings.
"""
from __future__ import annotations

from app.models.schemas import CacheEngine

REDIS_PORT = 6379
MEMCACHED_PORT = 11211
VALKEY_PORT = 6379


CACHE_ENGINE_PORT_MAP: dict[CacheEngine, int] = {
    CacheEngine.REDIS: REDIS_PORT,
    CacheEngine.VALKEY: VALKEY_PORT,
    CacheEngine.MEMCACHED: MEMCACHED_PORT,
}


def _cache_memcached_cluster(cache_instance: str) -> str:
    return f"""\
resource "aws_elasticache_cluster" "app" {{
  cluster_id = "${{var.app_name}}-cache"
  engine = "memcached"
  node_type = "{cache_instance}"
  num_cache_nodes = 1
  parameter_group_name = "default.memcached1.6"
  port = {MEMCACHED_PORT}
  security_group_ids = [aws_security_group.cache.id]
}}
"""


def _cache_replication_group(
    *,
    cache_engine: CacheEngine,
    cache_instance: str,
) -> str:
    engine = cache_engine.value.lower()
    engine_version = "7.2" if cache_engine == CacheEngine.VALKEY else "7.1"
    return f"""\
resource "aws_elasticache_replication_group" "app" {{
  replication_group_id = "${{var.app_name}}-cache"
  description = "Cache tier for ${{var.app_name}}"
  engine = "{engine}"
  engine_version = "{engine_version}"
  node_type = "{cache_instance}"
  num_cache_clusters = 1
  parameter_group_name = "default.{engine}7"
  port = {CACHE_ENGINE_PORT_MAP[cache_engine]}
  security_group_ids = [aws_security_group.cache.id]
}}
"""
