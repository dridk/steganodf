#!/bin/bash
# Assemble www/ so the static page can run steganodf in the browser.
#
#   ./build_site.sh              rebuild the wheel and fetch the dependencies
#   ./build_site.sh --wheel-only rebuild the steganodf wheel only
#
# The wheel filename carries the version, so a new build lands under a new name
# and the old one has to go: leaving it behind is how www/ ends up serving a
# stale steganodf. pyscript.json is regenerated for the same reason — it used to
# be maintained by hand, and drifted until it was both pointing at an outdated
# wheel and missing numpy, which broke `import steganodf` outright.
set -euo pipefail

cd "$(dirname "$0")"

# Debian and friends ship python3 without a python alias.
PYTHON=${PYTHON:-$(command -v python || command -v python3)}

# Build the steganodf wheel, replacing any previous one.
rm -f www/steganodf-*.whl
"$PYTHON" -m build --wheel --outdir www/

"$PYTHON" sync_packages.py

if [ "${1:-}" = "--wheel-only" ]; then
    exit 0
fi

# Runtime dependencies, fetched once. -nc keeps a re-run from piling up
# polars-....whl.1 copies next to the real one.
wget -nc -P www https://github.com/pola-rs/polars/releases/download/py-1.19.0/polars-1.19.0-cp39-abi3-emscripten_3_1_58_wasm32.whl
wget -nc -P www https://files.pythonhosted.org/packages/09/19/1bb346c0e581557c88946d2bb979b2bee8992e72314cfb418b5440e383db/reedsolo-1.7.0-py3-none-any.whl

# The download step can add wheels the previous sync did not know about.
"$PYTHON" sync_packages.py
