import pytest

from noesis.application.service import Noesis


@pytest.fixture
def core(tmp_path):
    return Noesis(tmp_path / "noesis.db")


@pytest.fixture(autouse=True)
def restricted_sandbox_selector(monkeypatch):
    """Opt-in workaround: this runner denies socketpairs used to wake event loops."""
    import os
    if os.environ.get('NOESIS_SANDBOX_TEST') == '1':
        import selectors
        original = selectors.EpollSelector.select
        def poll(self, timeout=None):
            return original(self, .01 if timeout is None else min(timeout, .01))
        monkeypatch.setattr(selectors.EpollSelector, 'select', poll)
