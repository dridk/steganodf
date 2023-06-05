import pandas as pd
import argparse 
import steganodf as st
from pathlib import Path

supported_format = {
        ".csv" : (pd.read_csv, pd.DataFrame.to_csv),
        ".parquet": (pd.read_parquet, pd.DataFrame.to_parquet)
        }


def encode(input_file:Path, output_file:Path, payload:str):

    extension = input_file.suffix
    
    if extension not in supported_format:
        raise Exception("File Format is not supported")
    
    reader, writer  = supported_format[extension]
    df = reader(input_file)
    encoded_df  = st.encode_pandas(df, payload)
    
    writer(encoded_df, output_file, index=None)
    


def decode(input_file:Path):

    extension = input_file.suffix
    
    if extension not in supported_format:
        raise Exception("File Format is not supported")
    
    reader, _ = supported_format[extension]

    df = reader(input_file)
    
    message = st.decode_pandas(df)
    return message

    
def cli():

    parser = argparse.ArgumentParser(prog='steganodf', description="a Tool to hide a message in a tabular file")
    subparsers = parser.add_subparsers(dest='command')

    # Sous-commande "encode"
    encode_parser = subparsers.add_parser('encode', help='Encode a file')
    encode_parser.add_argument('--input', "-i", type=Path, required=True, help='source file (csv,parquet)')
    encode_parser.add_argument('--output',"-o", type=Path,required=True, help='File with the hidding message (csv,parquet)')
    encode_parser.add_argument('--payload',"-p", type=str, required=True, help='Payload message')

    # Sous-commande "decode"
    decode_parser = subparsers.add_parser('decode', help='File with the hidding message (csv or parquet)')
    decode_parser.add_argument('--input', "-i", type=Path,required=True, help='Input file')

    args = parser.parse_args()

    if args.command == 'encode':
        encode(args.input, args.output, args.payload)
    elif args.command == 'decode':
        print(decode(args.input))
    else:
        parser.print_help()
    



if __name__ == "__main__":


    cli()

