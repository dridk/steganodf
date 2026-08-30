"""Guard the generated www/pyscript.json against drifting from the package.

PyScript downloads each entry by name, so a stale wheel filename here is a 404
in the browser and `import steganodf` fails outright. Run `make site-wheel`
after bumping the version to regenerate this file.
"""

import json
import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = json.loads((ROOT / "www" / "pyscript.json").read_text())["packages"]


def test_pyscript_ships_the_current_steganodf_wheel():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    wheels = [name for name in PACKAGES if name.startswith("steganodf-")]

    assert wheels == [f"steganodf-{version}-py3-none-any.whl"]


def test_pyscript_keeps_the_pinned_wheels():
    # numpy is the one dependency Pyodide already bundles; everything else has
    # to name the wheel served next to the page.
    named = [name for name in PACKAGES if not name.endswith(".whl")]

    assert named == ["numpy"]
