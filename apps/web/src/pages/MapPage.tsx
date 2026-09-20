import "maplibre-gl/dist/maplibre-gl.css";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Filter, Layers, ListFilter, MapPin, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { fetchDatasetStatus, fetchDevelopmentRecords, fetchMapLayerCatalog } from "../api";
import { DevelopmentMap } from "../components/DevelopmentMap";
import { StatusBadge } from "../components/StatusBadge";
import type { ConfidenceLevel, DevelopmentRecord } from "../types";
import {
  CONFIDENCE_OPTIONS,
  DEVELOPMENT_TYPE_OPTIONS,
  FLAG_OPTIONS,
  STATUS_OPTIONS,
  developmentTypeLabel,
  filterRecords,
  formatArea,
} from "../utils/records";
import { performanceMark } from "../utils/performance";

const INITIAL_STATUSES = STATUS_OPTIONS.map((option) => option.value);
const INITIAL_CONFIDENCE: ConfidenceLevel[] = ["high", "medium", "low"];
const INITIAL_TYPES = DEVELOPMENT_TYPE_OPTIONS.map((option) => option.value);

function toggleValue<T extends string>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((candidate) => candidate !== value) : [...values, value];
}

export function MapPage() {
  const [statuses, setStatuses] = useState(INITIAL_STATUSES);
  const [confidenceLevels, setConfidenceLevels] =
    useState<ConfidenceLevel[]>(INITIAL_CONFIDENCE);
  const [developmentTypes, setDevelopmentTypes] = useState<string[]>(INITIAL_TYPES);
  const [flagTypes, setFlagTypes] = useState<string[] | undefined>(undefined);
  const [visibleOverlayIds, setVisibleOverlayIds] = useState<string[]>([]);
  const catalogInitialized = useRef(false);
  const [selectedRecord, setSelectedRecord] = useState<DevelopmentRecord | null>(null);

  const filters = useMemo(
    () => ({ statuses, confidenceLevels, developmentTypes, flagTypes }),
    [statuses, confidenceLevels, developmentTypes, flagTypes]
  );

  const recordsQuery = useQuery({
    queryKey: ["development-records", filters],
    queryFn: () => fetchDevelopmentRecords(filters)
  });

  const catalogQuery = useQuery({
    queryKey: ["map-layers"],
    queryFn: fetchMapLayerCatalog,
    staleTime: 60_000
  });

  const datasetStatusQuery = useQuery({
    queryKey: ["dataset-status"],
    queryFn: fetchDatasetStatus
  });

  const records = recordsQuery.isError ? [] : recordsQuery.data?.records ?? [];
  const catalogLayers = catalogQuery.data?.layers ?? [];
  const dataMode = recordsQuery.data?.data_mode ?? catalogQuery.data?.data_mode ?? datasetStatusQuery.data?.data_mode;

  useEffect(() => {
    if (!catalogQuery.data) return;
    const ids = new Set(catalogQuery.data.layers.map((layer) => layer.id));
    setVisibleOverlayIds((current) => {
      if (catalogInitialized.current) return current.filter((id) => ids.has(id));
      catalogInitialized.current = true;
      return catalogQuery.data.layers
        .filter((layer) => layer.default_visible)
        .map((layer) => layer.id);
    });
  }, [catalogQuery.data]);

  useEffect(() => {
    if (!selectedRecord) return;
    const stillMatchesFilters = filterRecords([selectedRecord], filters).length > 0;
    const returnedByQuery = records.some((record) => record.public_id === selectedRecord.public_id);
    if (
      recordsQuery.isError ||
      !stillMatchesFilters ||
      (!recordsQuery.isFetching && !returnedByQuery)
    ) {
      setSelectedRecord(null);
    }
  }, [filters, records, recordsQuery.isError, recordsQuery.isFetching, selectedRecord]);
  useEffect(() => {
    if (recordsQuery.isSuccess) performanceMark("list-ready");
  }, [recordsQuery.isSuccess]);

  const resetFilters = () => {
    setStatuses(INITIAL_STATUSES);
    setConfidenceLevels(INITIAL_CONFIDENCE);
    setDevelopmentTypes(INITIAL_TYPES);
    setFlagTypes(undefined);
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
            <button
              className="icon-button"
              type="button"
              onClick={resetFilters}
              title="Reset filters"
              aria-label="Reset filters"
            >
              <RotateCcw size={16} aria-hidden />
            </button>
          </div>

          <div className="control-group">
            <h2>Status</h2>
            <div className="check-grid">
              {STATUS_OPTIONS.map((option) => (
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
            {DEVELOPMENT_TYPE_OPTIONS.map((option) => (
              <label key={option.value} className="check-row">
                <input
                  type="checkbox"
                  checked={developmentTypes.includes(option.value)}
                  onChange={() =>
                    setDevelopmentTypes((current) => toggleValue(current, option.value))
                  }
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>

          <div className="control-group">
            <h2>Context Flags</h2>
            <p className="muted" aria-live="polite">
              {flagTypes === undefined
                ? "No flag restriction (all records)"
                : flagTypes.length
                  ? "Selected flags"
                  : "No flags selected — no results"}
            </p>
            {flagTypes !== undefined ? (
              <button
                className="secondary-action"
                type="button"
                onClick={() => setFlagTypes(undefined)}
              >
                Clear flag restriction
              </button>
            ) : null}
            {FLAG_OPTIONS.map((option) => (
              <label key={option.value} className="check-row">
                <input
                  type="checkbox"
                  checked={flagTypes?.includes(option.value) ?? false}
                  onChange={() =>
                    setFlagTypes((current) => toggleValue(current ?? [], option.value))
                  }
                />
                <span>{option.label}</span>
              </label>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <span>
              <Layers size={17} aria-hidden />
              Layers
            </span>
          </div>
          {catalogQuery.isLoading ? <p className="muted">Loading environmental layer catalog...</p> : null}
          {catalogQuery.isError ? (
            <p className="error-text" role="alert">
              Environmental layer metadata is unavailable. Try again after initialization completes.
            </p>
          ) : null}
          {!catalogQuery.isLoading && !catalogQuery.isError && catalogLayers.length === 0 ? (
            <p className="muted">No environmental layers are available for this dataset.</p>
          ) : null}
          {!catalogQuery.isLoading && !catalogQuery.isError && catalogLayers.length > 0 ? (
            <div className="layer-list">
              {catalogLayers.map((layer) => {
                const preparing = layer.delivery_status === "processing";
                const ready = layer.delivery_status === "ready";
                return (
                  <div key={layer.id}>
                    <label className="check-row">
                      <input
                        type="checkbox"
                        checked={visibleOverlayIds.includes(layer.id)}
                        disabled={!ready}
                        onChange={() =>
                          setVisibleOverlayIds((current) => toggleValue(current, layer.id))
                        }
                      />
                      <span>{layer.title}</span>
                    </label>
                    {preparing ? <p className="muted">Tiles are being prepared for this layer.</p> : null}
                    {!preparing && !ready ? (
                      <p className="muted">This layer is currently unavailable.</p>
                    ) : null}
                    <p className="muted">{layer.attribution}</p>
                  </div>
                );
              })}
            </div>
          ) : null}
        </section>

        <section className="panel record-list-panel">
          <div className="panel-heading">
            <span>
              <ListFilter size={17} aria-hidden />
              Records
            </span>
            <strong aria-live="polite">{records.length}</strong>
          </div>
          {recordsQuery.isLoading ? <p className="muted">Loading development records...</p> : null}
          {recordsQuery.isError ? (
            <p className="error-text" role="alert">Development data is unavailable. Try again after initialization completes.</p>
          ) : null}
          {!recordsQuery.isLoading && !recordsQuery.isError && records.length === 0 ? (
            <p className="muted" role="status" aria-live="polite">
              No development records are available for these filters.
            </p>
          ) : null}
          {dataMode === "demo" ? <p className="muted">Demo data — not live planning data.</p> : null}
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
