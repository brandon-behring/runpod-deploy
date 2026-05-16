"""Sphinx configuration for runpod-deploy docs (v0.7.8).

Shipped in v0.7.8 (Phase 1 of the Sphinx documentation migration; see
~/.claude/plans/examine-all-git-issues-synchronous-tulip.md for the full
plan with Q1-Q14 decisions). Phase 2 adds per-module autodoc API pages;
Phase 3 publishes to GitHub Pages.

Key locked decisions:

- pydata-sphinx-theme (Q7) — match eval-toolkit for cross-project consistency
- myst-nb for Markdown parsing (Q1) — even with `nb_execution_mode = "off"`
  (Q8) so jupyter-cache stays unused
- per-module autodoc, deferred to Phase 2 (Q3)
- single-version, GitHub Pages (Phase 3)
- intersphinx to Python stdlib only — no scientific Python surface here
- `sphinx-build -W --keep-going` enforced in CI (Q9)
"""

from __future__ import annotations

import importlib.metadata
from datetime import datetime

# -- Project information --------------------------------------------------

project = "runpod-deploy"
author = "Brandon Behring"
copyright_year = datetime.now().strftime("%Y")
copyright = f"{copyright_year}, Brandon Behring"

# Pull __version__ from installed package metadata so docs build doesn't
# need to import runpod_deploy at conf-time.
try:
    release = importlib.metadata.version("runpod-deploy")
except importlib.metadata.PackageNotFoundError:
    release = "0.7.8-dev"
version = ".".join(release.split(".")[:2])  # 0.7 from 0.7.8

# -- General configuration ------------------------------------------------

extensions = [
    "myst_nb",  # MyST Markdown (supersedes myst-parser; nb execution gated by nb_execution_mode)
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",  # NumPy-style docstring parser
    "sphinx.ext.intersphinx",
    "sphinx.ext.mathjax",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
    "sphinx_copybutton",
    "sphinx_design",
]

# autodoc / autosummary (used by Phase 2)
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}
autosummary_generate = True
napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_use_param = True
napoleon_use_rtype = True

# Type-hint rendering — `sphinx-autodoc-typehints` integrates with napoleon
typehints_fully_qualified = False
always_document_param_types = True

# MyST-NB / MyST-Parser configuration
nb_execution_mode = "off"  # Q8 — no notebooks in runpod-deploy today; YAGNI on cell execution
nb_execution_timeout = 90
nb_execution_show_tb = True
nb_merge_streams = True
myst_enable_extensions = [
    "amsmath",
    "dollarmath",
    "deflist",
    "fieldlist",
    "colon_fence",
    "linkify",
    "substitution",
    "tasklist",
    "attrs_block",
    "attrs_inline",
]
myst_heading_anchors = 3  # auto-generate anchors for H1-H3

# Intersphinx — runpod-deploy public API references stdlib types only.
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# Source files
source_suffix = {
    ".md": "myst-nb",
    ".rst": "restructuredtext",
}
master_doc = "index"
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
]

# -- HTML output --------------------------------------------------------

html_theme = "pydata_sphinx_theme"
html_title = project
html_static_path = ["_static"]

html_theme_options = {
    "github_url": "https://github.com/brandon-behring/runpod-deploy",
    "use_edit_page_button": True,
    "show_prev_next": True,
    "navigation_with_keys": True,
    "footer_start": ["copyright", "last-updated"],
    "footer_end": ["sphinx-version", "theme-version"],
    "icon_links": [
        {
            "name": "PyPI",
            "url": "https://pypi.org/project/runpod-deploy/",
            "icon": "fa-brands fa-python",
        },
    ],
}

html_context = {
    "github_user": "brandon-behring",
    "github_repo": "runpod-deploy",
    "github_version": "main",
    "doc_path": "docs/source",
}

# Clean-slate advantage (Q9) — start strict from day one.
nitpicky = True
