import pytest


@pytest.fixture(autouse=True)
def _sin_scrape_real(monkeypatch):
    """Ningun test dispara el scrape real; los que prueban ausencias re-mockean."""
    import analyzer
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: None, raising=False)
