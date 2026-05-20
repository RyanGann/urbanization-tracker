import type { ConfidenceLevel, DevelopmentRecord, DevelopmentStatus, RecordFilters } from "../types";

export const STATUS_OPTIONS: Array<{ value: DevelopmentStatus; label: string }> = [
  { value: "layout", label: "Layout" },
  { value: "preliminary", label: "Preliminary" },
  { value: "final", label: "Final" },
  { value: "issued_permit", label: "Issued permit" },
  { value: "completed", label: "Completed" },
  { value: "proposed", label: "Proposed" }
];

export const CONFIDENCE_OPTIONS: Array<{ value: ConfidenceLevel; label: string }> = [
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" }
];

export const DEVELOPMENT_TYPE_LABELS: Record<string, string> = {
  subdivision: "Subdivision",
  building_permit: "Building permit"
};

export function statusLabel(status: DevelopmentStatus | string): string {
  return STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status;
}

export function confidenceLabel(confidence: ConfidenceLevel | string): string {
  return confidence.charAt(0).toUpperCase() + confidence.slice(1);
}

export function developmentTypeLabel(value: string): string {
  return DEVELOPMENT_TYPE_LABELS[value] ?? value.replaceAll("_", " ");
}

export function formatArea(areaSqM: number | null): string {
  if (!areaSqM) {
    return "Not available";
  }
  const acres = areaSqM / 4046.8564224;
  return `${acres.toFixed(1)} acres`;
}

export function uniqueFlagTypes(records: DevelopmentRecord[]): string[] {
  return Array.from(
    new Set(records.flatMap((record) => record.proximity_flags.map((flag) => flag.flag_type)))
  ).sort();
}

export function filterRecords(
  records: DevelopmentRecord[],
  filters: Partial<RecordFilters>
): DevelopmentRecord[] {
  return records.filter((record) => {
    const statusMatch = !filters.statuses?.length || filters.statuses.includes(record.status);
    const confidenceMatch =
      !filters.confidenceLevels?.length ||
      filters.confidenceLevels.includes(record.confidence_level);
    const typeMatch =
      !filters.developmentTypes?.length ||
      filters.developmentTypes.includes(record.development_type);
    const flagMatch =
      !filters.flagTypes?.length ||
      record.proximity_flags.some((flag) => filters.flagTypes?.includes(flag.flag_type));

    return statusMatch && confidenceMatch && typeMatch && flagMatch;
  });
}
