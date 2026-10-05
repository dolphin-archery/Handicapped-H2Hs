"""Generate THIRD_PARTY_NOTICES.md from the installed dependencies.

Lists the licence and copyright texts of the third-party code the web app ships to browsers:

* the production npm packages in ``web/package-lock.json`` (read from ``web/node_modules``), and
* the Python packages the browser installs at run time (read from the active Python environment).

Run from the repository root after ``npm ci`` (in ``web/``) and ``uv sync``::

    uv run python scripts/generate_third_party_notices.py

Use ``--check`` to fail (exit code 1) if the committed file is out of date.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "THIRD_PARTY_NOTICES.md"
LOCKFILE = ROOT / "web" / "package-lock.json"

# Python distributions the browser installs at run time (web/pyodide-requirements.txt plus fpdf2's
# dependencies). numpy itself comes from Pyodide's own build. Keep in step with that file.
BROWSER_PYTHON_PACKAGES = ["archeryutils", "numpy", "fpdf2", "pillow", "fonttools", "defusedxml"]

_LICENCE_FILE = re.compile(r"^(licen[cs]e|copying|notice)([.\-_].*)?$", re.IGNORECASE)


def _read_text(path: Path) -> str:
    """Read a text file as UTF-8 (undecodable bytes replaced), with Unix newlines and no trailing space.

    Parameters
    ----------
    path : pathlib.Path
        The file to read.

    Returns
    -------
    str
        The file's text.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _npm_packages() -> list[dict]:
    """Collect the production npm packages that can end up in the browser bundle.

    Reads ``web/package-lock.json``, skipping dev-only packages and ``@types/*`` (type declarations
    that are not shipped).

    Returns
    -------
    list[dict]
        One dict per package, sorted by name, with keys ``name``, ``version``, ``licence``,
        ``url`` (repository URL or empty) and ``texts`` (list of ``(file name, text)``).
    """
    packages = json.loads(LOCKFILE.read_text(encoding="utf-8"))["packages"]
    result = []
    for path, info in packages.items():
        if not path or info.get("dev"):
            continue
        name = path.split("node_modules/", 1)[-1]
        if name.startswith("@types/"):
            continue
        folder = ROOT / "web" / path
        manifest = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        repository = manifest.get("repository", "")
        url = repository.get("url", "") if isinstance(repository, dict) else repository
        texts = sorted(
            (f.name, _read_text(f))
            for f in folder.iterdir()
            if f.is_file() and _LICENCE_FILE.match(f.name)
        )
        result.append(
            {
                "name": name,
                "version": info.get("version", manifest.get("version", "")),
                "licence": str(info.get("license", manifest.get("license", "UNKNOWN"))),
                "url": url,
                "texts": texts,
            }
        )
    return sorted(result, key=lambda p: p["name"])


def _python_packages() -> list[dict]:
    """Collect the Python packages the browser installs at run time.

    Reads each distribution's metadata and licence files from the active Python environment.

    Returns
    -------
    list[dict]
        One dict per package in ``BROWSER_PYTHON_PACKAGES`` order, with the same keys as
        ``_npm_packages``.
    """
    result = []
    for name in BROWSER_PYTHON_PACKAGES:
        dist = md.distribution(name)
        meta = dist.metadata
        expression = meta.get("License-Expression") or ""
        legacy = (meta.get("License") or "").strip()
        if not expression and legacy and "\n" not in legacy and len(legacy) <= 60:
            expression = legacy  # a short one-line licence name, not a pasted licence text
        if not expression:
            classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License")]
            expression = "; ".join(c.split("::")[-1].strip() for c in classifiers) or "see licence text"
        url = meta.get("Home-page") or next(
            (u.split(",", 1)[1].strip() for u in meta.get_all("Project-URL") or [] if "," in u), ""
        )
        texts = sorted(
            (str(f), _read_text(Path(dist.locate_file(f))))
            for f in dist.files or []
            if _LICENCE_FILE.match(Path(str(f)).name)
        )
        result.append(
            {"name": name, "version": dist.version, "licence": expression, "url": url, "texts": texts}
        )
    return result


def _section(package: dict) -> str:
    """Render one package's section of the notices file.

    Parameters
    ----------
    package : dict
        A package dict from ``_npm_packages`` or ``_python_packages``.

    Returns
    -------
    str
        Markdown: heading, licence line, then each licence text in a fenced block (or a note when
        the package ships no licence file).
    """
    lines = [f"### {package['name']} {package['version']}", "", f"Licence: {package['licence']}"]
    if package["url"]:
        lines.append(f"Source: {package['url']}")
    if not package["texts"]:
        lines += [
            "",
            "This package ships no licence file; the licence above is the one it declares in its "
            "package metadata. See the source link for the licence text and copyright holders.",
        ]
    for file_name, text in package["texts"]:
        lines += ["", f"`{file_name}`", "", "~~~text", text, "~~~"]
    return "\n".join(lines)


def build_notices() -> str:
    """Build the full text of THIRD_PARTY_NOTICES.md.

    Returns
    -------
    str
        The Markdown document, ending with a newline.
    """
    npm = _npm_packages()
    py = _python_packages()
    parts = [
        "# Third-party notices",
        "",
        "Handicapped H2Hs is licensed under the GNU AGPL-3.0-only (see `LICENSE` and `NOTICE.md`). "
        "It uses the third-party software below, which is covered by its own licences, reproduced "
        "here to meet their notice requirements. Nothing in this file changes those licences.",
        "",
        "This file is generated by `scripts/generate_third_party_notices.py`; do not edit it by hand. "
        "The JavaScript packages are the production dependencies of the web app (some may be used "
        "only at build time or in tests of the bundle and not appear in the shipped files). The "
        "Python packages are those the browser installs at run time; `numpy` and the Python "
        "runtime itself come from the Pyodide project (https://pyodide.org), which is "
        "MPL-2.0-licensed, and are loaded unmodified from its distribution. The Python packages are "
        "listed with the versions in this repository's environment; the browser may receive a "
        "different release.",
        "",
        "`fpdf2` is licensed under the LGPL-3.0. It is used unmodified as a separate library "
        "installed from PyPI when the app runs, and is not copied into this repository.",
        "",
        "## Summary",
        "",
        "| Package | Version | Licence |",
        "|---|---|---|",
    ]
    parts += [f"| {p['name']} (npm) | {p['version']} | {p['licence']} |" for p in npm]
    parts += [f"| {p['name']} (Python) | {p['version']} | {p['licence']} |" for p in py]
    parts += ["", "## JavaScript packages (npm)", ""]
    parts += [_section(p) + "\n" for p in npm]
    parts += ["## Python packages (installed in the browser)", ""]
    parts += [_section(p) + "\n" for p in py]
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    """Write (or with ``--check`` verify) THIRD_PARTY_NOTICES.md.

    Returns
    -------
    int
        0 on success; 1 if ``--check`` finds the committed file out of date.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args()
    text = build_notices()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUTPUT.exists() else ""
        if current != text:
            print(f"{OUTPUT.name} is out of date; run this script to regenerate it.", file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
