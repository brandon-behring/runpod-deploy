# Minimal Sphinx Makefile for runpod-deploy docs.
# Standard sphinx-quickstart boilerplate; invoke `make html` to build.
# Strict (-W --keep-going) is applied in CI; local builds are permissive
# so you can iterate quickly.

SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = build

.PHONY: help Makefile

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

# Catch-all target: route unknown targets to Sphinx using the new "make
# mode" option ("$(SPHINXBUILD) -M ...") — e.g. `make html`, `make clean`.
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
