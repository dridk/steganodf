"""Import and unify all available methods found in this subpackage"""
import functools
import pandas as pd
from pathlib import Path

from . import bytesplit

METHODS = {
    'bytesplit': bytesplit,
}
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
        return func(reader(input_file), writer(output_file), message, password)

def dec_verify_decode_input(func: callable):
    @functools.wraps(func)
    def repl(input_file: Path, password: None | str):
        extension = input_file.suffix
        if extension not in SUPPORTED_FORMATS_IO:
            raise ValueError(f"File Format {extension} is not supported")
        reader, _ = SUPPORTED_FORMATS_IO[extension]
        return func(reader(input_file), password)


for name, method in METHODS.items():
    for expected_func in ('encode', 'decode'):
        if not hasattr(method, expected_func):
            print(f"WARNING: method {name} does not define an {expected_func} function.")
    method.encode = dec_verify_encode_input(method.encode)
    method.decode = dec_verify_decode_input(method.decode)





