#!/usr/bin/env python3
"""Regenerate the auto-managed section of `examples/README.md`.

For every subdirectory of `examples/`, extract a short description from
its `README.md` (H1 + first paragraph) and render a bullet list between
the marker comments:

    <!-- begin examples-index -->
    ...
    <!-- end examples-index -->

Idempotent: running the script twice produces the same output. Run
manually via `make examples-index` whenever a new example is added or
its README's title/lede changes; the "By use case" table at the top of
`examples/README.md` stays human-maintained.

Usage:
    python scripts/regen_examples_index.py
    make examples-index   # equivalent
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES_DIR = _REPO_ROOT / "examples"
_INDEX_FILE = _EXAMPLES_DIR / "README.md"
# Sphinx mirror (Phase 1 of 3, v0.7.8) — same content rendered for the
# docs site so users can browse examples without leaving the Sphinx nav.
_DOCS_MIRROR_FILE = _REPO_ROOT / "docs" / "source" / "examples.md"
_DOCS_MIRROR_LINK_PREFIX = "https://github.com/brandon-behring/runpod-deploy/tree/main/examples/"
_BEGIN_MARKER = "<!-- begin examples-index -->"
_END_MARKER = "<!-- end examples-index -->"

# H1 title plus the first non-empty paragraph after it.
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _short_description(readme_text: str) -> tuple[str | None, str | None]:
    """Return (title, lede) extracted from an example README's H1 + first paragraph.

    Returns ``(None, None)`` if no H1 is found.
    """
    match = _TITLE_RE.search(readme_text)
    if not match:
        return None, None
    title = match.group(1).strip()
    after_title = readme_text[match.end() :]
    # Walk paragraphs (blocks separated by blank lines). Skip blank
    # leading lines + skip blocks that look like other headers.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", after_title) if p.strip()]
    lede = next(
        (p for p in paragraphs if not p.lstrip().startswith(("#", "|", "-", "*", "```"))),
        None,
    )
    if lede is not None:
        # Collapse internal newlines + truncate over-long ledes.
        lede = " ".join(line.strip() for line in lede.splitlines())
        if len(lede) > 240:
            lede = lede[:237].rstrip() + "..."
    return title, lede


def _scan_examples() -> list[tuple[str, str | None, str | None]]:
    """Return a list of (dirname, title, lede) tuples sorted by dirname.

    `title` or `lede` may be None for directories that don't have a
    README.md or whose README lacks an H1 / lede paragraph.
    """
    out: list[tuple[str, str | None, str | None]] = []
    for child in sorted(_EXAMPLES_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        readme = child / "README.md"
        if readme.exists():
            title, lede = _short_description(readme.read_text())
        else:
            title, lede = None, None
        out.append((child.name, title, lede))
    return out


def _render(entries: list[tuple[str, str | None, str | None]], *, link_prefix: str = "") -> str:
    """Render the entries as a markdown bullet list.

    Parameters
    ----------
    entries
        Sequence of (dirname, title, lede) tuples.
    link_prefix
        Prefix prepended to each bullet's link target. Empty string yields
        repo-relative links (used by ``examples/README.md`` where the
        rendered page sits next to the example dirs). The
        ``docs/source/examples.md`` mirror passes a full GitHub URL prefix
        so links resolve from the published docs site.
    """
    if not entries:
        return "_(no example directories found under examples/)_"
    lines: list[str] = []
    for dirname, title, lede in entries:
        link_target = f"{link_prefix}{dirname}/"
        display_title = title or dirname
        if lede:
            lines.append(f"- **[`{dirname}/`]({link_target})** — _{display_title}_. {lede}")
        elif title:
            lines.append(f"- **[`{dirname}/`]({link_target})** — _{display_title}_.")
        else:
            lines.append(
                f"- **[`{dirname}/`]({link_target})** — (no README.md; "
                f"see the contained `*.yaml` for the config.)"
            )
    return "\n".join(lines)


def _splice(index_text: str, payload: str) -> str:
    """Replace content between marker comments in `index_text`."""
    begin = index_text.find(_BEGIN_MARKER)
    end = index_text.find(_END_MARKER)
    if begin == -1 or end == -1:
        raise RuntimeError(
            f"markers not found in {_INDEX_FILE}; expected\n"
            f"  {_BEGIN_MARKER}\n  {_END_MARKER}\n"
            "add them around the auto-managed section and re-run."
        )
    if begin > end:
        raise RuntimeError(f"begin marker after end marker in {_INDEX_FILE}; check ordering.")
    return index_text[: begin + len(_BEGIN_MARKER)] + "\n\n" + payload + "\n\n" + index_text[end:]


def _render_docs_mirror(entries: list[tuple[str, str | None, str | None]]) -> str:
    """Render the standalone Sphinx-mirror page (``docs/source/examples.md``).

    Unlike ``examples/README.md`` (which splices a bullet list between
    markers in a human-maintained host page), the docs mirror is a complete
    auto-generated page. Edit this template here, not in the rendered file.
    """
    payload = _render(entries, link_prefix=_DOCS_MIRROR_LINK_PREFIX)
    return (
        "# Examples\n"
        "\n"
        "Worked examples of runpod-deploy job configs. Each example lives in its\n"
        "own subdirectory of [`examples/`](https://github.com/brandon-behring/"
        "runpod-deploy/tree/main/examples). Links below open the example\n"
        "directory on GitHub.\n"
        "\n"
        "<!-- AUTO-GENERATED by scripts/regen_examples_index.py — do not edit by hand. -->\n"
        "\n"
        f"{payload}\n"
    )


def _write_if_changed(path: Path, new_text: str) -> bool:
    """Write ``new_text`` to ``path`` only if it differs from current contents.

    Returns True when the file was rewritten (i.e., content changed).
    """
    if path.exists() and path.read_text() == new_text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text)
    return True


def main() -> int:
    """Regenerate the index files. Returns 0 on success, non-zero on error.

    Writes to both ``examples/README.md`` (splice into markers) and
    ``docs/source/examples.md`` (standalone Sphinx page mirror).
    """
    if not _INDEX_FILE.exists():
        print(f"ERROR: {_INDEX_FILE} not found", file=sys.stderr)
        return 1
    entries = _scan_examples()

    # examples/README.md — splice into markers
    repo_payload = _render(entries)
    new_repo_text = _splice(_INDEX_FILE.read_text(), repo_payload)
    repo_changed = _write_if_changed(_INDEX_FILE, new_repo_text)
    if repo_changed:
        print(
            f"OK: regenerated {_INDEX_FILE.relative_to(_REPO_ROOT)} "
            f"with {len(entries)} example(s)"
        )
    else:
        print(f"OK: {_INDEX_FILE.relative_to(_REPO_ROOT)} is up to date")

    # docs/source/examples.md — standalone Sphinx mirror
    docs_text = _render_docs_mirror(entries)
    docs_changed = _write_if_changed(_DOCS_MIRROR_FILE, docs_text)
    if docs_changed:
        print(
            f"OK: regenerated {_DOCS_MIRROR_FILE.relative_to(_REPO_ROOT)} "
            f"with {len(entries)} example(s)"
        )
    else:
        print(f"OK: {_DOCS_MIRROR_FILE.relative_to(_REPO_ROOT)} is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
