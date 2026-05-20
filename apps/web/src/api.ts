import type {
  Alert,
  ChangeLogEntry,
  ConnectorHealth,
  DevelopmentRecord,
  DevelopmentRecordCollection,
  DuplicateCandidate,
  EnvironmentalOverlay,
  Jurisdiction,
  RecordFilters,
  RecordVersion,
  SourceDocument,
  SourceHealth,
  StagedDevelopmentRecord,
  UserSubmission,
  UserSubmissionCreate,
  UserSubmissionReceipt,
  WatchArea,
  WatchAreaCreate,
  WatchAreaReceipt
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const REVIEWER_TOKEN_KEY = "urbanization-tracker:reviewer-token";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ApiRequestInit extends RequestInit {
  reviewer?: boolean;
}

export function getReviewerToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(REVIEWER_TOKEN_KEY) ?? "";
}

export function setReviewerToken(token: string) {
  if (typeof window === "undefined") return;
  const trimmed = token.trim();
  if (trimmed) {
    window.sessionStorage.setItem(REVIEWER_TOKEN_KEY, trimmed);
  } else {
    window.sessionStorage.removeItem(REVIEWER_TOKEN_KEY);
  }
}

async function request<T>(path: string, init?: ApiRequestInit): Promise<T> {
  const { reviewer = false, headers, ...fetchInit } = init ?? {};
  const requestHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string> | undefined)
  };
  const reviewerToken = reviewer ? getReviewerToken() : "";
  if (reviewerToken) {
    requestHeaders.Authorization = `Bearer ${reviewerToken}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: requestHeaders,
    ...fetchInit
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail || `Request failed with status ${response.status}`);
  }

  return response.json() as Promise<T>;
}

function appendArrayParams(
  params: URLSearchParams,
  key: string,
  values: string[] | undefined
) {
  values?.forEach((value) => params.append(key, value));
}

function filterQuery(filters: Partial<RecordFilters>): string {
  const params = new URLSearchParams();
  appendArrayParams(params, "status", filters.statuses);
  appendArrayParams(params, "confidence", filters.confidenceLevels);
  appendArrayParams(params, "development_type", filters.developmentTypes);
  appendArrayParams(params, "flag", filters.flagTypes);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function fetchDevelopmentRecords(
  filters: Partial<RecordFilters>
): Promise<DevelopmentRecordCollection> {
  return request<DevelopmentRecordCollection>(`/api/development-records${filterQuery(filters)}`);
}

export function fetchDevelopmentRecord(publicId: string): Promise<DevelopmentRecord> {
  return request<DevelopmentRecord>(`/api/development-records/${publicId}`);
}

export function fetchEnvironmentalOverlays(): Promise<EnvironmentalOverlay[]> {
  return request<EnvironmentalOverlay[]>("/api/environmental-overlays");
}

export function fetchStagedRecords(): Promise<StagedDevelopmentRecord[]> {
  return request<StagedDevelopmentRecord[]>("/api/reviewer/staged-records", {
    reviewer: true
  });
}

export function fetchSourceHealth(): Promise<SourceHealth> {
  return request<SourceHealth>("/api/source-health");
}

export function fetchJurisdictions(): Promise<Jurisdiction[]> {
  return request<Jurisdiction[]>("/api/jurisdictions");
}

export function fetchConnectorHealth(): Promise<ConnectorHealth[]> {
  return request<ConnectorHealth[]>("/api/connector-health");
}

export function fetchSourceDocuments(): Promise<SourceDocument[]> {
  return request<SourceDocument[]>("/api/source-documents");
}

export function fetchDuplicateCandidates(): Promise<DuplicateCandidate[]> {
  return request<DuplicateCandidate[]>("/api/reviewer/duplicate-candidates", {
    reviewer: true
  });
}

export function fetchReviewerPublicSubmissions(): Promise<UserSubmission[]> {
  return request<UserSubmission[]>("/api/reviewer/public-submissions", {
    reviewer: true
  });
}

export function createPublicSubmission(
  submission: UserSubmissionCreate
): Promise<UserSubmissionReceipt> {
  return request<UserSubmissionReceipt>("/api/public-submissions", {
    method: "POST",
    body: JSON.stringify(submission)
  });
}

export function fetchReviewerWatchAreas(): Promise<WatchArea[]> {
  return request<WatchArea[]>("/api/reviewer/watch-areas", {
    reviewer: true
  });
}

export function createWatchArea(watchArea: WatchAreaCreate): Promise<WatchAreaReceipt> {
  return request<WatchAreaReceipt>("/api/watch-areas", {
    method: "POST",
    body: JSON.stringify(watchArea)
  });
}

export function fetchReviewerAlerts(): Promise<Alert[]> {
  return request<Alert[]>("/api/reviewer/alerts", {
    reviewer: true
  });
}

export function fetchChangeLog(): Promise<ChangeLogEntry[]> {
  return request<ChangeLogEntry[]>("/api/change-log");
}

export function fetchRecordVersions(publicId: string): Promise<RecordVersion[]> {
  return request<RecordVersion[]>(`/api/development-records/${publicId}/versions`);
}

export function exportReviewerDecisions() {
  return request("/api/reviewer/decisions/export", { reviewer: true });
}

export function importReviewerDecisions(decisions: unknown[]) {
  return request("/api/reviewer/decisions/import", {
    reviewer: true,
    method: "POST",
    body: JSON.stringify({ decisions })
  });
}

export function approveStagedRecord(id: string, notes: string): Promise<DevelopmentRecord> {
  return request<DevelopmentRecord>(`/api/reviewer/staged-records/${id}/approve`, {
    reviewer: true,
    method: "POST",
    body: JSON.stringify({ notes })
  });
}

export function rejectStagedRecord(
  id: string,
  notes: string
): Promise<StagedDevelopmentRecord> {
  return request<StagedDevelopmentRecord>(`/api/reviewer/staged-records/${id}/reject`, {
    reviewer: true,
    method: "POST",
    body: JSON.stringify({ notes })
  });
}

export function markStagedRecordNeedsInfo(
  id: string,
  notes: string
): Promise<StagedDevelopmentRecord> {
  return request<StagedDevelopmentRecord>(`/api/reviewer/staged-records/${id}/needs-info`, {
    reviewer: true,
    method: "POST",
    body: JSON.stringify({ notes })
  });
}
