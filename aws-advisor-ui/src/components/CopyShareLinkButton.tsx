"use client";

import { useCallback, useState } from "react";
import { createShareLink, shareUrl } from "@/lib/api";

/** "Copy share link" — same understated button style as the other report actions. */
export function CopyShareLinkButton({ jobId, restricted = false }: { jobId: string; restricted?: boolean }) {
  const [copied, setCopied] = useState(false);
  const [pending, setPending] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [manualLink, setManualLink] = useState<string | null>(null);

  const handleCopy = useCallback(async () => {
    setPending(true);
    setCopyError(null);
    setManualLink(null);
    let url: string | undefined;
    try {
      const id = restricted ? (await createShareLink(jobId)).share_id : jobId;
      url = shareUrl(id);
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        setManualLink(url);
        return;
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
      if (url) setManualLink(url);
      else setCopyError("Couldn’t create the share link. Try again.");
    } finally {
      setPending(false);
    }
  }, [jobId, restricted]);

  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={handleCopy}
        disabled={pending}
        aria-label="Copy share link"
        className="border border-border-subtle px-3 py-1.5 font-mono text-xs text-ink-dim uppercase tracking-wider transition-colors duration-150 hover:text-amber hover:border-amber/40 hover:bg-white/[0.03]"
      >
        {pending ? "creating link…" : copied ? "link copied" : "copy share link"}
      </button>
      {copied && <span role="status" className="sr-only">Share link copied.</span>}
      {copyError && <p role="alert" className="mt-2 text-xs text-red-200">{copyError}</p>}
      {manualLink && (
        <input
          readOnly value={manualLink} aria-label="Share link"
          onFocus={(event) => event.currentTarget.select()}
          className="mt-2 block w-full border border-border-subtle bg-canvas p-2 text-xs text-ink"
        />
      )}
    </div>
  );
}
