"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchSharedJob } from "@/lib/api";
import type { JobResponse } from "@/lib/types";
import { ResultReport } from "@/components/ResultReport";
import { TerraformViewer } from "@/components/TerraformViewer";
import { WellArchitectedReview } from "@/components/WellArchitectedReview";
import { ContainerizedAlternative } from "@/components/ContainerizedAlternative";
import { CostSection } from "@/components/CostSection";
import { ConfidenceStrip } from "@/components/ConfidenceStrip";
import { ResultSummaryStrip } from "@/components/ResultSummaryStrip";
import { RequestSummary } from "@/components/RequestSummary";
import { CopyReportButton } from "@/components/CopyReportButton";
import { ExportPdfButton } from "@/components/ExportPdfButton";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; job: JobResponse }
  | { kind: "unavailable" };

/**
 * Read-only shared recommendation view.
 *
 * Data comes from GET /api/share/{job_id}, which only ever answers for
 * finished jobs — anything else (running, errored, unknown id) renders the
 * honest not-available state, never a broken page.
 *
 * Rendering reuses the exact same result components as an active session
 * (ResultReport, TerraformViewer, …) with no new display code. Read-only is
 * enforced by composition: FollowupPanel and the "New Analysis" reset are
 * simply not mounted here, so there is no input and no editing of any kind.
 */
export default function SharePage() {
  const params = useParams<{ jobId: string }>();
  const jobId = params?.jobId ?? "";
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetchSharedJob(jobId)
      .then((job) => {
        if (!cancelled) setState({ kind: "ready", job });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "unavailable" });
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  return (
    <div className="min-h-dvh flex flex-col">
      <header className="border-b border-border-subtle px-6 py-3 shrink-0">
        <div className="max-w-6xl mx-auto flex items-center gap-3">
          <Link href="/" className="flex items-baseline gap-2">
            <span className="font-mono text-sm font-medium text-amber tracking-tight">
              aws-instance-advisor
            </span>
            <span className="font-mono text-xs text-ink-dim">v2</span>
          </Link>
          <span className="border border-border-subtle px-2 py-0.5 font-mono text-[11px] text-ink-dim uppercase tracking-wider">
            shared
          </span>
        </div>
      </header>

      <main className="flex-1 w-full max-w-6xl mx-auto px-6 py-6">
        {state.kind === "loading" && (
          <section aria-label="Loading shared recommendation">
            <p className="font-mono text-xs text-ink-dim">
              loading shared recommendation…
            </p>
          </section>
        )}

        {state.kind === "unavailable" && (
          <section aria-label="Recommendation unavailable">
            <p className="font-mono text-sm text-ink">recommendation unavailable</p>
            <p className="mt-2 font-sans text-sm text-ink-muted leading-relaxed">
              This recommendation isn&apos;t available (it may still be
              running, or the link is invalid).
            </p>
            <Link
              href="/"
              className="mt-4 inline-block font-mono text-xs text-amber hover:underline"
            >
              Start your own analysis →
            </Link>
          </section>
        )}

        {state.kind === "ready" && <SharedResult job={state.job} />}
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

function SharedResult({ job }: { job: JobResponse }) {
  const sdr = job.result?.system_design_recommendation;
  const technicalNeeds = job.result?.technical_needs;
  const tfFiles = job.result?.terraform_files;

  // The backend only answers /share for done jobs, so a missing payload here
  // is a data problem, not an editing opportunity — stay honest, stay static.
  if (!sdr) {
    return (
      <section aria-label="Recommendation unavailable">
        <p className="font-mono text-sm text-ink">recommendation unavailable</p>
        <p className="mt-2 font-sans text-sm text-ink-muted leading-relaxed">
          This recommendation isn&apos;t available (it may still be running,
          or the link is invalid).
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Shared recommendation">
      {/* ── Framing: obviously a shared view, not an active session ── */}
      <p className="font-mono text-xs text-ink-muted">
        Viewing a shared recommendation
      </p>
      {technicalNeeds && (
        <h1 className="mt-1 font-mono text-xl text-ink">
          &ldquo;{technicalNeeds.scaling_recommendation}&rdquo;
        </h1>
      )}

      <ResultSummaryStrip sdr={sdr} />

      <div className="mb-4 flex flex-wrap items-center gap-2 print:hidden">
        <CopyReportButton sdr={sdr} technicalNeeds={technicalNeeds} />
        <ExportPdfButton />
      </div>

      {sdr.well_architected_review && sdr.well_architected_review.length > 0 && (
        <div id="well-architected" className="py-6 scroll-mt-16">
          <WellArchitectedReview findings={sdr.well_architected_review} />
        </div>
      )}

      <ConfidenceStrip sdr={sdr} />

      <ResultReport sdr={sdr} technicalNeeds={technicalNeeds} />

      {sdr.containerized_alternative?.recommended && (
        <div id="containerized-alternative" className="py-6 scroll-mt-16">
          <ContainerizedAlternative alternative={sdr.containerized_alternative} />
        </div>
      )}

      {technicalNeeds && (
        <RequestSummary tn={technicalNeeds} repoAnalysisNote={sdr.repo_analysis_note} />
      )}

      {sdr.estimated_cost && (
        <CostSection
          cost={sdr.estimated_cost}
          databaseNeeded={sdr.database.needed}
          cacheNeeded={sdr.cache.needed}
        />
      )}

      {tfFiles && Object.keys(tfFiles).length > 0 && (
        <div id="terraform" className="py-6 scroll-mt-16">
          <TerraformViewer files={tfFiles} recommendation={sdr} />
        </div>
      )}
    </section>
  );
}
