import type { Feature, FeatureCollection, GeoJsonProperties, Geometry } from "geojson";
import maplibregl, {
  type GeoJSONSource,
  type LngLatBoundsLike,
  type Map as MapLibreMap,
  type MapLayerMouseEvent,
  type StyleSpecification
} from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import type { DevelopmentRecord, EnvironmentalOverlay } from "../types";
import { statusLabel } from "../utils/records";

interface DevelopmentMapProps {
  records: DevelopmentRecord[];
  overlays: EnvironmentalOverlay[];
  visibleOverlayIds: string[];
  selectedId: string | null;
  onSelect: (record: DevelopmentRecord) => void;
}

const MAP_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "background",
      type: "background",
      paint: {
        "background-color": "#e9efe9"
      }
    }
  ]
};

const INITIAL_BOUNDS: LngLatBoundsLike = [
  [-86.88, 34.6],
  [-86.42, 34.91]
];

function toFeature(record: DevelopmentRecord): Feature<Geometry, GeoJsonProperties> {
  return {
    type: "Feature",
    id: record.public_id,
    geometry: record.geometry,
    properties: {
      public_id: record.public_id,
      title: record.title,
      status: record.status,
      development_type: record.development_type,
      confidence_level: record.confidence_level,
      geometry_confidence: record.geometry_confidence
    }
  };
}

function featureCollection(features: Feature<Geometry, GeoJsonProperties>[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features
  };
}

function upsertSource(map: MapLibreMap, sourceId: string, data: FeatureCollection) {
  const source = map.getSource(sourceId) as GeoJSONSource | undefined;
  if (source) {
    source.setData(data);
    return;
  }

  map.addSource(sourceId, {
    type: "geojson",
    data
  });
}

function polygonFeatures(records: DevelopmentRecord[]): FeatureCollection {
  return featureCollection(
    records.filter((record) => record.geometry.type !== "Point").map((record) => toFeature(record))
  );
}

function pointFeatures(records: DevelopmentRecord[]): FeatureCollection {
  return featureCollection(
    records.filter((record) => record.geometry.type === "Point").map((record) => toFeature(record))
  );
}

function overlayColor(overlay: EnvironmentalOverlay): string {
  if (overlay.category === "wetlands") return "#3f8f73";
  if (overlay.category === "floodplain") return "#4f85c7";
  if (overlay.category === "waterways") return "#2d6fb7";
  if (overlay.category === "protected_area") return "#76a857";
  return "#384a50";
}

function overlayLayerIds(overlay: EnvironmentalOverlay): string[] {
  if (overlay.geom_type === "polygon" && overlay.category !== "boundary") {
    return [`env-${overlay.id}-fill`, `env-${overlay.id}-line`];
  }
  return [`env-${overlay.id}-line`];
}

function ensureDevelopmentLayers(map: MapLibreMap) {
  if (!map.getLayer("development-polygons-fill")) {
    map.addLayer({
      id: "development-polygons-fill",
      type: "fill",
      source: "development-polygons",
      paint: {
        "fill-color": [
          "match",
          ["get", "status"],
          "layout",
          "#f2b84b",
          "preliminary",
          "#d66d4a",
          "final",
          "#356db0",
          "issued_permit",
          "#5d7280",
          "#7f6bb1"
        ],
        "fill-opacity": 0.56
      }
    });
  }

  if (!map.getLayer("development-polygons-line")) {
    map.addLayer({
      id: "development-polygons-line",
      type: "line",
      source: "development-polygons",
      paint: {
        "line-color": "#20313a",
        "line-width": 1.4
      }
    });
  }

  if (!map.getLayer("development-points")) {
    map.addLayer({
      id: "development-points",
      type: "circle",
      source: "development-points",
      paint: {
        "circle-color": "#5d7280",
        "circle-radius": 7,
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2
      }
    });
  }
}

function ensureOverlayLayer(map: MapLibreMap, overlay: EnvironmentalOverlay) {
  const sourceId = `env-${overlay.id}`;
  const color = overlayColor(overlay);

  if (overlay.geom_type === "polygon" && overlay.category !== "boundary") {
    if (!map.getLayer(`env-${overlay.id}-fill`)) {
      map.addLayer(
        {
          id: `env-${overlay.id}-fill`,
          type: "fill",
          source: sourceId,
          paint: {
            "fill-color": color,
            "fill-opacity": overlay.category === "floodplain" ? 0.2 : 0.18
          }
        },
        "development-polygons-fill"
      );
    }
    if (!map.getLayer(`env-${overlay.id}-line`)) {
      map.addLayer(
        {
          id: `env-${overlay.id}-line`,
          type: "line",
          source: sourceId,
          paint: {
            "line-color": color,
            "line-width": 1.1,
            "line-opacity": 0.76
          }
        },
        "development-polygons-fill"
      );
    }
    return;
  }

  if (!map.getLayer(`env-${overlay.id}-line`)) {
    map.addLayer(
      {
        id: `env-${overlay.id}-line`,
        type: "line",
        source: sourceId,
        paint: {
          "line-color": color,
          "line-width": overlay.category === "boundary" ? 2 : 2.5,
          "line-dasharray": overlay.category === "boundary" ? [2, 2] : [1, 0],
          "line-opacity": overlay.category === "boundary" ? 0.8 : 0.95
        }
      },
      "development-polygons-fill"
    );
  }
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function DevelopmentMap({
  records,
  overlays,
  visibleOverlayIds,
  selectedId,
  onSelect
}: DevelopmentMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const handlersAttachedRef = useRef(false);
  const recordsRef = useRef(records);
  const [mapReady, setMapReady] = useState(false);
  const [appliedFeatureCount, setAppliedFeatureCount] = useState(0);

  recordsRef.current = records;

  const selectedRecord = useMemo(
    () => records.find((record) => record.public_id === selectedId) ?? null,
    [records, selectedId]
  );

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      attributionControl: false,
      minZoom: 8
    });
    map.fitBounds(INITIAL_BOUNDS, { padding: 28, duration: 0 });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.addControl(
      new maplibregl.AttributionControl({
        compact: true,
        customAttribution: "Seed data for planning MVP"
      }),
      "bottom-right"
    );
    map.once("load", () => setMapReady(true));
    if (import.meta.env.DEV) {
      (
        window as typeof window & {
          __urbanizationTrackerMap?: MapLibreMap;
        }
      ).__urbanizationTrackerMap = map;
    }
    mapRef.current = map;

    return () => {
      popupRef.current?.remove();
      if (import.meta.env.DEV) {
        delete (
          window as typeof window & {
            __urbanizationTrackerMap?: MapLibreMap;
          }
        ).__urbanizationTrackerMap;
      }
      map.remove();
      mapRef.current = null;
      handlersAttachedRef.current = false;
      setMapReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) {
      return;
    }

    upsertSource(map, "development-polygons", polygonFeatures(records));
    upsertSource(map, "development-points", pointFeatures(records));
    ensureDevelopmentLayers(map);

    overlays.forEach((overlay) => {
      upsertSource(map, `env-${overlay.id}`, overlay.features);
      ensureOverlayLayer(map, overlay);
      overlayLayerIds(overlay).forEach((layerId) => {
        if (map.getLayer(layerId)) {
          map.setLayoutProperty(
            layerId,
            "visibility",
            visibleOverlayIds.includes(overlay.id) ? "visible" : "none"
          );
        }
      });
    });
    setAppliedFeatureCount(records.length);

    if (!handlersAttachedRef.current) {
      const handleClick = (event: MapLayerMouseEvent) => {
        const feature = event.features?.[0];
        const publicId = feature?.properties?.public_id as string | undefined;
        const record = recordsRef.current.find((candidate) => candidate.public_id === publicId);
        if (!record) {
          return;
        }
        onSelect(record);
        popupRef.current?.remove();
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: "280px" })
          .setLngLat(record.centroid)
          .setHTML(
            `<strong>${escapeHtml(record.title)}</strong><br /><span>${escapeHtml(
              statusLabel(record.status)
            )}</span><br /><a href="/records/${escapeHtml(record.public_id)}">Open detail</a>`
          )
          .addTo(map);
      };

      ["development-polygons-fill", "development-points"].forEach((layerId) => {
        map.on("click", layerId, handleClick);
        map.on("mouseenter", layerId, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layerId, () => {
          map.getCanvas().style.cursor = "";
        });
      });
      handlersAttachedRef.current = true;
    }
  }, [records, overlays, visibleOverlayIds, onSelect, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedRecord) {
      return;
    }

    map.easeTo({
      center: selectedRecord.centroid,
      zoom: Math.max(map.getZoom(), 11.2),
      duration: 550
    });
  }, [selectedRecord]);

  return (
    <div
      className="map-stage"
      data-feature-count={appliedFeatureCount}
      data-testid="development-map"
    >
      <div ref={containerRef} className="map-canvas" aria-label="Development map" />
    </div>
  );
}
