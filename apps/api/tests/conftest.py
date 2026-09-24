import pytest

from app.public_quota import _local_counts


@pytest.fixture(autouse=True)
def reset_local_public_quota() -> None:
    """Each in-process test owns a fresh demo quota; production never calls this."""
    _local_counts.clear()
