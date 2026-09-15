"use client";

/**
 * PipelineTrace
 *
 * Renders a CI-pipeline–style execution trace for a completed advisor run,
 * using ONLY real data from RunRecord. No timing is simulated or inferred.
 *
 * What we know per run (from the observability table):
 *   total_latency_s  — total wall-clock time for the whole run
 *   retry_count      — how many LLM retries occurred across the run
 *   grounding_passed — whether the grounding check passed / failed / didn't run
 *   model_used       — which LLM model handled the final response
 *
 * What we do NOT have per run:
 *   Per-node latency — the backend records one row per run, not per node.
 *   Which specific nodes retried — retry_count is run-total.
 *
 * Design decisions:
 *   - All pipeline nodes are shown in order (the graph topology is fixed).
 *   - The grounding node gets a real pass/fail annotation from grounding_passed.
 *   - Retries are annotated as a run-level badge, not pinned to a specific node,
 *     because we genuinely don't know which node retried.
 *   - Per-node timing boxes are NOT shown because we don't have that data.
 *     Only the total latency is shown, on the final node.
 *   - Nodes are connected by thin lines, matching the StageProgress visual language.
 */

import type { RunRecord } from "@/lib/types";
import { ORDERED_STAGES } from "@/lib/types";

// The stages that appear in a completed run (Initializing is synthetic — the
// backend never emits it as a node label, it's just the initial UI state).
// We skip it in the trace and show only the real graph nodes.
const PIPELINE_NODES = ORDERED_STAGES.filter((s) => s !== "Initializing");

interface Props {
  run: RunRecord;
}

function formatLatency(s: number | null): string {
  if (s == null) return "—";
  if (s < 1) return `${Math.round(s * 1000)}ms`;
  return `${s.toFixed(1)}s`;
}

// Which node index is the grounding check
const GROUNDING_IDX = PIPELINE_NODES.findIndex(
  (s) => s === "Checking recommendation consistency"
);

export function PipelineTrace({ run }: Props) {
  const hasRetries = (run.retry_count ?? 0) > 0;

  return (
    <div className="py-3 px-1">
      {/* ── Run-level metadata strip ── */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 mb-4 pl-1">
        {run.model_used && (
          <span className="font-mono text-xs text-ink-dim">
            <span className="text-ink-muted">model</span>{" "}
            <span className="text-ink">{run.model_used}</span>
          </span>
        )}
        <span className="font-mono text-xs text-ink-dim">
          <span className="text-ink-muted">total</span>{" "}
          <span className="text-ink tabular-nums">
            {formatLatency(run.total_latency_s)}
          </span>
        </span>
        {hasRetries && (
          <span className="font-mono text-xs tabular-nums">
            <span
              className="inline-block px-1.5 py-0.5 border"
              style={{
                borderColor: "rgba(232,163,61,0.35)",
                color: "rgba(232,163,61,0.85)",
              }}
            >
              {run.retry_count}{" "}
              {run.retry_count === 1 ? "retry" : "retries"}
            </span>
          </span>
        )}
      </div>

      {/* ── Node sequence ── */}
      <ol className="space-y-0" aria-label="pipeline execution trace">
        {PIPELINE_NODES.map((stage, idx) => {
          const isGrounding = idx === GROUNDING_IDX;
          const isLast = idx === PIPELINE_NODES.length - 1;

          // Grounding annotation — only when we have real data
          const groundingAnnotation =
            isGrounding && run.grounding_passed != null
              ? run.grounding_passed
                ? "pass"
                : "review"
              : null;

          return (
            <li key={stage} className="flex items-stretch gap-3">
              {/* ── Left column: dot + connector ── */}
              <div className="flex flex-col items-center shrink-0 w-4">
                {/* Node dot */}
                <div
                  className="w-2 h-2 rounded-full mt-2 shrink-0"
                  style={{
                    backgroundColor:
                      isGrounding && run.grounding_passed === false
                        ? "rgba(232,163,61,0.35)"
                        : "rgba(232,163,61,0.7)",
                  }}
                  aria-hidden
                />
                {/* Connector line to next node */}
                {!isLast && (
                  <div
                    className="w-px flex-1 mt-0.5"
                    style={{ backgroundColor: "rgba(237,237,234,0.16)" }}
                    aria-hidden
                  />
                )}
              </div>

              {/* ── Right column: label + annotation ── */}
              <div className="flex items-center gap-2 py-1.5 min-w-0 flex-1">
                <span className="font-mono text-xs text-ink-dim leading-tight">
                  {stage}
                </span>

                {/* Grounding result badge — real data only */}
                {groundingAnnotation != null && (
                  <span
                    className="font-mono text-[10px] px-1.5 py-0.5 border shrink-0"
                    style={
                      groundingAnnotation === "pass"
                        ? {
                            borderColor: "rgba(232,163,61,0.4)",
                            color: "rgba(232,163,61,0.9)",
                          }
                        : {
                            borderColor: "rgba(232,163,61,0.2)",
                            color: "rgba(232,163,61,0.45)",
                          }
                    }
                    title={
                      groundingAnnotation === "pass"
                        ? "Consistency check passed"
                        : "Consistency check flagged issues — see run result"
                    }
                  >
                    {groundingAnnotation}
                  </span>
                )}

                {/* Total latency on the last node — only real data */}
                {isLast && run.total_latency_s != null && (
                  <span className="font-mono text-[10px] text-ink-dim tabular-nums ml-auto shrink-0">
                    {formatLatency(run.total_latency_s)}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
