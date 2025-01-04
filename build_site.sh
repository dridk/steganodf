#!/bin/bash


# Build steganodf wheel 
python -m build --wheel --outdir www/


# Download polars
wget -P www https://github.com/pola-rs/polars/releases/download/py-1.19.0/polars-1.19.0-cp39-abi3-emscripten_3_1_58_wasm32.whl

# Download reedsolo
wget -P www https://files.pythonhosted.org/packages/09/19/1bb346c0e581557c88946d2bb979b2bee8992e72314cfb418b5440e383db/reedsolo-1.7.0-py3-none-any.whl
