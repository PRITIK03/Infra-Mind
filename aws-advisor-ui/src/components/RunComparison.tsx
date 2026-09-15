"use client";

import type { RecommendationSnapshot, RunRecord } from "@/lib/types";
import { CostBar } from "./CostBar";
import { TopologyDiagram } from "./TopologyDiagram";

interface Props {
  runs: [RunRecord, RunRecord];
  onClose: () => void;
}

function value(snapshot: RecommendationSnapshot | null, key: keyof RecommendationSnapshot): string {
  const item = snapshot?.[key];
  return item == null || item === "" ? "—" : String(item);
}

function cost(value: number | null): string {
  return value == null ? "—" : `$${value.toFixed(2)}/mo`;
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

function snapshotRecommendation(snapshot: RecommendationSnapshot | null) {
  return {
    compute: {
      recommended_instance: snapshot?.compute_instance ?? "—",
      why: "",
      assumptions: [],
      confidence: "medium" as const,
    },
    database: {
      needed: snapshot?.database_instance != null,
      recommended_instance: snapshot?.database_instance,
      engine_suggestion: snapshot?.database_engine,
      why: "",
      assumptions: [],
      confidence: "medium" as const,
    },
    cache: {
      needed: snapshot?.cache_instance != null,
      recommended_instance: snapshot?.cache_instance,
      engine: snapshot?.cache_engine as "Redis" | "Memcached" | "Valkey" | null | undefined,
      why: "",
      assumptions: [],
      confidence: "medium" as const,
    },
    load_balancer: {
      needed: snapshot?.load_balancer_type != null,
      load_balancer_type: snapshot?.load_balancer_type,
      why: "",
    },
    architecture_summary: "",
  };
}

export function RunComparison({ runs, onClose }: Props) {
  const [first, second] = runs;
  const firstSnapshot = first.recommendation_snapshot;
  const secondSnapshot = second.recommendation_snapshot;
  const rows: Array<{ label: string; key: keyof RecommendationSnapshot }> = [
    { label: "Compute instance", key: "compute_instance" },
    { label: "Database instance", key: "database_instance" },
    { label: "Database engine", key: "database_engine" },
    { label: "Cache instance", key: "cache_instance" },
    { label: "Cache engine", key: "cache_engine" },
    { label: "Load balancer", key: "load_balancer_type" },
    { label: "Minimum instances", key: "min_instances" },
    { label: "Maximum instances", key: "max_instances" },
  ];
  const firstCost = first.estimated_cost_low ?? first.estimated_cost_high;
  const secondCost = second.estimated_cost_low ?? second.estimated_cost_high;
  const costDelta = firstCost != null && secondCost != null ? secondCost - firstCost : null;
  const costDeltaLabel = costDelta == null
    ? "—"
    : `${costDelta >= 0 ? "+" : "−"}$${Math.abs(costDelta).toFixed(2)}/mo`;

  return (
    <section className="border border-border-subtle animate-fade-in" aria-label="Run comparison">
      <div className="flex items-center justify-between gap-4 border-b border-border-subtle px-4 py-3">
        <div>
          <p className="font-mono text-xs text-amber uppercase tracking-widest">run comparison</p>
          <p className="font-sans text-xs text-ink-muted mt-1">Differences are highlighted between the selected completed runs.</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="border border-border-subtle px-3 py-1.5 font-mono text-xs text-ink-dim hover:text-amber hover:border-amber/40 hover:bg-white/[0.03]"
        >
          close
        </button>
      </div>

      <div className="grid gap-4 border-b border-border-subtle p-4 md:grid-cols-2">
        {[first, second].map((run, index) => (
          <div key={run.job_id}>
            <p className="mb-2 font-mono text-[10px] uppercase tracking-widest text-ink-dim">
              run {index + 1} · {shortId(run.job_id)}
            </p>
            <TopologyDiagram
              sdr={snapshotRecommendation(run.recommendation_snapshot)}
              technicalNeeds={run.recommendation_snapshot
                ? {
                    min_instances: run.recommendation_snapshot.min_instances ?? 1,
                    max_instances: run.recommendation_snapshot.max_instances ?? 1,
                  }
                : undefined}
            />
          </div>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] border-collapse">
          <thead>
            <tr className="border-b border-border-subtle">
              <th className="text-left px-4 py-3 font-mono text-xs text-ink-dim uppercase tracking-wider">value</th>
              <th className="text-left px-4 py-3 font-mono text-xs text-ink uppercase tracking-wider">run 1 · {shortId(first.job_id)}</th>
              <th className="text-left px-4 py-3 font-mono text-xs text-ink uppercase tracking-wider">run 2 · {shortId(second.job_id)}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const firstValue = value(firstSnapshot, row.key);
              const secondValue = value(secondSnapshot, row.key);
              const changed = firstValue !== secondValue;
              return (
                <tr key={row.key} className="border-b border-border-faint">
                  <th className="text-left px-4 py-2.5 font-mono text-xs text-ink-dim font-normal">{row.label}</th>
                  <td className={`px-4 py-2.5 font-mono text-xs ${changed ? "text-amber" : "text-ink"}`}>{firstValue}</td>
                  <td className={`px-4 py-2.5 font-mono text-xs ${changed ? "text-amber" : "text-ink"}`}>{secondValue}</td>
                </tr>
              );
            })}
            <tr className="border-b border-border-faint">
              <th className="text-left px-4 py-2.5 font-mono text-xs text-ink-dim font-normal">Estimated cost</th>
              <td className="px-4 py-2.5 font-mono text-xs text-ink">{cost(firstCost)}</td>
              <td className="px-4 py-2.5 font-mono text-xs text-ink">{cost(secondCost)}</td>
            </tr>
            <tr className="border-b border-border-faint align-top">
              <th className="text-left px-4 py-2.5 font-mono text-xs text-ink-dim font-normal">Cost by tier</th>
              <td className="px-4 py-2.5">
                <CostBar
                  compute={firstSnapshot?.compute_monthly}
                  database={firstSnapshot?.database_monthly}
                  cache={firstSnapshot?.cache_monthly}
                />
              </td>
              <td className="px-4 py-2.5">
                <CostBar
                  compute={secondSnapshot?.compute_monthly}
                  database={secondSnapshot?.database_monthly}
                  cache={secondSnapshot?.cache_monthly}
                />
              </td>
            </tr>
            <tr>
              <th className="text-left px-4 py-2.5 font-mono text-xs text-ink-dim font-normal">Cost delta · run 2 − run 1</th>
              <td colSpan={2} className={`px-4 py-2.5 font-mono text-xs ${costDelta == null || costDelta === 0 ? "text-ink" : "text-amber"}`}>{costDeltaLabel}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}