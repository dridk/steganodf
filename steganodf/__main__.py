import os
import sys
import argparse
import polars as pl
import steganodf as st
from pathlib import Path

from steganodf.algorithms import ALGORITHMS

SUPPORTED_FORMATS_IO = {
    ".csv": (pl.read_csv, pl.DataFrame.write_csv),
    ".parquet": (pl.read_parquet, pl.DataFrame.write_parquet),
}


def get_supported_input_format():
    return tuple(i for i, _ in SUPPORTED_FORMATS_IO if i and callable(i))
def get_supported_output_format():
    return tuple(o for _, o in SUPPORTED_FORMATS_IO if o and callable(o))


def read_file(path:Path) -> pl.DataFrame:
    reader, _ = SUPPORTED_FORMATS_IO[path.suffix]
    return reader(path)


def write_file(df: pl.DataFrame, path:Path):
    _, writer = SUPPORTED_FORMATS_IO[path.suffix]
    writer(df, path)
    

    
def ap_input_file(fname: str) -> Path:
    fname = Path(fname)
    if not os.path.exists(fname):
        raise argparse.ArgumentTypeError(f"{fname} does not exists")
    if not SUPPORTED_FORMATS_IO.get(fname.suffix, (None, None))[0]:
        raise argparse.ArgumentTypeError(f"{fname} of format {fname.suffix} is not supported. Supported input file format are {', '.join(get_supported_input_format())}")
    return Path(fname)

def ap_output_file(fname: str) -> Path:
    fname = Path(fname)
    if not SUPPORTED_FORMATS_IO.get(fname.suffix, (None, None))[1]:
        raise argparse.ArgumentTypeError(f"{fname} of format {fname.suffix} is not supported. Supported output file format are {', '.join(get_supported_output_format())}")
    return Path(fname)


def parse_cli(args = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='steganodf', description="a Tool to hide a message in a tabular file")
    subparsers = parser.add_subparsers(dest='command', required=True)

    def add_common_args(subparser):
        subparser.add_argument('input', type=ap_input_file, help="Input file")
        subparser.add_argument('--password', '-p', type=str, required=False, help="Password to use")
        subparser.add_argument('--algorithm', '-a', type=str, choices=list(ALGORITHMS.keys()), help="Algorithm to use", default="bitpool")

    # command "encode"
    encode_parser = subparsers.add_parser('encode', help="Encode given message in the input file data, write it to the output")
    add_common_args(encode_parser)
    encode_parser.add_argument('output', type=ap_output_file, help="File in which to write the data with message encoded in it")
    encode_parser.add_argument('--message', '-m', type=str, required=True, help="Message to encode")

    # command "decode"
    decode_parser = subparsers.add_parser('decode', help="Decode a file with a hidden message")
    add_common_args(decode_parser)

    return parser.parse_args(args)


def main():
    args = parse_cli()

    if args.command == "encode":

        df = read_file(args.input)
        new_df = st.encode_polars(df, payload=args.message.encode(), algorithm=args.algorithm, password=args.password)
        write_file(new_df, args.output)

    
    elif args.command == "decode":
        df = read_file(args.input)
        print(st.decode_polars(df, algorithm=args.algorithm, password=args.password).decode())

if __name__ == "__main__":
    main()
