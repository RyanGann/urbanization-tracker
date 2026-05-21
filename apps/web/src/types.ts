import type { FeatureCollection, Geometry } from "geojson";

export type DevelopmentStatus =
  | "layout"
  | "preliminary"
  | "final"
  | "issued_permit"
  | "completed"
  | "proposed";

export type ReviewStatus = "pending" | "needs_info" | "rejected" | "approved" | "published";
export type ConfidenceLevel = "low" | "medium" | "high";

export interface ProximityFlag {
  flag_type: string;
  label: string;
  relationship: string;
  distance_m: number | null;
  threshold_m: number | null;
  source_name: string;
  source_url: string;
  caveat: string;
}

export interface DevelopmentRecord {
  public_id: string;
  title: string;
  description: string;
  development_type: string;
  status: DevelopmentStatus;
  source_status: string;
  source_url: string;
  source_agency: string;
  date_discovered: string;
  date_last_checked: string;
  application_date: string | null;
  approval_date: string | null;
  permit_issue_date: string | null;
  review_status: ReviewStatus;
  confidence_level: ConfidenceLevel;
  geometry_source: string;
  geometry_confidence: ConfidenceLevel;
  geometry: Geometry;
  centroid: [number, number];
  area_sq_m: number | null;
  address: string | null;
  parcel_ids: string[];
  source_fields: Record<string, unknown>;
  proximity_flags: ProximityFlag[];
}

export interface DevelopmentRecordCollection {
  records: DevelopmentRecord[];
}

export interface StagedDevelopmentRecord {
  id: string;
  title: string;
  description: string;
  development_type: string;
  source_status: string;
  normalized_status: DevelopmentStatus;
  source_url: string;
  source_agency: string;
  date_discovered: string;
  review_status: ReviewStatus;
  record_confidence: ConfidenceLevel;
  geometry_source: string;
  geometry_confidence: ConfidenceLevel;
  geometry: Geometry;
  source_payload: Record<string, unknown>;
  normalization_notes: string;
}

export interface EnvironmentalOverlay {
  id: string;
  name: string;
  category: string;
  source_url: string;
  attribution: string;
  caveat: string;
  geom_type: "polygon" | "line" | "point";
  features: FeatureCollection;
}

export interface SourceHealth {
  run_id?: string;
  checked_at?: string;
  status: string;
  records?: {
    raw?: number;
    staged?: number;
    published?: number;
    proximity_flags?: number;
  };
  sources: Array<{
    key: string;
    name: string;
    source_url: string;
    status: string;
    records_seen: number;
    records_created: number;
    error_count: number;
    validation_errors: string[];
  }>;
}

export interface SourceDocument {
  id: string;
  title: string;
  url: string;
  document_date: string | null;
  fetched_at: string | null;
  sha256: string | null;
  content_type: string | null;
  storage_uri: string | null;
  extracted_text_uri: string | null;
  extraction_status: string;
  parsed_item_count: number;
  text_excerpt: string | null;
}

export interface UserSubmissionCreate {
  title: string;
  source_url: string | null;
  notes: string;
  submitter_contact: string | null;
  geometry: Geometry | null;
}

export interface UserSubmission {
  id: string;
  title: string;
  source_url: string | null;
  notes: string;
  submitter_contact_hash: string | null;
  status: ReviewStatus;
  created_at: string;
  staged_record_id: string;
}

export interface UserSubmissionReceipt {
  id: string;
  title: string;
  status: ReviewStatus;
  created_at: string;
}

export interface WatchAreaCreate {
  name: string;
  email: string;
  geometry: Geometry;
  filters: Record<string, unknown>;
}

export interface WatchArea {
  id: string;
  name: string;
  email_hash: string;
  email_hint: string;
  geometry: Geometry;
  filters: Record<string, unknown>;
  created_at: string;
  alert_count: number;
}

export interface WatchAreaReceipt {
  id: string;
  name: string;
  email_hint: string;
  created_at: string;
  alert_count: number;
}

export interface Alert {
  id: string;
  watch_area_id: string;
  record_public_id: string;
  record_title: string;
  alert_type: string;
  status: string;
  delivery_channel: string;
  created_at: string;
  sent_at: string | null;
  summary: string;
}

export interface AlertDeliveryResult {
  configured: boolean;
  attempted: number;
  sent: number;
  suppressed: number;
  failed: number;
  errors: string[];
}

export interface ReviewerDecisionSnapshot {
  staged_id: string;
  title: string;
  source_url: string;
  review_status: ReviewStatus;
  review_notes: string | null;
  exported_at: string;
}

export interface ReviewerDecisionImportResult {
  applied: number;
  missing: string[];
}

export interface RecordVersion {
  id: string;
  public_id: string;
  version_number: number;
  changed_at: string;
  changed_by: string;
  change_type: string;
  snapshot: Record<string, unknown>;
}

export interface ChangeLogEntry {
  id: string;
  public_id: string;
  title: string;
  changed_at: string;
  change_type: string;
  summary: string;
}

export interface DuplicateCandidate {
  id: string;
  staged_record_id: string;
  staged_title: string;
  candidate_public_id: string;
  candidate_title: string;
  score: number;
  reasons: string[];
}

export interface JurisdictionSource {
  key: string;
  name: string;
  connector_type: string;
  parser_key: string;
  source_url: string;
  active: boolean;
  privacy_review: string;
  safety_review: string;
  config: Record<string, unknown>;
}

export interface Jurisdiction {
  id: string;
  name: string;
  state: string;
  country: string;
  timezone: string;
  default_center: [number, number];
  sources: JurisdictionSource[];
}

export interface ConnectorHealth {
  key: string;
  name: string;
  jurisdiction_id: string;
  jurisdiction_name: string;
  connector_type: string;
  parser_key: string;
  source_url: string;
  active: boolean;
  status: string;
  records_seen: number;
  records_created: number;
  error_count: number;
  last_checked_at: string | null;
  privacy_review: string;
  safety_review: string;
}

export interface RecordFilters {
  statuses: DevelopmentStatus[];
  confidenceLevels: ConfidenceLevel[];
  developmentTypes: string[];
  flagTypes: string[];
}
