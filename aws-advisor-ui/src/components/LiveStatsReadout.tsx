"use client";

import { useEffect, useState } from "react";
import { getStats } from "@/lib/api";

interface Stats {
  ec2: number;
  rds: number;
  cache: number;
}

function fmt(n: number): string {
  return n.toLocaleString("en-US");
}

export function LiveStatsReadout() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getStats()
      .then((s) => { if (!cancelled) { setStats(s); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    // Skeleton bar matching the final line's shape (single mono text line).
    // animate-pulse is disabled under prefers-reduced-motion (globals.css),
    // leaving a static placeholder bar.
    return (
      <span
        className="inline-block h-3 w-72 max-w-full bg-white/[0.07] animate-pulse"
        role="status"
        aria-label="loading instance data"
      />
    );
  }

  if (!stats) return null;

  return (
    <span className="font-mono text-xs text-ink-dim">
      <span className="text-ink-muted">{fmt(stats.ec2)}</span> EC2
      {" · "}
      <span className="text-ink-muted">{fmt(stats.rds)}</span> RDS
      {" · "}
      <span className="text-ink-muted">{fmt(stats.cache)}</span> cache types tracked live
    </span>
  );
}
