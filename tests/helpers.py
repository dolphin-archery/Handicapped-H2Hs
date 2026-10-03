"""Shared helpers for tests driving the overview / per-match / advance page flow."""

import re

from h2h.models import METRE, YARD, TargetSetup

# Named target setups reused across tests.
PORTSMOUTH = TargetSetup(distance=20, unit=YARD, face_cm=60)  # indoor
WA18 = TargetSetup(distance=18, unit=METRE, face_cm=40)  # indoor
OUTDOOR_70M = TargetSetup(distance=70, unit=METRE, face_cm=122)  # outdoor

_MATCH_LINK = re.compile(r'href="/event/match/(\d+)"')
_SCORE_INPUT = re.compile(r'name="score_(\d+)"')
_PASS_HEADING = re.compile(r"Pass (\d+) of (\d+)")


def save_match(client, match_index, scores):
    """POST one match's scores to its page.

    Parameters
    ----------
    client : flask.testing.FlaskClient
        Test client with an event already set up.
    match_index : int
        Position of the match in the current pass.
    scores : dict[int, int | str]
        Mapping of archer index to the score text/number to submit.

    Returns
    -------
    werkzeug.test.TestResponse
        The (non-redirect-followed) response.
    """
    return client.post(
        f"/event/match/{match_index}",
        data={f"score_{archer}": str(score) for archer, score in scores.items()},
    )


def pass_position(client):
    """The (current pass, total passes) shown on the overview page.

    Parameters
    ----------
    client : flask.testing.FlaskClient
        Test client with an event already set up.

    Returns
    -------
    tuple[int, int]
        1-based current pass number and the total number of passes.
    """
    page = client.get("/event/rotation").data.decode()
    current, total = _PASS_HEADING.search(page).groups()
    return int(current), int(total)


def score_current_pass(client, score_fn=lambda archer: 60):
    """Score every match of the current pass through the match pages.

    The matches (and the archers in each) are discovered from the rendered
    overview and match pages rather than assumed, so this stays correct
    whatever order the scheduler produces them in.

    Parameters
    ----------
    client : flask.testing.FlaskClient
        Test client with an event already set up.
    score_fn : callable(int) -> int, default=lambda archer: 60
        Score to enter for a given archer index.

    Returns
    -------
    list[list[int]]
        For each match in the pass, the archer indices that were scored.
    """
    overview = client.get("/event/rotation").data.decode()
    scored = []
    for match_index in sorted({int(m) for m in _MATCH_LINK.findall(overview)}):
        page = client.get(f"/event/match/{match_index}").data.decode()
        archers = sorted({int(a) for a in _SCORE_INPUT.findall(page)})
        save_match(client, match_index, {a: score_fn(a) for a in archers})
        scored.append(archers)
    return scored


def play_whole_event(client, score_fn=lambda archer: 60):
    """Score every pass of the event, advancing between passes.

    Parameters
    ----------
    client : flask.testing.FlaskClient
        Test client with an event already set up.
    score_fn : callable(int) -> int, default=lambda archer: 60
        Score to enter for a given archer index.

    Returns
    -------
    list[list[list[int]]]
        For each pass, the archer indices scored in each of its matches.
    """
    _, total = pass_position(client)
    passes = []
    for pass_number in range(1, total + 1):
        passes.append(score_current_pass(client, score_fn))
        if pass_number < total:
            client.post("/event/advance")
    return passes


def record_whole_rotation(event, score=60):
    """Record every match of an Event's current rotation directly on the model.

    Parameters
    ----------
    event : h2h.models.Event
        Event to record scores on.
    score : int, default=60
        Score given to every archer in the rotation.
    """
    for match in event.matches(event.current_rotation_index):
        event.record_match({p: score for p in match if p is not None})


def _text(fragment):
    """Plain text of an HTML fragment, with tags removed and whitespace collapsed."""
    return " ".join(re.sub(r"<[^>]+>", " ", fragment).split())


def overview_table(html):
    """The overview page's matches table as plain text.

    Parameters
    ----------
    html : str
        Rendered /event/rotation page.

    Returns
    -------
    tuple[list[str], list[list[str]]]
        The column headings, and one list of cell texts per body row.
    """
    table = html[html.index("<table>") : html.index("</table>")]
    headings = [_text(h) for h in re.findall(r"<th>(.*?)</th>", table, re.S)]
    rows = [
        [_text(cell) for cell in re.findall(r"<td>(.*?)</td>", row, re.S)]
        for row in re.findall(r"<tr>(.*?)</tr>", table, re.S)
        if "<td>" in row
    ]
    return headings, rows
