"""Validate YAML code-block examples in `docs/` against the live schema.

Extracts every ```yaml fenced block from every Markdown file under
`docs/` (recipes + top-level reference docs). Each block that looks
like a *full* runpod-deploy job config (has `schema_version:` at the
top level) is fed to `load_job_spec` via a tempfile. Anything that
parses cleanly is considered current; anything that fails surfaces
recipe-doc drift from the actual schema.

Snippet blocks (no `schema_version:` — e.g., just a `staging:` or
`run:` excerpt) are skipped: they're partial and need surrounding
context to validate.

This catches the failure mode where a recipe doc gets out of sync
with the live schema: a field renamed, a required key added, or a
deprecated key removed, and the example silently rots.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runpod_deploy.config import load_job_spec

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS_ROOT = _REPO_ROOT / "docs"

# Match fenced YAML blocks anywhere in markdown:
#   ```yaml
#   ...
#   ```
_YAML_BLOCK_RE = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)


def _extract_yaml_blocks(md_path: Path) -> list[tuple[Path, int, str]]:
    """Return (path, block_index_within_file, block_text) tuples."""
    text = md_path.read_text()
    return [
        (md_path, idx, match.group(1)) for idx, match in enumerate(_YAML_BLOCK_RE.finditer(text))
    ]


def _looks_like_full_job_config(block_text: str) -> bool:
    """Heuristic: a `schema_version:` at column 0 indicates a top-level YAML."""
    return any(line.startswith("schema_version:") for line in block_text.splitlines())


def _collect_all_blocks() -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for md_path in sorted(_DOCS_ROOT.rglob("*.md")):
        out.extend(_extract_yaml_blocks(md_path))
    return out


@pytest.mark.unit
def test_docs_have_at_least_one_full_config_yaml_block() -> None:
    """Sanity: at least one doc-embedded YAML is a full config we can validate.

    If this fails, the doc surface has no full-config examples to
    lint — which means PR-P's purpose evaporated. A canary against
    accidental wholesale doc refactor.
    """
    blocks = _collect_all_blocks()
    full = [b for b in blocks if _looks_like_full_job_config(b[2])]
    assert full, (
        "expected at least one full job-config YAML block under docs/ "
        "(matched by `schema_version:` at column 0); found none"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "doc_path,block_index,block_text",
    _collect_all_blocks(),
    ids=lambda x: x.name if isinstance(x, Path) else str(x),
)
def test_doc_yaml_block_full_config_parses(
    doc_path: Path,
    block_index: int,
    block_text: str,
    tmp_path: Path,
) -> None:
    """Every full-config YAML embedded in `docs/` parses cleanly via `load_job_spec`.

    Skips snippet blocks (no `schema_version:`) — they can't be
    validated without surrounding context.
    """
    if not _looks_like_full_job_config(block_text):
        pytest.skip(
            f"{doc_path.relative_to(_REPO_ROOT)} block #{block_index}: snippet, no schema_version:"
        )

    # Strip leading comment lines that include placeholder paths the
    # parser would misinterpret. Comments are valid YAML; this is
    # defensive.
    config_path = tmp_path / f"{doc_path.stem}_{block_index}.yaml"
    config_path.write_text(block_text)

    try:
        load_job_spec(config_path)
    except Exception as exc:
        # Mirror the source-block context in the failure message so a
        # consumer reading the test output can find the offending doc + block.
        rel = doc_path.relative_to(_REPO_ROOT)
        raise AssertionError(
            f"YAML block #{block_index} in {rel} fails `load_job_spec`: {exc}\n\n"
            f"Block content:\n{block_text}"
        ) from exc
