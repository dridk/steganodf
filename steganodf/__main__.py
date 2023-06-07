import pandas as pd
import argparse
import steganodf as st
from pathlib import Path

supported_format = {
    ".csv": (pd.read_csv, pd.DataFrame.to_csv),
    ".parquet": (pd.read_parquet, pd.DataFrame.to_parquet),
}


def encode(
    input_file: Path, output_file: Path, message: str, password: None | str = None
):
    extension = input_file.suffix

    if extension not in supported_format:
        raise Exception("File Format is not supported")

    reader, writer = supported_format[extension]
    df = reader(input_file)
    encoded_df = st.encode_pandas(df, message, password=password)

    writer(encoded_df, output_file, index=None)


def decode(input_file: Path, password: None | str):
    extension = input_file.suffix

    if extension not in supported_format:
        raise Exception("File Format is not supported")

    reader, _ = supported_format[extension]

    df = reader(input_file)

    message = st.decode_pandas(df, password=password)
    return message


def cli(args):
    parser = argparse.ArgumentParser(
        prog="steganodf", description="a Tool to hide a message in a tabular file"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Sous-commande "encode"
    encode_parser = subparsers.add_parser("encode", help="Encode a file")
    encode_parser.add_argument(
        "--input", "-i", type=Path, required=True, help="source file (csv,parquet)"
    )
    encode_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="File with the hidding message (csv,parquet)",
    )
    encode_parser.add_argument(
        "--message", "-m", type=str, required=True, help="Payload message"
    )
    encode_parser.add_argument(
        "--password", "-p", type=str, required=False, help="Use a password"
    )

    # Sous-commande "decode"
    decode_parser = subparsers.add_parser(
        "decode", help="File with the hidding message (csv or parquet)"
    )
    decode_parser.add_argument(
        "--input", "-i", type=Path, required=True, help="Input file"
    )
    decode_parser.add_argument(
        "--password", "-p", type=str, required=False, help="Use a password"
    )

    parsed_args = parser.parse_args(args)

    if parsed_args.command == "encode":
        encode(
            parsed_args.input,
            parsed_args.output,
            parsed_args.message,
            parsed_args.password,
        )
    elif parsed_args.command == "decode":
        print(decode(parsed_args.input, parsed_args.password))
    else:
        parser.print_help()


if __name__ == "__main__":
    import sys

    cli(sys.argv[1:])
