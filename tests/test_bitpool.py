import pytest
import polars as pl
from steganodf.algorithms.bitpool import BitPool


def test_masking():
    a = BitPool()

    assert a.mask_separator(b"\xFF\xA1\xF1") == b"\xF1\xF2\xA1\xF1\xF3"
    assert a.unmask_separator(b"\xF1\xF2\xA1\xF1\xF3") == b"\xFF\xA1\xF1"

    payload = b"hello\xFFsteganodf"
    mask = a.mask_separator(payload)

    assert a.unmask_separator(mask) == payload


def test_without_password(df: pl.DataFrame):

    payload = b"sacha, je suis sacha et j'aime le chocolat"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    decoded_payload = algorithm.decode(df_encoded)

    print(decoded_payload)

    assert decoded_payload == payload


def test_encode(df: pl.DataFrame):

    payload = b"bob leponge"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    print(len(df_encoded), len(df))


def test_decode(df: pl.DataFrame):

    payload = b"bob leponge"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    payload = algorithm.decode(df_encoded)


def test_with_password(df: pl.DataFrame):

    payload = b"hello"
    algorithm = BitPool(password="password")
    df_encoded = algorithm.encode(df, payload=payload)
    assert payload == algorithm.decode(df_encoded)


# @pytest.mark.parametrize("error_count", range(10))
# def test_with_error(error_count):

# 	payload = b"hello"
# 	algorithm = BitPool(password="password")
# 	df_encoded = algorithm.encode(dfs[0].cast(pl.Utf8()), payload=payload)
# 	df_pandas = df_encoded.to_pandas()

# 	# Test with 10 errors
# 	for i in range(0,error_count):
# 		df_pandas.iat[i,0] = "@"


# 	assert payload == algorithm.decode(pl.from_pandas(df_pandas)), f"with error count = {i}"
