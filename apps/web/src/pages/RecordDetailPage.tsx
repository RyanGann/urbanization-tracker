import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, MapPin } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { fetchDevelopmentRecord, fetchRecordVersions } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { developmentTypeLabel, formatArea, statusLabel } from "../utils/records";

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "Not available";
  }
  return String(value);
}

export function RecordDetailPage() {
  const { publicId } = useParams();
  const recordQuery = useQuery({
    queryKey: ["development-record", publicId],
    queryFn: () => fetchDevelopmentRecord(publicId ?? ""),
    enabled: Boolean(publicId)
  });
  const versionsQuery = useQuery({
    queryKey: ["record-versions", publicId],
    queryFn: () => fetchRecordVersions(publicId ?? ""),
    enabled: Boolean(publicId)
  });

  if (recordQuery.isLoading) {
    return (
      <main className="page-shell">
        <p className="muted">Loading record...</p>
      </main>
    );
  }

  if (recordQuery.isError || !recordQuery.data) {
    return (
      <main className="page-shell">
        <Link className="back-link" to="/">
          <ArrowLeft size={16} aria-hidden />
          Back to map
        </Link>
        <section className="panel empty-state">
          <h1>Record not found</h1>
          <p>The API did not return a matching development record.</p>
        </section>
      </main>
    );
  }

  const record = recordQuery.data;

  return (
    <main className="page-shell">
      <Link className="back-link" to="/">
        <ArrowLeft size={16} aria-hidden />
        Back to map
      </Link>

      <section className="detail-layout">
        <article className="detail-main panel">
          <div className="selected-title">
            <MapPin size={20} aria-hidden />
            <h1>{record.title}</h1>
          </div>
          <div className="badge-row">
            <StatusBadge value={record.status} />
            <StatusBadge value={record.confidence_level} kind="confidence" />
            <StatusBadge value={record.review_status} kind="review" />
          </div>
          <p className="lede">{record.description}</p>

          <dl className="facts detail-facts">
            <div>
              <dt>Status</dt>
              <dd>{statusLabel(record.status)}</dd>
            </div>
            <div>
              <dt>Development type</dt>
              <dd>{developmentTypeLabel(record.development_type)}</dd>
            </div>
            <div>
              <dt>Source status</dt>
              <dd>{record.source_status}</dd>
            </div>
            <div>
              <dt>Source agency</dt>
              <dd>{record.source_agency}</dd>
            </div>
            <div>
              <dt>Date discovered</dt>
              <dd>{record.date_discovered}</dd>
            </div>
            <div>
              <dt>Last checked</dt>
              <dd>{record.date_last_checked}</dd>
            </div>
            <div>
              <dt>Application date</dt>
              <dd>{renderValue(record.application_date)}</dd>
            </div>
            <div>
              <dt>Approval date</dt>
              <dd>{renderValue(record.approval_date)}</dd>
            </div>
            <div>
              <dt>Permit issue date</dt>
              <dd>{renderValue(record.permit_issue_date)}</dd>
            </div>
            <div>
              <dt>Area</dt>
              <dd>{formatArea(record.area_sq_m)}</dd>
            </div>
          </dl>

          <section className="detail-section">
            <h2>Geometry Provenance</h2>
            <dl className="facts detail-facts">
              <div>
                <dt>Geometry source</dt>
                <dd>{record.geometry_source}</dd>
              </div>
              <div>
                <dt>Geometry confidence</dt>
                <dd>
                  <StatusBadge value={record.geometry_confidence} kind="confidence" />
                </dd>
              </div>
              <div>
                <dt>Centroid</dt>
                <dd>
                  {record.centroid[1].toFixed(4)}, {record.centroid[0].toFixed(4)}
                </dd>
              </div>
            </dl>
          </section>

          <section className="detail-section">
            <h2>Environmental Context</h2>
            <div className="flag-stack">
              {record.proximity_flags.length ? (
                record.proximity_flags.map((flag) => (
                  <article key={flag.flag_type} className="flag-item">
                    <strong>{flag.label}</strong>
                    <span>{flag.caveat}</span>
                    <a href={flag.source_url} target="_blank" rel="noreferrer">
                      {flag.source_name}
                    </a>
                  </article>
                ))
              ) : (
                <p className="muted">No seed environmental flags are attached to this record.</p>
              )}
            </div>
          </section>
        </article>

        <aside className="detail-side">
          <section className="panel">
            <h2>Source Link</h2>
            <a className="source-card" href={record.source_url} target="_blank" rel="noreferrer">
              <span>{record.source_agency}</span>
              <ExternalLink size={16} aria-hidden />
            </a>
          </section>

          <section className="panel">
            <h2>Original Source Fields</h2>
            <dl className="source-fields">
              {Object.entries(record.source_fields).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{renderValue(value)}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="panel caveat-panel">
            <h2>Use Caveat</h2>
            <p>
              This public record is screening-level context. Verify source agency material before
              legal, permitting, engineering, ecological, or flood insurance decisions.
            </p>
          </section>

          <section className="panel">
            <h2>Version History</h2>
            <div className="compact-list">
              {versionsQuery.data?.map((version) => (
                <div key={version.id} className="compact-row">
                  <span>
                    <strong>Version {version.version_number}</strong>
                    <small>{version.change_type}</small>
                  </span>
                  <small>{version.changed_at}</small>
                </div>
              ))}
              {versionsQuery.data?.length === 0 ? (
                <p className="muted">No versions recorded yet.</p>
              ) : null}
            </div>
          </section>
        </aside>
      </section>
    </main>
  );
}
