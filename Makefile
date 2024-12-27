install:
	python -m pip install -e ".[all]"
test:
	pytest --doctest-modules steganodf tests
