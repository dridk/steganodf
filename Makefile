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

# La publication est faite par la CI (.github/workflows/publish.yml).
# Cette cible ne fait que rappeler la procédure et afficher la version courante.
publish:
	@VERSION=$$($(PYTHON) -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"); \
	 echo "Version courante : $$VERSION"; \
	 echo "Checklist : bump pyproject.toml -> uv lock -> commit -> merge dev dans main"; \
	 echo "Puis     : git tag $$VERSION && git push origin $$VERSION"
