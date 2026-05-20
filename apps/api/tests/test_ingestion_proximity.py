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
