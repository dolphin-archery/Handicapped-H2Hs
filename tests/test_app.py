"""Generic infra-level tests for the Flask web layer (h2h.app).

Route-specific behaviour for the rotation-based event flow lives in
tests/test_event_routes.py, tests/test_handicap_calculator.py, etc. -- this
file is deliberately just the app-level smoke tests.
"""

from h2h.app import create_app
from h2h.state import SessionState


def make_client():
    """A Flask test client with its own isolated SessionState."""
    return create_app(state=SessionState()).test_client()


def test_index_redirects_to_stage1():
    """GET / should redirect to the Stage 1 event setup page."""
    client = make_client()
    response = client.get("/", follow_redirects=True)
    assert response.status_code == 200
    assert b"Event setup - Stage 1" in response.data


def test_stats_importable_without_flask_running():
    """The stats module must import cleanly with no Flask app created/running."""
    import h2h.stats  # noqa: F401
