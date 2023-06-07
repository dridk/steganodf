from steganodf import (
    PayloadError,
    encode_index,
    decode_index,
    encode_pandas,
    decode_pandas,
)
import pytest
import pandas as pd
import os


def test_encode_indexes():
    indexes = list(range(100))
    exp_msg = "sacha"

    # test encoding
    encoded = encode_index(indexes, exp_msg)
    assert type(encoded) == list
    assert len(encoded) == len(indexes)


def test_decode_indexes():
    indexes = list(range(100))
    payload = "sacha"
    assert decode_index(encode_index(indexes, payload)) == payload


def test_encode_pandas():
    # without duplicate
    df = pd.DataFrame([f"s{i}" for i in range(200)])
    new_df = encode_pandas(df, "hello")
    assert len(df) == len(new_df)

    # with duplicate
    df = pd.DataFrame([f"s{i}" for i in range(50)] + [f"s{i}" for i in range(200)])
    new_df = encode_pandas(df, "hello")
    assert len(df) == len(new_df)


def test_decode_pandas():
    message = "hello"
    # without duplicate
    df = pd.DataFrame([f"s{i}" for i in range(200)])
    new_df = encode_pandas(df, message)

    assert decode_pandas(new_df) == message

    # with duplicate
    df = pd.DataFrame([f"s{i}" for i in range(50)] + [f"s{i}" for i in range(200)])
    new_df = encode_pandas(df, message)
    assert decode_pandas(new_df) == message

    # With password
    new_df = encode_pandas(df, message, password="secret")

    with pytest.raises(PayloadError):
        decode_pandas(new_df, password="bad_secret")

    assert decode_pandas(new_df, password="secret") == message
