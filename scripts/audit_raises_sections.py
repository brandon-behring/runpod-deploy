#!/usr/bin/env python3
"""Audit docstring `Raises:` sections against actual raise sites.

For every function (top-level or method) in `src/runpod_deploy/`:

- Parse the docstring. If it has a ``Raises:`` section (or
  ``:raises X:`` rst-style markers), extract the listed exception
  types.
- Walk the function body's AST for ``raise <Type>(...)`` statements,
  collecting the exception types that appear.
- Compare the two sets. Report:
    * Documented but not raised (stale doc — ``Raises:`` says
      ``ValueError`` but no ``raise ValueError`` appears).
    * Raised but not documented (undeclared — body raises
      ``KeyError`` but the docstring doesn't say so).

Exit code: 0 if every function is consistent or has no
``Raises:`` section + no body raises; 1 if any mismatch is found.

Usage:
    python scripts/audit_raises_sections.py [SRC_PATH]

Defaults to ``src/runpod_deploy``. Pass a different directory or
file to audit a specific subset.

Ported from `eval-toolkit/scripts/audit_raises_sections.py` (adapted
for runpod-deploy's docstring conventions per CLAUDE.md §11).

Limitations:
- ``raise`` (no expression — re-raise) is ignored; the type isn't
  syntactically visible.
- ``raise some_var`` where ``some_var`` is computed elsewhere is
  ignored.
- Exception types from inside ``except`` clauses are NOT excluded;
  if a function catches ``X`` and re-raises ``X``, the audit
  considers ``X`` raised. This matches the docstring's perspective.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_RAISES_HEADER_RE = re.compile(r"^\s*Raises:\s*$", re.MULTILINE)
_RST_RAISES_RE = re.compile(r":raises\s+([A-Za-z][\w.]*)\s*:")


def _documented_exceptions(docstring: str | None) -> set[str]:
    """Extract exception names from a NumPy-style or rst-style docstring."""
    if not docstring:
        return set()
    names: set[str] = set()
    # NumPy-style: `Raises:\n    ValueError:\n        ...`
    if _RAISES_HEADER_RE.search(docstring):
        # Take everything after the header to the next blank line
        # (or end of docstring) and pull the entries from it.
        post = docstring.split("Raises:", 1)[1]
        # Stop at the next NumPy-style section header (e.g., "Returns:").
        for line in post.splitlines():
            if re.match(r"^\s*[A-Z][a-z]+:\s*$", line) and "Raises:" not in line:
                break
            match = re.match(r"^\s+([A-Za-z][\w.]*)\s*:", line)
            if match:
                names.add(match.group(1))
    # rst-style: `:raises ValueError:`
    for match in _RST_RAISES_RE.finditer(docstring):
        names.add(match.group(1))
    return names


def _raised_exceptions(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Walk a function body's AST; collect raise-site exception type names."""
    raised: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Raise) and node.exc is not None:
            exc = node.exc
            # `raise ValueError(...)` → Call(func=Name(...))
            if isinstance(exc, ast.Call):
                func_node = exc.func
                if isinstance(func_node, ast.Name):
                    raised.add(func_node.id)
                elif isinstance(func_node, ast.Attribute):
                    raised.add(func_node.attr)
            # `raise ValueError` (no call) → Name(...)
            elif isinstance(exc, ast.Name):
                raised.add(exc.id)
            elif isinstance(exc, ast.Attribute):
                raised.add(exc.attr)
            # `raise X from Y` → covered by node.exc being the X side
            # `raise some_expr` → skipped (not syntactically a name)
    return raised


def _audit_file(path: Path) -> list[str]:
    """Return a list of human-readable findings for one file (empty if clean)."""
    findings: list[str] = []
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError as exc:
        return [f"{path}: failed to parse: {exc}"]
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        documented = _documented_exceptions(ast.get_docstring(node))
        raised = _raised_exceptions(node)
        # Filter "obviously fine" cases: function with no docs and no raises.
        if not documented and not raised:
            continue
        stale = documented - raised
        undeclared = raised - documented
        # Only report if there's a Raises: section AND the lists disagree.
        # A function with no Raises: section but body raises is fine
        # (docstring author chose not to document — many internal helpers
        # don't list raises). We only enforce consistency when authors
        # opted INTO documenting.
        if not documented:
            continue
        if stale:
            findings.append(
                f"{path}:{node.lineno} {node.name}(): "
                f"docstring lists {sorted(stale)} but body never raises them"
            )
        if undeclared:
            findings.append(
                f"{path}:{node.lineno} {node.name}(): "
                f"body raises {sorted(undeclared)} but docstring's Raises: omits them"
            )
    return findings


def main(argv: list[str]) -> int:
    """Walk ``src_root`` for ``*.py`` files and audit each. Return exit code."""
    if len(argv) > 1:
        src_root = Path(argv[1])
    else:
        src_root = Path(__file__).resolve().parents[1] / "src" / "runpod_deploy"
    if not src_root.exists():
        print(f"ERROR: src path not found: {src_root}", file=sys.stderr)
        return 2

    py_files = [src_root] if src_root.is_file() else sorted(src_root.rglob("*.py"))

    all_findings: list[str] = []
    for path in py_files:
        all_findings.extend(_audit_file(path))

    if not all_findings:
        n = len(py_files)
        print(
            f"OK: audited {n} file{'' if n == 1 else 's'} under {src_root}; "
            f"all Raises: docstring sections match actual raise sites."
        )
        return 0

    print("Raises:-section mismatches:")
    for finding in all_findings:
        print(f"  {finding}")
    print(
        f"\nFound {len(all_findings)} mismatch{'' if len(all_findings) == 1 else 'es'}.\n"
        "Either update the docstring's Raises: section, or update the body, "
        "to bring them into sync.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
