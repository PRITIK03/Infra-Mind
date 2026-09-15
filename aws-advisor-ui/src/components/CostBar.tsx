"use client";

interface CostBarSegment {
  label: "Compute" | "Database" | "Cache";
  value: number;
}

interface Props {
  compute?: number | null;
  database?: number | null;
  cache?: number | null;
  className?: string;
}

const OPACITY: Record<CostBarSegment["label"], number> = {
  Compute: 0.9,
  Database: 0.62,
  Cache: 0.38,
};

function formatValue(value: number): string {
  return `$${Math.round(value).toLocaleString("en-US")}`;
}

export function CostBar({ compute, database, cache, className = "" }: Props) {
  const segments: CostBarSegment[] = [
    compute != null && compute > 0 ? { label: "Compute", value: compute } : null,
    database != null && database > 0 ? { label: "Database", value: database } : null,
    cache != null && cache > 0 ? { label: "Cache", value: cache } : null,
  ].filter((segment): segment is CostBarSegment => segment !== null);
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);

  if (!segments.length || total <= 0) return null;

  return (
    <div className={`space-y-2 ${className}`} aria-label="Cost by tier">
      <div className="flex h-12 w-full overflow-hidden border border-border-subtle">
        {segments.map((segment) => (
          <div
            key={segment.label}
            className="flex min-w-0 flex-col justify-center gap-0.5 border-r border-canvas px-2 last:border-r-0"
            style={{
              width: `${(segment.value / total) * 100}%`,
              backgroundColor: `rgba(232,163,61,${OPACITY[segment.label]})`,
            }}
            title={`${segment.label}: ${formatValue(segment.value)}`}
          >
            <span className="truncate font-mono text-[10px] uppercase tracking-wider text-canvas">
              {segment.label}
            </span>
            <span className="truncate font-mono text-xs text-canvas">
              {formatValue(segment.value)}
            </span>
          </div>
        ))}
      </div>
      <div className="flex justify-between font-mono text-[10px] uppercase tracking-wider text-ink-dim">
        <span>cost by tier</span>
        <span>{formatValue(total)} total</span>
      </div>
    </div>
  );
}
