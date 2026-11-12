import Link from "next/link";

/**
 * Styled 404 — same engineering-console language as the rest of the app:
 * near-black canvas, monospace headings, amber used sparingly.
 */
export default function NotFound() {
  return (
    <div className="min-h-dvh flex flex-col items-center justify-center px-6">
      <p className="font-mono text-xs text-ink-muted uppercase tracking-widest">
        error 404
      </p>
      <h1 className="mt-3 font-mono text-2xl text-ink tracking-tight">
        page not found
      </h1>
      <p className="mt-3 max-w-md text-center text-sm text-ink-dim">
        The page you requested doesn&apos;t exist — it may have moved, or the
        link may be stale. Shared results expire along with their jobs.
      </p>
      <nav className="mt-8 flex items-center gap-3 font-mono text-xs">
        <Link
          href="/"
          className="text-amber hover:text-amber/60 transition-colors"
        >
          ← back to advisor
        </Link>
        <span className="text-ink-dim">·</span>
        <Link
          href="/history"
          className="text-ink-dim hover:text-amber transition-colors"
        >
          run history
        </Link>
        <span className="text-ink-dim">·</span>
        <Link
          href="/how-it-works"
          className="text-ink-dim hover:text-amber transition-colors"
        >
          how it works
        </Link>
      </nav>
    </div>
  );
}
