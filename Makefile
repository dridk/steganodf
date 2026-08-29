PYTHON ?= python3

.PHONY: install test serve dev wheel site-wheel build-site publish

install:
	$(PYTHON) -m pip install -e ".[dev]"
test:
	pytest --doctest-modules steganodf tests

serve:
	$(PYTHON) -m http.server --directory www

dev:
	live-server

wheel:
	$(PYTHON) -m build --wheel

# Rebuild the wheel served by the web page and re-point pyscript.json at it.
site-wheel:
	./build_site.sh --wheel-only

build-site:
	./build_site.sh

publish:
