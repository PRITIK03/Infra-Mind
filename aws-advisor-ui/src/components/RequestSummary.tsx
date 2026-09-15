"use client";

import type { TechnicalNeeds, UserRequirements } from "@/lib/types";
import { formatConcurrency } from "@/lib/reportMarkdown";

interface Props {
  tn: TechnicalNeeds;
  requirements?: UserRequirements;
  repoAnalysisNote?: string | null;
}

function _label(label: string) {
  return (
    <span className="font-mono text-xs text-ink-dim uppercase tracking-wider">
      {label}
    </span>
  );
}

export function RequestSummary({ tn, requirements, repoAnalysisNote }: Props) {
  return (
    <aside className="min-w-0" aria-label="request summary">
      <div>
        <div className="flex items-center gap-2 mb-4">
          <span className="font-mono text-xs text-ink-muted uppercase tracking-widest">
            request summary
          </span>
          <span className="flex-1 border-t border-border-subtle" />
        </div>

        <dl className="grid gap-3">
          <div>
            {_label("estimated concurrency")}
            <dd className="font-mono text-sm text-ink mt-0.5">
              {formatConcurrency(tn.estimated_concurrency, requirements?.workload_type)}
            </dd>
          </div>

          {requirements?.requests_per_second != null && (
            <div>
              {_label("stated requests / second")}
              <dd className="font-mono text-sm text-ink mt-0.5">
                {requirements.requests_per_second} RPS
              </dd>
            </div>
          )}

          {requirements?.registered_users != null && (
            <div>
              {_label("stated registered users")}
              <dd className="font-mono text-sm text-ink mt-0.5">
                {requirements.registered_users.toLocaleString("en-US")}
              </dd>
            </div>
          )}

          <div>
            {_label("traffic pattern")}
            <dd className="font-sans text-sm text-ink mt-0.5">
              {tn.traffic_pattern || "unknown"}
            </dd>
          </div>

          <div>
            {_label("resource profile")}
            <dd className="font-sans text-sm text-ink mt-0.5">
              {tn.resource_profile || "unknown"}
            </dd>
          </div>

          <div className="flex justify-between">
            <span className="font-mono text-xs text-ink-dim uppercase tracking-wider">
              gpu required
            </span>
            <span className="font-mono text-sm text-ink">
              {tn.requires_gpu ? "yes" : "no"}
            </span>
          </div>

          <div className="flex justify-between">
            <span className="font-mono text-xs text-ink-dim uppercase tracking-wider">
              min / max instances
            </span>
            <span className="font-mono text-sm text-ink">
              {tn.min_instances} / {tn.max_instances}
            </span>
          </div>

          <div>
            {_label("scaling")}
            <dd className="font-sans text-sm text-ink mt-0.5">
              {tn.scaling_recommendation}
            </dd>
          </div>

          {tn.needs_database !== undefined && (
            <div className="flex justify-between">
              <span className="font-mono text-xs text-ink-dim uppercase tracking-wider">
                database
              </span>
              <span className="font-mono text-sm text-ink">
                {tn.needs_database ? "yes" : "no"}
              </span>
            </div>
          )}

          {tn.needs_cache !== undefined && (
            <div className="flex justify-between">
              <span className="font-mono text-xs text-ink-dim uppercase tracking-wider">
                cache
              </span>
              <span className="font-mono text-sm text-ink">
                {tn.needs_cache ? "yes" : "no"}
              </span>
            </div>
          )}
        </dl>
        {repoAnalysisNote && (
          <p className="mt-5 border-l border-border-subtle pl-3 font-sans text-xs leading-relaxed text-ink-dim">
            Note: repository analysis was requested but unavailable; recommendation is based on stated requirements only.
          </p>
        )}
      </div>
    </aside>
  );
}
