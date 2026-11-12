"""
Terminal node: converts a completed SystemDesignRecommendation into Terraform
(HCL) files for review.

Orchestrates terraform file generation by delegating to resource builders in
the app.agent.nodes.terraform package.
"""
from __future__ import annotations

import re

from app.agent.nodes.terraform.cache import (
    CACHE_ENGINE_PORT_MAP,
    _cache_memcached_cluster,
    _cache_replication_group,
)
from app.agent.nodes.terraform.compute import _launch_template_asg
from app.agent.nodes.terraform.database import (
    RDS_ENGINE_PORT_MAP,
    RDS_PORT,
    _rds_engine,
    _rds_instance,
)
from app.agent.nodes.terraform.header import (
    _AI_WARNING_BLOCK,
    _comment_block,
    _header,
)
from app.agent.nodes.terraform.load_balancer import (
    _LB_ALB,
    _LB_NLB,
    _OUTPUT_LB,
    _OUTPUT_MEMCACHED,
    _OUTPUT_RDS,
    _OUTPUT_REPLICATION_GROUP,
)
from app.agent.nodes.terraform.security_groups import (
    _SG_COMPUTE_FROM_LB,
    _SG_COMPUTE_STANDALONE,
    _sg_cache_from_compute,
    _sg_db_from_compute,
    _sg_lb,
)
from app.agent.state import AgentState
from app.analysis.deployment_handoff import build_deployment_handoff
from app.models.schemas import (
    CacheEngine,
    SystemDesignRecommendation,
    TechnicalNeeds,
)

_VARIABLES_TF = """\
variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Short application name, used as a resource name prefix."
  type        = string
  default     = "app"
}

variable "app_port" {
  description = "TCP port the application listens on inside the compute tier."
  type        = number
  default     = 80
}
"""

_DATABASE_VARIABLES_TF = """\
variable "db_username" {
  description = "RDS master username. RDS manages its password in Secrets Manager."
  type        = string
  default     = "dbadmin"
}
"""


def _build_main(
    sdr: SystemDesignRecommendation,
    tn: TechnicalNeeds,
) -> str:
    compute_instance = sdr.compute.recommended_instance
    db_instance = sdr.database.recommended_instance if sdr.database.needed else None
    cache_engine = sdr.cache.engine if sdr.cache.needed else None
    cache_instance = sdr.cache.recommended_instance if cache_engine else None
    instance_type_pattern = r"[a-z0-9-]+(?:\.[a-z0-9-]+)+"
    if not re.fullmatch(instance_type_pattern, compute_instance) or any(
        instance and not re.fullmatch(instance_type_pattern, instance)
        for instance in (db_instance, cache_instance)
    ):
        raise ValueError("Invalid AWS instance type in Terraform recommendation.")

    lb_type = (sdr.load_balancer.load_balancer_type or "").lower()
    use_nlb = "network" in lb_type or "nlb" in lb_type
    parts: list[str] = []

    parts.append(_AI_WARNING_BLOCK)

    parts.append(_comment_block(sdr.architecture_summary))
    parts.append("")

    parts.append(_header(compute_instance))
    parts.append("")

    # Security groups
    if sdr.load_balancer.needed:
        parts.append(_sg_lb("var.app_port" if use_nlb else "80"))
        parts.append("")
        parts.append(_SG_COMPUTE_FROM_LB)
    else:
        parts.append(_SG_COMPUTE_STANDALONE)
    parts.append("")

    # Launch template + ASG
    parts.append(_launch_template_asg(
        min_instances=tn.min_instances,
        max_instances=tn.max_instances,
        with_target_group=sdr.load_balancer.needed,
    ))
    parts.append("")

    # Database
    if db_instance:
        db_engine = _rds_engine(sdr.database.engine_suggestion)
        db_port = RDS_ENGINE_PORT_MAP.get(db_engine, RDS_PORT)
        parts.extend([_sg_db_from_compute(db_port), ""])
        parts.append(_rds_instance(
            db_engine=db_engine,
            db_instance=db_instance,
        ))
        parts.append("")

    # Cache
    if cache_instance and cache_engine:
        parts.extend([_sg_cache_from_compute(CACHE_ENGINE_PORT_MAP[cache_engine]), ""])
        if cache_engine == CacheEngine.MEMCACHED:
            parts.append(_cache_memcached_cluster(cache_instance))
        else:
            parts.append(_cache_replication_group(
                cache_engine=cache_engine,
                cache_instance=cache_instance,
            ))
        parts.append("")

    # Load balancer
    if sdr.load_balancer.needed:
        parts.append(_LB_NLB if use_nlb else _LB_ALB)
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _build_outputs(
    sdr: SystemDesignRecommendation,
) -> str:
    parts: list[str] = []
    if sdr.load_balancer.needed:
        parts.append(_OUTPUT_LB)
    if sdr.database.needed and sdr.database.recommended_instance:
        parts.append(_OUTPUT_RDS)
    if sdr.cache.needed and sdr.cache.engine and sdr.cache.recommended_instance:
        if sdr.cache.engine == CacheEngine.MEMCACHED:
            parts.append(_OUTPUT_MEMCACHED)
        else:
            parts.append(_OUTPUT_REPLICATION_GROUP)
    if not parts:
        return ""
    return "\n".join(parts).rstrip() + "\n"


def generate_terraform(state: AgentState) -> AgentState:
    sdr: SystemDesignRecommendation | None = state.get("system_design_recommendation")
    tn: TechnicalNeeds | None = state.get("technical_needs")

    if sdr is None or tn is None:
        raise RuntimeError(
            "system_design_recommendation and technical_needs must be present "
            "before calling generate_terraform."
        )

    variables_tf = _VARIABLES_TF
    if sdr.database.needed and sdr.database.recommended_instance:
        variables_tf += "\n" + _DATABASE_VARIABLES_TF

    state["terraform_files"] = {
        "main.tf": _build_main(sdr, tn),
        "variables.tf": variables_tf,
        "outputs.tf": _build_outputs(sdr),
    }
    state["system_design_recommendation"] = sdr.model_copy(update={
        "deployment_handoff": build_deployment_handoff(state),
    })
    return state
