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
  WatchArea,
  WatchAreaCreate
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...init?.headers
    },
    ...init
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with status ${response.status}`);
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
  return request<StagedDevelopmentRecord[]>("/api/reviewer/staged-records");
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
  return request<DuplicateCandidate[]>("/api/reviewer/duplicate-candidates");
}

export function fetchPublicSubmissions(): Promise<UserSubmission[]> {
  return request<UserSubmission[]>("/api/public-submissions");
}

export function createPublicSubmission(
  submission: UserSubmissionCreate
): Promise<UserSubmission> {
  return request<UserSubmission>("/api/public-submissions", {
    method: "POST",
    body: JSON.stringify(submission)
  });
}

export function fetchWatchAreas(): Promise<WatchArea[]> {
  return request<WatchArea[]>("/api/watch-areas");
}

export function createWatchArea(watchArea: WatchAreaCreate): Promise<WatchArea> {
  return request<WatchArea>("/api/watch-areas", {
    method: "POST",
    body: JSON.stringify(watchArea)
  });
}

export function fetchAlerts(): Promise<Alert[]> {
  return request<Alert[]>("/api/alerts");
}

export function fetchChangeLog(): Promise<ChangeLogEntry[]> {
  return request<ChangeLogEntry[]>("/api/change-log");
}

export function fetchRecordVersions(publicId: string): Promise<RecordVersion[]> {
  return request<RecordVersion[]>(`/api/development-records/${publicId}/versions`);
}

export function exportReviewerDecisions() {
  return request("/api/reviewer/decisions/export");
}

export function importReviewerDecisions(decisions: unknown[]) {
  return request("/api/reviewer/decisions/import", {
    method: "POST",
    body: JSON.stringify({ decisions })
  });
}

export function approveStagedRecord(id: string, notes: string): Promise<DevelopmentRecord> {
  return request<DevelopmentRecord>(`/api/reviewer/staged-records/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ notes })
  });
}

export function rejectStagedRecord(
  id: string,
  notes: string
): Promise<StagedDevelopmentRecord> {
  return request<StagedDevelopmentRecord>(`/api/reviewer/staged-records/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ notes })
  });
}

export function markStagedRecordNeedsInfo(
  id: string,
  notes: string
): Promise<StagedDevelopmentRecord> {
  return request<StagedDevelopmentRecord>(`/api/reviewer/staged-records/${id}/needs-info`, {
    method: "POST",
    body: JSON.stringify({ notes })
  });
}
