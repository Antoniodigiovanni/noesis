import pytest

from noesis.application.service import Noesis


@pytest.fixture
def core(tmp_path):
    return Noesis(tmp_path / "noesis.db")
