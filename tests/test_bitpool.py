import pytest
import polars as pl
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


