"use client";

import type { InstanceCandidate, SystemDesignRecommendation, TechnicalNeeds } from "@/lib/types";
import { ArchSummary } from "./ArchSummary";
import { ConfidenceDot } from "./ConfidenceDot";
import { CostSection } from "./CostSection";
import { TopologyDiagram } from "./TopologyDiagram";
import { CandidateLandscape } from "./CandidateLandscape";
import { ScalingRangeBar } from "./ScalingRangeBar";
import { ConfidenceStrip } from "./ConfidenceStrip";
import { CopyableValue } from "./CopyableValue";

interface Props {
  sdr: SystemDesignRecommendation;
  technicalNeeds?: TechnicalNeeds;
  instanceCandidates?: InstanceCandidate[];
}

// ── Tiny helpers ────────────────────────────────────────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 mb-4">
      <span className="font-mono text-xs text-ink-muted uppercase tracking-widest">
        {label}
      </span>
      <span className="flex-1 border-t border-border-subtle" />
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0 flex flex-col gap-0.5">
      <span className="font-mono text-xs text-ink-dim uppercase tracking-wider">
        {label}
      </span>
      <div className="text-ink">{children}</div>
    </div>
  );
}

function MonoValue({ value }: { value: string }) {
  return (
    <CopyableValue value={value} className="font-mono text-sm text-ink">
      {value}
    </CopyableValue>
  );
}

function AssumptionsList({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <details className="group mt-1">
      <summary className="inline-flex items-center gap-1.5 font-mono text-xs text-ink-dim hover:text-ink-muted transition-colors cursor-pointer select-none">
        <span
          aria-hidden
          className="inline-block transition-transform duration-150 motion-reduce:transition-none group-open:rotate-90"
        >
          ▶
        </span>
        {items.length} assumption{items.length !== 1 ? "s" : ""}
      </summary>
      <ul className="mt-2 space-y-1 pl-4 border-l border-border-subtle">
        {items.map((a, i) => (
          <li key={i} className="font-sans text-xs text-ink-muted leading-relaxed">
            {a}
          </li>
        ))}
      </ul>
    </details>
  );
}

// ── Tier sections ────────────────────────────────────────────────────────────

function ComputeSection({
  compute,
  technicalNeeds,
  instanceCandidates,
}: {
  compute: SystemDesignRecommendation["compute"];
  technicalNeeds?: TechnicalNeeds;
  instanceCandidates?: InstanceCandidate[];
}) {
  return (
    <section>
      <SectionHeader label="compute" />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="instance type">
          <MonoValue value={compute.recommended_instance} />
        </Field>
        <Field label="confidence">
          <ConfidenceDot level={compute.confidence} />
        </Field>
        <Field label="rationale">
          <p className="font-sans text-sm text-ink-muted leading-relaxed">
            {compute.why}
          </p>
        </Field>
        {compute.alternative_instance && (
          <Field label="alternative">
            <MonoValue value={compute.alternative_instance} />
            {compute.trade_off && (
              <p className="font-sans text-xs text-ink-dim mt-0.5 leading-relaxed">
                {compute.trade_off}
              </p>
            )}
          </Field>
        )}
      </div>
      <AssumptionsList items={compute.assumptions} />

      {/* ScalingRangeBar — only when technical_needs present */}
      {technicalNeeds && (
        <div className="mt-5">
          <span className="font-mono text-xs text-ink-dim uppercase tracking-wider block mb-2">
            scaling range
          </span>
          <ScalingRangeBar
            minInstances={technicalNeeds.min_instances}
            maxInstances={technicalNeeds.max_instances}
            scalingRecommendation={technicalNeeds.scaling_recommendation}
          />
        </div>
      )}

      {/* CandidateLandscape — only when candidates present */}
      {instanceCandidates && instanceCandidates.length > 0 && (
        <div className="mt-5">
          <span className="font-mono text-xs text-ink-dim uppercase tracking-wider block mb-2">
            candidate landscape
          </span>
          <CandidateLandscape
            candidates={instanceCandidates}
            recommendedInstance={compute.recommended_instance}
            alternativeInstance={compute.alternative_instance}
          />
        </div>
      )}
    </section>
  );
}

function DatabaseSection({
  database,
}: {
  database: SystemDesignRecommendation["database"];
}) {
  if (!database.needed) {
    return (
      <section>
        <SectionHeader label="database" />
        <p className="font-sans text-sm text-ink-muted">{database.why}</p>
      </section>
    );
  }
  return (
    <section>
      <SectionHeader label="database" />
      <div className="grid gap-3 sm:grid-cols-2">
        {database.recommended_instance && (
          <Field label="instance class">
            <MonoValue value={database.recommended_instance} />
          </Field>
        )}
        {database.engine_suggestion && (
          <Field label="engine">
            <MonoValue value={database.engine_suggestion} />
          </Field>
        )}
        <Field label="confidence">
          <ConfidenceDot level={database.confidence} />
        </Field>
        <Field label="rationale">
          <p className="font-sans text-sm text-ink-muted leading-relaxed">
            {database.why}
          </p>
        </Field>
        {database.alternative_instance && (
          <Field label="alternative">
            <MonoValue value={database.alternative_instance} />
          </Field>
        )}
      </div>
      <AssumptionsList items={database.assumptions} />
    </section>
  );
}

function CacheSection({
  cache,
}: {
  cache: SystemDesignRecommendation["cache"];
}) {
  if (!cache.needed) {
    return (
      <section>
        <SectionHeader label="cache" />
        <p className="font-sans text-sm text-ink-muted">{cache.why}</p>
      </section>
    );
  }
  return (
    <section>
      <SectionHeader label="cache" />
      <div className="grid gap-3 sm:grid-cols-2">
        {cache.recommended_instance && (
          <Field label="node type">
            <MonoValue value={cache.recommended_instance} />
          </Field>
        )}
        {cache.engine && (
          <Field label="engine">
            <MonoValue value={cache.engine} />
          </Field>
        )}
        <Field label="confidence">
          <ConfidenceDot level={cache.confidence} />
        </Field>
        <Field label="rationale">
          <p className="font-sans text-sm text-ink-muted leading-relaxed">
            {cache.why}
          </p>
        </Field>
        {cache.alternative_instance && (
          <Field label="alternative">
            <MonoValue value={cache.alternative_instance} />
            {cache.alternative_engine && (
              <span className="font-mono text-xs text-ink-dim ml-2">
                ({cache.alternative_engine})
              </span>
            )}
          </Field>
        )}
      </div>
      <AssumptionsList items={cache.assumptions} />
    </section>
  );
}

function LoadBalancerSection({
  lb,
}: {
  lb: SystemDesignRecommendation["load_balancer"];
}) {
  return (
    <section>
      <SectionHeader label="load balancer" />
      {lb.needed ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {lb.load_balancer_type && (
            <Field label="type">
              <MonoValue value={lb.load_balancer_type} />
            </Field>
          )}
          <Field label="rationale">
            <p className="font-sans text-sm text-ink-muted leading-relaxed">
              {lb.why}
            </p>
          </Field>
        </div>
      ) : (
        <p className="font-sans text-sm text-ink-muted">{lb.why}</p>
      )}
    </section>
  );
}

// ── Main export ──────────────────────────────────────────────────────────────

export function ResultReport({ sdr, technicalNeeds, instanceCandidates }: Props) {
  return (
    <div className="min-w-0 animate-fade-in space-y-0">

      {/* ── Topology diagram — first thing shown ── */}
      <section className="result-section py-6">
        <div className="flex items-center gap-2 mb-4">
          <span className="font-mono text-xs text-amber uppercase tracking-widest">
            architecture topology
          </span>
          <span className="flex-1 border-t border-amber/20" />
        </div>
        <TopologyDiagram sdr={sdr} technicalNeeds={technicalNeeds} />
      </section>

      <hr className="console-rule" />

      {/* ── Architecture summary ── */}
      <section className="result-section result-section-delay-1 py-6">
        <div className="flex items-center gap-2 mb-4">
          <span className="font-mono text-xs text-amber uppercase tracking-widest">
            architecture summary
          </span>
          <span className="flex-1 border-t border-amber/20" />
        </div>

        {sdr.grounding_passed != null && (
          <div className="mb-4">
            <div className="inline-flex items-center gap-2 border border-border-subtle px-3 py-2">
              <span
                className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                style={{
                  backgroundColor: sdr.grounding_passed
                    ? "rgba(232,163,61,1.0)"
                    : "rgba(232,163,61,0.35)",
                }}
                aria-label={
                  sdr.grounding_passed
                    ? "grounding verified consistent"
                    : "grounding review recommended"
                }
              />
              <span className="font-mono text-xs text-ink">
                {sdr.grounding_passed ? "Verified consistent" : "Review recommended"}
              </span>
            </div>
            {!sdr.grounding_passed && sdr.grounding_notes && sdr.grounding_notes.length > 0 && (
              <details className="group mt-2">
                <summary className="inline-flex items-center gap-1.5 font-mono text-xs text-ink-dim hover:text-ink-muted transition-colors cursor-pointer select-none">
                  <span
                    aria-hidden
                    className="inline-block transition-transform duration-150 motion-reduce:transition-none group-open:rotate-90"
                  >
                    ▶
                  </span>
                  grounding notes ({sdr.grounding_notes.length})
                </summary>
                <ul className="mt-2 pl-4 border-l border-border-subtle space-y-1">
                  {sdr.grounding_notes.map((note, i) => (
                    <li key={i} className="font-sans text-xs text-ink-muted leading-relaxed">
                      {note}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        <ArchSummary text={sdr.architecture_summary} />
      </section>

      <hr className="console-rule" />

      {/* ── Confidence strip — all needed tiers at a glance ── */}
      <section className="result-section result-section-delay-2 py-6">
        <div className="flex items-center gap-2 mb-4">
          <span className="font-mono text-xs text-ink-muted uppercase tracking-widest">
            confidence by tier
          </span>
          <span className="flex-1 border-t border-border-subtle" />
        </div>
        <ConfidenceStrip sdr={sdr} />
      </section>

      <hr className="console-rule" />

      {/* ── Estimated monthly cost ── */}
      {sdr.estimated_cost && (
        <section className="result-section result-section-delay-3 py-6 scroll-mt-16" id="cost">
          <div className="flex items-center gap-2 mb-4">
            <span className="font-mono text-xs text-amber uppercase tracking-widest">
              estimated monthly cost
            </span>
            <span className="flex-1 border-t border-amber/20 w-8" />
          </div>
          <CostSection
            cost={sdr.estimated_cost}
            databaseNeeded={sdr.database.needed}
            cacheNeeded={sdr.cache.needed}
          />
        </section>
      )}

      <hr className="console-rule" />

      {/* ── Tier sections ── */}
      <div id="compute" className="result-section result-section-delay-4 py-6 scroll-mt-16">
        <ComputeSection
          compute={sdr.compute}
          technicalNeeds={technicalNeeds}
          instanceCandidates={instanceCandidates}
        />
      </div>

      <hr className="console-rule" />

      <div id="database" className="result-section result-section-delay-5 py-6 scroll-mt-16">
        <DatabaseSection database={sdr.database} />
      </div>

      <hr className="console-rule" />

      <div id="cache" className="result-section result-section-delay-6 py-6 scroll-mt-16">
        <CacheSection cache={sdr.cache} />
      </div>

      <hr className="console-rule" />

      <div id="load-balancer" className="result-section result-section-delay-7 py-6 scroll-mt-16">
        <LoadBalancerSection lb={sdr.load_balancer} />
      </div>
    </div>
  );
}
