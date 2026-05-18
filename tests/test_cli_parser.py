"""Regression tests for the CLI parser shape.

Pin the runpod-deploy CLI subcommand surface so that accidental removal
or rename of a subcommand fails CI at the smallest possible scope.
"""

from __future__ import annotations

import argparse

import pytest

from runpod_deploy.cli import _HANDLERS, _build_parser

_EXPECTED_SUBCOMMANDS = frozenset(
    {
        "validate",
        "run",
        "cleanup",
        "ls-stale",
        "logs",
        "gpu-list",
        "gpu-inventory",
        "gpu-prices",
        "estimate",
        "ls-runs",
        "compare-runs",
        "events",
        "events-query",
        "capture-env",
        "manifest-summary",
    }
)


@pytest.mark.unit
def test_build_parser_returns_argument_parser() -> None:
    """_build_parser is pure and returns a fully-configured ArgumentParser."""
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


@pytest.mark.unit
def test_build_parser_registers_all_expected_subcommands() -> None:
    """All subcommands in _HANDLERS must be registered on the parser.

    Catches accidental removal of a subcommand from _build_parser without
    a matching removal from _HANDLERS (or vice versa).
    """
    parser = _build_parser()
    subparser_action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    registered = frozenset(subparser_action.choices)
    assert registered == _EXPECTED_SUBCOMMANDS


@pytest.mark.unit
def test_handlers_keys_match_registered_subcommands() -> None:
    """_HANDLERS must dispatch every registered subcommand and only those."""
    parser = _build_parser()
    subparser_action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    registered = frozenset(subparser_action.choices)
    handlers = frozenset(_HANDLERS.keys())
    assert handlers == registered, (
        f"handlers/parser divergence — only in _HANDLERS: {handlers - registered}; "
        f"only in parser: {registered - handlers}"
    )


@pytest.mark.unit
def test_build_parser_is_pure_idempotent() -> None:
    """Repeated calls produce parsers with the same subcommand set."""
    first = _build_parser()
    second = _build_parser()
    first_subs = next(a for a in first._actions if isinstance(a, argparse._SubParsersAction))
    second_subs = next(a for a in second._actions if isinstance(a, argparse._SubParsersAction))
    assert frozenset(first_subs.choices) == frozenset(second_subs.choices)
