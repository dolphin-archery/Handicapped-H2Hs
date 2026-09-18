"""Entry point for the Handicapped H2H scoring tool.

Run with `uv run main.py` to start a local Flask server for running fair,
handicap-based archer-vs-archer matches over a single 60-arrow round.
"""

from h2h.app import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
