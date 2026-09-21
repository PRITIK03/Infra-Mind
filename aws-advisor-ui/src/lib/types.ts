// ─── API contract types ────────────────────────────────────────────────────
// Mirror the FastAPI backend schemas exactly. Field names match
// the JSON produced by _job_response() and _serialize_result().

export type JobStatus =
  | "collecting"
  | "awaiting_input"
  | "running"
  | "done"
  | "error";

export type CacheEngine = "Memcached" | "Redis" | "Valkey";

export interface InstanceRecommendation {
  recommended_instance: string;
  why: string;
  assumptions: string[];
  confidence: "low" | "medium" | "high";
  alternative_instance?: string | null;
  trade_off?: string | null;
}

export interface DatabaseRecommendation {
  needed: boolean;
  recommended_instance?: string | null;
  engine_suggestion?: string | null;
  why: string;
  assumptions: string[];
  confidence: "low" | "medium" | "high";
  alternative_instance?: string | null;
}

export interface CacheRecommendation {
  needed: boolean;
  recommended_instance?: string | null;
  engine?: CacheEngine | null;
  why: string;
  assumptions: string[];
  confidence: "low" | "medium" | "high";
  alternative_instance?: string | null;
  alternative_engine?: CacheEngine | null;
}

export interface LoadBalancerRecommendation {
  needed: boolean;
  load_balancer_type?: string | null;
  why: string;
}

export interface EstimatedCost {
  compute_monthly_low?: number | null;
  compute_monthly_high?: number | null;
  database_monthly?: number | null;
  cache_monthly?: number | null;
  total_monthly_low?: number | null;
  total_monthly_high?: number | null;
}

export interface SystemDesignRecommendation {
  compute: InstanceRecommendation;
  database: DatabaseRecommendation;
  cache: CacheRecommendation;
  load_balancer: LoadBalancerRecommendation;
  architecture_summary: string;
  repo_analysis_note?: string | null;
  estimated_cost?: EstimatedCost | null;
  grounding_passed?: boolean | null;
  /** Array of issue strings from the grounding check; empty when passed */
  grounding_notes?: string[] | null;
}

export interface UserRequirements {
  workload_type?: "web_app" | "api_service" | "batch_processing" | "ml_inference" | "other" | null;
  registered_users?: number | null;
  requests_per_second?: number | null;
}

export interface JobResult {
  system_design_recommendation?: SystemDesignRecommendation;
  /** Legacy V1 fallback — rendered if system_design_recommendation is absent */
  recommendation?: InstanceRecommendation;
  terraform_files?: Record<string, string>;
  /** Live EC2 candidate pool used by the recommender — for CandidateLandscape */
  instance_candidates?: InstanceCandidate[];
  /** Derived technical needs — for ScalingRangeBar */
  technical_needs?: TechnicalNeeds;
  user_requirements?: UserRequirements;
  total_elapsed_ms?: number | null;
  retry_count?: number | null;
}

// ─── TechnicalNeeds (subset of fields the frontend needs) ─────────────────
export interface TechnicalNeeds {
  estimated_concurrency: number;
  min_instances: number;
  max_instances: number;
  scaling_recommendation: string;
  needs_database: boolean;
  needs_cache: boolean;
  load_balancer_needed: boolean;
  resource_profile: string;
  traffic_pattern: string;
  requires_gpu: boolean;
  reasoning: string;
}

// ─── InstanceCandidate ────────────────────────────────────────────────────
export interface InstanceCandidate {
  instance_type: string;
  vcpu: number;
  memory_gib: number;
  gpu_count: number;
  gpu_model?: string | null;
  gpu_memory_gib?: number | null;
  network_performance?: string | null;
  hourly_price_usd?: number | null;
}

// ─── Polling response shapes ───────────────────────────────────────────────
// Fields are conditionally present — absent when not applicable.

export interface FollowupExchange {
  question: string;
  answer: string;
  timestamp: string;
}

export interface JobResponse {
  job_id: string;
  status: JobStatus;
  current_stage: string;
  created_at: number;
  // awaiting_input only:
  next_question?: string;
  // done only:
  result?: JobResult;
  /** Rate-limit retry progress message — set by backend during retries */
  retry_info?: string | null;
  // error only:
  error?: string;
  /** Conversational follow-up Q&A history — populated after job is done */
  followup_history?: FollowupExchange[];
}

// ─── Ordered stage list — drives the progress step-list ───────────────────
// Matches STAGE_LABELS in app/api/jobs.py (including the grounding_check node).

export const ORDERED_STAGES = [
  "Initializing",
  "Collecting requirements",
  "Validating requirements",
  "Reasoning about system design",
  "Researching compute options",
  "Researching database options",
  "Researching cache options",
  "Building final recommendation",
  "Checking recommendation consistency",
  "Generating Terraform",
] as const;

export type StageName = (typeof ORDERED_STAGES)[number];

// ─── Run history / observability ────────────────────────────────────────────
// Field names match the backend's get_runs() response exactly.
// Backend: job_id, timestamp, total_latency_s (float seconds),
//          model_used, retry_count, grounding_passed,
//          estimated_cost_low, estimated_cost_high

export interface RunRecord {
  /** Primary key from the backend run_history table */
  job_id: string;
  timestamp: string;
  /** Wall-clock seconds from job start to completion (float) */
  total_latency_s: number | null;
  model_used: string | null;
  retry_count: number | null;
  grounding_passed: boolean | null;
  estimated_cost_low: number | null;
  estimated_cost_high: number | null;
  recommendation_snapshot: RecommendationSnapshot | null;
}

export interface RecommendationSnapshot {
  compute_instance: string | null;
  compute_monthly?: number | null;
  database_instance: string | null;
  database_engine: string | null;
  database_monthly?: number | null;
  cache_instance: string | null;
  cache_engine: string | null;
  cache_monthly?: number | null;
  load_balancer_type: string | null;
  min_instances: number | null;
  max_instances: number | null;
}

export interface RunsResponse {
  observability_configured: boolean;
  runs: RunRecord[];
  total?: number;
  page?: number;
  page_size?: number;
}
