"use client";

import { useCallback, useEffect, useState } from "react";
import type { SystemDesignRecommendation, TechnicalNeeds, UserRequirements } from "@/lib/types";
import { recommendationToMarkdown } from "@/lib/reportMarkdown";

interface Props {
  sdr: SystemDesignRecommendation;
  technicalNeeds?: TechnicalNeeds;
  userRequirements?: UserRequirements;
}

export function CopyReportButton({ sdr, technicalNeeds, userRequirements }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(
        recommendationToMarkdown({ sdr, technicalNeeds, userRequirements }),
      );
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [sdr, technicalNeeds, userRequirements]);

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
