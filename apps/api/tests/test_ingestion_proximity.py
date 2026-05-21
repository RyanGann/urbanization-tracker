from app.ingestion.proximity import compute_proximity_flags
from app.ingestion.sources.huntsville import FEMA_FLOODPLAIN_1PCT, USFWS_WETLANDS


def test_computes_floodplain_and_wetland_flags() -> None:
    records = [
        {
            "public_id": "hsv-subdivision-test",
            "development_type": "subdivision",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-86.6, 34.7],
                        [-86.59, 34.7],
                        [-86.59, 34.71],
                        [-86.6, 34.71],
                        [-86.6, 34.7],
                    ]
                ],
            },
            "proximity_flags": [],
        }
    ]
    floodplain = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"OBJECTID": 1},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-86.601, 34.699],
                            [-86.595, 34.699],
                            [-86.595, 34.705],
                            [-86.601, 34.705],
                            [-86.601, 34.699],
                        ]
                    ],
                },
            }
        ],
    }
    wetlands = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"OBJECTID": 2},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-86.604, 34.7],
                            [-86.603, 34.7],
                            [-86.603, 34.701],
                            [-86.604, 34.701],
                            [-86.604, 34.7],
                        ]
                    ],
                },
            }
        ],
    }

    count = compute_proximity_flags(
        records,
        [
            (FEMA_FLOODPLAIN_1PCT, floodplain),
            (USFWS_WETLANDS, wetlands),
        ],
    )

    assert count == 2
    assert {flag["flag_type"] for flag in records[0]["proximity_flags"]} == {
        "intersects_floodplain",
        "near_wetland",
    }
    methods = {flag["method"] for flag in records[0]["proximity_flags"]}
    assert methods == {
        "local_projected_geometry_intersection_epsg4326",
        "local_projected_geometry_distance_epsg4326",
    }


def test_floodplain_bbox_overlap_does_not_create_false_intersection() -> None:
    records = [
        {
            "public_id": "hsv-subdivision-triangle",
            "development_type": "subdivision",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-86.6, 34.7],
                        [-86.59, 34.7],
                        [-86.6, 34.71],
                        [-86.6, 34.7],
                    ]
                ],
            },
            "proximity_flags": [],
        }
    ]
    floodplain = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"OBJECTID": 10},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-86.5905, 34.7095],
                            [-86.5905, 34.706],
                            [-86.594, 34.7095],
                            [-86.5905, 34.7095],
                        ]
                    ],
                },
            }
        ],
    }

    count = compute_proximity_flags(records, [(FEMA_FLOODPLAIN_1PCT, floodplain)])

    assert count == 0
    assert records[0]["proximity_flags"] == []


def test_wetland_distance_uses_geometry_edges_not_bbox_only() -> None:
    records = [
        {
            "public_id": "hsv-subdivision-near-wetland",
            "development_type": "subdivision",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-86.6, 34.7],
                        [-86.595, 34.7],
                        [-86.6, 34.705],
                        [-86.6, 34.7],
                    ]
                ],
            },
            "proximity_flags": [],
        }
    ]
    wetlands = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"OBJECTID": 20},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-86.596, 34.705],
                            [-86.595, 34.706],
                            [-86.596, 34.706],
                            [-86.596, 34.705],
                        ]
                    ],
                },
            }
        ],
    }

    count = compute_proximity_flags(records, [(USFWS_WETLANDS, wetlands)])

    assert count == 1
    [flag] = records[0]["proximity_flags"]
    assert flag["flag_type"] == "near_wetland"
    assert flag["relationship"] == "within"
    assert 0 < flag["distance_m"] < 500
