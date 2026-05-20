import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  Bell,
  Check,
  ExternalLink,
  FileText,
  GitMerge,
  Globe2,
  Inbox,
  KeyRound,
  MapPinned,
  RotateCcw,
  X
} from "lucide-react";
import { FormEvent, useState } from "react";

import {
  ApiError,
  approveStagedRecord,
  fetchConnectorHealth,
  fetchDuplicateCandidates,
  fetchJurisdictions,
  fetchReviewerAlerts,
  fetchReviewerPublicSubmissions,
  fetchReviewerWatchAreas,
  fetchSourceHealth,
  fetchSourceDocuments,
  fetchStagedRecords,
  getReviewerToken,
  markStagedRecordNeedsInfo,
  rejectStagedRecord,
  setReviewerToken
} from "../api";
import { StatusBadge } from "../components/StatusBadge";
import type { DevelopmentRecord, StagedDevelopmentRecord } from "../types";
import { developmentTypeLabel, statusLabel } from "../utils/records";

type ReviewAction = "approve" | "reject" | "needs_info";

interface MutationInput {
  id: string;
  action: ReviewAction;
  notes: string;
}

function sourcePayloadRows(record: StagedDevelopmentRecord) {
  return Object.entries(record.source_payload).map(([key, value]) => (
    <div key={key}>
      <dt>{key.replaceAll("_", " ")}</dt>
      <dd>{String(value)}</dd>
    </div>
  ));
}

function isUnauthorized(error: unknown) {
  return error instanceof ApiError && error.status === 401;
}

export function ReviewerPage() {
  const [notesById, setNotesById] = useState<Record<string, string>>({});
  const [tokenInput, setTokenInput] = useState(() => getReviewerToken());
  const queryClient = useQueryClient();

  const stagedQuery = useQuery({
    queryKey: ["reviewer", "staged-records"],
    queryFn: fetchStagedRecords
  });
  const sourceHealthQuery = useQuery({
    queryKey: ["source-health"],
    queryFn: fetchSourceHealth
  });
  const sourceDocumentsQuery = useQuery({
    queryKey: ["source-documents"],
    queryFn: fetchSourceDocuments
  });
  const duplicateCandidatesQuery = useQuery({
    queryKey: ["reviewer", "duplicate-candidates"],
    queryFn: fetchDuplicateCandidates
  });
  const submissionsQuery = useQuery({
    queryKey: ["reviewer", "public-submissions"],
    queryFn: fetchReviewerPublicSubmissions
  });
  const watchAreasQuery = useQuery({
    queryKey: ["reviewer", "watch-areas"],
    queryFn: fetchReviewerWatchAreas
  });
  const alertsQuery = useQuery({
    queryKey: ["reviewer", "alerts"],
    queryFn: fetchReviewerAlerts
  });
  const connectorHealthQuery = useQuery({
    queryKey: ["connector-health"],
    queryFn: fetchConnectorHealth
  });
  const jurisdictionsQuery = useQuery({
    queryKey: ["jurisdictions"],
    queryFn: fetchJurisdictions
  });

  const reviewMutation = useMutation<DevelopmentRecord | StagedDevelopmentRecord, Error, MutationInput>({
    mutationFn: ({ id, action, notes }: MutationInput) => {
      if (action === "approve") return approveStagedRecord(id, notes);
      if (action === "reject") return rejectStagedRecord(id, notes);
      return markStagedRecordNeedsInfo(id, notes);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviewer", "staged-records"] });
      queryClient.invalidateQueries({ queryKey: ["reviewer", "public-submissions"] });
      queryClient.invalidateQueries({ queryKey: ["development-records"] });
    }
  });

  const records = stagedQuery.data ?? [];
  const reviewerAccessRequired = [
    stagedQuery,
    duplicateCandidatesQuery,
    submissionsQuery,
    watchAreasQuery,
    alertsQuery
  ].some((query) => isUnauthorized(query.error));

  const saveToken = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setReviewerToken(tokenInput);
    queryClient.invalidateQueries({ queryKey: ["reviewer"] });
  };

  const clearToken = () => {
    setTokenInput("");
    setReviewerToken("");
    queryClient.invalidateQueries({ queryKey: ["reviewer"] });
  };

  return (
    <main className="page-shell reviewer-shell">
      <section className="review-header">
        <div>
          <h1>Reviewer Queue</h1>
          <p>
            Seed staged records are intentionally narrow: inspect provenance, confirm uncertainty,
            then publish or hold the candidate.
          </p>
        </div>
        <button
          className="icon-link"
          type="button"
          onClick={() => stagedQuery.refetch()}
          title="Refresh queue"
        >
          <RotateCcw size={16} aria-hidden />
          Refresh
        </button>
      </section>

      {reviewerAccessRequired ? (
        <section className="panel access-panel">
          <div className="panel-heading">
            <span>
              <KeyRound size={17} aria-hidden />
              Reviewer Access
            </span>
          </div>
          <form className="access-form" onSubmit={saveToken}>
            <label className="form-field">
              <span>Access token</span>
              <input
                required
                type="password"
                value={tokenInput}
                onChange={(event) => setTokenInput(event.target.value)}
              />
            </label>
            <div className="review-actions">
              <button className="primary-action" type="submit">
                Save token
              </button>
              <button className="secondary-action" type="button" onClick={clearToken}>
                Clear
              </button>
            </div>
          </form>
        </section>
      ) : null}

      <section className="panel health-panel">
        <div className="panel-heading">
          <span>Source Health</span>
          <StatusBadge value={sourceHealthQuery.data?.status ?? "unknown"} kind="review" />
        </div>
        {sourceHealthQuery.data ? (
          <div className="health-content">
            <dl className="facts detail-facts">
              <div>
                <dt>Last checked</dt>
                <dd>{sourceHealthQuery.data.checked_at ?? "Not available"}</dd>
              </div>
              <div>
                <dt>Published records</dt>
                <dd>{sourceHealthQuery.data.records?.published ?? 0}</dd>
              </div>
              <div>
                <dt>Raw records</dt>
                <dd>{sourceHealthQuery.data.records?.raw ?? 0}</dd>
              </div>
              <div>
                <dt>Proximity flags</dt>
                <dd>{sourceHealthQuery.data.records?.proximity_flags ?? 0}</dd>
              </div>
            </dl>
            <div className="source-health-list">
              {sourceHealthQuery.data.sources.map((source) => (
                <a
                  key={source.key}
                  className="source-health-row"
                  href={source.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <span>
                    <strong>{source.name}</strong>
                    <small>
                      {source.records_seen} seen, {source.error_count} errors
                    </small>
                  </span>
                  <StatusBadge value={source.status} kind="review" />
                </a>
              ))}
            </div>
          </div>
        ) : (
          <p className="muted health-content">No ingestion health has been recorded yet.</p>
        )}
      </section>

      <section className="phase3-grid">
        <article className="panel list-panel">
          <div className="panel-heading">
            <span>
              <Activity size={17} aria-hidden />
              Connector Health
            </span>
            <strong>{connectorHealthQuery.data?.length ?? 0}</strong>
          </div>
          <div className="compact-list">
            {connectorHealthQuery.data?.map((connector) => (
              <a
                key={connector.key}
                className="compact-row"
                href={connector.source_url}
                target="_blank"
                rel="noreferrer"
              >
                <span>
                  <strong>{connector.name}</strong>
                  <small>
                    {connector.jurisdiction_name} · {connector.connector_type} ·{" "}
                    {connector.records_seen} seen
                  </small>
                </span>
                <StatusBadge value={connector.status} kind="review" />
              </a>
            ))}
          </div>
        </article>

        <article className="panel list-panel">
          <div className="panel-heading">
            <span>
              <Globe2 size={17} aria-hidden />
              Jurisdictions
            </span>
            <strong>{jurisdictionsQuery.data?.length ?? 0}</strong>
          </div>
          <div className="compact-list">
            {jurisdictionsQuery.data?.map((jurisdiction) => (
              <div key={jurisdiction.id} className="compact-row">
                <span>
                  <strong>{jurisdiction.name}</strong>
                  <small>
                    {jurisdiction.state}, {jurisdiction.country} · {jurisdiction.sources.length} sources
                  </small>
                </span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="phase3-grid">
        <article className="panel list-panel">
          <div className="panel-heading">
            <span>
              <FileText size={17} aria-hidden />
              Agenda Documents
            </span>
            <strong>{sourceDocumentsQuery.data?.length ?? 0}</strong>
          </div>
          <div className="compact-list">
            {sourceDocumentsQuery.data?.map((document) => (
              <a
                key={document.id}
                className="compact-row"
                href={document.url}
                target="_blank"
                rel="noreferrer"
              >
                <span>
                  <strong>{document.title}</strong>
                  <small>
                    {document.parsed_item_count} candidates, {document.extraction_status}
                  </small>
                </span>
                <ExternalLink size={15} aria-hidden />
              </a>
            ))}
            {sourceDocumentsQuery.data?.length === 0 ? (
              <p className="muted">No agenda documents ingested yet.</p>
            ) : null}
          </div>
        </article>

        <article className="panel list-panel">
          <div className="panel-heading">
            <span>
              <GitMerge size={17} aria-hidden />
              Duplicate Signals
            </span>
            <strong>{duplicateCandidatesQuery.data?.length ?? 0}</strong>
          </div>
          <div className="compact-list">
            {duplicateCandidatesQuery.data?.slice(0, 6).map((candidate) => (
              <div key={candidate.id} className="compact-row">
                <span>
                  <strong>{candidate.staged_title}</strong>
                  <small>
                    Possible match: {candidate.candidate_title} ({Math.round(candidate.score * 100)}
                    %)
                  </small>
                </span>
              </div>
            ))}
            {duplicateCandidatesQuery.data?.length === 0 ? (
              <p className="muted">No duplicate candidates detected.</p>
            ) : null}
          </div>
        </article>

        <article className="panel list-panel">
          <div className="panel-heading">
            <span>
              <Inbox size={17} aria-hidden />
              Public Submissions
            </span>
            <strong>{submissionsQuery.data?.length ?? 0}</strong>
          </div>
          <div className="compact-list">
            {submissionsQuery.data?.map((submission) => (
              <div key={submission.id} className="compact-row">
                <span>
                  <strong>{submission.title}</strong>
                  <small>{submission.created_at}</small>
                </span>
                <StatusBadge value={submission.status} kind="review" />
              </div>
            ))}
            {submissionsQuery.data?.length === 0 ? (
              <p className="muted">No public submissions yet.</p>
            ) : null}
          </div>
        </article>
      </section>

      <section className="phase3-grid">
        <article className="panel list-panel">
          <div className="panel-heading">
            <span>
              <Bell size={17} aria-hidden />
              Queued Alerts
            </span>
            <strong>{alertsQuery.data?.length ?? 0}</strong>
          </div>
          <div className="compact-list">
            {alertsQuery.data?.slice(0, 6).map((alert) => (
              <div key={alert.id} className="compact-row">
                <span>
                  <strong>{alert.record_title}</strong>
                  <small>{alert.delivery_channel} · {alert.summary}</small>
                </span>
                <StatusBadge value={alert.status} kind="review" />
              </div>
            ))}
            {alertsQuery.data?.length === 0 ? (
              <p className="muted">No queued alerts.</p>
            ) : null}
          </div>
        </article>

        <article className="panel list-panel">
          <div className="panel-heading">
            <span>
              <MapPinned size={17} aria-hidden />
              Watch Areas
            </span>
            <strong>{watchAreasQuery.data?.length ?? 0}</strong>
          </div>
          <div className="compact-list">
            {watchAreasQuery.data?.slice(0, 6).map((watchArea) => (
              <div key={watchArea.id} className="compact-row">
                <span>
                  <strong>{watchArea.name}</strong>
                  <small>{watchArea.email_hint}</small>
                </span>
                <span className="count-pill">{watchArea.alert_count}</span>
              </div>
            ))}
            {watchAreasQuery.data?.length === 0 ? (
              <p className="muted">No watch areas saved.</p>
            ) : null}
          </div>
        </article>
      </section>

      {stagedQuery.isLoading ? <p className="muted">Loading reviewer queue...</p> : null}
      {stagedQuery.isError && !reviewerAccessRequired ? (
        <p className="error-text">Could not load the reviewer queue from the API.</p>
      ) : null}

      <div className="review-grid">
        {records.map((record) => {
          const notes = notesById[record.id] ?? "";
          const disabled = reviewMutation.isPending || record.review_status !== "pending";

          return (
            <article key={record.id} className="panel review-card">
              <div className="review-card-header">
                <div>
                  <h2>{record.title}</h2>
                  <p>{record.description}</p>
                </div>
                <StatusBadge value={record.review_status} kind="review" />
              </div>

              <div className="badge-row">
                <StatusBadge value={record.normalized_status} />
                <StatusBadge value={record.record_confidence} kind="confidence" />
                <StatusBadge value={record.geometry_confidence} kind="confidence" />
              </div>

              <dl className="facts detail-facts">
                <div>
                  <dt>Type</dt>
                  <dd>{developmentTypeLabel(record.development_type)}</dd>
                </div>
                <div>
                  <dt>Source status</dt>
                  <dd>{record.source_status}</dd>
                </div>
                <div>
                  <dt>Normalized status</dt>
                  <dd>{statusLabel(record.normalized_status)}</dd>
                </div>
                <div>
                  <dt>Source agency</dt>
                  <dd>{record.source_agency}</dd>
                </div>
                <div>
                  <dt>Geometry source</dt>
                  <dd>{record.geometry_source}</dd>
                </div>
              </dl>

              <section className="detail-section">
                <h3>Normalization Notes</h3>
                <p>{record.normalization_notes}</p>
              </section>

              <section className="detail-section">
                <h3>Source Payload</h3>
                <dl className="source-fields">{sourcePayloadRows(record)}</dl>
              </section>

              <label className="notes-field">
                <span>Reviewer notes</span>
                <textarea
                  value={notes}
                  onChange={(event) =>
                    setNotesById((current) => ({
                      ...current,
                      [record.id]: event.target.value
                    }))
                  }
                  rows={4}
                  placeholder="Add a short reason or geometry caveat."
                />
              </label>

              <div className="review-actions">
                <button
                  className="primary-action"
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    reviewMutation.mutate({ id: record.id, action: "approve", notes })
                  }
                >
                  <Check size={16} aria-hidden />
                  Approve
                </button>
                <button
                  className="secondary-action"
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    reviewMutation.mutate({ id: record.id, action: "needs_info", notes })
                  }
                >
                  <AlertCircle size={16} aria-hidden />
                  Needs info
                </button>
                <button
                  className="danger-action"
                  type="button"
                  disabled={disabled}
                  onClick={() =>
                    reviewMutation.mutate({ id: record.id, action: "reject", notes })
                  }
                >
                  <X size={16} aria-hidden />
                  Reject
                </button>
                <a className="icon-link" href={record.source_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={16} aria-hidden />
                  Source
                </a>
              </div>
            </article>
          );
        })}
      </div>
    </main>
  );
}
