"use client";

import type { SystemDesignRecommendation } from "@/lib/types";

interface Props {
  sdr: SystemDesignRecommendation;
}

function fmtCost(low?: number | null, high?: number | null): string | null {
  if (low == null && high == null) return null;
  const fmt = (v: number) =>
    v < 10 ? `$${v.toFixed(2)}` : `$${Math.round(v).toLocaleString("en-US")}`;
  if (low == null) return `${fmt(high!)}/mo`;
  if (high == null) return `${fmt(low)}/mo`;
  if (Math.abs(high - low) < 1) return `${fmt(low)}/mo`;
  return `${fmt(low)}–${fmt(high)}/mo`;
}

interface CellProps {
  label: string;
  children: React.ReactNode;
}
function Cell({ label, children }: CellProps) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="font-mono text-[10px] text-ink-dim uppercase tracking-wider leading-none">
        {label}
      </span>
      <div className="font-mono text-sm text-ink leading-snug truncate">
        {children}
      </div>
    </div>
  );
}

/**
 * A single dense header row shown at the very top of a completed result.
 * Surfaces the four most decision-critical values — compute instance, total
 * cost, grounding status, and Well-Architected finding count — so the page
 * reads as a considered whole rather than a scroll of independent sections.
 *
 * All values are already computed by the backend; nothing is fabricated here.
 */
export function ResultSummaryStrip({ sdr }: Props) {
  const costStr = fmtCost(
    sdr.estimated_cost?.total_monthly_low,
    sdr.estimated_cost?.total_monthly_high,
  );

  const waCount = sdr.well_architected_review?.length ?? 0;
  const waWarnings = sdr.well_architected_review?.filter((f) => f.severity === "warning").length ?? 0;

  // Grounding dot — same amber opacity pattern as ResultReport's inline dot
  const groundingOpacity =
    sdr.grounding_passed == null ? 0.15 : sdr.grounding_passed ? 1.0 : 0.35;
  const groundingLabel =
    sdr.grounding_passed == null
      ? "not checked"
      : sdr.grounding_passed
        ? "verified"
        : "review";

  return (
    <div
      className={[
        "border-b border-amber/20 pb-5 mb-6",
        "flex flex-wrap items-end gap-x-8 gap-y-3",
        "print-summary-strip",
      ].join(" ")}
      aria-label="Result summary"
    >
      {/* Compute */}
      <Cell label="compute">
        {sdr.compute.recommended_instance}
      </Cell>

      {/* Total cost */}
      {costStr && (
        <>
          <span className="hidden sm:block self-stretch border-l border-border-subtle" aria-hidden />
          <Cell label="est. monthly cost">
            {costStr}
          </Cell>
        </>
      )}

      {/* Grounding */}
      {sdr.grounding_passed != null && (
        <>
          <span className="hidden sm:block self-stretch border-l border-border-subtle" aria-hidden />
          <Cell label="grounding">
            <span className="inline-flex items-center gap-1.5">
              <span
                className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                style={{ backgroundColor: `rgba(232,163,61,${groundingOpacity})` }}
                aria-hidden
              />
              {groundingLabel}
            </span>
          </Cell>
        </>
      )}

      {/* Well-Architected findings */}
      {waCount > 0 && (
        <>
          <span className="hidden sm:block self-stretch border-l border-border-subtle" aria-hidden />
          <Cell label="well-architected">
            <span className="inline-flex items-center gap-1.5">
              {waWarnings > 0 && (
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ backgroundColor: "rgba(232,163,61,0.9)" }}
                  aria-hidden
                />
              )}
              {waCount} finding{waCount !== 1 ? "s" : ""}
              {waWarnings > 0 && (
                <span className="text-ink-dim">
                  · {waWarnings} warning{waWarnings !== 1 ? "s" : ""}
                </span>
              )}
            </span>
          </Cell>
        </>
      )}
    </div>
  );
}
