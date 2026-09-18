"""Flask web layer for the Handicapped H2H scoring tool.

This module wires up routes only; all statistics live in `h2h.stats` and are
independently importable/testable without Flask running (see AISpec.md
section 4).
"""

from flask import Flask


def create_app() -> Flask:
    """Build and return the Flask application.

    Returns
    -------
    flask.Flask
        Configured Flask app, not yet run.
    """
    app = Flask(__name__)

    @app.get("/")
    def index() -> str:
        """Placeholder landing page; replaced by the setup page in a later task."""
        return "Handicapped H2H"

    return app
