import type { ConfidenceLevel, DevelopmentStatus, ReviewStatus } from "../types";
import { confidenceLabel, statusLabel } from "../utils/records";

interface StatusBadgeProps {
  value: DevelopmentStatus | ReviewStatus | ConfidenceLevel | string;
  kind?: "status" | "confidence" | "review";
}

export function StatusBadge({ value, kind = "status" }: StatusBadgeProps) {
  const label = kind === "confidence" ? confidenceLabel(value) : statusLabel(value);
  return <span className={`badge badge-${kind} badge-${value}`}>{label}</span>;
}
