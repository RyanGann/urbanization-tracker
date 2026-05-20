import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Filter, Layers, ListFilter, MapPin, RotateCcw } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { fetchDevelopmentRecords, fetchEnvironmentalOverlays } from "../api";
import { DevelopmentMap } from "../components/DevelopmentMap";
import { StatusBadge } from "../components/StatusBadge";
import type { ConfidenceLevel, DevelopmentRecord, DevelopmentStatus } from "../types";
import {
  CONFIDENCE_OPTIONS,
  STATUS_OPTIONS,
  developmentTypeLabel,
  formatArea,
  uniqueFlagTypes
} from "../utils/records";

const INITIAL_STATUSES: DevelopmentStatus[] = ["layout", "preliminary", "final", "issued_permit"];
const INITIAL_CONFIDENCE: ConfidenceLevel[] = ["high", "medium", "low"];
const INITIAL_TYPES = ["subdivision", "building_permit"];
const INITIAL_OVERLAYS = [
  "pilot-boundary",
  "wetlands",
  "floodplain",
  "hydrography",
  "parks-open-space"
];

function toggleValue<T extends string>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((candidate) => candidate !== value) : [...values, value];
}

export function MapPage() {
  const [statuses, setStatuses] = useState<DevelopmentStatus[]>(INITIAL_STATUSES);
  const [confidenceLevels, setConfidenceLevels] =
    useState<ConfidenceLevel[]>(INITIAL_CONFIDENCE);
  const [developmentTypes, setDevelopmentTypes] = useState<string[]>(INITIAL_TYPES);
  const [flagTypes, setFlagTypes] = useState<string[]>([]);
  const [visibleOverlayIds, setVisibleOverlayIds] = useState<string[]>(INITIAL_OVERLAYS);
  const [selectedRecord, setSelectedRecord] = useState<DevelopmentRecord | null>(null);

  const filters = useMemo(
    () => ({ statuses, confidenceLevels, developmentTypes, flagTypes }),
    [statuses, confidenceLevels, developmentTypes, flagTypes]
  );

  const recordsQuery = useQuery({
    queryKey: ["development-records", filters],
    queryFn: () => fetchDevelopmentRecords(filters)
  });

  const overlaysQuery = useQuery({
    queryKey: ["environmental-overlays"],
    queryFn: fetchEnvironmentalOverlays
  });

  const records = recordsQuery.data?.records ?? [];
  const overlays = overlaysQuery.data ?? [];
  const availableFlags = uniqueFlagTypes(recordsQuery.data?.records ?? records);

  const resetFilters = () => {
    setStatuses(INITIAL_STATUSES);
    setConfidenceLevels(INITIAL_CONFIDENCE);
    setDevelopmentTypes(INITIAL_TYPES);
    setFlagTypes([]);
    setVisibleOverlayIds(INITIAL_OVERLAYS);
  };

  const handleSelect = useCallback((record: DevelopmentRecord) => {
    setSelectedRecord(record);
  }, []);

  return (
    <main className="workspace">
      <aside className="sidebar" aria-label="Map filters and records">
        <section className="panel">
          <div className="panel-heading">
            <span>
              <Filter size={17} aria-hidden />
              Filters
            </span>
            <button className="icon-button" type="button" onClick={resetFilters} title="Reset filters">
              <RotateCcw size={16} aria-hidden />
            </button>
          </div>

          <div className="control-group">
            <h2>Status</h2>
            <div className="check-grid">
              {STATUS_OPTIONS.slice(0, 4).map((option) => (
                <label key={option.value} className="check-row">
                  <input
                    type="checkbox"
                    checked={statuses.includes(option.value)}
                    onChange={() => setStatuses((current) => toggleValue(current, option.value))}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="control-group">
            <h2>Confidence</h2>
            <div className="segmented" aria-label="Confidence filters">
              {CONFIDENCE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={confidenceLevels.includes(option.value) ? "active" : ""}
                  onClick={() =>
                    setConfidenceLevels((current) => toggleValue(current, option.value))
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="control-group">
            <h2>Record Type</h2>
            <label className="check-row">
              <input
                type="checkbox"
                checked={developmentTypes.includes("subdivision")}
                onChange={() =>
                  setDevelopmentTypes((current) => toggleValue(current, "subdivision"))
                }
              />
              <span>Subdivisions</span>
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={developmentTypes.includes("building_permit")}
                onChange={() =>
                  setDevelopmentTypes((current) => toggleValue(current, "building_permit"))
                }
              />
              <span>Building permits</span>
            </label>
          </div>

          <div className="control-group">
            <h2>Context Flags</h2>
            {availableFlags.length ? (
              availableFlags.map((flag) => (
                <label key={flag} className="check-row">
                  <input
                    type="checkbox"
                    checked={flagTypes.includes(flag)}
                    onChange={() => setFlagTypes((current) => toggleValue(current, flag))}
                  />
                  <span>{flag.replaceAll("_", " ")}</span>
                </label>
              ))
            ) : (
              <p className="muted">No active flags in the current result set.</p>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <span>
              <Layers size={17} aria-hidden />
              Layers
            </span>
          </div>
          <div className="layer-list">
            {overlays.map((overlay) => (
              <label key={overlay.id} className="check-row">
                <input
                  type="checkbox"
                  checked={visibleOverlayIds.includes(overlay.id)}
                  onChange={() =>
                    setVisibleOverlayIds((current) => toggleValue(current, overlay.id))
                  }
                />
                <span>{overlay.name}</span>
              </label>
            ))}
          </div>
        </section>

        <section className="panel record-list-panel">
          <div className="panel-heading">
            <span>
              <ListFilter size={17} aria-hidden />
              Records
            </span>
            <strong>{records.length}</strong>
          </div>
          {recordsQuery.isLoading ? <p className="muted">Loading seed records...</p> : null}
          {recordsQuery.isError ? (
            <p className="error-text">Could not load records from the API.</p>
          ) : null}
          <div className="record-list">
            {records.map((record) => (
              <button
                key={record.public_id}
                className={`record-row ${
                  selectedRecord?.public_id === record.public_id ? "selected" : ""
                }`}
                type="button"
                onClick={() => setSelectedRecord(record)}
              >
                <span className="record-title">{record.title}</span>
                <span className="record-meta">
                  {developmentTypeLabel(record.development_type)}
                  <StatusBadge value={record.status} />
                </span>
              </button>
            ))}
          </div>
        </section>
      </aside>

      <section className="map-column">
        <DevelopmentMap
          records={records}
          overlays={overlays}
          visibleOverlayIds={visibleOverlayIds}
          selectedId={selectedRecord?.public_id ?? null}
          onSelect={handleSelect}
        />
        <footer className="map-footer">
          <span>
            Screening-level context only. Verify source agency materials before legal, permitting,
            engineering, ecological, flood insurance, or environmental-impact decisions.
          </span>
        </footer>
      </section>

      <aside className="detail-rail" aria-label="Selected record">
        {selectedRecord ? (
          <article className="panel selected-record">
            <div className="selected-title">
              <MapPin size={18} aria-hidden />
              <h1>{selectedRecord.title}</h1>
            </div>
            <div className="badge-row">
              <StatusBadge value={selectedRecord.status} />
              <StatusBadge value={selectedRecord.confidence_level} kind="confidence" />
              <StatusBadge value={selectedRecord.geometry_confidence} kind="confidence" />
            </div>
            <p>{selectedRecord.description}</p>
            <dl className="facts">
              <div>
                <dt>Source agency</dt>
                <dd>{selectedRecord.source_agency}</dd>
              </div>
              <div>
                <dt>Geometry source</dt>
                <dd>{selectedRecord.geometry_source}</dd>
              </div>
              <div>
                <dt>Last checked</dt>
                <dd>{selectedRecord.date_last_checked}</dd>
              </div>
              <div>
                <dt>Area</dt>
                <dd>{formatArea(selectedRecord.area_sq_m)}</dd>
              </div>
            </dl>
            <div className="flag-stack">
              {selectedRecord.proximity_flags.length ? (
                selectedRecord.proximity_flags.map((flag) => (
                  <div key={`${selectedRecord.public_id}-${flag.flag_type}`} className="flag-item">
                    <strong>{flag.label}</strong>
                    <span>{flag.caveat}</span>
                  </div>
                ))
              ) : (
                <p className="muted">No seed environmental flags attached.</p>
              )}
            </div>
            <div className="button-row">
              <Link className="primary-action" to={`/records/${selectedRecord.public_id}`}>
                Open detail
              </Link>
              <a
                className="icon-link"
                href={selectedRecord.source_url}
                target="_blank"
                rel="noreferrer"
                title="Open source"
              >
                <ExternalLink size={16} aria-hidden />
                Source
              </a>
            </div>
          </article>
        ) : (
          <article className="panel empty-state">
            <MapPin size={24} aria-hidden />
            <h1>Select a record</h1>
            <p>Click a map feature or record row to inspect source links, confidence, and context.</p>
          </article>
        )}
      </aside>
    </main>
  );
}
