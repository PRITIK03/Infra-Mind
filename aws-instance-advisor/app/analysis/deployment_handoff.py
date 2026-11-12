"""Concrete deployment work derived from existing inputs and the emitted scaffold.

No model calls, network requests, or claims that the application is deployed.
"""

from app.agent.state import AgentState
from app.models.schemas import DeploymentAction, DeploymentHandoff, WorkloadType


def build_deployment_handoff(state: AgentState) -> DeploymentHandoff:
    sdr = state["system_design_recommendation"]
    needs = state["technical_needs"]
    requirements = state.get("requirements")
    repository = state.get("repository_report")
    workload = requirements.workload_type if requirements else None
    database_target = requirements.database_engine if requirements else None
    if database_target is None and repository:
        stores = sorted(set(repository.configured_databases) - {"Redis"})
        if stores:
            database_target = ", ".join(stores)
    resources = [f"EC2 {sdr.compute.recommended_instance} · Auto Scaling group {needs.min_instances}–{needs.max_instances}"]
    if sdr.database.needed and sdr.database.recommended_instance:
        resources.append(f"RDS {sdr.database.engine_suggestion or 'PostgreSQL'} · {sdr.database.recommended_instance}")
    if sdr.cache.needed and sdr.cache.engine and sdr.cache.recommended_instance:
        resources.append(f"ElastiCache {sdr.cache.engine.value} · {sdr.cache.recommended_instance}")
    if sdr.load_balancer.needed:
        kind = (sdr.load_balancer.load_balancer_type or "").lower()
        resources.append("Network Load Balancer" if "network" in kind or "nlb" in kind else "Application Load Balancer")

    actions = [
        DeploymentAction(
            id="export-scope", phase="before_apply", title="Review the infrastructure scaffold",
            detail="Terraform defines infrastructure only. CloudFormation export is not available. "
            "Run terraform init, validate and plan in the target account; review costs and changes before applying. "
            "Store state in an encrypted backend with access controls and locking.",
        ),
        DeploymentAction(
            id="network", phase="before_apply", title="Choose the region and network",
            detail="The scaffold uses the account's default VPC and default subnets, with us-east-1 as the default region. "
            "Confirm regional instance availability, design private placement for data and compute, "
            "and review public ingress, outbound access and security groups.",
        ),
        DeploymentAction(
            id="application", phase="before_apply", title="Supply the application and startup process",
            detail="EC2 starts stock Amazon Linux, without your application. Supply a tested image or release artifact, "
            "startup configuration, dependency installation, runtime version and app_port. "
            "Confirm CPU architecture compatibility, writable storage and health checks.",
        ),
        DeploymentAction(
            id="identity", phase="before_apply", title="Configure workload identity and secrets",
            detail="Add a least-privilege instance role and scoped access to required AWS resources. "
            "Load application secrets at runtime from a managed secret store; do not put them in source, "
            "user data or Terraform variables. Use a non-admin database identity for the application when applicable.",
        ),
        DeploymentAction(
            id="cost", phase="before_apply", title="Complete the cost estimate",
            detail="The displayed instance subtotal uses us-east-1 on-demand rates for 730 hours. "
            "It excludes load balancers, disks and database storage, I/O, backups, network transfer, NAT, "
            "logs, secrets, taxes and support. Reprice the chosen region and set a budget alert.",
        ),
    ]
    if sdr.grounding_passed is not True:
        actions.insert(0, DeploymentAction(
            id="consistency", phase="before_apply", title="Resolve the consistency review",
            detail="The recommendation has not passed its consistency check. Review the reported notes "
            "and reconcile workload requirements with the resource choices before using the export.",
        ))
    if needs.needs_database and not (sdr.database.needed and sdr.database.recommended_instance):
        actions.append(DeploymentAction(
            id="unsized-database", phase="before_apply", title="Size the missing database tier",
            detail="The workload needs a database, but no RDS instance was selected from the catalog. "
            "The export omits it and the instance subtotal is incomplete.",
        ))
    if needs.needs_cache and not (sdr.cache.needed and sdr.cache.recommended_instance and sdr.cache.engine):
        actions.append(DeploymentAction(
            id="unsized-cache", phase="before_apply", title="Size the missing cache tier",
            detail="The workload needs a cache, but no valid node and engine were selected. "
            "The export omits it and the instance subtotal is incomplete.",
        ))
    if repository and any(finding.severity == "high" for finding in repository.findings):
        actions.append(DeploymentAction(
            id="repository-security", phase="before_apply", title="Resolve high-priority repository findings",
            detail="Review the evidence in Repository analysis. Rotate any confirmed exposed credentials "
            "and fix or mitigate confirmed vulnerabilities before deployment. Static scanning is not a security certification.",
        ))
    if repository and (repository.coverage == "partial" or any(repository.skipped.values()) or repository.advisory_status != "checked"):
        actions.append(DeploymentAction(
            id="repository-coverage", phase="before_apply", title="Complete the repository review",
            detail="Review the scan's excluded files, coverage limits and dependency advisory status. "
            "Run the application's tests and dependency checks in CI; unread files and runtime behavior remain unverified.",
        ))
    if sdr.containerized_alternative and sdr.containerized_alternative.recommended:
        actions.append(DeploymentAction(
            id="container-choice", phase="before_apply", title="Choose EC2 or the container alternative",
            detail="The export provisions EC2. The Fargate task size is an alternative only; "
            "using it requires a container registry, task definition, ECS service or scheduled task, "
            "execution and task roles, networking, logging and scaling configuration.",
        ))
    if workload == WorkloadType.BATCH_PROCESSING:
        actions.append(DeploymentAction(
            id="batch", phase="before_apply", title="Define job execution and recovery",
            detail="Choose a scheduler or queue, worker concurrency, timeouts, idempotency, retries, dead-letter handling "
            "and durable checkpoints. EC2 capacity alone does not dispatch jobs. Remove public application ingress "
            "unless a worker actually serves requests; compare AWS Batch for managed scheduling.",
        ))
    if needs.max_instances > needs.min_instances:
        actions.append(DeploymentAction(
            id="scaling", phase="before_traffic", title="Configure and test automatic scaling",
            detail="The Auto Scaling group has a capacity range but no scaling policy. Choose a measured CPU, "
            "request or queue metric, configure target tracking and instance warmup, and test scale-out, scale-in "
            "and connection draining under representative load.",
        ))
    if workload == WorkloadType.ML_INFERENCE or needs.requires_gpu or (repository and repository.local_inference):
        actions.append(DeploymentAction(
            id="inference", phase="before_traffic", title="Benchmark model serving",
            detail="Measure model size, peak RAM/VRAM, cold start, throughput and latency at the intended concurrency. "
            "Verify drivers and runtime compatibility. Test batching, model caching and quantization against an "
            "accuracy baseline before choosing them; model weights and serving software are not included.",
        ))
    if sdr.database.needed and sdr.database.recommended_instance:
        actions.append(DeploymentAction(
            id="database", phase="before_traffic", title="Migrate data and test database recovery",
            detail=f"The scaffold provisions a single-AZ {sdr.database.engine_suggestion or 'PostgreSQL'} instance "
            "with managed master credentials, encryption, backups and deletion protection. "
            "Confirm engine version, schema compatibility, storage/IOPS and connection limits. Plan migrations, "
            "test restore, and choose Multi-AZ and retention from your recovery and availability targets.",
        ))
    elif database_target == "external":
        actions.append(DeploymentAction(
            id="external-database", phase="before_traffic", title="Connect the existing database",
            detail="No replacement database is provisioned. Verify private connectivity or restricted allowlists, "
            "TLS, credentials, latency, connection limits, backups and recovery with the existing provider.",
        ))
    elif database_target not in (None, "none"):
        actions.append(DeploymentAction(
            id="separate-database", phase="before_apply", title=f"Plan {database_target} persistence",
            detail="This database target is outside the generated RDS resources. Choose its hosting, durable storage, "
            "access controls and backup strategy separately. An empty EC2 host does not provide configured persistence.",
        ))
    if sdr.cache.needed:
        actions.append(DeploymentAction(
            id="cache", phase="before_traffic", title="Set cache behavior and failure handling",
            detail="Set eviction policy, TTLs, memory limits, connection security and application behavior on cache loss. "
            "The scaffold creates one cache node; choose replication and failover if the workload requires them.",
        ))
    if workload != WorkloadType.BATCH_PROCESSING:
        actions.append(DeploymentAction(
            id="ingress", phase="before_traffic", title="Configure secure application ingress",
            detail="Set the domain, DNS, TLS certificate, listener and real health-check path. "
            "The scaffold does not configure HTTPS. Decide whether authentication, WAF or request throttling "
            "is needed for the workload's exposure and abuse risks.",
        ))
    actions.extend([
        DeploymentAction(
            id="operations", phase="before_traffic", title="Add monitoring and a rollback path",
            detail="Collect application logs and workload metrics, set actionable alarms, define an owner and runbook, "
            "and test a repeatable release and rollback. Define acceptable downtime and data loss, then exercise recovery.",
        ),
        DeploymentAction(
            id="load-test", phase="before_traffic", title="Validate the workload under real load",
            detail="Benchmark representative requests or jobs, data size and burst patterns against latency, throughput "
            "and memory targets. Verify architecture-specific dependencies and persistent storage. "
            "Instance sizing is provisional until these measurements support it.",
        ),
    ])
    return DeploymentHandoff(generated_resources=resources, actions=actions)
