from pathlib import Path


def test_render_blueprint_defines_ingestion_cron_jobs() -> None:
    content = (_repo_root() / "render.yaml").read_text(encoding="utf-8")

    huntsville = _service_block(content, "urbanization-tracker-huntsville-ingestion")
    assert (
        'dockerCommand: sh -c "alembic upgrade head && python -m app.ingestion.cli '
        'ingest-huntsville --data-dir /app/data"'
    ) in huntsville
    assert _env_var_value(huntsville, "PROCESSED_STORE_BACKEND") == "postgres"
    assert _env_var_value(huntsville, "PHASE3_STORE_BACKEND") == "postgres"
    assert _env_var_value(huntsville, "HOSTED_INGESTION_ENABLED") == "false"

    agenda = _service_block(content, "urbanization-tracker-agenda-ingestion")
    assert (
        'dockerCommand: sh -c "alembic upgrade head && python -m app.ingestion.cli '
        'ingest-huntsville-agendas --data-dir /app/data --document-limit 3"'
    ) in agenda
    assert _env_var_value(agenda, "PROCESSED_STORE_BACKEND") == "postgres"
    assert _env_var_value(agenda, "PHASE3_STORE_BACKEND") == "postgres"
    assert _env_var_value(agenda, "HOSTED_INGESTION_ENABLED") == "false"

    madison_county = _service_block(content, "urbanization-tracker-madison-county-ingestion")
    assert (
        'dockerCommand: sh -c "alembic upgrade head && python -m app.ingestion.cli '
        'ingest-madison-county --data-dir /app/data"'
    ) in madison_county
    assert _env_var_value(madison_county, "PROCESSED_STORE_BACKEND") == "postgres"
    assert _env_var_value(madison_county, "PHASE3_STORE_BACKEND") == "postgres"
    assert _env_var_value(madison_county, "HOSTED_INGESTION_ENABLED") == "false"

    alert_delivery = _service_block(content, "urbanization-tracker-alert-delivery")
    assert (
        'dockerCommand: sh -c "alembic upgrade head && python -m app.ingestion.cli send-alerts"'
    ) in alert_delivery
    assert _env_var_value(alert_delivery, "PROCESSED_STORE_BACKEND") == "postgres"
    assert _env_var_value(alert_delivery, "PHASE3_STORE_BACKEND") == "postgres"


def test_render_blueprint_uses_private_alpha_defaults() -> None:
    content = (_repo_root() / "render.yaml").read_text(encoding="utf-8")

    api = _service_block(content, "urbanization-tracker-api")
    assert "    region: ohio\n" in api
    assert "    plan: starter\n" in api
    assert "    autoDeployTrigger: checksPass\n" in api
    assert _env_var_value(api, "CORS_ORIGINS") == (
        "https://urbanization-tracker-web.onrender.com"
    )
    assert _env_var_value(api, "PUBLIC_BASE_URL") == (
        "https://urbanization-tracker-web.onrender.com"
    )

    web = _service_block(content, "urbanization-tracker-web")
    assert "    plan: free\n" in web
    assert _env_var_value(web, "VITE_API_BASE_URL") == (
        "https://urbanization-tracker-api.onrender.com"
    )

    database = content[content.index("databases:\n") :]
    assert "    region: ohio\n" in database
    assert "    plan: basic-1gb\n" in database
    assert "    ipAllowList: []\n" in database


def _service_block(content: str, name: str) -> str:
    marker = f"    name: {name}\n"
    name_index = content.find(marker)
    if name_index == -1:
        raise AssertionError(f"Could not find Render service named {name}.")

    block_start = content.rfind("\n  - type:", 0, name_index)
    if block_start == -1:
        raise AssertionError(f"Could not find the start of the {name} Render service block.")
    block_start += 1

    next_block_start = content.find("\n  - type:", name_index)
    if next_block_start == -1:
        next_block_start = content.find("\ndatabases:", name_index)
    if next_block_start == -1:
        next_block_start = len(content)

    return content[block_start:next_block_start]


def _env_var_value(service_block: str, key: str) -> str:
    marker = f"      - key: {key}\n"
    key_index = service_block.find(marker)
    if key_index == -1:
        raise AssertionError(f"Could not find env var {key} in Render service block.")

    value_prefix = "        value: "
    value_start = service_block.find(value_prefix, key_index + len(marker))
    if value_start == -1:
        raise AssertionError(f"Could not find a value for env var {key}.")
    next_key_start = service_block.find("      - key:", key_index + len(marker))
    if next_key_start != -1 and next_key_start < value_start:
        raise AssertionError(f"Could not find a value before the next env var for {key}.")

    value_start += len(value_prefix)
    value_end = service_block.find("\n", value_start)
    return service_block[value_start:value_end].strip('"')


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "render.yaml").exists():
            return parent
    raise AssertionError("Could not locate repository root.")
