"use client";

import type { ConsensusResult as ConsensusResultType } from "@/lib/types";

interface Props {
  consensus: ConsensusResultType;
}

const TIER_LABELS: Record<string, string> = {
  compute: "Compute",
  database: "Database",
  cache: "Cache",
  load_balancer: "Load balancer",
};

function tierLabel(tier: string): string {
  return TIER_LABELS[tier] ?? tier;
}

function agreementLabel(level: ConsensusResultType["agreement_level"]): string {
  switch (level) {
    case "full":
      return "full agreement";
    case "partial":
      return "partial agreement";
    case "significant_disagreement":
      return "significant disagreement";
    default:
      return "consensus unavailable";
  }
}

function shortModel(model: string): string {
  return model.length > 28 ? `${model.slice(0, 25)}…` : model;
}

/**
 * Opt-in multi-model consensus result.
 *
 * Renders nothing when consensus was declined (enabled=false) — the backend
 * only marks it enabled when a real second-model comparison ran. When enabled,
 * it surfaces the deterministic agreement_level and a per-tier diff that reuses
 * the same side-by-side two-column presentation as RunComparison (two choices
 * for the same tier, differences flagged with the same amber dot).
 */
export function ConsensusResult({ consensus }: Props) {
  if (!consensus.enabled) return null;

  return (
    <section
      id="consensus"
      className="border border-border-subtle animate-fade-in mt-6 scroll-mt-16"
      aria-label="Consensus check"
    >
      <div className="flex items-center justify-between gap-4 border-b border-border-subtle px-4 py-3">
        <div>
          <p className="font-mono text-xs text-amber uppercase tracking-widest">
            consensus check
          </p>
          <p className="font-sans text-xs text-ink-muted mt-1">
            second opinion by{" "}
            <span className="font-mono text-ink">{shortModel(consensus.secondary_model)}</span>{" "}
            vs primary{" "}
            <span className="font-mono text-ink">{shortModel(consensus.primary_model)}</span>
          </p>
        </div>
        <span className="font-mono text-xs text-ink uppercase tracking-wider">
          {agreementLabel(consensus.agreement_level)}
        </span>
      </div>

      {consensus.disagreements.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] border-collapse">
            <thead>
              <tr className="border-b border-border-subtle">
                <th className="text-left px-4 py-3 font-mono text-xs text-ink-dim uppercase tracking-wider">
                  tier
                </th>
                <th className="text-left px-4 py-3 font-mono text-xs text-ink uppercase tracking-wider">
                  primary · {shortModel(consensus.primary_model)}
                </th>
                <th className="text-left px-4 py-3 font-mono text-xs text-ink uppercase tracking-wider">
                  second · {shortModel(consensus.secondary_model)}
                </th>
              </tr>
            </thead>
            <tbody>
              {consensus.disagreements.map((d) => (
                <tr key={d.tier} className="border-b border-border-faint">
                  <th className="text-left px-4 py-2.5 font-mono text-xs text-ink-dim font-normal">
                    {tierLabel(d.tier)}
                  </th>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center gap-1.5">
                      <span
                        className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ backgroundColor: "rgba(232,163,61,0.9)" }}
                        aria-label="value differs"
                      />
                      <span className="font-mono text-xs text-ink">{d.primary_choice}</span>
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center gap-1.5">
                      <span
                        className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ backgroundColor: "rgba(232,163,61,0.9)" }}
                        aria-label="value differs"
                      />
                      <span className="font-mono text-xs text-ink">{d.secondary_choice}</span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {consensus.agreements.length > 0 && (
        <p className="px-4 py-3 font-mono text-xs text-ink-dim">
          agreed on:{" "}
          <span className="text-ink-muted">
            {consensus.agreements.map(tierLabel).join(", ")}
          </span>
        </p>
      )}

      {consensus.note && (
        <p className="px-4 py-3 border-t border-border-subtle font-sans text-xs text-ink-dim leading-relaxed">
          {consensus.note}
        </p>
      )}
    </section>
  );
}
