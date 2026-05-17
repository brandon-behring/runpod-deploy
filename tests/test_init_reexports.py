"""Verify the top-level ``runpod_deploy`` package re-exports the public API.

Sanity test for the curated ``__all__`` in ``runpod_deploy/__init__.py``:
every name in ``__all__`` must be importable from the package, and
every name documented in the module docstring (the 4-use-case API) must
actually be present.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_init_all_entries_are_importable() -> None:
    """Every name in ``__all__`` must be importable via the top-level package."""
    import runpod_deploy

    for name in runpod_deploy.__all__:
        assert hasattr(
            runpod_deploy, name
        ), f"runpod_deploy.__all__ lists {name!r} but it is not importable"


@pytest.mark.unit
def test_forensics_functions_are_top_level() -> None:
    """The 3 forensics functions are part of the documented Python API surface."""
    from runpod_deploy import load_events, load_manifest, walk_run_dirs
    from runpod_deploy.forensics import (
        load_events as fe_load_events,
    )
    from runpod_deploy.forensics import (
        load_manifest as fe_load_manifest,
    )
    from runpod_deploy.forensics import (
        walk_run_dirs as fe_walk_run_dirs,
    )

    assert load_events is fe_load_events
    assert load_manifest is fe_load_manifest
    assert walk_run_dirs is fe_walk_run_dirs


@pytest.mark.unit
def test_init_all_groups_alphabetized() -> None:
    """``__all__`` groups constants, classes, and functions; each group is alphabetical.

    The convention (visible in the file): all-caps constants first
    (alphabetical), then PascalCase classes (alphabetical), then
    snake_case callables (alphabetical). This test enforces only the
    *within-group* alphabetization, not the across-group order.
    """
    import runpod_deploy

    constants = [n for n in runpod_deploy.__all__ if n.isupper()]
    classes = [n for n in runpod_deploy.__all__ if n[0].isupper() and not n.isupper()]
    callables = [n for n in runpod_deploy.__all__ if n[0].islower()]
    assert constants == sorted(constants), f"constants not alphabetical: {constants}"
    assert classes == sorted(classes), f"classes not alphabetical: {classes}"
    assert callables == sorted(callables), f"callables not alphabetical: {callables}"
