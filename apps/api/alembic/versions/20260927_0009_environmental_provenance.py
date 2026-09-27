"""Retain immutable shadow environmental provenance and canonical revisions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260927_0009"
down_revision = "20260924_0008"
branch_labels = None
depends_on = None

PROVENANCE_GUARDS_SQL = r"""
CREATE FUNCTION b02_lock_observation(source text, run text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(
    jsonb_build_array('b02-observation-v1', source, run)::text, 0));
END $$;
CREATE FUNCTION b02_parent_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bound_old jsonb; bound_new jsonb; attested boolean;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.canonical_revision <> 0 THEN RAISE EXCEPTION 'canonical revision is generated'; END IF;
    RETURN NEW;
  END IF;
  attested := EXISTS(SELECT 1 FROM environmental_attestations WHERE environmental_layer_id=OLD.id);
  IF TG_OP = 'DELETE' THEN
    IF OLD.layer_key IS NOT NULL OR attested THEN
      RAISE EXCEPTION 'versioned parent identity is retained';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.id <> OLD.id OR (OLD.layer_key IS NOT NULL AND
     (NEW.layer_key IS DISTINCT FROM OLD.layer_key OR
      NEW.data_version IS DISTINCT FROM OLD.data_version)) THEN
    RAISE EXCEPTION 'versioned parent identity is immutable';
  END IF;
  bound_old := to_jsonb(OLD) - ARRAY['canonical_revision','loaded_at',
                                    'import_started_at','import_finished_at'];
  bound_new := to_jsonb(NEW) - ARRAY['canonical_revision','loaded_at',
                                    'import_started_at','import_finished_at'];
  IF NEW.canonical_revision <> OLD.canonical_revision THEN
    IF pg_trigger_depth() <> 2 OR NEW.canonical_revision <> OLD.canonical_revision + 1 OR
       bound_old IS DISTINCT FROM bound_new OR attested THEN
      RAISE EXCEPTION 'canonical revision is generated';
    END IF;
  ELSIF bound_old IS DISTINCT FROM bound_new THEN
    IF attested THEN RAISE EXCEPTION 'attested parent content is immutable'; END IF;
    NEW.canonical_revision := OLD.canonical_revision + 1;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER b02_parent BEFORE INSERT OR UPDATE OR DELETE ON environmental_layers
FOR EACH ROW EXECUTE FUNCTION b02_parent_guard();

CREATE FUNCTION b02_feature_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_id integer;
BEGIN
  IF TG_OP='UPDATE' AND NEW.environmental_layer_id <> OLD.environmental_layer_id THEN
    RAISE EXCEPTION 'canonical feature parent is immutable';
  END IF;
  parent_id := CASE WHEN TG_OP='DELETE' THEN OLD.environmental_layer_id
                    ELSE NEW.environmental_layer_id END;
  PERFORM 1 FROM environmental_layers WHERE id=parent_id FOR UPDATE;
  IF EXISTS(SELECT 1 FROM environmental_attestations WHERE environmental_layer_id=parent_id) THEN
    RAISE EXCEPTION 'attested feature content is immutable';
  END IF;
  UPDATE environmental_layers SET canonical_revision=canonical_revision+1 WHERE id=parent_id;
  RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER b02_feature BEFORE INSERT OR UPDATE OR DELETE ON environmental_features
FOR EACH ROW EXECUTE FUNCTION b02_feature_guard();

CREATE FUNCTION b02_attestation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual_revision bigint;
BEGIN
  IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'provenance identity is immutable'; END IF;
  SELECT canonical_revision INTO actual_revision FROM environmental_layers
    WHERE id=NEW.environmental_layer_id FOR UPDATE;
  IF actual_revision IS NULL OR actual_revision <> NEW.canonical_revision THEN
    RAISE EXCEPTION 'canonical revision changed';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER b02_attestation BEFORE INSERT OR UPDATE OR DELETE ON environmental_attestations
FOR EACH ROW EXECUTE FUNCTION b02_attestation_guard();

CREATE FUNCTION b02_link_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'provenance identity is immutable'; END IF;
  IF NOT EXISTS(SELECT 1 FROM environmental_attestations p,
                jsonb_array_elements(p.binding_json->'references') AS item
                WHERE p.id=NEW.attestation_id AND item->>'id'=NEW.reference_id::text
                AND item->>'role'=NEW.role AND (item->>'sequence')::integer=NEW.sequence) THEN
    RAISE EXCEPTION 'provenance link is outside bound exact set';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER b02_link BEFORE INSERT OR UPDATE OR DELETE ON environmental_attestation_references
FOR EACH ROW EXECUTE FUNCTION b02_link_guard();

CREATE FUNCTION b02_artifact_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE protected boolean;
BEGIN
  IF TG_TABLE_NAME='artifact_references' THEN
    IF TG_OP='INSERT' THEN
      PERFORM b02_lock_observation(NEW.source_key, NEW.run_id);
    ELSIF TG_OP='UPDATE' AND (NEW.source_key, NEW.run_id) IS DISTINCT FROM
                            (OLD.source_key, OLD.run_id) THEN
      IF (NEW.source_key, NEW.run_id) < (OLD.source_key, OLD.run_id) THEN
        PERFORM b02_lock_observation(NEW.source_key, NEW.run_id);
        PERFORM b02_lock_observation(OLD.source_key, OLD.run_id);
      ELSE
        PERFORM b02_lock_observation(OLD.source_key, OLD.run_id);
        PERFORM b02_lock_observation(NEW.source_key, NEW.run_id);
      END IF;
    ELSE
      PERFORM b02_lock_observation(OLD.source_key, OLD.run_id);
    END IF;
    IF TG_OP='INSERT' THEN
      IF EXISTS(SELECT 1 FROM environmental_attestations
                WHERE source_key=NEW.source_key AND run_id=NEW.run_id) THEN
        IF NOT EXISTS(SELECT 1 FROM artifact_references r
                      WHERE r.source_key=NEW.source_key AND r.run_id=NEW.run_id
                      AND r.artifact_type=NEW.artifact_type AND r.logical_key=NEW.logical_key
                      AND (r.blob_id,r.required,r.content_type,r.source_url,r.parent_reference_id)
                          IS NOT DISTINCT FROM
                          (NEW.blob_id,NEW.required,NEW.content_type,NEW.source_url,
                           NEW.parent_reference_id)) THEN
          RAISE EXCEPTION 'attested observation is immutable';
        END IF;
      END IF;
      RETURN NEW;
    END IF;
    protected := EXISTS(SELECT 1 FROM environmental_attestation_references
                         WHERE reference_id=OLD.id);
    IF TG_OP='UPDATE' AND EXISTS(SELECT 1 FROM environmental_attestations
                                WHERE source_key=NEW.source_key AND run_id=NEW.run_id) THEN
      protected := true;
    END IF;
  ELSIF TG_TABLE_NAME='artifact_blobs' THEN
    protected := EXISTS(SELECT 1 FROM environmental_attestation_references l
                        JOIN artifact_references r ON r.id=l.reference_id WHERE r.blob_id=OLD.id);
  ELSE
    protected := EXISTS(SELECT 1 FROM environmental_attestations
                        WHERE source_key=OLD.source_key AND run_id=OLD.run_id);
  END IF;
  IF protected THEN RAISE EXCEPTION 'attested artifact identity is immutable'; END IF;
  RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER b02_reference BEFORE INSERT OR UPDATE OR DELETE ON artifact_references
FOR EACH ROW EXECUTE FUNCTION b02_artifact_guard();
CREATE TRIGGER b02_blob BEFORE UPDATE OR DELETE ON artifact_blobs
FOR EACH ROW EXECUTE FUNCTION b02_artifact_guard();
CREATE TRIGGER b02_seal BEFORE UPDATE OR DELETE ON artifact_run_seals
FOR EACH ROW EXECUTE FUNCTION b02_artifact_guard();

CREATE FUNCTION b02_no_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'canonical provenance tables cannot be truncated'; END $$;
CREATE TRIGGER b02_parent_truncate BEFORE TRUNCATE ON environmental_layers
FOR EACH STATEMENT EXECUTE FUNCTION b02_no_truncate();
CREATE TRIGGER b02_feature_truncate BEFORE TRUNCATE ON environmental_features
FOR EACH STATEMENT EXECUTE FUNCTION b02_no_truncate();
CREATE TRIGGER b02_proof_truncate BEFORE TRUNCATE ON environmental_attestations
FOR EACH STATEMENT EXECUTE FUNCTION b02_no_truncate();
CREATE TRIGGER b02_link_truncate BEFORE TRUNCATE ON environmental_attestation_references
FOR EACH STATEMENT EXECUTE FUNCTION b02_no_truncate();
CREATE TRIGGER b02_reference_truncate BEFORE TRUNCATE ON artifact_references
FOR EACH STATEMENT EXECUTE FUNCTION b02_no_truncate();
CREATE TRIGGER b02_blob_truncate BEFORE TRUNCATE ON artifact_blobs
FOR EACH STATEMENT EXECUTE FUNCTION b02_no_truncate();
CREATE TRIGGER b02_seal_truncate BEFORE TRUNCATE ON artifact_run_seals
FOR EACH STATEMENT EXECUTE FUNCTION b02_no_truncate();
"""


def upgrade() -> None:
    op.add_column(
        "environmental_layers",
        sa.Column("canonical_revision", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_table(
        "environmental_attestations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "environmental_layer_id",
            sa.Integer(),
            sa.ForeignKey("environmental_layers.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("sink_id", sa.String(64), nullable=False),
        sa.Column("canonical_revision", sa.BigInteger(), nullable=False),
        sa.Column("proof_sha256", sa.String(64), nullable=False),
        sa.Column("binding_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["source_key", "run_id"],
            ["artifact_run_seals.source_key", "artifact_run_seals.run_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("canonical_revision >= 0", name="ck_environmental_proof_revision"),
        sa.CheckConstraint("proof_sha256 ~ '^[0-9a-f]{64}$'", name="ck_environmental_proof_digest"),
        sa.CheckConstraint(
            "jsonb_typeof(binding_json) = 'object' AND octet_length(binding_json::text) <= 1048576",
            name="ck_environmental_proof_binding_bound",
        ),
    )
    op.create_table(
        "environmental_attestation_references",
        sa.Column(
            "attestation_id",
            sa.Uuid(),
            sa.ForeignKey("environmental_attestations.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "reference_id",
            sa.Uuid(),
            sa.ForeignKey("artifact_references.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(48), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "attestation_id", "role", "sequence", name="uq_environmental_proof_role"
        ),
    )
    op.execute(PROVENANCE_GUARDS_SQL)


def downgrade() -> None:
    raise RuntimeError("Environmental provenance is retained; destructive downgrade is unsupported")
