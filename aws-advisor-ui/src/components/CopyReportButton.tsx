"use client";

import { useCallback, useEffect, useState } from "react";
import { recommendationToMarkdown, type ReportData } from "@/lib/reportMarkdown";

export function CopyReportButton({
  sdr, technicalNeeds, userRequirements, repository, repositoryProgress,
  repositoryAssumptions, repositoryDeploymentNotes,
}: ReportData) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(
        recommendationToMarkdown({
          sdr, technicalNeeds, userRequirements, repository, repositoryProgress,
          repositoryAssumptions, repositoryDeploymentNotes,
        }),
      );
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [sdr, technicalNeeds, userRequirements, repository, repositoryProgress, repositoryAssumptions, repositoryDeploymentNotes]);

  useEffect(() => {
    const handleCommandCopy = () => void handleCopy();
    window.addEventListener("copy-report", handleCommandCopy);
    return () => window.removeEventListener("copy-report", handleCommandCopy);
  }, [handleCopy]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label="Copy report as Markdown"
      className="border border-border-subtle px-3 py-1.5 font-mono text-xs text-ink-dim uppercase tracking-wider transition-colors duration-150 hover:text-amber hover:border-amber/40 hover:bg-white/[0.03]"
    >
      {copied ? "copied" : "copy report as markdown"}
    </button>
  );
}
