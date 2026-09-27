"""Minimal migrated normal-role truncation diagnostic, separate from full proof."""

import json

from alembic.config import Config
from b02_provenance import NORMAL_ROLE, normal, refusal
from sqlalchemy import text

from alembic import command
from app.db import SessionLocal


def counts() -> list[int]:
    with SessionLocal() as session:
        return [
            session.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in (
                "environmental_layers",
                "environmental_features",
                "environmental_attestations",
                "environmental_attestation_references",
                "environmental_display_parts",
            )
        ]


command.upgrade(Config("alembic.ini"), "head")
with SessionLocal.begin() as session:
    session.execute(text(f"CREATE ROLE {NORMAL_ROLE} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"))
    session.execute(text(f"GRANT USAGE ON SCHEMA public TO {NORMAL_ROLE}"))
    session.execute(
        text(
            f"GRANT SELECT,INSERT,UPDATE,DELETE,TRUNCATE ON ALL TABLES "
            f"IN SCHEMA public TO {NORMAL_ROLE}"
        )
    )
    normal(session)
before = counts()
restrict = refusal("TRUNCATE environmental_features", {})
cascade = refusal("TRUNCATE environmental_features CASCADE", {})
assert restrict == "0A000" and cascade == "P0001", {"restrict": restrict, "cascade": cascade}
assert counts() == before
print(
    json.dumps(
        {
            "diagnostic_only": True,
            "migration": "20260927_0009",
            "normal_role": NORMAL_ROLE,
            "restrict_sqlstate": restrict,
            "cascade_sqlstate": cascade,
            "data_and_proof_counts_unchanged": True,
        }
    )
)
