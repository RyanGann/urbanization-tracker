import pytest

from app.config import get_settings
from app.seed_store import reset_seed_state


@pytest.fixture(autouse=True)
def explicit_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing fixture-dependent tests opt into demo data explicitly."""
    monkeypatch.setenv("DATA_MODE", "demo")
    get_settings.cache_clear()
    reset_seed_state()
    yield
    get_settings.cache_clear()
