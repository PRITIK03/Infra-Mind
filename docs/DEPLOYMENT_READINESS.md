# Demo and release requirements

InfraMind helps developers compare an AWS resource plan against their workload and repository evidence, then identify the work needed for deployment. The output is a sizing hypothesis and an infrastructure scaffold. A complete application deployment still requires an artifact, startup configuration, workload-specific networking and identity, and operational validation.

## What is implemented

| Capability | Current behavior |
| --- | --- |
| Public GitHub input | Resolve one commit, scan supported files within explicit bounds, report exclusions and access failures. Private repository authentication is not supported. |
| Recommendation correctness | Initial, repaired and second-model recommendations use the same catalog checks, database-target enforcement and deterministic enrichment. An unavailable consistency check stays unverified. |
| Deployment handoff | Inventory the generated resources and list work before applying infrastructure and before serving traffic. Tailor persistence, batch, inference and repository-review steps to known input. |
| Terraform | Generate EC2/ASG, optional RDS, ElastiCache and ALB/NLB. The current network uses the default VPC and subnets. |
| Report export | Show the handoff on the result, include it in Markdown and PDF, and bundle it with the web Terraform ZIP as `DEPLOYMENT.md`. |
| CloudFormation | Not implemented. A second exporter needs resource parity and independent template validation. |
| Container alternative | Offer a Fargate task size when suitable repository evidence exists. ECS resources and application images are not generated. |

The instance subtotal is not a full AWS bill. It uses us-east-1 rates for the selected instances; storage, I/O, load balancers, backups, networking, secrets, logs, taxes and support remain outside it. Verify prices and resource availability in the intended region.

## Reproducible local demo

Install the backend and frontend dependencies using the root README. Start the isolated fixture backend from `aws-instance-advisor`:

```sh
python scripts/dev_seed_and_serve.py
```

This script seeds illustrative results, substitutes external providers and disables database, Redis and Sentry connections. It binds to localhost. It is a local demo/test helper, not the production entrypoint.

Build the frontend with `NEXT_PUBLIC_API_URL=http://localhost:8000` and `NEXT_PUBLIC_SITE_URL=http://localhost:3000`, then run `npm start`. Open `/share/seed-e2e-full-stack` for a seeded result. Use `https://github.com/inframind-demo/public-service` in the form to exercise the fixture-backed repository flow. The fixture owner is intentionally intercepted locally and is not a real scan. Illustrative prices and model conclusions are not live verification.

## Restricted hosted demonstration

Use the normal backend entrypoint, the frontend's production build, and a persistent Redis instance. Keep one backend replica/worker and restrict access at the hosting ingress.

- Supply provider credentials through the host's secret manager and set the exact frontend CORS origin. CORS does not authenticate users.
- Terminate HTTPS, preserve streaming responses, disable proxy buffering for SSE and set sufficient request/idle timeouts. Exercise the polling fallback too.
- Treat original job IDs as access capabilities. Do not expose them in logs or analytics. Repository public shares intentionally omit source findings, prompts, Terraform and the deployment handoff.
- Configure provider budgets and a shared ingress quota. The in-process IP and repository limits do not provide a distributed spending cap.
- Check liveness/readiness and test a workload-only run, a repository-only run, an inaccessible repository, clarification, completed result, share and export.
- Test restart behavior. Completed jobs may survive in Redis; in-flight graph state and clarification ownership remain tied to the original worker.

## Before a public multi-tenant release

These are remaining capabilities and validation tasks, not claims of readiness:

1. Add identity, tenant ownership and authorization to jobs, history, follow-up and share lifecycle. Define retention, deletion and revocation behavior.
2. Move active execution to a durable job model with worker coordination, idempotent retries and resumable clarification. Validate multi-worker routing, restarts and interrupted external calls.
3. Enforce distributed request, concurrency and provider-spend quotas. Test cancellation, timeouts, queue pressure and abuse controls.
4. Add an operated release pipeline with secret injection, rollback, telemetry redaction, alerts, dependency scanning and tested backups/restores.
5. Validate a production deployment in its target AWS account and region, including HTTPS, private connectivity and network failure. Unit tests and Terraform validation do not prove an AWS deployment.
6. Evaluate recommendation quality against measured reference workloads. Typed region, minimum RAM/VRAM, job duration and availability/recovery constraints are still future sizing improvements.

## Infrastructure export expansion

Start with typed deployment inputs such as application artifact, runtime, port, health check, region and availability requirements. Then add configured network, identity, startup and scaling resources with scenario tests. Add CloudFormation as a second exporter over shared resource intent only when equivalent resource inventories and both formats can be validated. Keep migrations explicit for existing infrastructure.

AWS distinguishes an Auto Scaling group's capacity limits from a configured [dynamic scaling policy](https://docs.aws.amazon.com/autoscaling/ec2/userguide/as-scale-based-on-demand.html). [ECS Service Auto Scaling](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-auto-scaling.html) adjusts service task counts. The handoff makes these missing configuration steps explicit.
