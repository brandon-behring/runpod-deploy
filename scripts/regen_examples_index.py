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


def _render(entries: list[tuple[str, str | None, str | None]]) -> str:
    """Render the entries as a markdown bullet list."""
    if not entries:
        return "_(no example directories found under examples/)_"
    lines: list[str] = []
    for dirname, title, lede in entries:
        link_target = f"{dirname}/"
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


def main() -> int:
    """Regenerate the index. Returns 0 on success, non-zero on error."""
    if not _INDEX_FILE.exists():
        print(f"ERROR: {_INDEX_FILE} not found", file=sys.stderr)
        return 1
    entries = _scan_examples()
    payload = _render(entries)
    new_text = _splice(_INDEX_FILE.read_text(), payload)
    if new_text == _INDEX_FILE.read_text():
        print(f"OK: {_INDEX_FILE.relative_to(_REPO_ROOT)} is up to date")
        return 0
    _INDEX_FILE.write_text(new_text)
    print(
        f"OK: regenerated {_INDEX_FILE.relative_to(_REPO_ROOT)} " f"with {len(entries)} example(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
