"use client";

import type { EstimatedCost } from "@/lib/types";
import { AnimatedNumber } from "./AnimatedNumber";
import { CopyableValue } from "./CopyableValue";
import { CostBar } from "./CostBar";

interface Props {
  cost?: EstimatedCost | null;
  databaseNeeded: boolean;
  cacheNeeded: boolean;
}

function fmt(value: number | null | undefined): string {
  if (value == null) return "—";
  return `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function fmtRange(low: number | null | undefined, high: number | null | undefined): string {
  if (low == null || high == null) return "—";
  if (low === high) return fmt(low);
  return `${fmt(low)} - ${fmt(high)}`;
}

function animatedCurrency(value: number): React.ReactNode {
  return <AnimatedNumber value={value} format={(current) => fmt(current)} />;
}

export function CostSection({ cost, databaseNeeded, cacheNeeded }: Props) {
  if (!cost) return null;

  const lines = [
    { label: "compute", low: cost.compute_monthly_low, high: cost.compute_monthly_high, fallback: "—" },
    {
      label: "database",
      low: databaseNeeded ? cost.database_monthly : null,
      high: databaseNeeded ? cost.database_monthly : null,
      fallback: databaseNeeded && cost.database_monthly == null ? "pricing unavailable" : "—",
    },
    {
      label: "cache",
      low: cacheNeeded ? cost.cache_monthly : null,
      high: cacheNeeded ? cost.cache_monthly : null,
      fallback: cacheNeeded && cost.cache_monthly == null ? "pricing unavailable" : "—",
    },
  ];

  const totalDisplay = fmtRange(cost.total_monthly_low, cost.total_monthly_high);
  const totalUnavailable = cost.total_monthly_low == null || cost.total_monthly_high == null;
  const midpoint = (low: number | null | undefined, high: number | null | undefined) =>
    low != null && high != null ? (low + high) / 2 : null;

  return (
    <section>
      <CostBar
        compute={midpoint(cost.compute_monthly_low, cost.compute_monthly_high)}
        database={databaseNeeded ? cost.database_monthly : null}
        cache={cacheNeeded ? cost.cache_monthly : null}
        className="mb-5"
      />
      <div className="grid gap-3 sm:grid-cols-2">
        {lines.map((line) => {
          const displayValue = line.low != null && line.high != null
            ? fmtRange(line.low, line.high)
            : line.fallback;
          return (
            <div key={line.label} className="min-w-0 flex justify-between gap-4">
              <span className="font-mono text-xs text-ink-dim uppercase tracking-wider">{line.label}</span>
              <CopyableValue
                value={displayValue}
                className={line.fallback === "pricing unavailable"
                  ? "min-w-0 text-right break-words font-sans text-sm text-ink-dim"
                  : "min-w-0 text-right break-words font-mono text-sm text-ink"}
              >
                {line.low != null && line.high != null
                  ? line.low === line.high
                    ? animatedCurrency(line.low)
                    : <>{animatedCurrency(line.low)} - {animatedCurrency(line.high)}</>
                  : line.fallback}
              </CopyableValue>
            </div>
          );
        })}
      </div>

      <div className="min-w-0 flex justify-between gap-4 mt-4 pt-3 border-t border-border-subtle">
        <span className="font-mono text-xs text-ink-dim uppercase tracking-wider">total</span>
        <CopyableValue value={totalUnavailable ? "pricing unavailable" : totalDisplay} className="min-w-0 text-right break-words font-mono text-sm text-amber">
          {!totalUnavailable && cost.total_monthly_low != null && cost.total_monthly_high != null
            ? cost.total_monthly_low === cost.total_monthly_high
              ? animatedCurrency(cost.total_monthly_low)
              : <>{animatedCurrency(cost.total_monthly_low)} - {animatedCurrency(cost.total_monthly_high)}</>
            : "pricing unavailable"}
          {!totalUnavailable && " /mo"}
        </CopyableValue>
      </div>

      <p className="font-sans text-xs text-ink-dim leading-relaxed mt-3">
        On-demand only. Based on us-east-1 hourly rates × 730 hours. Does not
        include reserved/spot discounts, data transfer, or support plans.
      </p>
    </section>
  );
}
