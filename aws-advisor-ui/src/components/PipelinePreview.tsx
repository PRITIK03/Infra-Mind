"use client";

const STAGES = [
  "Requirements",
  "System Design Reasoning",
  "Live AWS Research",
  "Recommendation",
  "Terraform",
] as const;

export function PipelinePreview() {
  return (
    <section className="mt-10 border border-border-subtle px-4 py-4" aria-label="Advisor pipeline">
      <div className="flex items-center gap-2 mb-4">
        <span className="font-mono text-[10px] text-amber uppercase tracking-widest">pipeline</span>
        <span className="flex-1 border-t border-border-subtle" />
        <span className="font-mono text-[10px] text-ink-dim">5 stages</span>
      </div>
      <ol className="grid gap-0 sm:grid-cols-5">
        {STAGES.map((stage, index) => (
          <li key={stage} className="relative flex items-center gap-2 py-2 sm:block sm:pr-3">
            <span className="relative z-10 inline-block h-2 w-2 shrink-0 bg-amber/70" aria-hidden="true" />
            {index < STAGES.length - 1 && (
              <span className="absolute left-1 top-5 h-px w-3/4 bg-border-subtle sm:left-2 sm:top-3 sm:w-full" aria-hidden="true" />
            )}
            <span className="relative z-10 bg-canvas pr-2 font-mono text-[11px] leading-tight text-ink-dim sm:mt-3 sm:block">
              {stage}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
