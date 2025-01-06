import pytest
import random
import polars as pl
from steganodf.algorithms.bitpool import BitPool


def test_masking():
    a = BitPool()

    assert a.mask_separator(b"\xFF\xA1\xF1") == b"\xF1\xF2\xA1\xF1\xF3"
    assert a.unmask_separator(b"\xF1\xF2\xA1\xF1\xF3") == b"\xFF\xA1\xF1"

    payload = b"hello\xFFsteganodf"
    mask = a.mask_separator(payload)

    assert a.unmask_separator(mask) == payload


def test_small():
    pass


def test_without_password(df: pl.DataFrame):

    payload = b"hellosdfsfsfsfsfsf sf sfs f "
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

    payload = b"hello sacha, je suis boby"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    algorithm.decode(df_encoded)


def test_with_password(df: pl.DataFrame):

    payload = b"hello"
    algorithm = BitPool(password="password")
    df_encoded = algorithm.encode(df, payload=payload)
    assert payload == algorithm.decode(df_encoded)


# @pytest.mark.parametrize("error_count", range(0, 100, 10))
# def test_with_error(df, error_count):

#     payload = b"hello"
#     algorithm = BitPool(bit_per_row=2)
#     df_encoded = algorithm.encode(df, payload=payload)

#     df_encoded = df_encoded.to_pandas()
#     # Test with 10 errors

#     size = df_encoded.shape[0] * df_encoded.shape[1]
#     cells = list(range(0, size))
#     cells = random.sample(cells, error_count)
#     for index in cells:
#         x = index % df.shape[0]
#         y = index // df.shape[0]
#         df_encoded.iat[x, y] = -10

#     assert payload == algorithm.decode(
#         pl.from_pandas(df_encoded)
#     ), f"with error count = {error_count}"


# @pytest.mark.parametrize("error_count", range(1, 100))
# def test_with_deletion(df, error_count):

#     payload = b"hello"
#     algorithm = BitPool()
#     df_encoded = algorithm.encode(df, payload=payload)

#     df_encoded = df_encoded.to_pandas()
#     # Test with 10 errors
#     index = df_encoded.sample(error_count).index
#     df_encoded = df_encoded.drop(index)
#     assert payload == algorithm.decode(pl.from_pandas(df_encoded)), f"with error count = {i}"
