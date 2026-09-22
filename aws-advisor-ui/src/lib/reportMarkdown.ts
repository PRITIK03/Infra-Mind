import type {
  EstimatedCost,
  SystemDesignRecommendation,
  TechnicalNeeds,
  UserRequirements,
} from "./types";

interface ReportData {
  sdr: SystemDesignRecommendation;
  technicalNeeds?: TechnicalNeeds;
  userRequirements?: UserRequirements;
}

export function formatConcurrency(
  count: number,
  workloadType?: UserRequirements["workload_type"],
): string {
  const unit = workloadType === "batch_processing" ? "job/worker slot" : "user";
  return `${count} concurrent ${unit}${count === 1 ? "" : "s"}`;
}

function costValue(value: number | null | undefined): string | null {
  return value == null ? null : `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function costRange(low: number | null | undefined, high: number | null | undefined): string | null {
  const lowValue = costValue(low);
  const highValue = costValue(high);
  if (!lowValue && !highValue) return null;
  if (lowValue && highValue && lowValue !== highValue) return `${lowValue} - ${highValue}`;
  return lowValue ?? highValue;
}

function addField(lines: string[], label: string, value: string | null | undefined) {
  if (value != null && value !== "") lines.push(`- ${label}: ${value}`);
}

function addTier(
  lines: string[],
  label: string,
  tier: {
    needed?: boolean;
    why: string;
    confidence: string;
    recommended_instance?: string | null;
    engine_suggestion?: string | null;
    engine?: string | null;
    alternative_instance?: string | null;
    trade_off?: string | null;
    assumptions?: string[];
  },
) {
  lines.push(`### ${label}`);
  if (tier.needed === false) {
    lines.push("- Status: not needed");
  } else {
    addField(lines, "Recommended", tier.recommended_instance);
    addField(lines, "Engine", tier.engine_suggestion ?? tier.engine);
    addField(lines, "Confidence", tier.confidence);
    addField(lines, "Why", tier.why);
    addField(lines, "Alternative", tier.alternative_instance);
    addField(lines, "Trade-off", tier.trade_off);
    if (tier.assumptions?.length) {
      lines.push("- Assumptions:");
      tier.assumptions.forEach((assumption) => lines.push(`  - ${assumption}`));
    }
  }
  if (tier.needed === false) addField(lines, "Why", tier.why);
  lines.push("");
}

function addCost(lines: string[], cost: EstimatedCost, sdr: SystemDesignRecommendation) {
  lines.push("## Estimated Monthly Cost");
  const compute = costRange(cost.compute_monthly_low, cost.compute_monthly_high);
  addField(lines, "Compute", compute);
  if (sdr.database.needed) {
    addField(lines, "Database", costValue(cost.database_monthly) ?? "pricing unavailable");
  } else {
    lines.push("- Database: not needed");
  }
  if (sdr.cache.needed) {
    addField(lines, "Cache", costValue(cost.cache_monthly) ?? "pricing unavailable");
  } else {
    lines.push("- Cache: not needed");
  }
  addField(lines, "Total", costRange(cost.total_monthly_low, cost.total_monthly_high));
  lines.push("");
}

export function recommendationToMarkdown({ sdr, technicalNeeds, userRequirements }: ReportData): string {
  const lines = ["# AWS Instance Recommendation", ""];
  lines.push("## Architecture Summary", "", sdr.architecture_summary, "");

  lines.push("## Topology", "");
  const topology = ["Users"];
  if (sdr.load_balancer.needed && sdr.load_balancer.load_balancer_type) {
    topology.push(sdr.load_balancer.load_balancer_type);
  }
  topology.push(sdr.compute.recommended_instance);
  if (sdr.cache.needed && sdr.cache.recommended_instance) topology.push(sdr.cache.recommended_instance);
  if (sdr.database.needed && sdr.database.recommended_instance) topology.push(sdr.database.recommended_instance);
  lines.push(`Users -> ${topology.slice(1).join(" -> ")}`, "");

  if (userRequirements || technicalNeeds) {
    lines.push("## Request Context", "");
    if (userRequirements?.registered_users != null) {
      addField(lines, "Stated registered users", userRequirements.registered_users.toLocaleString("en-US"));
    }
    if (userRequirements?.requests_per_second != null) {
      addField(lines, "Stated requests per second", `${userRequirements.requests_per_second} RPS`);
    }
    if (technicalNeeds) {
      addField(
        lines,
        "Estimated concurrency",
        formatConcurrency(technicalNeeds.estimated_concurrency, userRequirements?.workload_type),
      );
      addField(lines, "Traffic pattern", technicalNeeds.traffic_pattern);
      addField(lines, "Resource profile", technicalNeeds.resource_profile);
    }
    lines.push("");
  }

  addTier(lines, "Compute", sdr.compute);
  if (sdr.containerized_alternative) {
    lines.push("### Containerized Alternative (ECS Fargate)");
    if (sdr.containerized_alternative.fargate_cpu_units != null && sdr.containerized_alternative.fargate_memory_mib != null) {
      lines.push(`- Task Size: ${sdr.containerized_alternative.fargate_cpu_units} CPU units / ${sdr.containerized_alternative.fargate_memory_mib} MiB`);
    }
    addField(lines, "Why", sdr.containerized_alternative.why);
    addField(lines, "Trade-off", sdr.containerized_alternative.trade_off);
    lines.push("");
  }
  addTier(lines, "Database", sdr.database);
  addTier(lines, "Cache", sdr.cache);
  lines.push("### Load Balancer");
  lines.push(`- Status: ${sdr.load_balancer.needed ? "needed" : "not needed"}`);
  addField(lines, "Type", sdr.load_balancer.load_balancer_type);
  addField(lines, "Why", sdr.load_balancer.why);
  lines.push("");

  if (sdr.estimated_cost) addCost(lines, sdr.estimated_cost, sdr);

  return lines.join("\n").trim() + "\n";
}
