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

    payload = b"hello sacha"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    decoded_payload = algorithm.decode(df_encoded)

    print(decoded_payload)

    assert decoded_payload == payload


def test_encode(df: pl.DataFrame):

    payload = b"dsfsdfsdf sdfzkejrze rze rzer zfsd fs"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    assert len(df_encoded) == len(df)


def test_decode(df: pl.DataFrame):

    payload = b"hello sacha le chat"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    algorithm.decode(df_encoded)


def test_with_password(df: pl.DataFrame):

    payload = b"hello"
    algorithm = BitPool(password="password")
    df_encoded = algorithm.encode(df, payload=payload)
    assert payload == algorithm.decode(df_encoded)


# @pytest.mark.parametrize("error_count", range(5))
def test_with_error(df):

    payload = b"hello"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    df_encoded = df_encoded.to_pandas()
    # Test with 10 errors
    for i in range(0, 2):
        df_encoded.iat[i, 0] = -10

    assert payload == algorithm.decode(pl.from_pandas(df_encoded)), f"with error count = {i}"


@pytest.mark.parametrize("error_count", range(1, 5))
def test_with_deletion(df, error_count):

    payload = b"hello"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    df_encoded = df_encoded.to_pandas()
    # Test with 10 errors
    index = df_encoded.sample(error_count).index
    df_encoded = df_encoded.drop(index)
    assert payload == algorithm.decode(pl.from_pandas(df_encoded)), f"with error count = {i}"
