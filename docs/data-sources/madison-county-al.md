# Madison County, AL Data Sources

## Active Sources

### Madison County Subdivisions

- Jurisdiction config: `apps/api/app/jurisdictions/madison-county-al.json`
- Source key: `madison_county_subdivisions`
- Source URL: https://maps.huntsvilleal.gov/server/rest/services/Housing/SubdivisionsInMadisonCounty/MapServer/0
- Connector: ArcGIS REST feature layer
- Geometry: polygon
- Parser: `madison_county_subdivisions`
- Ingestion command:

```bash
make ingest-madison-county
```

The layer is a recorded subdivision context source. Published records are normalized as
`completed` subdivision records because the source fields describe filed subdivision plats rather
than current applications or permits. Public UI copy should keep that caveat visible and avoid
presenting the records as current construction, title, engineering, or legal determinations.

## Privacy And Safety Notes

- Expected fields are subdivision metadata, document references, filing dates, parcel counts, and
  polygon geometry.
- No personal contact fields are expected.
- Raw payloads should remain internal audit artifacts until redistribution terms are clarified.
- `DateFiled` is parsed when available; `YearFiled` is retained as source context without
  fabricating an exact date.
