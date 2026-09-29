"use client";

import type { ContainerizedAlternative as ContainerizedAlternativeType } from "@/lib/types";

interface Props {
  alternative: ContainerizedAlternativeType;
}

// Sub-section within Compute — flat style (no card border, no tinted bg),
// consistent with how CandidateLandscape and ScalingRangeBar sub-sections
// are rendered inside ResultReport's ComputeSection.
export function ContainerizedAlternative({ alternative }: Props) {
  return (
    <div className="mt-5">
      {/* Header row — amber label (section-level accent) + inline spec */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <span className="font-mono text-xs text-amber uppercase tracking-widest">
          containerized alternative (ecs fargate)
        </span>
        {alternative.fargate_cpu_units != null && alternative.fargate_memory_mib != null && (
          <span className="font-mono text-xs text-ink-muted">
            <span className="font-mono text-sm text-ink">{alternative.fargate_cpu_units}</span>{" "}
            CPU units ·{" "}
            <span className="font-mono text-sm text-ink">{alternative.fargate_memory_mib}</span>{" "}
            MiB
          </span>
        )}
      </div>

      <p className="font-sans text-sm text-ink-muted leading-relaxed">
        {alternative.why}
      </p>

      {alternative.trade_off && (
        <div className="mt-3 pt-3 border-t border-border-subtle">
          {/* Sub-label uses same token as Field label — text-xs not text-[10px] */}
          <span className="font-mono text-xs text-ink-dim uppercase tracking-wider block mb-1">
            trade-off
          </span>
          <p className="font-sans text-xs text-ink-dim leading-relaxed">
            {alternative.trade_off}
          </p>
        </div>
      )}
    </div>
  );
}
