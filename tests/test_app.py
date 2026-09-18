"""Tests for the Flask web layer (h2h.app)."""

from h2h.app import create_app


def test_index_returns_200():
    """GET / should return HTTP 200."""
    client = create_app().test_client()
    response = client.get("/")
    assert response.status_code == 200


def test_stats_importable_without_flask_running():
    """The stats module must import cleanly with no Flask app created/running."""
    import h2h.stats  # noqa: F401
