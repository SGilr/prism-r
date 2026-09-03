# PRISM-R pipeline entry points.
# build.py is the canonical way to refresh the processed data.

PYTHON ?= .venv/bin/python

.PHONY: build test test-fast clean-processed

# Run the full pipeline and write data/processed/manifest.json.
build:
	$(PYTHON) pipeline/build.py

# Run the test suite, including the slow end-to-end smoke test.
test:
	$(PYTHON) -m pytest

# Run the test suite without the slow end-to-end smoke test.
test-fast:
	$(PYTHON) -m pytest -m "not slow"

# Remove every generated file in data/processed/. Rebuild with make build.
clean-processed:
	rm -f data/processed/*.json data/processed/build.log
