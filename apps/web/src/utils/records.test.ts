import { describe, expect, it } from "vitest";

import type { DevelopmentRecord } from "../types";
import { filterRecords, formatArea, statusLabel, uniqueFlagTypes } from "./records";

const baseRecord: DevelopmentRecord = {
  public_id: "seed-a",
  title: "Seed A",
  description: "Seed",
  development_type: "subdivision",
  status: "layout",
  source_status: "Layout",
  source_url: "https://example.test",
  source_agency: "Seed agency",
  date_discovered: "2026-05-20",
  date_last_checked: "2026-05-20",
  application_date: null,
  approval_date: null,
  permit_issue_date: null,
  review_status: "published",
  confidence_level: "high",
  geometry_source: "Seed geometry",
  geometry_confidence: "high",
  geometry: {
    type: "Point",
    coordinates: [-86.58, 34.73]
  },
  centroid: [-86.58, 34.73],
  area_sq_m: 4046.8564224,
  address: null,
  parcel_ids: [],
  source_fields: {},
  proximity_flags: [
    {
      flag_type: "near_waterway",
      label: "Near waterway",
      relationship: "within",
      distance_m: 82,
      threshold_m: 100,
      source_name: "Hydrography",
      source_url: "https://example.test/hydrography",
      caveat: "Context only"
    }
  ]
};

describe("record utilities", () => {
  it("formats status labels", () => {
    expect(statusLabel("issued_permit")).toBe("Issued permit");
  });

  it("formats area in acres", () => {
    expect(formatArea(4046.8564224)).toBe("1.0 acres");
  });

  it("collects unique flag types", () => {
    expect(uniqueFlagTypes([baseRecord])).toEqual(["near_waterway"]);
  });

  it("filters by status, confidence, type, and flag", () => {
    const filtered = filterRecords([baseRecord], {
      statuses: ["layout"],
      confidenceLevels: ["high"],
      developmentTypes: ["subdivision"],
      flagTypes: ["near_waterway"]
    });

    expect(filtered).toEqual([baseRecord]);
  });
});
