"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getRuns } from "@/lib/api";
import { PipelineTrace } from "@/components/PipelineTrace";
import { ErrorPanel } from "@/components/ErrorPanel";
import { RunComparison } from "@/components/RunComparison";
import { CostTrend } from "@/components/CostTrend";
import type { RunRecord } from "@/lib/types";

type SortKey = "timestamp" | "latency";
type SortDir = "asc" | "desc";

function Wordmark() {
  return (
    <div className="flex items-baseline gap-2">
      <span className="font-mono text-sm font-medium text-amber tracking-tight">
        aws-instance-advisor
      </span>
      <span className="font-mono text-xs text-ink-dim">v2</span>
    </div>
  );
}

function GroundingDot({ passed }: { passed: boolean | null }) {
  if (passed == null) {
    return (
      <span
        className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
        style={{ backgroundColor: "rgba(237,237,234,0.15)" }}
        aria-label="grounding not available"
        title="grounding not available"
      />
    );
  }
  return (
    <span
      className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
      style={{ backgroundColor: `rgba(232,163,61,${passed ? 1.0 : 0.35})` }}
      aria-label={passed ? "grounding passed" : "grounding review recommended"}
      title={passed ? "grounding passed" : "grounding review recommended"}
    />
  );
}

/** Format total_latency_s (seconds, float) for display */
function formatLatency(s: number | null): string {
  if (s == null) return "—";
  if (s < 1) return `${Math.round(s * 1000)}ms`;
  return `${s.toFixed(1)}s`;
}

/**
 * Format estimated cost range.
 * Backend provides estimated_cost_low / estimated_cost_high (monthly USD).
 * Show range when both are present and differ, otherwise single value.
 */
function formatCostRange(low: number | null, high: number | null): string {
  const fmtOne = (v: number) => {
    if (v === 0) return "$0";
    if (v < 0.01) return "< $0.01";
    if (v < 10) return `$${v.toFixed(2)}`;
    return `$${Math.round(v)}`;
  };
  if (low == null && high == null) return "—";
  if (low == null) return fmtOne(high!);
  if (high == null) return fmtOne(low);
  if (Math.abs(high - low) < 0.01) return fmtOne(low);
  return `${fmtOne(low)}–${fmtOne(high)}`;
}

function pad(n: number): string {
  return n.toString().padStart(2, "0");
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    return `${months[d.getMonth()]} ${pad(d.getDate())}, ${d.getFullYear()}, ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  } catch {
    return iso;
  }
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

type SortIconProps = { active: boolean; dir: SortDir };
function SortIcon({ active, dir }: SortIconProps) {
  return (
    <span
      className="font-mono text-[10px] ml-1 select-none"
      style={{ opacity: active ? 1 : 0.3 }}
    >
      {active ? (dir === "asc" ? "▲" : "▼") : "↕"}
    </span>
  );
}

// ── Expandable pipeline trace row ─────────────────────────────────────────────

function RunRow({ run, selected, onToggle }: { run: RunRecord; selected: boolean; onToggle: () => void }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* ── Summary row ── */}
      <tr
        className="border-b border-border-faint hover:bg-border-faint transition-colors cursor-pointer"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={open ? "Collapse pipeline trace" : "Expand pipeline trace"}
      >
        <td className="px-3 py-2.5 w-10" onClick={(event) => event.stopPropagation()}>
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={`Select run ${shortId(run.job_id)} for comparison`}
            className="accent-amber focus-visible:outline focus-visible:outline-1 focus-visible:outline-amber/60 focus-visible:outline-offset-2"
          />
        </td>
        {/* Expand chevron */}
        <td className="px-3 py-2.5 w-6 shrink-0">
          <span
            className="font-mono text-[10px] text-ink-dim select-none transition-transform inline-block"
            style={{ transform: open ? "rotate(90deg)" : "none" }}
            aria-hidden
          >
            ▶
          </span>
        </td>

        <td className="font-mono text-xs text-ink px-3 py-2.5 whitespace-nowrap">
          {formatTimestamp(run.timestamp)}
        </td>

        <td className="font-mono text-xs text-ink px-3 py-2.5 text-right whitespace-nowrap tabular-nums">
          {formatLatency(run.total_latency_s)}
        </td>

        <td className="font-mono text-xs text-ink px-3 py-2.5 text-right whitespace-nowrap tabular-nums">
          {run.retry_count ?? 0}
        </td>

        <td className="px-3 py-2.5">
          <span className="inline-flex items-center gap-1.5">
            <GroundingDot passed={run.grounding_passed} />
            <span className="font-mono text-xs text-ink-dim">
              {run.grounding_passed == null
                ? "—"
                : run.grounding_passed
                  ? "pass"
                  : "review"}
            </span>
          </span>
        </td>

        <td className="font-mono text-xs text-ink px-3 py-2.5 text-right whitespace-nowrap tabular-nums">
          {formatCostRange(run.estimated_cost_low, run.estimated_cost_high)}
          {run.estimated_cost_low != null && (
            <span className="text-ink-dim">/mo</span>
          )}
        </td>
      </tr>

      {/* ── Expandable pipeline trace ── */}
      {open && (
        <tr className="border-b border-border-faint">
          {/* Span all columns (chevron + 5 data cols = 6 total) */}
          <td colSpan={7} className="px-6 pb-4 pt-1">
            <div
              className="border-l-2 pl-4"
              style={{ borderColor: "rgba(232,163,61,0.2)" }}
            >
              <p className="font-mono text-[10px] text-ink-dim uppercase tracking-widest mb-2 mt-1">
                execution trace
              </p>
              <PipelineTrace run={run} />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [observabilityConfigured, setObservabilityConfigured] = useState<boolean | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("timestamp");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const resp = await getRuns();
        if (cancelled) return;
        setObservabilityConfigured(resp.observability_configured);
        setRuns(resp.runs);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load run history");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [reloadTick]);

  const retry = () => setReloadTick((tick) => tick + 1);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sortedRuns = useMemo(() => {
    const copy = [...runs];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "timestamp") {
        const ta = a.timestamp ? new Date(a.timestamp).getTime() : 0;
        const tb = b.timestamp ? new Date(b.timestamp).getTime() : 0;
        cmp = (Number.isFinite(ta) ? ta : 0) - (Number.isFinite(tb) ? tb : 0);
      } else if (sortKey === "latency") {
        const la = a.total_latency_s ?? -1;
        const lb = b.total_latency_s ?? -1;
        cmp = la - lb;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [runs, sortKey, sortDir]);

  const selectedRuns = runs.filter((run) => selectedIds.includes(run.job_id));
  const toggleSelection = (jobId: string) => {
    setSelectedIds((current) => {
      if (current.includes(jobId)) return current.filter((id) => id !== jobId);
      if (current.length >= 2) return current;
      return [...current, jobId];
    });
    setComparisonOpen(false);
  };

  return (
    <div className="min-h-dvh flex flex-col">
      {/* ── Header (content capped to match main width on wide screens) ── */}
      <header className="border-b border-border-subtle shrink-0">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <Link href="/" className="hover:opacity-80 transition-opacity">
              <Wordmark />
            </Link>
            <nav className="flex items-center gap-1">
              <Link
                href="/"
                className="font-mono text-xs text-ink-dim hover:text-amber transition-colors px-2 py-1"
              >
                advisor
              </Link>
              <span
                className="font-mono text-xs text-ink px-2 py-1 border-b-2 border-amber cursor-default"
                aria-current="page"
              >
                run history
              </span>
            </nav>
          </div>
          {process.env.NEXT_PUBLIC_API_URL && (
            <span className="font-mono text-xs text-ink-dim hidden sm:block">
              {process.env.NEXT_PUBLIC_API_URL}
            </span>
          )}
        </div>
      </header>

      {/* ── Main ── */}
      <main className="flex-1 w-full max-w-6xl mx-auto px-6 py-12 flex flex-col gap-8">
        <section className="animate-fade-in">
          <div className="flex items-center justify-between gap-4 mb-2">
            <h1 className="font-mono text-xl font-medium text-ink tracking-tight">
              Historical runs
            </h1>
            <button
              type="button"
              disabled={selectedIds.length !== 2}
              onClick={() => setComparisonOpen(true)}
              className="border border-border-subtle px-3 py-1.5 font-mono text-xs text-ink-dim uppercase tracking-wider transition-colors hover:text-amber hover:border-amber/40 hover:bg-white/[0.03] disabled:cursor-not-allowed disabled:opacity-40"
            >
              compare {selectedIds.length}/2
            </button>
          </div>
          <p className="font-sans text-sm text-ink-muted leading-relaxed max-w-xl">
            Completed advisor runs with latency, retry count, grounding result, and
            estimated monthly cost. Select two runs to compare their actual recommendations.
          </p>
        </section>

        {comparisonOpen && selectedRuns.length === 2 && (
          <RunComparison
            runs={[selectedRuns[0], selectedRuns[1]]}
            onClose={() => setComparisonOpen(false)}
          />
        )}

        {!loading && !error && observabilityConfigured === true && runs.length > 0 && (
          <CostTrend runs={runs} />
        )}

        {/* ── Loading: skeleton rows matching the table shape ── */}
        {loading && (
          <div
            className="border border-border-subtle"
            role="status"
            aria-label="loading run history"
          >
            {[64, 52, 58, 48, 60].map((width, index) => (
              <div
                key={index}
                className={`flex items-center gap-4 px-3 py-3 ${
                  index < 4 ? "border-b border-border-faint" : ""
                }`}
              >
                <span className="w-4 h-3 bg-white/[0.05]" />
                <span
                  className="h-3 bg-white/[0.07] animate-pulse"
                  style={{ width: `${width}%` }}
                />
                <span className="ml-auto h-3 w-14 bg-white/[0.05]" />
              </div>
            ))}
          </div>
        )}

        {/* ── Error ── */}
        {/* ── Error — shared panel: what happened → message → retry ── */}
        {error && <ErrorPanel message={error} onRetry={retry} />}

        {/* ── Observability not configured ── */}
        {!loading && !error && observabilityConfigured === false && (
          <section className="border border-border-subtle p-10 animate-fade-in">
            <div className="flex flex-col items-center text-center max-w-md mx-auto gap-4">
              <span
                className="inline-block w-8 h-8 rounded-full"
                style={{ backgroundColor: "rgba(237,237,234,0.06)" }}
              />
              <p className="font-mono text-sm text-ink">
                Run history isn&apos;t enabled
              </p>
              <p className="font-sans text-sm text-ink-muted leading-relaxed">
                Configure{" "}
                <code className="font-mono text-xs text-ink-dim">DATABASE_URL</code>{" "}
                on the backend to track runs over time.
              </p>
            </div>
          </section>
        )}

        {/* ── No runs yet ── */}
        {!loading && !error && observabilityConfigured === true && runs.length === 0 && (
          <section className="border border-border-subtle p-10 animate-fade-in">
            <div className="flex flex-col items-center text-center max-w-md mx-auto gap-4">
              <span
                className="inline-block w-8 h-8 rounded-full"
                style={{ backgroundColor: "rgba(237,237,234,0.06)" }}
              />
              <p className="font-mono text-sm text-ink">No runs yet</p>
              <p className="font-sans text-sm text-ink-muted leading-relaxed">
                Completed advisor runs will appear here.{" "}
                <Link href="/" className="text-amber hover:underline">
                  Run an analysis →
                </Link>
              </p>
            </div>
          </section>
        )}

        {/* ── Run table ── */}
        {!loading && !error && observabilityConfigured === true && runs.length > 0 && (
          <section className="animate-fade-in overflow-x-auto">
            <table className="w-full border-collapse min-w-[680px]">
              <thead>
                <tr className="border-b border-border-subtle">
                  {/* Chevron column */}
                  <th className="w-10 px-3 py-2 font-mono text-[10px] text-ink-dim uppercase tracking-wider text-left">select</th>
                  <th className="w-6 px-3 py-2" aria-hidden />
                  <th
                    className="text-left font-mono text-xs text-ink-dim uppercase tracking-wider px-3 py-2 cursor-pointer select-none hover:text-ink-muted transition-colors whitespace-nowrap"
                    onClick={() => toggleSort("timestamp")}
                  >
                    timestamp
                    <SortIcon active={sortKey === "timestamp"} dir={sortDir} />
                  </th>
                  <th
                    className="text-right font-mono text-xs text-ink-dim uppercase tracking-wider px-3 py-2 cursor-pointer select-none hover:text-ink-muted transition-colors whitespace-nowrap"
                    onClick={() => toggleSort("latency")}
                  >
                    latency
                    <SortIcon active={sortKey === "latency"} dir={sortDir} />
                  </th>
                  <th className="text-right font-mono text-xs text-ink-dim uppercase tracking-wider px-3 py-2 whitespace-nowrap">
                    retries
                  </th>
                  <th className="text-left font-mono text-xs text-ink-dim uppercase tracking-wider px-3 py-2 whitespace-nowrap">
                    grounding
                  </th>
                  <th className="text-right font-mono text-xs text-ink-dim uppercase tracking-wider px-3 py-2 whitespace-nowrap">
                    est. cost/mo
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedRuns.map((run) => (
                  <RunRow
                    key={run.job_id}
                    run={run}
                    selected={selectedIds.includes(run.job_id)}
                    onToggle={() => toggleSelection(run.job_id)}
                  />
                ))}
              </tbody>
            </table>

            {/* Row count footer */}
            <p className="font-mono text-xs text-ink-dim mt-3 text-right">
              {sortedRuns.length}{" "}
              {sortedRuns.length === 1 ? "run" : "runs"}
            </p>
          </section>
        )}
      </main>

      {/* ── Footer ── */}
      <footer className="border-t border-border-subtle px-6 py-3 shrink-0">
        <p className="font-mono text-xs text-ink-dim text-center">
          AI-generated infrastructure — review every{" "}
          <code className="text-ink-dim">terraform plan</code> before applying
        </p>
      </footer>
    </div>
  );
}
