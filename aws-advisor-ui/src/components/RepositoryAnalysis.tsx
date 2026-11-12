import type { RepositoryFinding, RepositoryProgress, RepositoryReport } from "@/lib/types";

const categories = {
  security: "Security",
  deployment: "Deployment",
  database: "Database",
  inference: "Models and inference",
  workflow: "Workflows",
  application: "Application",
} as const;

const skippedLabels: Record<string, string> = {
  binary: "Binary or model assets",
  generated_or_vendored: "Generated or vendored",
  link_or_submodule: "Links or submodules",
  file_size_limit: "File size limit",
  scan_budget: "Scan limit",
  unreadable: "Unreadable files",
  unsupported_encoding: "Unsupported encoding",
};

const advisoryLabels: Record<RepositoryReport["advisory_status"], string> = {
  not_configured: "Dependency advisory checks were not enabled.",
  no_supported_dependencies: "No supported pinned dependencies were available for advisory checks.",
  checked: "Checked supported pinned dependencies against the offline advisory database.",
  checked_capped: "Checked supported pinned dependencies. Showing the first 12 matching advisories.",
  partial: "Dependency advisory checks covered only part of the supported inventory.",
  unavailable: "Dependency advisory checks could not finish.",
};

export function repositoryFailureMessage(progress: RepositoryProgress): string {
  switch (progress.reason) {
    case "not_accessible":
      return "Couldn’t access the repository. It may be private or the link may be incorrect.";
    case "not_public":
      return "This repository isn’t public. Use a public GitHub repository.";
    case "disabled":
      return "Repository analysis is currently disabled.";
    case "empty":
      return "The repository has no files on its default branch.";
    case "no_source":
      return "No readable source files were available within the scan limits.";
    case "timeout":
      return "The repository scan timed out. Try again.";
    case "busy":
      return "Repository scanning is busy. Try again shortly.";
    case "rate_limited": {
      const minutes = Math.ceil((progress.retry_after_seconds ?? 0) / 60);
      return minutes > 0
        ? `GitHub has limited requests. Try again in about ${minutes} ${minutes === 1 ? "minute" : "minutes"}.`
        : "GitHub has limited requests. Try again later.";
    }
    default:
      return "GitHub couldn’t be reached. Try again shortly.";
  }
}

function Evidence({ finding, commitUrl }: { finding: RepositoryFinding; commitUrl: string }) {
  if (!finding.path) return null;
  const path = finding.path.split("/").map(encodeURIComponent).join("/");
  const suffix = finding.line ? `#L${finding.line}` : "";
  return (
    <a
      href={`${commitUrl}/${path}${suffix}`}
      className="inline-block max-w-full break-all font-mono text-xs text-amber underline underline-offset-4"
      target="_blank"
      rel="noreferrer"
    >
      {finding.path}{finding.line ? `:${finding.line}` : ""}
    </a>
  );
}

interface Props {
  report?: RepositoryReport;
  progress?: RepositoryProgress;
  assumptions?: string[];
  deploymentNotes?: string[];
}

export function RepositoryAnalysis({ report, progress, assumptions, deploymentNotes }: Props) {
  if (!report) {
    if (progress?.status !== "unavailable") return null;
    return (
      <section id="repository" aria-labelledby="repository-title" className="scroll-mt-8 border-t border-border-subtle py-6">
        <h2 id="repository-title" className="text-lg font-medium text-ink">Repository analysis</h2>
        <p className="mt-2 text-sm text-ink/80">{repositoryFailureMessage(progress)}</p>
        <p className="mt-1 text-sm text-ink/80">This recommendation is based on your workload details only.</p>
      </section>
    );
  }

  const { owner, name } = report.repository;
  const repositoryUrl = `https://github.com/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`;
  const commit = encodeURIComponent(report.commit_sha);
  // Blob URLs take the SHA before the path, whereas commit links use /commit.
  const sourceUrl = `${repositoryUrl}/blob/${commit}`;
  const facts = [
    ["Stack", report.stack],
    ["Data stores", report.databases],
    ["Workflows", report.workflows],
  ] as const;
  const skipped = Object.entries(report.skipped).filter(([, count]) => count > 0);

  return (
    <section id="repository" aria-labelledby="repository-title" className="scroll-mt-8 border-t border-border-subtle py-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h2 id="repository-title" className="text-lg font-medium text-ink">Repository analysis</h2>
        <p className="text-sm text-ink/80">
          {report.coverage === "partial" ? "Partial scan" : "Scan complete"} · {report.files_analyzed.toLocaleString()} of {report.files_discovered.toLocaleString()} tracked files read
        </p>
      </div>
      <p className="mt-2 break-all text-sm">
        <a className="text-ink underline underline-offset-4" href={repositoryUrl} target="_blank" rel="noreferrer">{owner}/{name}</a>
        {" "}
        <a className="ml-1 font-mono text-xs text-amber underline underline-offset-4" href={`${repositoryUrl}/commit/${commit}`} target="_blank" rel="noreferrer" aria-label={`Analyzed commit ${report.commit_sha}`}>
          {report.commit_sha.slice(0, 8)}
        </a>
      </p>

      {Boolean(assumptions?.length || deploymentNotes?.length) && (
        <div className="mt-5 border-l-2 border-amber/60 pl-4">
          <h3 className="text-sm font-medium text-ink">{assumptions?.length ? "Provisional sizing" : "Before deployment"}</h3>
          <ul className="mt-2 space-y-1 text-sm text-ink/85">
            {[...(assumptions ?? []), ...(deploymentNotes ?? [])].map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      )}

      {facts.some(([, values]) => values.length > 0) && (
        <dl className="my-5 grid gap-3 border-y border-border-subtle py-4 sm:grid-cols-3">
          {facts.filter(([, values]) => values.length > 0).map(([label, values]) => (
            <div key={label} className="min-w-0">
              <dt className="text-sm text-ink/75">{label}</dt>
              <dd className="mt-1 text-sm font-medium text-ink">{values.join(", ")}</dd>
            </div>
          ))}
        </dl>
      )}
      {Object.entries(categories).map(([category, label]) => {
        const findings = report.findings.filter((finding) => finding.category === category);
        if (!findings.length) return null;
        return (
          <details key={category} className="group border-b border-border-subtle print:hidden">
            <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-3 py-2 text-sm text-ink marker:content-none">
              <span className="font-medium">{label}</span>
              <span className="flex items-center gap-2 text-ink/75">
                {findings.length}
                {findings.some((finding) => finding.severity === "high") && <span className="text-amber">Needs review</span>}
                <span aria-hidden="true" className="group-open:hidden">+</span>
                <span aria-hidden="true" className="hidden group-open:inline">−</span>
              </span>
            </summary>
            <ul className="divide-y divide-border-subtle pb-2">
              {findings.map((finding, index) => (
                <li key={`${finding.title}-${finding.path}-${index}`} className="py-3">
                  <p className="text-sm font-medium text-ink">{finding.title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-ink/80">{finding.action}</p>
                  <Evidence finding={finding} commitUrl={sourceUrl} />
                </li>
              ))}
            </ul>
          </details>
        );
      })}
      {report.findings.length > 0 && (
        <ul className="hidden space-y-2 print:block">
          {report.findings.map((finding, index) => (
            <li key={index} className="text-sm"><strong>{finding.title}.</strong> {finding.action} <Evidence finding={finding} commitUrl={sourceUrl} /></li>
          ))}
        </ul>
      )}

      <p className="mt-4 text-xs text-ink/75">{advisoryLabels[report.advisory_status]}</p>
      {(skipped.length > 0 || report.limitations.length > 0) && (
        <ul className="mt-2 space-y-1 text-xs text-ink/75" aria-label="Scan coverage">
          {skipped.map(([reason, count]) => <li key={reason}>{skippedLabels[reason] ?? "Other skipped files"} · {count.toLocaleString()}</li>)}
          {report.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
        </ul>
      )}
    </section>
  );
}
