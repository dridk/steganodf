import pytest
import polars as pl
import pandas as pd 
from steganodf.algorithms.bitpool import BitPool

from .utils import load_parameters


dfs, ids = load_parameters()

@pytest.mark.parametrize("df", dfs, ids=ids)
def test_without_password(df):

	payload = b"hello"
	algorithm = BitPool()
	df_encoded = algorithm.encode(df, payload=payload)

	assert payload == algorithm.decode(df_encoded)


@pytest.mark.parametrize("df", dfs, ids=ids)
def test_with_password(df):

	payload = b"hello"
	algorithm = BitPool(password="password")
	df_encoded = algorithm.encode(df, payload=payload)
	assert payload == algorithm.decode(df_encoded)


@pytest.mark.parametrize("error_count", range(10))
def test_with_error(error_count):

	payload = b"hello"
	algorithm = BitPool(password="password")
	df_encoded = algorithm.encode(dfs[0].cast(pl.Utf8()), payload=payload)
	df_pandas = df_encoded.to_pandas()

	# Test with 10 errors 
	for i in range(0,error_count):
		df_pandas.iat[i,0] = "@"
	
	
	assert payload == algorithm.decode(pl.from_pandas(df_pandas)), f"with error count = {i}"
