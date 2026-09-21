"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useJobPoller } from "@/hooks/useJobPoller";
import { StageProgress } from "@/components/StageProgress";
import { AwaitingInputPanel } from "@/components/AwaitingInputPanel";
import { ResultReport } from "@/components/ResultReport";
import { TerraformViewer } from "@/components/TerraformViewer";
import { FollowupPanel } from "@/components/FollowupPanel";
import { ErrorPanel } from "@/components/ErrorPanel";
import { LiveStatsReadout } from "@/components/LiveStatsReadout";
import { SectionNav } from "@/components/SectionNav";
import { RequestSummary } from "@/components/RequestSummary";
import { CopyReportButton } from "@/components/CopyReportButton";
import { PipelineTrace } from "@/components/PipelineTrace";
import type { RunRecord } from "@/lib/types";
import { BackendStatus } from "@/components/BackendStatus";
import { CommandPalette } from "@/components/CommandPalette";
import { PipelinePreview } from "@/components/PipelinePreview";
import { getRuns } from "@/lib/api";

// ── Example prompts drawn from the validated test scenarios ─────────────────
const EXAMPLES = [
  {
    label: "flash-sale e-commerce",
    prompt:
      "Flash-sale e-commerce site. We expect 50 000 registered users and up to 2 000 concurrent shoppers during sale windows. Traffic is very bursty. We need a database and probably a cache layer.",
  },
  {
    label: "steady SaaS API",
    prompt:
      "B2B SaaS REST API with about 500 registered customers. Traffic is steady, roughly 80 req/s at peak. Needs a relational database, no GPU.",
  },
  {
    label: "nightly batch processor",
    prompt:
      "Nightly CSV batch job that processes 10 GB of transaction data. Runs once at 2 AM, single concurrent job, no real-time users. No persistent database needed.",
  },
  {
    label: "ML inference service",
    prompt:
      "Real-time ML inference endpoint for image classification. About 200 req/s, low latency required, GPU acceleration needed. No database.",
  },
] as const;

// ── Wordmark ─────────────────────────────────────────────────────────────────
function Wordmark() {
  return (
    <div className="flex items-baseline gap-2">
      <span className="font-mono text-sm font-medium text-amber tracking-tight">
        aws-instance-advisor
      </span>
      <span className="font-mono text-xs text-ink-dim">v2</span>
    </div>
  );
}

// ── Command-prompt input ──────────────────────────────────────────────────────
interface InputPanelProps {
  onSubmit: (msg: string) => void;
  disabled: boolean;
  submitHint: string;
}

// Auto-grow cap — roughly ten comfortable lines before the box scrolls.
const TEXTAREA_MAX_PX = 220;

function InputPanel({ onSubmit, disabled, submitHint }: InputPanelProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Grow the prompt box with its content, capped at TEXTAREA_MAX_PX
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = value
      ? `${Math.min(el.scrollHeight, TEXTAREA_MAX_PX)}px`
      : "";
  }, [value]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Cmd/Ctrl+Enter submits; plain Enter adds newline
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      const trimmed = value.trim();
      if (trimmed && !disabled) {
        onSubmit(trimmed);
        setValue("");
      }
    }
  };

  const fillExample = (prompt: string) => {
    setValue(prompt);
    textareaRef.current?.focus();
  };

  return (
    <div className="w-full">
      {/* Prompt chips */}
      <div className="mb-5">
        <div className="flex items-center gap-2 mb-3">
          <span className="font-mono text-xs text-ink-dim uppercase tracking-widest">
            examples
          </span>
          <span className="flex-1 border-t border-border-subtle" />
        </div>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              onClick={() => fillExample(ex.prompt)}
              disabled={disabled}
              className={[
                "border border-border-subtle px-3 py-1.5",
                "font-mono text-xs text-ink-dim",
                "transition-colors duration-150",
                "hover:text-amber hover:border-amber/40 hover:bg-white/[0.03]",
                "active:translate-y-px",
                "disabled:opacity-30 disabled:cursor-not-allowed",
              ].join(" ")}
            >
              {ex.label}
            </button>
          ))}
        </div>
      </div>

      {/* Main input */}
      <form onSubmit={handleSubmit}>
        <div
          className={[
            "flex gap-0 border border-border-subtle",
            "transition-colors duration-150",
            "focus-within:border-amber/30",
          ].join(" ")}
        >
          {/* Prompt sigil */}
          <div className="flex items-start pt-3 px-3 shrink-0 border-r border-border-subtle">
            <span className="font-mono text-sm text-amber leading-6">&gt;</span>
          </div>

          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="describe your application and workload…"
            aria-label="Describe your application and workload"
            disabled={disabled}
            rows={4}
            className={[
              "flex-1 bg-transparent resize-none",
              "font-sans text-sm text-ink placeholder:text-ink-dim",
              "px-3 py-3 outline-none leading-relaxed",
              "min-h-[96px] overflow-y-auto",
              "disabled:opacity-40 disabled:cursor-not-allowed",
            ].join(" ")}
          />
        </div>

        <div className="flex items-center justify-between mt-2">
          <span className="font-mono text-xs text-ink-dim">
            {submitHint} to submit
          </span>
          <button
            type="submit"
            disabled={!value.trim() || disabled}
            className={[
              "border border-border-subtle px-5 py-2",
              "font-mono text-xs text-ink-muted uppercase tracking-wider",
              "transition-colors duration-150",
              "enabled:text-amber enabled:border-amber/60 enabled:hover:bg-amber/[0.04]",
              "hover:text-amber hover:border-amber/40 hover:bg-white/[0.03]",
              "active:translate-y-px",
              "disabled:opacity-30 disabled:cursor-not-allowed",
              "disabled:hover:text-ink-muted disabled:hover:border-border-subtle",
            ].join(" ")}
          >
            run →
          </button>
        </div>
      </form>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Home() {
  const router = useRouter();
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [recentRun, setRecentRun] = useState<RunRecord | null>(null);
  const [platformHint, setPlatformHint] = useState("⌘K / Ctrl+K");
  const [submitHint, setSubmitHint] = useState("⌘↵ / Ctrl+↵");
  const {
    status,
    currentStage,
    nextQuestion,
    jobResponse,
    error,
    retryInfo,
    isWakingUp,
    isActive,
    submit,
    answer,
    reset,
    totalElapsedMs,
    retryCount,
  } = useJobPoller();

  useEffect(() => {
    const isApple = /Mac|iPhone|iPad/.test(navigator.platform);
    setPlatformHint(isApple ? "⌘K" : "Ctrl+K");
    setSubmitHint(isApple ? "⌘↵" : "Ctrl+↵");
    getRuns()
      .then((response) => {
        if (response.observability_configured && response.runs.length > 0) {
          setRecentRun(response.runs[0]);
        }
      })
      .catch(() => setRecentRun(null));
  }, []);

  const showLanding = status === null;
  const showProgress = status !== null && status !== "done" && status !== "error";
  const showResult = status === "done" && jobResponse?.result != null;
  const showError = status === "error" && error != null;

  const sdr = jobResponse?.result?.system_design_recommendation;
  const tfFiles = jobResponse?.result?.terraform_files;
  const technicalNeeds = jobResponse?.result?.technical_needs;
  const userRequirements = jobResponse?.result?.user_requirements;
  const instanceCandidates = jobResponse?.result?.instance_candidates;
  const resultCost = sdr?.estimated_cost;
  const traceRun: RunRecord | null = showResult && jobResponse?.result
    ? {
        job_id: jobResponse.job_id,
        timestamp: new Date(jobResponse.created_at * 1000).toISOString(),
        total_latency_s: totalElapsedMs != null ? totalElapsedMs / 1000 : null,
        model_used: null,
        retry_count: retryCount,
        grounding_passed: sdr?.grounding_passed ?? null,
        estimated_cost_low: resultCost?.total_monthly_low ?? null,
        estimated_cost_high: resultCost?.total_monthly_high ?? null,
        recommendation_snapshot: null,
      }
    : null;

  const recentSnapshot = recentRun?.recommendation_snapshot;
  const recentCost = recentRun?.estimated_cost_low ?? recentRun?.estimated_cost_high;
  const recentTs = recentRun ? Date.parse(recentRun.timestamp) : Number.NaN;
  const recentAge = Number.isFinite(recentTs)
    ? Math.max(0, Math.round((Date.now() - recentTs) / 60000))
    : null;

  return (
    <div className="min-h-dvh flex flex-col">
      {/* ── Top bar (content capped to match main width on wide screens) ── */}
      <header className="border-b border-border-subtle shrink-0">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3 sm:gap-6 min-w-0">
            <Wordmark />
            <nav className="flex items-center gap-1">
              <Link
                href="/"
                className="font-mono text-xs text-ink px-2 py-1 border-b-2 border-amber cursor-default"
                aria-current="page"
              >
                advisor
              </Link>
              <Link
                href="/history"
                className="font-mono text-xs text-ink-dim hover:text-amber hover:bg-white/[0.03] transition-colors px-2 py-1"
              >
                run history
              </Link>
            </nav>
          </div>
          {process.env.NEXT_PUBLIC_API_URL && (
            <span className="flex items-center gap-2">
              <BackendStatus />
              <span className="font-mono text-xs text-ink-dim hidden sm:block">
                {process.env.NEXT_PUBLIC_API_URL}
              </span>
            </span>
          )}
        </div>
      </header>

      {/* ── Main content ── */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-6 py-12 flex flex-col gap-10">
        {isWakingUp && (
          <p
            className="font-mono text-xs text-amber animate-pulse"
            role="status"
            aria-live="polite"
          >
            waking up backend…
          </p>
        )}

        {/* ── Landing / input ── */}
        {showLanding && (
          <section className="animate-fade-in max-w-3xl w-full mx-auto">
            <div className="mb-8">
              <h1 className="font-mono text-xl font-medium text-ink mb-2 tracking-tight">
                <span className="text-amber mr-2" aria-hidden="true">
                  &gt;
                </span>
                AWS Instance Advisor
              </h1>
              <p className="font-sans text-sm text-ink-muted leading-relaxed max-w-xl">
                Describe your application and workload. The advisor reasons about
                your requirements, researches live AWS instance data, and returns
                a vetted compute, database, cache, and load-balancer recommendation
                — plus ready-to-apply Terraform.
              </p>
              <div className="mt-4">
                <LiveStatsReadout />
              </div>
            </div>
            <InputPanel onSubmit={submit} disabled={isActive} submitHint={submitHint} />
            <p className="mt-3 text-center font-mono text-[10px] text-ink-dim">
              {platformHint} for quick actions
            </p>
            {recentRun && recentSnapshot && (
              <div className="mt-8 border-l-2 border-amber/30 pl-3" aria-label="Recent activity">
                <p className="font-mono text-[10px] uppercase tracking-widest text-ink-dim">recent activity</p>
                <p className="mt-1 font-mono text-xs text-ink-muted">
                  Last run: {recentSnapshot.compute_instance ?? "compute unavailable"}
                  {recentSnapshot.database_engine ? ` + ${recentSnapshot.database_engine}` : ""}
                  {recentCost != null ? ` — $${Math.round(recentCost).toLocaleString("en-US")}/mo` : ""}
                  {recentAge != null ? ` — ${recentAge} min ago` : ""}
                  {" "}
                  <Link href="/history" className="text-amber hover:underline">view history</Link>
                </p>
              </div>
            )}
            <PipelinePreview />
          </section>
        )}

        {/* ── Active job: re-prompt input at top + progress below ── */}
        {showProgress && (
          <section className="animate-fade-in space-y-8 max-w-3xl w-full mx-auto">
            {/* Allow new input only when awaiting — blocked while running */}
            {status === "awaiting_input" && nextQuestion ? (
              <AwaitingInputPanel
                question={nextQuestion}
                onAnswer={answer}
                disabled={false}
              />
            ) : (
              /* Compact "running" header */
              <div className="flex items-center gap-3">
                <span className="w-2 h-2 rounded-full bg-amber animate-pulse shrink-0" />
                <span className="font-mono text-sm text-ink-muted typewriter-cursor">
                  {currentStage || "Initializing"}
                </span>
              </div>
            )}

            <hr className="console-rule" />

<StageProgress
              currentStage={currentStage}
              status={status}
              retryInfo={retryInfo}
/>
          </section>
        )}

        {/* ── Result ── */}
{showResult && sdr && (
              <section>
                {/* "New analysis" action in top bar */}
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-amber uppercase tracking-widest">
                      recommendation
                    </span>
                    <span className="flex-1 border-t border-amber/20 w-8" />
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-3">
                    {totalElapsedMs != null && (
                      <span className="font-mono text-xs text-ink-dim tabular-nums">
                        completed in {totalElapsedMs < 1000
                          ? `${totalElapsedMs}ms`
                          : `${(totalElapsedMs / 1000).toFixed(totalElapsedMs < 10000 ? 1 : 0)}s`}
                        {retryCount != null && retryCount > 0 ? `, ${retryCount} ${retryCount === 1 ? "retry" : "retries"}` : ""}
                      </span>
                    )}
                    <CopyReportButton
                      sdr={sdr}
                      technicalNeeds={technicalNeeds}
                      userRequirements={userRequirements}
                    />
                    <button
                      type="button"
                      onClick={reset}
                      className={[
                        "border border-border-subtle px-3 py-1.5",
                        "font-mono text-xs text-ink-dim uppercase tracking-wider",
                        "transition-colors duration-150",
                        "hover:text-amber hover:border-amber/40 hover:bg-white/[0.03]",
                        "active:translate-y-px",
                      ].join(" ")}
                    >
                      ↩ new analysis
                    </button>
                  </div>
                </div>

                <div className="grid gap-6 xl:grid-cols-[200px_1fr_280px]">
                  {/* Left: sticky section nav (desktop only) */}
                  <SectionNav
                    sdr={sdr}
                    technicalNeeds={technicalNeeds}
                    hasTerraform={Boolean(tfFiles && Object.keys(tfFiles).length > 0)}
                  />

                  {/* Center: main report */}
                  <div className="min-w-0">
                    <ResultReport
                      sdr={sdr}
                      technicalNeeds={technicalNeeds}
                      instanceCandidates={instanceCandidates}
                    />

                    {tfFiles && Object.keys(tfFiles).length > 0 && (
                      <>
                        <hr className="console-rule my-0" />

                        <div id="terraform" className="py-6 scroll-mt-16">
                          <TerraformViewer files={tfFiles} recommendation={sdr} />
                        </div>
                      </>
                    )}

                    {/* Follow-up Q&A — only on completed jobs */}
                    <hr className="console-rule my-0" />
                    <FollowupPanel
                      jobId={jobResponse!.job_id}
                      initialHistory={jobResponse!.followup_history ?? []}
                    />
                  </div>

                  {/* Right: sticky request summary (desktop only) */}
                  <div className="min-w-0 flex flex-col gap-6 xl:sticky xl:top-24 self-start">
                    {technicalNeeds && (
                      <RequestSummary
                        tn={technicalNeeds}
                        requirements={userRequirements}
                        repoAnalysisNote={sdr.repo_analysis_note}
                      />
                    )}
                    {traceRun && (
                      <section className="border-t border-border-subtle pt-6">
                        <div className="flex items-center gap-2 mb-3">
                          <span className="font-mono text-xs text-ink-muted uppercase tracking-widest">
                            pipeline trace
                          </span>
                          <span className="flex-1 border-t border-border-subtle" />
                        </div>
                        <PipelineTrace run={traceRun} />
                      </section>
                    )}
                  </div>
                </div>
              </section>
            )}

        <CommandPalette
          open={commandPaletteOpen}
          onOpenChange={setCommandPaletteOpen}
          onNewAnalysis={reset}
          onCopyReport={showResult ? () => window.dispatchEvent(new Event("copy-report")) : undefined}
          onViewRawJson={showResult && tfFiles ? () => window.dispatchEvent(new Event("view-raw-json")) : undefined}
          onGoToHistory={() => router.push("/history")}
          resultSections={showResult ? [
            ...(sdr?.estimated_cost ? [{ id: "cost", label: "Cost" }] : []),
            { id: "compute", label: "Compute" },
            { id: "database", label: "Database" },
            { id: "cache", label: "Cache" },
            { id: "load-balancer", label: "Load Balancer" },
            ...(tfFiles ? [{ id: "terraform", label: "Terraform" }] : []),
          ] : []}
        />

        {/* ── Error ── */}
        {showError && (
          <section>
            <ErrorPanel message={error!} onRetry={reset} />
          </section>
        )}
      </main>

      {/* ── Footer ── */}
      <footer className="border-t border-border-subtle px-6 py-3 shrink-0">
        <p className="font-mono text-xs text-ink-dim text-center">
          AI-generated infrastructure — review every{" "}
          <code className="text-ink-dim">terraform plan</code> before applying
        </p>
      </footer>
    </div>
  );
}
