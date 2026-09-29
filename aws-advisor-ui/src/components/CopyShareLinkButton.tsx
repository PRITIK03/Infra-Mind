"use client";

import { useCallback, useState } from "react";
import { shareUrl } from "@/lib/api";

/** "Copy share link" — same understated button style as the other report actions. */
export function CopyShareLinkButton({ jobId }: { jobId: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      const url = shareUrl(jobId);
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = url;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [jobId]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label="Copy share link"
      className="border border-border-subtle px-3 py-1.5 font-mono text-xs text-ink-dim uppercase tracking-wider transition-colors duration-150 hover:text-amber hover:border-amber/40 hover:bg-white/[0.03]"
    >
      {copied ? "link copied" : "copy share link"}
    </button>
  );
}
