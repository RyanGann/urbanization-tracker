from app.ingestion.normalize import (
    normalize_building_permit,
    normalize_madison_county_subdivision,
    normalize_new_subdivision,
)


def test_normalizes_new_subdivision_to_published_polygon_record() -> None:
    staged, published, errors = normalize_new_subdivision(
        {
            "type": "Feature",
            "properties": {
                "SubdID": 42,
                "Subdivision": "Example Ridge",
                "Phase": "Ph 1",
                "Status": "Preliminary",
                "HousingUnits": 12,
                "HousingUnitType": "Lots",
                "Prelim_date": 1774310400000,
            },
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
        },
        "2026-05-20T12:00:00+00:00",
    )

    assert errors == []
    assert staged["review_status"] == "approved"
    assert published["status"] == "preliminary"
    assert published["geometry_confidence"] == "high"
    assert published["source_url"].endswith("/Housing/NewSubdivisions/MapServer/0")
    assert published["application_date"] == "2026-03-24"


def test_normalizes_building_permit_as_low_confidence_point_context() -> None:
    _staged, published, errors = normalize_building_permit(
        {
            "type": "Feature",
            "properties": {
                "PermitID": 100,
                "Subdivision": "Example Ridge",
                "OccupancyType": "Single Family",
                "TypeOfWork": "New Construction",
                "Permit_Issue_DateTime": 1778240880000,
            },
            "geometry": {"type": "Point", "coordinates": [-86.6, 34.7]},
        },
        "2026-05-20T12:00:00+00:00",
    )

    assert errors == []
    assert published["status"] == "issued_permit"
    assert published["development_type"] == "building_permit"
    assert published["geometry_confidence"] == "low"
    assert published["permit_issue_date"] == "2026-05-08"


def test_normalizes_madison_county_subdivision_as_recorded_context() -> None:
    staged, published, errors = normalize_madison_county_subdivision(
        {
            "type": "Feature",
            "properties": {
                "OBJECTID": 7,
                "Subd_ID": 95,
                "Subd_Name": "Abernathy Estates",
                "Subd_Type": "S",
                "Parcels": "8",
                "YearFiled": 1987,
                "DateFiled": "6/24/1987",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-86.72, 34.72],
                        [-86.71, 34.72],
                        [-86.71, 34.73],
                        [-86.72, 34.73],
                        [-86.72, 34.72],
                    ]
                ],
            },
        },
        "2026-05-20T12:00:00+00:00",
    )

    assert errors == []
    assert staged["review_status"] == "approved"
    assert published["public_id"].startswith("madison-county-subdivision-95")
    assert published["status"] == "completed"
    assert published["source_status"] == "Filed subdivision (1987-06-24)"
    assert published["approval_date"] == "1987-06-24"
    assert published["source_url"].endswith("/Housing/SubdivisionsInMadisonCounty/MapServer/0")
