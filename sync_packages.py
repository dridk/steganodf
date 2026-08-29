"""Regenerate www/pyscript.json from the dependencies pyproject.toml declares."""

import json
import pathlib
import re
import tomllib

www = pathlib.Path("www")
project = tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]
requirements = [*project["dependencies"], project["name"]]

packages = []
for requirement in requirements:
    name = re.split(r"[<>=!~\[;\s]", requirement, maxsplit=1)[0].strip()
    wheels = sorted(www.glob(f"{name}-*.whl"))
    wheels += sorted(www.glob(f"{name.replace('-', '_')}-*.whl"))
    packages.append(wheels[0].name if wheels else name)

path = www / "pyscript.json"
path.write_text(json.dumps({"packages": packages}, indent=2) + "\n")
print("pyscript.json ->", ", ".join(packages))
