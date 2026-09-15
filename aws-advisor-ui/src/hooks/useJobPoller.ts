"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { answerJob, createJob, healthCheck, pollJob } from "@/lib/api";
import type { JobResponse, JobStatus } from "@/lib/types";

const POLL_INTERVAL_MS = 2500;
const WAKE_THRESHOLD_MS = 5000;
const HEALTH_RETRY_DELAY_MS = 1000;

export interface UseJobPollerReturn {
  status: JobStatus | null;
  currentStage: string;
  nextQuestion: string | null;
  jobResponse: JobResponse | null;
  error: string | null;
  retryInfo: string | null;
  isWakingUp: boolean;
  isActive: boolean;
  submit: (message: string) => Promise<void>;
  answer: (reply: string) => Promise<void>;
  reset: () => void;
  totalElapsedMs: number | null;
  retryCount: number | null;
}

export function useJobPoller(): UseJobPollerReturn {
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobResponse, setJobResponse] = useState<JobResponse | null>(null);
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [currentStage, setCurrentStage] = useState<string>("");
  const [nextQuestion, setNextQuestion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryInfo, setRetryInfo] = useState<string | null>(null);
  const [isWakingUp, setIsWakingUp] = useState(false);
  const [totalElapsedMs, setTotalElapsedMs] = useState<number | null>(null);
  const [retryCount, setRetryCount] = useState<number | null>(null);

  // Track whether we should keep polling
  const pollingRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingSessionRef = useRef(0);
  const pollInFlightSessionRef = useRef<number | null>(null);
  const wakeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startTimeRef = useRef<number | null>(null);
  const lastRetryInfoRef = useRef<string | null>(null);

  const clearWakeTimer = useCallback(() => {
    if (wakeTimerRef.current !== null) {
      clearTimeout(wakeTimerRef.current);
      wakeTimerRef.current = null;
    }
  }, []);

  const stopPolling = useCallback(() => {
    pollingRef.current = false;
    pollingSessionRef.current += 1;
    pollInFlightSessionRef.current = null;
    clearWakeTimer();
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, [clearWakeTimer]);

  const applyResponse = useCallback(
    (resp: JobResponse) => {
      setJobResponse(resp);
      setStatus(resp.status);
      setCurrentStage(resp.current_stage);
      setRetryInfo(resp.retry_info ?? null);
      setIsWakingUp(false);

      if (resp.retry_info && resp.retry_info !== lastRetryInfoRef.current) {
        lastRetryInfoRef.current = resp.retry_info;
        setRetryCount((prev) => (prev == null ? 1 : prev + 1));
      }

      if (resp.status === "awaiting_input") {
        setNextQuestion(resp.next_question ?? null);
        stopPolling();
      } else if (resp.status === "done" || resp.status === "error") {
        if (resp.error) setError(resp.error);
        stopPolling();

        const serverElapsed = resp.result?.total_elapsed_ms;
        const serverRetries = resp.result?.retry_count;

        if (serverElapsed != null) {
          setTotalElapsedMs(serverElapsed);
        } else if (startTimeRef.current != null) {
          setTotalElapsedMs(Date.now() - startTimeRef.current);
        }

        if (serverRetries != null) {
          setRetryCount(serverRetries);
        }
      }
    },
    [stopPolling]
  );

  const startPolling = useCallback(
    (id: string) => {
      pollingRef.current = true;
      const session = ++pollingSessionRef.current;
      intervalRef.current = setInterval(async () => {
        if (
          !pollingRef.current ||
          pollingSessionRef.current !== session ||
          pollInFlightSessionRef.current !== null
        ) return;
        pollInFlightSessionRef.current = session;
        try {
          const resp = await pollJob(id);
          if (pollingSessionRef.current !== session) return;
          applyResponse(resp);
        } catch (err) {
          if (pollingSessionRef.current !== session) return;
          setError(err instanceof Error ? err.message : "Polling failed");
          stopPolling();
        } finally {
          if (pollInFlightSessionRef.current === session) {
            pollInFlightSessionRef.current = null;
          }
        }
      }, POLL_INTERVAL_MS);
    },
    [applyResponse, stopPolling]
  );

  // Clean up on unmount
  useEffect(() => () => {
    stopPolling();
    clearWakeTimer();
  }, [clearWakeTimer, stopPolling]);

  // A sleeping host can take several seconds to answer its first request.
  // Probe once on mount, retry once after a transient failure, and keep the
  // same notice available for a slow first recommendation request.
  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    const wakeTimer = setTimeout(() => {
      if (!cancelled) setIsWakingUp(true);
    }, WAKE_THRESHOLD_MS);

    const check = async (isRetry: boolean) => {
      try {
        await healthCheck();
        if (!cancelled) {
          clearTimeout(wakeTimer);
          setIsWakingUp(false);
        }
      } catch {
        if (!cancelled && !isRetry) {
          setIsWakingUp(true);
          retryTimer = setTimeout(() => { void check(true); }, HEALTH_RETRY_DELAY_MS);
        }
      }
    };

    void check(false);
    return () => {
      cancelled = true;
      clearTimeout(wakeTimer);
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, []);

  const submit = useCallback(
    async (message: string) => {
      clearWakeTimer();
      wakeTimerRef.current = setTimeout(() => setIsWakingUp(true), WAKE_THRESHOLD_MS);
      stopPolling();
      setJobId(null);
      setJobResponse(null);
      setStatus(null);
      setCurrentStage("Initializing");
      setNextQuestion(null);
      setRetryInfo(null);
      setError(null);
      setTotalElapsedMs(null);
      setRetryCount(null);
      startTimeRef.current = Date.now();
      lastRetryInfoRef.current = null;

      try {
        const { job_id } = await createJob(message);
        clearWakeTimer();
        setJobId(job_id);
        setStatus("collecting");
        startPolling(job_id);
      } catch (err) {
        clearWakeTimer();
        setError(err instanceof Error ? err.message : "Failed to start job");
        setStatus("error");
      }
    },
    [clearWakeTimer, stopPolling, startPolling]
  );

  const answer = useCallback(
    async (reply: string) => {
      if (!jobId) return;
      setNextQuestion(null);
      setStatus("running");
      setError(null);

      try {
        await answerJob(jobId, reply);
        startPolling(jobId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to submit answer");
        setStatus("error");
      }
    },
    [jobId, startPolling]
  );

  const reset = useCallback(() => {
    stopPolling();
    setIsWakingUp(false);
    setJobId(null);
    setJobResponse(null);
    setStatus(null);
    setCurrentStage("");
    setNextQuestion(null);
    setError(null);
    setRetryInfo(null);
    setTotalElapsedMs(null);
    setRetryCount(null);
    startTimeRef.current = null;
    lastRetryInfoRef.current = null;
  }, [stopPolling]);

  const isActive =
    status === "collecting" || status === "running";

  return {
    status,
    currentStage,
    nextQuestion,
    jobResponse,
    error,
    retryInfo,
    isWakingUp,
    isActive,
    submit,
    answer,
    reset,
    totalElapsedMs,
    retryCount,
  };
}
