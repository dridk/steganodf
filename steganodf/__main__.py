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
    return tuple(suffix for suffix, (reader, _) in SUPPORTED_FORMATS_IO.items() if callable(reader))


def get_supported_output_format():
    return tuple(suffix for suffix, (_, writer) in SUPPORTED_FORMATS_IO.items() if callable(writer))


def read_file(path: Path) -> pl.DataFrame:
    reader, _ = SUPPORTED_FORMATS_IO[path.suffix]
    return reader(path)


def write_file(df: pl.DataFrame, path: Path):
    _, writer = SUPPORTED_FORMATS_IO[path.suffix]
    writer(df, path)


def ap_input_file(fname: str) -> Path:
    fname = Path(fname)
    if not os.path.exists(fname):
        raise argparse.ArgumentTypeError(f"{fname} does not exists")
    if not SUPPORTED_FORMATS_IO.get(fname.suffix, (None, None))[0]:
        raise argparse.ArgumentTypeError(
            f"{fname} of format {fname.suffix} is not supported. Supported input file format are {', '.join(get_supported_input_format())}"
        )
    return Path(fname)


def ap_output_file(fname: str) -> Path:
    fname = Path(fname)
    if not SUPPORTED_FORMATS_IO.get(fname.suffix, (None, None))[1]:
        raise argparse.ArgumentTypeError(
            f"{fname} of format {fname.suffix} is not supported. Supported output file format are {', '.join(get_supported_output_format())}"
        )
    return Path(fname)


def parse_cli(args=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="steganodf", description="a Tool to hide a message in a tabular file"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_args(subparser):
        subparser.add_argument("input", type=ap_input_file, help="Input file")
        subparser.add_argument("--password", "-p", type=str, required=False, help="Password to use")
        subparser.add_argument(
            "--column",
            "-c",
            type=str,
            required=False,
            help="Name of the carrier column (bitvote/bitghost only)",
        )
        subparser.add_argument(
            "--algorithm",
            "-a",
            type=str,
            choices=list(ALGORITHMS.keys()),
            help="Algorithm to use",
            default="bitpool",
        )

    # command "encode"
    encode_parser = subparsers.add_parser(
        "encode", help="Encode given message in the input file data, write it to the output"
    )
    add_common_args(encode_parser)
    encode_parser.add_argument(
        "output",
        type=ap_output_file,
        help="File in which to write the data with message encoded in it",
    )
    encode_parser.add_argument("--message", "-m", type=str, required=True, help="Message to encode")

    # command "decode"
    decode_parser = subparsers.add_parser("decode", help="Decode a file with a hidden message")
    add_common_args(decode_parser)

    return parser.parse_args(args)


def main():
    args = parse_cli()

    # `column` is only accepted by the alteration algorithms, so forward it
    # only when the user set it (bitpool would reject an unexpected argument).
    extra = {"column": args.column} if args.column else {}

    if args.command == "encode":

        df = read_file(args.input)
        new_df = st.encode(
            df,
            payload=args.message.encode(),
            algorithm=args.algorithm,
            password=args.password,
            **extra,
        )
        write_file(new_df, args.output)

    elif args.command == "decode":
        df = read_file(args.input)
        payload = st.decode(df, algorithm=args.algorithm, password=args.password, **extra)
        if not payload:
            print(
                f"No message could be decoded from {args.input}. "
                "The file may not be watermarked, the password may be wrong, "
                "or the rows may have been reordered.",
                file=sys.stderr,
            )
            return 1
        print(payload.decode())

    return 0


if __name__ == "__main__":
    sys.exit(main())
