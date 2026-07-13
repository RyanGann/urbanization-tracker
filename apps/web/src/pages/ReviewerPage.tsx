import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  Bell,
  Check,
  Database,
  Download,
  ExternalLink,
  FileText,
  GitMerge,
  Globe2,
  Inbox,
  KeyRound,
  MapPinned,
  RotateCcw,
  Send,
  Upload,
  X
} from "lucide-react";
import { ChangeEvent, FormEvent, useState } from "react";

import {
  ApiError,
  approveStagedRecord,
  exportReviewerDecisions,
  fetchConnectorHealth,
  fetchDuplicateCandidates,
  fetchJurisdictions,
  fetchPhase3StoreStatus,
  fetchProcessedStoreStatus,
  fetchReviewerAlerts,
  fetchReviewerPublicSubmissions,
  fetchReviewerWatchAreas,
  fetchSourceHealth,
  fetchSourceDocuments,
  fetchStagedRecords,
  getReviewerToken,
  importReviewerDecisions,
  markStagedRecordNeedsInfo,
  rejectStagedRecord,
  sendQueuedAlerts,
  setReviewerToken
} from "../api";
import { StatusBadge } from "../components/StatusBadge";
import type {
  AlertDeliveryResult,
  DevelopmentRecord,
  ReviewerDecisionImportItem,
  ReviewStatus,
  StagedDevelopmentRecord,
  StoreCollectionStatus
} from "../types";
import { developmentTypeLabel, statusLabel } from "../utils/records";

type ReviewAction = "approve" | "reject" | "needs_info";
type HandoffMessage = { kind: "success" | "error"; text: string };

const ALERT_LIMIT_MIN = 1;
const ALERT_LIMIT_MAX = 500;
const REVIEW_STATUSES = new Set<ReviewStatus>([
  "pending",
  "needs_info",
  "rejected",
  "approved",
  "published"
]);

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

function alertDeliverySummary(result: AlertDeliveryResult) {
  const summary = result.configured
    ? `${result.sent} sent, ${result.suppressed} suppressed, ${result.failed} failed.`
    : "Delivery is not configured.";
  return result.errors.length ? `${summary} Errors: ${result.errors.join("; ")}` : summary;
}

interface PersistenceStoreStatus {
  backend: string;
  database_first: boolean;
  database_error: string | null;
  collections: StoreCollectionStatus[];
  raw_artifacts?: Array<{ name: string; artifact_count: number }>;
}

interface StoreStatusPanelProps {
  title: string;
  status?: PersistenceStoreStatus;
  isPending: boolean;
  isError: boolean;
}

function collectionLabel(name: string) {
  return name.replaceAll("_", " ");
}

function storeHealth(status: PersistenceStoreStatus) {
  if (status.database_error || status.collections.some((collection) => collection.artifact_error)) {
    return "failing";
  }
  if (
    !status.database_first ||
    status.collections.some((collection) => collection.requires_migration)
  ) {
    return "degraded";
  }
  return "healthy";
}

function StoreStatusPanel({ title, status, isPending, isError }: StoreStatusPanelProps) {
  return (
    <article className="panel list-panel store-status-panel">
      <div className="panel-heading">
        <h2>
          <Database size={17} aria-hidden />
          {title}
        </h2>
        {status ? <StatusBadge value={storeHealth(status)} kind="review" /> : null}
      </div>
      {status ? (
        <div className="store-status-content">
          <dl className="facts store-facts">
            <div>
              <dt>Active backend</dt>
              <dd>{status.backend}</dd>
            </div>
            <div>
              <dt>Authoritative store</dt>
              <dd>{status.database_first ? "Postgres" : "Local or in-memory"}</dd>
            </div>
          </dl>
          {status.database_error ? (
            <p className="store-error" role="alert">
              The database status check failed. Run deployment preflight before migration or
              ingestion.
            </p>
          ) : null}
          {!status.database_first ? (
            <p className="store-warning">
              Postgres is not authoritative for this store in the current environment.
            </p>
          ) : null}
          <div className="compact-list store-collection-list">
            {status.collections.map((collection) => (
              <div className="compact-row" key={collection.name}>
                <span>
                  <strong>{collectionLabel(collection.name)}</strong>
                  <small>
                    {collection.database_count} database · {collection.artifact_count} artifact
                    {collection.memory_count === undefined
                      ? ""
                      : ` · ${collection.memory_count} memory`}
                  </small>
                </span>
                {collection.artifact_error ? (
                  <span className="store-state store-state-error">Artifact error</span>
                ) : collection.requires_migration ? (
                  <span className="store-state store-state-warning">Migration required</span>
                ) : null}
              </div>
            ))}
          </div>
          {status.raw_artifacts?.length ? (
            <p className="store-raw-summary">
              Raw audit artifacts: {status.raw_artifacts.reduce(
                (total, artifact) => total + artifact.artifact_count,
                0
              )}
            </p>
          ) : null}
        </div>
      ) : (
        <p
          className={isError ? "store-error" : "muted store-status-message"}
          role={isError ? "alert" : undefined}
        >
          {isError
            ? "Store status is unavailable."
            : isPending
              ? "Loading store status…"
              : "No store status is available."}
        </p>
      )}
    </article>
  );
}

function reviewerDecisionImportItem(decision: unknown): ReviewerDecisionImportItem {
  if (!decision || typeof decision !== "object") {
    throw new Error("Each decision import item must be an object.");
  }
  const item = decision as Record<string, unknown>;
  const stagedId = item.staged_id;
  const reviewStatus = item.review_status;
  if (typeof stagedId !== "string" || !stagedId.trim()) {
    throw new Error("Each decision import item must include a staged_id.");
  }
  if (typeof reviewStatus !== "string" || !REVIEW_STATUSES.has(reviewStatus as ReviewStatus)) {
    throw new Error(`Decision ${stagedId} has an unsupported review_status.`);
  }
  const notes = item.review_notes ?? item.notes ?? null;
  return {
    staged_id: stagedId,
    review_status: reviewStatus as ReviewStatus,
    notes: typeof notes === "string" ? notes : null
  };
}

function importResultMessage(result: { applied: number; missing: string[] }) {
  if (!result.missing.length) return `Imported ${result.applied} decisions.`;
  return `Imported ${result.applied} decisions; missing IDs: ${result.missing.join(", ")}.`;
}

export function ReviewerPage() {
  const [notesById, setNotesById] = useState<Record<string, string>>({});
  const [tokenInput, setTokenInput] = useState(() => getReviewerToken());
  const [handoffMessage, setHandoffMessage] = useState<HandoffMessage | null>(null);
  const [alertLimit, setAlertLimit] = useState("25");
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
  const phase3StoreQuery = useQuery({
    queryKey: ["reviewer", "phase3-store"],
    queryFn: fetchPhase3StoreStatus
  });
  const processedStoreQuery = useQuery({
    queryKey: ["reviewer", "processed-store"],
    queryFn: fetchProcessedStoreStatus
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

  const exportMutation = useMutation({
    mutationFn: exportReviewerDecisions,
    onSuccess: (decisions) => {
      const blob = new Blob([JSON.stringify(decisions, null, 2)], {
        type: "application/json"
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `reviewer-decisions-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setHandoffMessage({
        kind: "success",
        text: `Exported ${decisions.length} reviewer decisions.`
      });
    },
    onError: (error) => {
      setHandoffMessage({ kind: "error", text: error.message });
    }
  });

  const importMutation = useMutation({
    mutationFn: importReviewerDecisions,
    onSuccess: (result) => {
      setHandoffMessage({ kind: "success", text: importResultMessage(result) });
      queryClient.invalidateQueries({ queryKey: ["reviewer", "staged-records"] });
      queryClient.invalidateQueries({ queryKey: ["reviewer", "public-submissions"] });
      queryClient.invalidateQueries({ queryKey: ["development-records"] });
    },
    onError: (error) => {
      setHandoffMessage({ kind: "error", text: error.message });
    }
  });

  const alertDeliveryMutation = useMutation({
    mutationFn: sendQueuedAlerts,
    onSuccess: (result) => {
      setHandoffMessage({
        kind: result.failed > 0 || !result.configured ? "error" : "success",
        text: alertDeliverySummary(result)
      });
      queryClient.invalidateQueries({ queryKey: ["reviewer", "alerts"] });
    },
    onError: (error) => {
      setHandoffMessage({ kind: "error", text: error.message });
    }
  });

  const records = stagedQuery.data ?? [];
  const reviewerAccessRequired = [
    stagedQuery,
    duplicateCandidatesQuery,
    submissionsQuery,
    watchAreasQuery,
    alertsQuery,
    phase3StoreQuery,
    processedStoreQuery
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

  const importDecisionFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const decisions = Array.isArray(parsed) ? parsed : parsed.decisions;
      if (!Array.isArray(decisions)) {
        throw new Error("Decision import file must contain an array or a decisions array.");
      }
      importMutation.mutate(decisions.map(reviewerDecisionImportItem));
    } catch (error) {
      setHandoffMessage({
        kind: "error",
        text: error instanceof Error ? error.message : "Could not import decisions."
      });
    }
  };

  const deliverAlerts = () => {
    const parsedLimit = Number(alertLimit);
    if (
      !Number.isInteger(parsedLimit) ||
      parsedLimit < ALERT_LIMIT_MIN ||
      parsedLimit > ALERT_LIMIT_MAX
    ) {
      setHandoffMessage({
        kind: "error",
        text: `Alert limit must be between ${ALERT_LIMIT_MIN} and ${ALERT_LIMIT_MAX}.`
      });
      return;
    }
    alertDeliveryMutation.mutate(parsedLimit);
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
          onClick={() => queryClient.invalidateQueries()}
          title="Refresh reviewer data"
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

      <section className="store-status-grid" aria-label="Persistence status">
        <StoreStatusPanel
          title="Processed Store"
          status={processedStoreQuery.data}
          isPending={processedStoreQuery.isPending}
          isError={processedStoreQuery.isError}
        />
        <StoreStatusPanel
          title="Phase 3 Store"
          status={phase3StoreQuery.data}
          isPending={phase3StoreQuery.isPending}
          isError={phase3StoreQuery.isError}
        />
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

      <section className="panel operations-panel">
        <div className="panel-heading">
          <h2>
            <GitMerge size={17} aria-hidden />
            Operations
          </h2>
        </div>
        <div className="operations-grid">
          <div className="operation-group">
            <div className="button-row">
              <button
                className="secondary-action"
                type="button"
                disabled={exportMutation.isPending}
                onClick={() => exportMutation.mutate()}
              >
                <Download size={16} aria-hidden />
                Export decisions
              </button>
              <label className="secondary-action file-action">
                <Upload size={16} aria-hidden />
                Import decisions
                <input
                  type="file"
                  accept="application/json,.json"
                  onChange={importDecisionFile}
                  disabled={importMutation.isPending}
                />
              </label>
            </div>
          </div>
          <div className="operation-group alert-delivery-control">
            <label className="inline-field">
              <span>Limit</span>
              <input
                min="1"
                max="500"
                type="number"
                value={alertLimit}
                onChange={(event) => setAlertLimit(event.target.value)}
              />
            </label>
            <button
              className="primary-action"
              type="button"
              disabled={alertDeliveryMutation.isPending}
              onClick={deliverAlerts}
            >
              <Send size={16} aria-hidden />
              Send alerts
            </button>
          </div>
        </div>
        {handoffMessage ? (
          <p className={handoffMessage.kind === "success" ? "success-text" : "error-text"}>
            {handoffMessage.text}
          </p>
        ) : null}
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
