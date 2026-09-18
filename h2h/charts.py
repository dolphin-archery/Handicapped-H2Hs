"""Advanced-mode distribution charts for the Handicapped H2H scoring tool.

Renders each archer's handicap-implied n_pass score distribution as a static
PNG, with their actual score for a given pass marked -- used only in
advanced mode (see AISpec.md section 5.4). Kept independent of Flask so it
can be tested in isolation.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from .models import Match


def render_pass_distributions(match: Match, pass_index: int) -> bytes:
    """Render both archers' score distributions for a scored pass as a PNG.

    Parameters
    ----------
    match : h2h.models.Match
        The match containing the pass to render.
    pass_index : int
        Index of the pass to render; must already be scored.

    Returns
    -------
    bytes
        PNG image data.

    Raises
    ------
    ValueError
        If the requested pass has not been scored yet.
    """
    p = match.passes[pass_index]
    if not p.is_scored:
        msg = f"Pass {pass_index} has not been scored yet."
        raise ValueError(msg)

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.5))
    per_archer = (
        (axes[0], match.archer_a, "a", p.score_a, p.percentile_a),
        (axes[1], match.archer_b, "b", p.score_b, p.percentile_b),
    )
    for ax, archer, key, score, pct in per_archer:
        dist = match.distribution_for(key)
        scores = sorted(dist)
        probs = [dist[s] for s in scores]
        ax.bar(scores, probs, width=0.8, color="#4c72b0")
        ax.axvline(score, color="#c44e52", linestyle="--", label=f"shot: {score:g}")
        ax.set_title(f"{archer.name} (h{archer.handicap}) - {pct * 100:.1f}th pctile")
        ax.set_xlabel("Pass score")
        ax.set_ylabel("Probability")
        ax.legend()

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
