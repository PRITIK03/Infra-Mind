"use client";

import { useRef, useState } from "react";
import type { FollowupExchange } from "@/lib/types";
import { askFollowup } from "@/lib/api";

interface Props {
  jobId: string;
  /** Seed from the polling response — may already have entries. */
  initialHistory?: FollowupExchange[];
}

/**
 * Conversational follow-up panel shown below the recommendation report.
 *
 * Understated monospace style consistent with the rest of the app —
 * no chat bubbles, just a simple input and a linear Q&A log.
 */
export function FollowupPanel({ jobId, initialHistory = [] }: Props) {
  const [history, setHistory] = useState<FollowupExchange[]>(initialHistory);
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    setValue("");

    try {
      const res = await askFollowup(jobId, trimmed);
      setHistory(res.followup_history);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Follow-up request failed";
      setError(msg);
      // Restore the question so the user can retry
      setValue(trimmed);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  return (
    <section id="followup" className="py-6 scroll-mt-16">
      {/* Section header */}
      <div className="flex items-center gap-2 mb-4">
        <span className="font-mono text-xs text-ink-muted uppercase tracking-widest">
          follow-up
        </span>
        <span className="flex-1 border-t border-border-subtle" />
      </div>

      {/* Q&A history */}
      {history.length > 0 && (
        <div className="space-y-4 mb-6">
          {history.map((ex, i) => (
            <div
              key={`${ex.timestamp}-${i}`}
              className="border-l-2 border-amber/20 pl-4 space-y-1"
            >
              <p className="font-mono text-xs text-amber">
                <span aria-hidden="true">&gt; </span>
                {ex.question}
              </p>
              <p className="font-sans text-sm text-ink-muted leading-relaxed whitespace-pre-wrap">
                {ex.answer}
              </p>
              <span className="font-mono text-[10px] text-ink-dim">
                {new Date(ex.timestamp).toLocaleTimeString()}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="flex gap-0">
        <div className="flex items-center px-3 border border-r-0 border-border-subtle shrink-0">
          <span className="font-mono text-sm text-amber" aria-hidden="true">
            &gt;
          </span>
        </div>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={
            loading
              ? "thinking…"
              : "ask a question about this recommendation…"
          }
          disabled={loading}
          aria-label="Ask a follow-up question about the recommendation"
          className={[
            "flex-1 bg-transparent border border-border-subtle",
            "font-sans text-sm text-ink placeholder:text-ink-dim",
            "px-3 py-2.5 outline-none",
            "transition-colors duration-150",
            "focus:border-amber/30",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          ].join(" ")}
        />
        <button
          type="submit"
          disabled={!value.trim() || loading}
          className={[
            "border border-l-0 border-border-subtle px-4 py-2.5",
            "font-mono text-xs text-ink-muted uppercase tracking-wider",
            "transition-colors duration-150",
            "enabled:text-amber enabled:border-amber/60 enabled:hover:bg-amber/[0.04]",
            "disabled:opacity-30 disabled:cursor-not-allowed",
          ].join(" ")}
        >
          {loading ? "…" : "ask"}
        </button>
      </form>

      {/* Loading indicator */}
      {loading && (
        <p className="mt-2 font-mono text-xs text-amber animate-pulse">
          generating answer…
        </p>
      )}

      {/* Error */}
      {error && (
        <p className="mt-2 font-mono text-xs text-red-400">
          {error}
        </p>
      )}
    </section>
  );
}
