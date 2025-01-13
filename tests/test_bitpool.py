import pytest
import string
import random
import pandas as pd
import polars as pl
import random
from steganodf.algorithms.bitpool import BitPool


def generate_payload(n: int):
    """
    Generate a random payload of size n
    """
    return "".join(random.choice(string.ascii_letters) for _ in range(n))


def test_stat(df):

    a = BitPool(bit_per_row=2)

    assert a.get_packet_size() > 0
    assert a.get_total_size_available(df) > 0
    assert a.get_data_size_available(df) > 0


def test_small(df):
    payload = b"h"
    algorithm = BitPool(bit_per_row=2)
    algorithm._parity_size = 1
    algorithm._data_size = 2
    df_encoded, count = algorithm._encode(df.head(200), payload=payload)

    print(f"payload size: {len(payload)} ")
    print(f"encoded block: {count} ")
    print(f"packet size: {algorithm.get_packet_size()} ")

    # check error

    pdf = df_encoded.to_pandas()

    # for i in range(300):
    #     pdf.iloc[i, 0] = 100

    print(pdf)

    result = algorithm._decode(pl.from_pandas(pdf))

    print(result)


def test_without_password(df: pl.DataFrame):

    payload = b"hello"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    decoded_payload = algorithm.decode(df_encoded)

    print(decoded_payload)

    assert decoded_payload == payload


def test_encode(df: pl.DataFrame):

    payload = b"hello"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    assert len(df_encoded) == len(df)


def test_decode(df: pl.DataFrame):

    payload = b"hi"
    algorithm = BitPool(bit_per_row=4)
    df_encoded = algorithm.encode(df, payload=payload)

    assert algorithm.decode(df_encoded) == payload


def test_with_password(df: pl.DataFrame):

    payload = b"hello"
    algorithm = BitPool(password="password")
    df_encoded = algorithm.encode(df, payload=payload)
    assert payload == algorithm.decode(df_encoded)


@pytest.mark.parametrize("error_count", range(0, 100, 10))
def test_with_error(df, error_count):

    payload = b"hello"
    algorithm = BitPool(bit_per_row=2)
    df_encoded = algorithm.encode(df, payload=payload)

    df_encoded = df_encoded.to_pandas()
    # Test with 10 errors

    size = df_encoded.shape[0] * df_encoded.shape[1]
    cells = list(range(0, size))
    cells = random.sample(cells, error_count)
    for index in cells:
        x = index % df.shape[0]
        y = index // df.shape[0]
        df_encoded.iat[x, y] = -10

    assert payload == algorithm.decode(
        pl.from_pandas(df_encoded)
    ), f"with error count = {error_count}"


@pytest.mark.parametrize("error_count", range(1, 100))
def test_with_deletion(df, error_count):

    payload = b"hello"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)

    df_encoded = df_encoded.to_pandas()
    # Test with 10 errors
    index = df_encoded.sample(error_count).index
    df_encoded = df_encoded.drop(index)
    assert payload == algorithm.decode(pl.from_pandas(df_encoded)), f"with error count = {i}"
