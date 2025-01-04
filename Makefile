.PHONY: build-site

install:
	python -m pip install -e ".[all]"
test:
	pytest --doctest-modules steganodf tests

serve:
	python -m http.server

dev:
	live-server

wheel:
	python -m build --wheel
	
build-site:
	./build_site.sh
	
