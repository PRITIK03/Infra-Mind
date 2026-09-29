"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { answerJob, createJob, healthCheck, pollJob, streamJobUrl } from "@/lib/api";
import type { JobResponse, JobStatus } from "@/lib/types";

const POLL_INTERVAL_MS = 2500;
const WAKE_THRESHOLD_MS = 5000;
const HEALTH_RETRY_DELAY_MS = 1000;
// Streaming fallback tuning (see startPolling):
//  - a stream that has delivered nothing within this many ticks (~5s) is
//    treated as accepted-but-buffered and abandoned for plain polling;
//  - a healthy stream gets a low-rate backstop poll every this many ticks
//    (~15s) so a mid-run silent stall still self-heals.
const STREAM_CONNECT_TICKS = 2;
const STREAM_STANDBY_TICKS = 6;

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

  // Track whether we should keep polling (the polling fallback path)
  const pollingRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollingSessionRef = useRef(0);
  const pollInFlightSessionRef = useRef<number | null>(null);
  // Active SSE connection, when the backend's /stream endpoint is serving us.
  // Preferring this over polling is what makes stage changes land instantly;
  // polling stays available underneath and takes over transparently if the
  // stream can't be established or breaks mid-run (proxies/buffering hosts).
  const streamRef = useRef<EventSource | null>(null);
  const streamActiveRef = useRef(false);
  const wakeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startTimeRef = useRef<number | null>(null);
  const lastRetryInfoRef = useRef<string | null>(null);

  const clearWakeTimer = useCallback(() => {
    if (wakeTimerRef.current !== null) {
      clearTimeout(wakeTimerRef.current);
      wakeTimerRef.current = null;
    }
  }, []);

  const closeStream = useCallback(() => {
    streamActiveRef.current = false;
    if (streamRef.current !== null) {
      try {
        streamRef.current.close();
      } catch {
        // EventSource.close() is infallible in practice; never break teardown.
      }
      streamRef.current = null;
    }
  }, []);

  const stopPolling = useCallback(() => {
    pollingRef.current = false;
    pollingSessionRef.current += 1;
    pollInFlightSessionRef.current = null;
    closeStream();
    clearWakeTimer();
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, [clearWakeTimer, closeStream]);

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
        // stopPolling closes the stream and clears the standby interval.
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

  const openStream = useCallback(
    (id: string, session: number, onEvent: (resp: JobResponse) => void) => {
      const url = streamJobUrl(id);
      if (url === null || typeof EventSource === "undefined") {
        // No backend URL or no SSE support: stay on polling from the start.
        return;
      }
      closeStream();
      streamActiveRef.current = true;
      try {
        const source = new EventSource(url);
        streamRef.current = source;
        source.onmessage = (event: MessageEvent) => {
          // Stale-source guard: only the current polling session's stream may
          // update state (and only while it is still the preferred transport).
          if (pollingSessionRef.current !== session || !streamActiveRef.current) return;
          let parsed: JobResponse;
          try {
            parsed = JSON.parse(event.data) as JobResponse;
          } catch {
            return; // a mangled frame must not kill the stream; heartbeats are ignored anyway
          }
          if (parsed == null || typeof parsed !== "object" || parsed.status == null) return;
          onEvent(parsed);
        };
        source.onerror = () => {
          // Stream failed to establish or broke mid-flight (proxies/buffering
          // hosts are the classic cause). Hand over to polling silently — the
          // user keeps getting updates, just on the poll cadence. Because the
          // polling loop is already running underneath, all this needs to do
          // is stop preferring the broken stream.
          if (pollingSessionRef.current !== session) return;
          streamActiveRef.current = false;
          try {
            source.close();
          } catch {
            // ignore — already tearing down
          }
          if (streamRef.current === source) streamRef.current = null;
        };
      } catch {
        // EventSource construction itself failed (blocked URL, CSP): polling
        // is already running underneath, so just don't prefer the stream.
        streamActiveRef.current = false;
      }
    },
    [closeStream]
  );

  const startPolling = useCallback(
    (id: string) => {
      pollingRef.current = true;
      const session = ++pollingSessionRef.current;
      let tick = 0;
      let sawStreamEvent = false;
      let streamEvents = 0;
      openStream(id, session, (streamResp) => {
        if (pollingSessionRef.current !== session) {
          return;
        }
        streamEvents += 1;
        sawStreamEvent = true;
        applyResponse(streamResp);
      });
      intervalRef.current = setInterval(async () => {
        if (
          !pollingRef.current ||
          pollingSessionRef.current !== session ||
          pollInFlightSessionRef.current !== null
        ) return;
        tick += 1;
        if (streamActiveRef.current) {
          if (!sawStreamEvent) {
            // The connection was accepted but no frame has arrived. The
            // server sends the current state immediately on connect, so a
            // healthy stream delivers within milliseconds — a silence this
            // long means a buffering/blocking proxy. Give up on the stream
            // and fall through to the poll below (the documented fallback).
            if (tick < STREAM_CONNECT_TICKS) return;
            closeStream();
          } else if (tick % STREAM_STANDBY_TICKS !== 0) {
            // Healthy stream: it already delivered anything newer, so poll
            // only at the low-rate backstop cadence — enough to self-heal the
            // rare "delivered once, then silently buffered" connection without
            // doubling backend traffic. If the stream errors, onerror clears
            // streamActiveRef and every tick polls again at full cadence.
            return;
          }
        }
        pollInFlightSessionRef.current = session;
        const eventsBeforePoll = streamEvents;
        try {
          const resp = await pollJob(id);
          if (pollingSessionRef.current !== session) return;
          // If the stream delivered anything while this poll was in flight,
          // the stream's snapshot is newer than the poll's — skip this one.
          if (streamEvents !== eventsBeforePoll) return;
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
    [applyResponse, closeStream, openStream, stopPolling]
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
