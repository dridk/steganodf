"""Import and unify all available methods found in this subpackage"""
import os
import glob
import importlib
import functools
import pandas as pd
from pathlib import Path

METHODS = {}
for modpath in glob.glob(str(Path('steganodf/methods/').absolute() / '*.py')):
    modname = os.path.splitext(modpath.split('/')[-1])[0]
    if not modname.startswith('_'):
        METHODS[modname] = importlib.import_module('steganodf.methods.' + modname)

DEFAULT_METHOD = 'bytesplit'


SUPPORTED_FORMATS_IO = {
    ".csv": (pd.read_csv, pd.DataFrame.to_csv),
    ".parquet": (pd.read_parquet, pd.DataFrame.to_parquet),
}


def dec_verify_encode_input(func: callable):
    @functools.wraps(func)
    def repl(input_file: Path, output_file: Path, message: str, password: None | str = None):
        extension = input_file.suffix
        if extension not in SUPPORTED_FORMATS_IO:
            raise ValueError(f"File format {extension} is not supported")
        reader, writer = SUPPORTED_FORMATS_IO[extension]
        return func(reader(input_file), functools.partial(writer, path_or_buf=output_file, index=None), message, password)
    return repl

def dec_verify_decode_input(func: callable):
    @functools.wraps(func)
    def repl(input_file: Path, password: None | str):
        extension = input_file.suffix
        if extension not in SUPPORTED_FORMATS_IO:
            raise ValueError(f"File Format {extension} is not supported")
        reader, _ = SUPPORTED_FORMATS_IO[extension]
        return func(reader(input_file), password)
    return repl


for name, method in METHODS.items():
    for expected_func in ('encode', 'decode'):
        if not hasattr(method, expected_func):
            print(f"WARNING: method {name} does not define an {expected_func} function.")
    method.encode = dec_verify_encode_input(method.encode)
    method.decode = dec_verify_decode_input(method.decode)



def encode(method, *args, **kwargs):
    if method.lower() not in METHODS:
        raise ValueError(f"Method {method} doesn't exists. Choose one among {', '.join(METHODS)}")
    return METHODS[method].encode(*args, **kwargs)

def decode(method, *args, **kwargs):
    if method.lower() not in METHODS:
        raise ValueError(f"Method {method} doesn't exists. Choose one among {', '.join(METHODS)}")
    return METHODS[method].decode(*args, **kwargs)


