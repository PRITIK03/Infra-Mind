import type { Metadata } from "next";
import Link from "next/link";
import { ORDERED_STAGES } from "@/lib/types";

export const metadata: Metadata = {
  title: "How it works — AWS Instance Advisor",
  description:
    "The real pipeline behind a recommendation: requirement collection, system-design reasoning, live instance research, grounding checks, and Terraform generation — stage by stage.",
};

/**
 * Static explainer for the fixed pipeline stages — same visual language as
 * StageProgress (thin connected dots, monospace stage names), but with
 * prose instead of live data.  The stage list comes from ORDERED_STAGES (the
 * single source the live progress UI uses), so this page can't drift from
 * what the agent actually runs.
 */

const STAGE_NOTES: Record<string, string> = {
  Initializing:
    "The client's opening frame, before the agent runs: requirements are empty and nothing has been executed yet. It's UI state rather than a backend stage — the run history deliberately skips it for the same reason.",
  "Collecting requirements":
    "Turn-by-turn gathering: the agent asks one clarifying question at a time until it has enough context, which is why the UI can pause with awaiting_input and accept an answer. Each answer resumes the run where it stopped — the loop is the agent's, not the UI's.",
  "Validating requirements":
    "Checks the gathered requirements for internal consistency before any expensive work starts, so malformed or contradictory answers get corrected here instead of propagating into research and cost estimates.",
  "Reasoning about system design":
    "Derives concurrency expectations, resource profile, traffic pattern, and scaling strategy from your answers. Everything sized later is sized against this reasoning — it is explicit, not implied by instance names.",
  "Researching compute options":
    "Fetches live instance data (instance types plus Vantage pricing) and selects a diverse set of candidates matched to your profile. Prices are current as of the fetch, never baked into the model.",
  "Researching database options":
    "The same approach for the data tier: candidates are researched against live data and kept only when you actually need a database, with engine choice and sizing tied to your stated workload.",
  "Researching cache options":
    "Works out whether a cache earns its keep for your traffic pattern, and if so which engine (Redis, Memcached, or Valkey) and size fit. When you don't need one, the tier is reported as not needed rather than padded.",
  "Building final recommendation":
    "Combines the reasoning and researched tiers into one coherent architecture — compute, database, cache, and load-balancer decisions, each with a rationale, assumptions, and a confidence level. Consensus mode (opt-in, costs one extra LLM call) re-generates the final recommendation against a second model and compares the two deterministically.",
  "Checking recommendation consistency":
    "Verifies the finished recommendation against your requirements and the researched data, hunting for contradictions (claiming auto-scaling while max instances is 1). On a hit it appends corrections and regenerates once; if it still disagrees, the result ships flagged rather than silently inconsistent.",
  "Generating Terraform":
    "Renders the recommendation as deployable .tf files for the selected tiers, written to terraform_output/. They are a reviewed starting point: the standing instruction to read every terraform plan before applying it is not a figure of speech.",
};

export default function HowItWorksPage() {
  return (
    <div className="min-h-dvh flex flex-col">
      <header className="border-b border-border-subtle shrink-0">
        <div className="max-w-4xl mx-auto px-6 py-3 flex items-center gap-3">
          <Link href="/" className="flex items-baseline gap-2">
            <span className="font-mono text-sm font-medium text-amber tracking-tight">
              aws-instance-advisor
            </span>
            <span className="font-mono text-xs text-ink-dim">v2</span>
          </Link>
          <nav className="flex items-center gap-1">
            <Link
              href="/"
              className="font-mono text-xs text-ink-dim hover:text-amber hover:bg-white/[0.03] transition-colors px-2 py-1"
            >
              advisor
            </Link>
            <Link
              href="/history"
              className="font-mono text-xs text-ink-dim hover:text-amber hover:bg-white/[0.03] transition-colors px-2 py-1"
            >
              run history
            </Link>
            <Link
              href="/how-it-works"
              className="font-mono text-xs text-ink px-2 py-1 border-b-2 border-amber cursor-default"
              aria-current="page"
            >
              how it works
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1 w-full max-w-4xl mx-auto px-6 py-10">
        <p className="font-mono text-xs text-ink-muted uppercase tracking-widest">
          how it works
        </p>
        <h1 className="mt-2 font-mono text-2xl text-ink">
          One fixed pipeline, every run
        </h1>
        <p className="mt-4 font-sans text-sm text-ink-muted leading-relaxed max-w-2xl">
          Every recommendation goes through the same stages in the same order —
          this is the exact list the live progress view renders while a run is
          executing. Below is what each stage actually does, in the language of
          what is implemented rather than what it sounds like.
        </p>

        <ol className="mt-10 space-y-0" aria-label="pipeline stages">
          {ORDERED_STAGES.map((stage, idx) => {
            const isLast = idx === ORDERED_STAGES.length - 1;
            return (
              <li key={stage} className="flex items-start gap-3 py-2">
                {/* Thin connected dots — same geometry as StageProgress */}
                <div className="flex flex-col items-center mt-1 shrink-0 w-4">
                  <div className="w-2 h-2 rounded-full shrink-0 bg-amber/70" aria-hidden />
                  {!isLast && (
                    <div
                      className="w-px flex-1 min-h-[12px] mt-1 bg-amber/30"
                      aria-hidden
                    />
                  )}
                </div>

                <div className="min-w-0 flex-1 pb-3">
                  <div className="flex items-baseline gap-3">
                    <span className="font-mono text-sm text-ink">{stage}</span>
                    <span className="font-mono text-[10px] text-ink-dim tabular-nums">
                      {String(idx + 1).padStart(2, "0")} /{" "}
                      {String(ORDERED_STAGES.length).padStart(2, "0")}
                    </span>
                  </div>
                  <p className="mt-1.5 font-sans text-sm text-ink-muted leading-relaxed">
                    {STAGE_NOTES[stage]}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>

        <hr className="console-rule my-6" />

        {/* Honest data note — mirrors PipelineTrace's disclosure pattern */}
        <section aria-label="What is measured">
          <p className="font-mono text-xs text-ink-muted uppercase tracking-widest">
            what is actually measured
          </p>
          <p className="mt-3 font-sans text-sm text-ink-muted leading-relaxed">
            The backend records one row per completed run — total latency, retry
            count, grounding result, model, and estimated cost — not per-stage
            timings. Run history and the pipeline trace annotate exactly those
            fields and dash the unknowns; this page adds prose, not simulated
            numbers. Health endpoints are local-only checks (config presence,
            Redis reachability) precisely so a monitor can hit them without
            spending model or pricing API quota.
          </p>
        </section>

        <p className="mt-8">
          <Link href="/" className="text-amber hover:underline font-mono text-xs">
            ← back to the advisor
          </Link>
        </p>
      </main>

      <footer className="border-t border-border-subtle px-6 py-3 shrink-0">
        <p className="font-mono text-xs text-ink-dim text-center">
          AI-generated infrastructure — review every{" "}
          <code className="text-ink-dim">terraform plan</code> before applying
        </p>
      </footer>
    </div>
  );
}
