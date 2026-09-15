"use client";

import type { RunRecord } from "@/lib/types";

interface Props {
  runs: RunRecord[];
}

function midpoint(run: RunRecord): number | null {
  const low = run.estimated_cost_low;
  const high = run.estimated_cost_high;
  if (low == null && high == null) return null;
  if (low == null) return high;
  if (high == null) return low;
  return (low + high) / 2;
}

function formatCost(value: number): string {
  return `$${Math.round(value).toLocaleString("en-US")}`;
}

export function CostTrend({ runs }: Props) {
  const points = runs
    .map((run) => ({ run, value: midpoint(run), time: new Date(run.timestamp).getTime() }))
    .filter((point): point is { run: RunRecord; value: number; time: number } => point.value != null && Number.isFinite(point.time))
    .sort((a, b) => a.time - b.time);

  return (
    <section className="border border-border-subtle p-4" aria-label="Cost over time">
      <div className="flex items-center justify-between gap-4 mb-3">
        <span className="font-mono text-xs text-ink-muted uppercase tracking-widest">cost over time</span>
        <span className="font-mono text-[10px] text-ink-dim">monthly midpoint</span>
      </div>
      {points.length < 2 ? (
        <p className="font-mono text-xs text-ink-dim py-6 text-center">
          not enough runs yet for a trend
        </p>
      ) : (
        <svg
          viewBox="0 0 720 150"
          className="w-full h-auto"
          role="img"
          aria-label={`Cost trend across ${points.length} persisted runs`}
        >
          <line x1="42" y1="124" x2="700" y2="124" stroke="rgba(237,237,234,0.12)" />
          <line x1="42" y1="20" x2="42" y2="124" stroke="rgba(237,237,234,0.12)" />
          {(() => {
            const values = points.map((point) => point.value);
            const min = Math.min(...values);
            const max = Math.max(...values);
            const span = max - min || 1;
            const x = (index: number) => 42 + (index / (points.length - 1)) * 658;
            const y = (value: number) => 124 - ((value - min) / span) * 92;
            const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index)},${y(point.value)}`).join(" ");
            return (
              <>
                <path d={path} fill="none" stroke="rgba(232,163,61,0.85)" strokeWidth="1.5" />
                {points.map((point, index) => (
                  <g key={point.run.job_id}>
                    <circle cx={x(index)} cy={y(point.value)} r="3" fill="#E8A33D" />
                    <text x={x(index)} y={y(point.value) - 9} textAnchor="middle" fill="rgba(237,237,234,0.65)" fontSize="10" fontFamily="'IBM Plex Mono', monospace">
                      {formatCost(point.value)}
                    </text>
                  </g>
                ))}
              </>
            );
          })()}
        </svg>
      )}
    </section>
  );
}
