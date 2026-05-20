import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Geometry } from "geojson";
import { Bell, ExternalLink, History, MapPinned, Send } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  createPublicSubmission,
  createWatchArea,
  fetchAlerts,
  fetchChangeLog,
  fetchPublicSubmissions,
  fetchWatchAreas
} from "../api";
import { StatusBadge } from "../components/StatusBadge";

const DEFAULT_BOUNDS = {
  west: "-86.70",
  south: "34.62",
  east: "-86.50",
  north: "34.82"
};

function boundsGeometry(west: string, south: string, east: string, north: string): Geometry {
  const w = Number(west);
  const s = Number(south);
  const e = Number(east);
  const n = Number(north);
  return {
    type: "Polygon",
    coordinates: [
      [
        [w, s],
        [e, s],
        [e, n],
        [w, n],
        [w, s]
      ]
    ]
  };
}

export function ParticipatePage() {
  const queryClient = useQueryClient();
  const [submissionTitle, setSubmissionTitle] = useState("");
  const [submissionUrl, setSubmissionUrl] = useState("");
  const [submissionNotes, setSubmissionNotes] = useState("");
  const [submissionContact, setSubmissionContact] = useState("");
  const [watchName, setWatchName] = useState("Southwest Huntsville");
  const [watchEmail, setWatchEmail] = useState("");
  const [bounds, setBounds] = useState(DEFAULT_BOUNDS);

  const submissionsQuery = useQuery({
    queryKey: ["public-submissions"],
    queryFn: fetchPublicSubmissions
  });
  const watchAreasQuery = useQuery({
    queryKey: ["watch-areas"],
    queryFn: fetchWatchAreas
  });
  const alertsQuery = useQuery({
    queryKey: ["alerts"],
    queryFn: fetchAlerts
  });
  const changeLogQuery = useQuery({
    queryKey: ["change-log"],
    queryFn: fetchChangeLog
  });

  const submissionMutation = useMutation({
    mutationFn: createPublicSubmission,
    onSuccess: () => {
      setSubmissionTitle("");
      setSubmissionUrl("");
      setSubmissionNotes("");
      setSubmissionContact("");
      queryClient.invalidateQueries({ queryKey: ["public-submissions"] });
      queryClient.invalidateQueries({ queryKey: ["staged-records"] });
    }
  });

  const watchMutation = useMutation({
    mutationFn: createWatchArea,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watch-areas"] });
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    }
  });

  const submitPublicSource = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submissionMutation.mutate({
      title: submissionTitle,
      source_url: submissionUrl || null,
      notes: submissionNotes,
      submitter_contact: submissionContact || null,
      geometry: boundsGeometry(bounds.west, bounds.south, bounds.east, bounds.north)
    });
  };

  const submitWatchArea = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    watchMutation.mutate({
      name: watchName,
      email: watchEmail,
      geometry: boundsGeometry(bounds.west, bounds.south, bounds.east, bounds.north),
      filters: {
        statuses: ["layout", "preliminary", "final", "proposed"],
        development_types: ["subdivision", "public_submission"]
      }
    });
  };

  return (
    <main className="page-shell phase3-shell">
      <section className="review-header">
        <div>
          <h1>Participate</h1>
          <p>Public source tips, watch areas, queued alerts, and recent record changes.</p>
        </div>
      </section>

      <section className="phase3-grid">
        <form className="panel form-panel" onSubmit={submitPublicSource}>
          <div className="panel-heading">
            <span>
              <Send size={17} aria-hidden />
              Public Submission
            </span>
          </div>
          <label className="form-field">
            <span>Title</span>
            <input
              required
              minLength={3}
              value={submissionTitle}
              onChange={(event) => setSubmissionTitle(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span>Source link</span>
            <input
              value={submissionUrl}
              onChange={(event) => setSubmissionUrl(event.target.value)}
              placeholder="https://"
            />
          </label>
          <label className="form-field">
            <span>Contact</span>
            <input
              value={submissionContact}
              onChange={(event) => setSubmissionContact(event.target.value)}
              placeholder="email@example.com"
            />
          </label>
          <label className="form-field">
            <span>Notes</span>
            <textarea
              required
              minLength={5}
              value={submissionNotes}
              onChange={(event) => setSubmissionNotes(event.target.value)}
            />
          </label>
          <button className="primary-action" type="submit" disabled={submissionMutation.isPending}>
            Submit
          </button>
          {submissionMutation.isSuccess ? (
            <p className="success-text">Submission added to the reviewer queue.</p>
          ) : null}
          {submissionMutation.isError ? (
            <p className="error-text">Submission could not be saved.</p>
          ) : null}
        </form>

        <form className="panel form-panel" onSubmit={submitWatchArea}>
          <div className="panel-heading">
            <span>
              <MapPinned size={17} aria-hidden />
              Watch Area
            </span>
          </div>
          <label className="form-field">
            <span>Name</span>
            <input
              required
              minLength={3}
              value={watchName}
              onChange={(event) => setWatchName(event.target.value)}
            />
          </label>
          <label className="form-field">
            <span>Email</span>
            <input
              required
              value={watchEmail}
              onChange={(event) => setWatchEmail(event.target.value)}
              placeholder="email@example.com"
            />
          </label>
          <div className="bounds-grid">
            {(["west", "south", "east", "north"] as const).map((key) => (
              <label key={key} className="form-field">
                <span>{key}</span>
                <input
                  required
                  inputMode="decimal"
                  value={bounds[key]}
                  onChange={(event) =>
                    setBounds((current) => ({ ...current, [key]: event.target.value }))
                  }
                />
              </label>
            ))}
          </div>
          <button className="primary-action" type="submit" disabled={watchMutation.isPending}>
            Save Watch
          </button>
          {watchMutation.isSuccess ? (
            <p className="success-text">Watch area saved and alerts queued.</p>
          ) : null}
          {watchMutation.isError ? <p className="error-text">Watch area could not be saved.</p> : null}
        </form>
      </section>

      <section className="phase3-grid">
        <article className="panel list-panel">
          <div className="panel-heading">
            <span>
              <Bell size={17} aria-hidden />
              Alerts
            </span>
            <strong>{alertsQuery.data?.length ?? 0}</strong>
          </div>
          <div className="compact-list">
            {alertsQuery.data?.map((alert) => (
              <Link key={alert.id} className="compact-row" to={`/records/${alert.record_public_id}`}>
                <span>
                  <strong>{alert.record_title}</strong>
                  <small>{alert.summary}</small>
                </span>
                <StatusBadge value={alert.status} kind="review" />
              </Link>
            ))}
            {alertsQuery.data?.length === 0 ? <p className="muted">No alerts queued.</p> : null}
          </div>
        </article>

        <article className="panel list-panel">
          <div className="panel-heading">
            <span>
              <History size={17} aria-hidden />
              Change Log
            </span>
          </div>
          <div className="compact-list">
            {changeLogQuery.data?.slice(0, 8).map((entry) => (
              <Link key={entry.id} className="compact-row" to={`/records/${entry.public_id}`}>
                <span>
                  <strong>{entry.title}</strong>
                  <small>{entry.summary}</small>
                </span>
                <small>{entry.changed_at}</small>
              </Link>
            ))}
          </div>
        </article>
      </section>

      <section className="phase3-grid">
        <article className="panel list-panel">
          <div className="panel-heading">
            <span>Submissions</span>
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
          </div>
        </article>

        <article className="panel list-panel">
          <div className="panel-heading">
            <span>Watch Areas</span>
            <strong>{watchAreasQuery.data?.length ?? 0}</strong>
          </div>
          <div className="compact-list">
            {watchAreasQuery.data?.map((watchArea) => (
              <div key={watchArea.id} className="compact-row">
                <span>
                  <strong>{watchArea.name}</strong>
                  <small>{watchArea.email_hint}</small>
                </span>
                <span className="count-pill">{watchArea.alert_count}</span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <a className="source-card archive-link" href="https://www.huntsvilleal.gov/planningagendas/" target="_blank" rel="noreferrer">
        <span>Planning Commission agenda archive</span>
        <ExternalLink size={16} aria-hidden />
      </a>
    </main>
  );
}
