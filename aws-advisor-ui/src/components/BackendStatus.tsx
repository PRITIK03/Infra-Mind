"use client";

import { useEffect, useState } from "react";
import { healthCheck } from "@/lib/api";

const POLL_INTERVAL_MS = 30_000;

type HealthState = "checking" | "healthy" | "unreachable";

export function BackendStatus() {
  const [state, setState] = useState<HealthState>("checking");

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const response = await healthCheck();
        if (!cancelled) setState(response.status === "ok" ? "healthy" : "unreachable");
      } catch {
        if (!cancelled) setState("unreachable");
      }
    };

    void check();
    const interval = window.setInterval(() => void check(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  const healthy = state === "healthy";
  return (
    <span
      className="inline-flex items-center gap-2 font-mono text-xs text-ink-dim"
      aria-label={`Backend status: ${state}`}
      title={`Backend status: ${state}`}
    >
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${healthy ? "bg-amber" : "bg-ink-dim"}`}
        aria-hidden="true"
      />
      <span className="hidden sm:inline">backend</span>
      <span className="sr-only">{state}</span>
    </span>
  );
}
