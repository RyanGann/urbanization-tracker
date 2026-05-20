# Privacy And Safety Checklist

Complete this before enabling a new source or exposing new fields publicly.

## Source And License

- [ ] Source URL is public and stable.
- [ ] Terms of use, license, or public-record status has been reviewed.
- [ ] Public UI links to the authoritative source.
- [ ] Raw payload storage is internal unless redistribution is clearly allowed.

## Personal Or Sensitive Data

- [ ] Applicant, owner, contractor, phone, email, and contact fields are hidden or omitted.
- [ ] Public submissions store contact details only as hashes or minimal hints.
- [ ] Addresses are displayed only when necessary and clearly part of the public record.
- [ ] Parcel/owner enrichment is deferred until a separate privacy review.

## Safety And Interpretation

- [ ] Geometry confidence is labeled.
- [ ] Point records are not described as footprints.
- [ ] Agenda/PDF-derived records remain reviewer-gated.
- [ ] Environmental layers include caveats and are never presented as legal determinations.
- [ ] Floodplain context is not described as flood insurance or engineering advice.
- [ ] Wetland context is not described as a jurisdictional wetland determination.

## Reviewer Workflow

- [ ] Staged records include source payload excerpts needed for review.
- [ ] Duplicate candidates are visible.
- [ ] Reviewer actions can be exported before bulk changes.
- [ ] Imported reviewer decisions are reviewed after import.

## Launch

- [ ] Connector health shows the source.
- [ ] Ingestion errors are visible to maintainers.
- [ ] Performance smoke tests pass with a larger synthetic dataset.
- [ ] Documentation explains source caveats and known gaps.
