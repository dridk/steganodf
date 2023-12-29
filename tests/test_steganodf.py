
import steganodf 
import pandas as pd
import polars as pl

def test_polars():

	payload = b"hello"
	df = pl.read_csv("examples/iris.csv")
	df_encoded = steganodf.encode_polars(df, payload)
	assert steganodf.decode_polars(df_encoded) == payload


def test_pandas():

	payload = b"hello"
	df = pd.read_csv("examples/iris.csv")
	df_encoded = steganodf.encode_pandas(df, payload)
	assert steganodf.decode_pandas(df_encoded) == payload
