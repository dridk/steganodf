import os
import sys
import argparse
import steganodf as st
from pathlib import Path

from . import methods
from .methods import SUPPORTED_FORMATS_IO, METHODS, DEFAULT_METHOD


def get_supported_input_format():
    return tuple(i for i, _ in SUPPORTED_FORMATS_IO if i and callable(i))
def get_supported_output_format():
    return tuple(o for _, o in SUPPORTED_FORMATS_IO if o and callable(o))



def ap_input_file(fname: str) -> Path:
    fname = Path(fname)
    if not os.path.exists(fname):
        raise argparse.ArgumentError(f"{fname} does not exists")
    if not SUPPORTED_FORMATS_IO.get(fname.suffix, (None, None))[0]:
        raise argparse.ArgumentError(f"{fname} of format {fname.suffix} is not supported. Supported input file format are {', '.join(get_supported_input_format())}")
    return Path(fname)

def ap_output_file(fname: str) -> Path:
    fname = Path(fname)
    if not SUPPORTED_FORMATS_IO.get(fname.suffix, (None, None))[1]:
        raise argparse.ArgumentError(f"{fname} of format {fname.suffix} is not supported. Supported output file format are {', '.join(get_supported_output_format())}")
    return Path(fname)


def parse_cli(args = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='steganodf', description="a Tool to hide a message in a tabular file")
    subparsers = parser.add_subparsers(dest='command', required=True)

    def add_common_args(subparser):
        subparser.add_argument('--input', '-i', type=ap_input_file, required=True, help="Input file")
        subparser.add_argument('--password', '-p', type=str, required=False, help="Password to use")
        subparser.add_argument('--method', '-t', type=str, choices=list(METHODS), help="Method to use", default=DEFAULT_METHOD)

    # command "encode"
    encode_parser = subparsers.add_parser('encode', help="Encode given message in the input file data, write it to the output")
    add_common_args(encode_parser)
    encode_parser.add_argument('--output', '-o', type=ap_output_file, required=True, help="File in which to write the data with message encoded in it")
    encode_parser.add_argument('--message', '-m', type=str, required=True, help="Message to encode")

    # command "decode"
    decode_parser = subparsers.add_parser('decode', help="Decode a file with a hidden message")
    add_common_args(decode_parser)

    return parser.parse_args(args)


def main():
    args = parse_cli()

    if args.command == "encode":
        methods.encode(args.method, args.input, args.output, args.message, args.password)
    elif args.command == "decode":
        print(methods.decode(args.method, args.input, args.password))


if __name__ == "__main__":
    main()
