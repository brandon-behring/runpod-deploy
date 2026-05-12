.PHONY: help install lint format test test-unit test-smoke type coverage ci clean

PYTHON := .venv/bin/python
VENV := .venv

help:
	@echo "Targets:"
	@echo "  install     Create .venv via uv and install dev dependencies"
	@echo "  lint        ruff check + black --check + mypy"
	@echo "  format      black + ruff check --fix"
	@echo "  test        pytest"
	@echo "  test-unit   pytest -m unit"
	@echo "  test-smoke  pytest -m smoke"
	@echo "  type        mypy strict on src/"
	@echo "  coverage    pytest with coverage report"
	@echo "  ci          lint + test + coverage"
	@echo "  clean       remove caches and build artifacts"

install:
	uv venv
	uv pip install -e ".[dev]"
	@echo "Activate: source $(VENV)/bin/activate"

lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m black --check src tests
	$(PYTHON) -m mypy src

format:
	$(PYTHON) -m black src tests
	$(PYTHON) -m ruff check --fix src tests

test:
	$(PYTHON) -m pytest

test-unit:
	$(PYTHON) -m pytest -m unit

test-smoke:
	$(PYTHON) -m pytest -m smoke

type:
	$(PYTHON) -m mypy src

coverage:
	$(PYTHON) -m pytest --cov=runpod_deploy --cov-report=term-missing --cov-fail-under=85

ci: lint test coverage

clean:
	rm -rf build dist *.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	@echo "Cleaned"
