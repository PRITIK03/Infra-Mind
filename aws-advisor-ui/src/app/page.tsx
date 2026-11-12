"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useJobPoller } from "@/hooks/useJobPoller";
import { StageProgress } from "@/components/StageProgress";
import { AwaitingInputPanel } from "@/components/AwaitingInputPanel";
// Code-split like TerraformViewer: the full report (and everything it pulls
// in) only exists once a run completes, never on the initial landing view.
const ResultReport = dynamic(
  () => import("@/components/ResultReport").then((m) => m.ResultReport),
  { ssr: false },
);
// Code-split: the viewer pulls in react-syntax-highlighter (Prism/refractor)
// and only mounts when a run actually produced Terraform files — keep it
// out of the initial landing-page bundle.
const TerraformViewer = dynamic(
  () => import("@/components/TerraformViewer").then((m) => m.TerraformViewer),
  { ssr: false },
);
import { FollowupPanel } from "@/components/FollowupPanel";
import { ErrorPanel } from "@/components/ErrorPanel";
import { SectionNav } from "@/components/SectionNav";
import { RequestSummary } from "@/components/RequestSummary";
import { CopyReportButton } from "@/components/CopyReportButton";
import { ExportPdfButton } from "@/components/ExportPdfButton";
import { CopyShareLinkButton } from "@/components/CopyShareLinkButton";
import { ResultSummaryStrip } from "@/components/ResultSummaryStrip";
import { ConsensusResult } from "@/components/ConsensusResult";
import { PipelineTrace } from "@/components/PipelineTrace";
import type { RunRecord } from "@/lib/types";
import { BackendStatus } from "@/components/BackendStatus";
import { CommandPalette } from "@/components/CommandPalette";
import { RepositoryAnalysis, repositoryFailureMessage } from "@/components/RepositoryAnalysis";
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
        InfraMind
      </span>
    </div>
  );
}

// ── Command-prompt input ──────────────────────────────────────────────────────
interface InputPanelProps {
  draft: { workload: string; githubUrl: string; compare: boolean };
  onChange: (draft: InputPanelProps["draft"]) => void;
  onSubmit: () => void;
  disabled: boolean;
  repositoryError?: string;
  error?: string;
}

const EMPTY_DRAFT = { workload: "", githubUrl: "", compare: false };
const FIELD_CLASS = "w-full rounded-lg border border-ink/40 bg-ink/[0.03] px-4 py-3 text-base leading-relaxed text-ink placeholder:text-ink/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber disabled:opacity-50";

function InputPanel({ draft, onChange, onSubmit, disabled, repositoryError, error }: InputPanelProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const repositoryRef = useRef<HTMLInputElement>(null);
  const canRun = Boolean(draft.workload.trim() || draft.githubUrl.trim()) && !disabled;

  useEffect(() => {
    if (repositoryError) repositoryRef.current?.focus();
  }, [repositoryError]);

  return (
    <form
      aria-busy={disabled}
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (canRun) onSubmit();
      }}
    >
      {error && <p className="text-sm text-red-200" role="alert">{error}</p>}
      <div>
        <label htmlFor="github-repository" className="mb-2 block text-sm font-medium text-ink">GitHub repository</label>
        <input
          id="github-repository"
          ref={repositoryRef}
          type="text"
          inputMode="url"
          autoCapitalize="none"
          autoComplete="off"
          spellCheck={false}
          maxLength={256}
          placeholder="https://github.com/owner/repository"
          value={draft.githubUrl}
          onChange={(event) => onChange({ ...draft, githubUrl: event.target.value })}
          aria-invalid={repositoryError ? true : undefined}
          aria-describedby={repositoryError ? "github-repository-error" : undefined}
          disabled={disabled}
          className={FIELD_CLASS}
        />
        {repositoryError && <p id="github-repository-error" role="alert" className="mt-2 text-sm text-red-200">{repositoryError}</p>}
      </div>
      <div>
        <label htmlFor="workload-details" className="mb-2 block text-sm font-medium text-ink">Workload details</label>
        <textarea
          id="workload-details"
          ref={textareaRef}
          value={draft.workload}
          onChange={(event) => onChange({ ...draft, workload: event.target.value })}
          onKeyDown={(event) => {
            if (!event.nativeEvent.isComposing && event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Describe your traffic, database, or deployment needs…"
          disabled={disabled}
          maxLength={10_000}
          rows={4}
          className={`${FIELD_CLASS} block min-h-28 resize-y`}
        />
        <div className="mt-2 flex flex-wrap gap-x-2" aria-label="Example workloads">
          {EXAMPLES.map((example) => (
            <button
              key={example.label}
              type="button"
              onClick={() => {
                onChange({ ...draft, workload: example.prompt });
                textareaRef.current?.focus();
              }}
              disabled={disabled}
              className="min-h-11 rounded-md px-2 text-sm text-ink/75 hover:bg-ink/[0.06] hover:text-ink disabled:opacity-50"
            >
              {example.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border-subtle pt-4">
        <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-ink/85">
          <input
            type="checkbox"
            checked={draft.compare}
            onChange={(event) => onChange({ ...draft, compare: event.target.checked })}
            disabled={disabled}
            className="accent-amber"
          />
          Compare with a second model
        </label>
        <button
          type="submit"
          disabled={!canRun}
          className="min-h-11 rounded-lg bg-amber px-5 text-sm font-semibold text-canvas transition-colors hover:bg-amber/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-amber disabled:cursor-not-allowed disabled:bg-ink/15 disabled:text-ink/60 max-sm:w-full"
        >
          {disabled ? "Starting analysis…" : "Run analysis"}
        </button>
      </div>
    </form>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Home() {
  const router = useRouter();
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [recentRun, setRecentRun] = useState<RunRecord | null>(null);
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const {
    status,
    currentStage,
    nextQuestion,
    jobResponse,
    error,
    retryInfo,
    isWakingUp,
    isActive,
    inputError,
    submit,
    answer,
    reset,
    totalElapsedMs,
    retryCount,
  } = useJobPoller();

  useEffect(() => {
    getRuns()
      .then((response) => {
        if (response.observability_configured && response.runs.length > 0) {
          setRecentRun(response.runs[0]);
        }
      })
      .catch(() => setRecentRun(null));
  }, []);

  const repositoryProgress = jobResponse?.repository;
  const failedRepository = repositoryProgress?.status === "unavailable" ? repositoryProgress : undefined;
  const canEditFailedRun = status === "error" && Boolean(draft.workload || draft.githubUrl);
  const showLanding = status === null || canEditFailedRun;
  const showProgress = status !== null && status !== "done" && status !== "error";
  const showResult = status === "done" && jobResponse?.result != null;
  const showError = status === "error" && error != null && !canEditFailedRun;
  const repositoryError = status === "error"
    ? inputError === "github_url" ? error ?? undefined
      : failedRepository ? `${repositoryFailureMessage(failedRepository)} Add workload details or edit the link.`
        : undefined
    : undefined;
  const report = jobResponse?.result?.repository_report;
  const repositoryAssumptions = jobResponse?.result?.repository_assumptions;
  const repositoryDeploymentNotes = jobResponse?.result?.repository_deployment_notes;
  const hasRepositorySection = Boolean(report || failedRepository);

  const sdr = jobResponse?.result?.system_design_recommendation;
  const tfFiles = jobResponse?.result?.terraform_files;
  const technicalNeeds = jobResponse?.result?.technical_needs;
  const userRequirements = jobResponse?.result?.user_requirements;
  const instanceCandidates = jobResponse?.result?.instance_candidates;
  const newAnalysis = () => {
    setDraft(EMPTY_DRAFT);
    reset();
  };
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
              <Link
                href="/how-it-works"
                className="font-mono text-xs text-ink-dim hover:text-amber hover:bg-white/[0.03] transition-colors px-2 py-1"
              >
                how it works
              </Link>
            </nav>
          </div>
          {process.env.NEXT_PUBLIC_API_URL && (
            <span className="flex items-center gap-2">
              <BackendStatus />
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
              <h1 className="font-sans text-3xl font-medium text-ink tracking-tight">
                Plan your AWS infrastructure
              </h1>
            </div>
            <InputPanel
              draft={draft}
              onChange={(nextDraft) => {
                setDraft(nextDraft);
                if (status === "error") reset();
              }}
              onSubmit={() => {
                const githubUrl = draft.githubUrl.trim();
                if (githubUrl) void submit(draft.workload.trim(), draft.compare, githubUrl);
                else void submit(draft.workload.trim(), draft.compare);
              }}
              disabled={isActive}
              repositoryError={repositoryError}
              error={canEditFailedRun && !repositoryError ? error ?? undefined : undefined}
            />
            {recentRun && recentSnapshot && (
              <div className="mt-8 border-l-2 border-amber/30 pl-3" aria-label="Recent activity">
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
              <div className="flex items-center gap-3" role="status" aria-live="polite">
                <span className="w-2 h-2 rounded-full bg-amber animate-pulse shrink-0" />
                <span className="font-mono text-sm text-ink-muted typewriter-cursor">
                  {currentStage || "Initializing"}
                </span>
              </div>
            )}
            {failedRepository && (
              <p className="text-sm text-ink/80" role="status">
                {repositoryFailureMessage(failedRepository)} Continuing with workload details.
              </p>
            )}

            <hr className="console-rule" />

            <StageProgress
              currentStage={currentStage}
              status={status}
              retryInfo={retryInfo}
              hasRepository={Boolean(repositoryProgress)}
            />
          </section>
        )}

        {/* ── Result ── */}
        {showResult && sdr && (
              <section>
                {/* "New analysis" action in top bar */}
                <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <h1 className="text-lg font-medium text-ink">Recommendation</h1>
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
                      repository={report}
                      repositoryProgress={repositoryProgress}
                      repositoryAssumptions={repositoryAssumptions}
                      repositoryDeploymentNotes={repositoryDeploymentNotes}
                    />
                    <CopyShareLinkButton jobId={jobResponse!.job_id} restricted={hasRepositorySection} />
                    <ExportPdfButton />
                    <button
                      type="button"
                      onClick={newAnalysis}
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

                {Boolean(repositoryAssumptions?.length) && (
                  <a href="#repository" className="mb-4 inline-block text-sm text-amber underline underline-offset-4">Review provisional sizing assumptions</a>
                )}
                <div className="grid gap-6 xl:grid-cols-[200px_1fr_280px]">
                  {/* Left: sticky section nav (desktop only) */}
                  <div className="print:hidden">
                    <SectionNav
                      sdr={sdr}
                      technicalNeeds={technicalNeeds}
                      hasTerraform={Boolean(tfFiles && Object.keys(tfFiles).length > 0)}
                      hasRepository={hasRepositorySection}
                    />
                  </div>

                  {/* Center: main report */}
                  <div className="min-w-0">
                    <ResultSummaryStrip sdr={sdr} />
                    <ResultReport
                      sdr={sdr}
                      technicalNeeds={technicalNeeds}
                      instanceCandidates={instanceCandidates}
                    />
                    <RepositoryAnalysis
                      report={report}
                      progress={repositoryProgress}
                      assumptions={repositoryAssumptions}
                      deploymentNotes={repositoryDeploymentNotes}
                    />

                    {sdr.consensus_result && (
                      <ConsensusResult consensus={sdr.consensus_result} />
                    )}

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
                  <div className="min-w-0 flex flex-col gap-6 xl:sticky xl:top-24 self-start print:hidden">
                    {technicalNeeds && (
                      <RequestSummary
                        tn={technicalNeeds}
                        requirements={userRequirements}
                        repoAnalysisNote={repositoryProgress ? undefined : sdr.repo_analysis_note}
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
          onNewAnalysis={newAnalysis}
          onCopyReport={showResult ? () => window.dispatchEvent(new Event("copy-report")) : undefined}
          onViewRawJson={showResult && tfFiles ? () => window.dispatchEvent(new Event("view-raw-json")) : undefined}
          onGoToHistory={() => router.push("/history")}
          resultSections={showResult ? [
            ...(sdr?.deployment_handoff ? [{ id: "deployment", label: "Deployment" }] : []),
            ...(sdr?.estimated_cost ? [{ id: "cost", label: "Cost" }] : []),
            { id: "compute", label: "Compute" },
            { id: "database", label: "Database" },
            { id: "cache", label: "Cache" },
            { id: "load-balancer", label: "Load Balancer" },
            ...(hasRepositorySection ? [{ id: "repository", label: "Repository analysis" }] : []),
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
