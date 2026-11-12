import type { DeploymentHandoff as Handoff } from "@/lib/types";

export function DeploymentHandoff({ handoff }: { handoff: Handoff }) {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-mono text-xs text-amber uppercase tracking-wider mb-3">
          Terraform scaffold
        </h3>
        <ul className="space-y-1.5">
          {handoff.generated_resources.map((resource) => (
            <li key={resource} className="font-mono text-xs text-ink break-words">{resource}</li>
          ))}
        </ul>
      </div>
      {(["before_apply", "before_traffic"] as const).map((phase) => {
        const actions = handoff.actions.filter((action) => action.phase === phase);
        if (!actions.length) return null;
        return (
          <div key={phase}>
            <h3 className="font-mono text-xs text-ink-muted uppercase tracking-wider mb-2">
              {phase === "before_apply" ? "Before applying" : "Before serving traffic"}
              <span className="ml-2 normal-case tracking-normal">{actions.length}</span>
            </h3>
            <div className="divide-y divide-border-subtle border-y border-border-subtle">
              {actions.map((action) => (
                <details key={action.id} className="group" open={action.id === "consistency"}>
                  <summary className="flex min-h-11 items-center justify-between gap-4 py-3 font-sans text-sm text-ink hover:text-amber transition-colors">
                    {action.title}
                    <span aria-hidden className="font-mono text-ink-muted group-open:rotate-90 motion-reduce:transition-none transition-transform">›</span>
                  </summary>
                  <p className="max-w-prose pb-4 pr-5 font-sans text-sm text-ink-muted leading-relaxed">
                    {action.detail}
                  </p>
                </details>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
