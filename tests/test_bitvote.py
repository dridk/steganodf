import math
import random
import string

import numpy as np
import polars as pl
import pytest

from steganodf.algorithms.algorithm import AlgorithmError
from steganodf.algorithms.bitvote import BitVote


def generate_payload(n: int) -> bytes:
    return "".join(random.choice(string.ascii_letters) for _ in range(n)).encode()


@pytest.mark.parametrize("size", [0, 1, 10, 19])
def test_roundtrip(df: pl.DataFrame, size):
    payload = generate_payload(size)
    algo = BitVote()
    encoded = algo.encode(df, payload)
    assert algo.decode(encoded) == payload


def test_payload_too_large(df: pl.DataFrame):
    algo = BitVote()
    with pytest.raises(AlgorithmError):
        algo.encode(df, generate_payload(algo.get_max_payload_size() + 1))


def test_shuffle_survives(df: pl.DataFrame):
    """The whole point: the message lives in the cell content, not the row
    order, so shuffling every row must not destroy it."""
    payload = b"made by steganodf"
    algo = BitVote()
    encoded = algo.encode(df, payload)
    shuffled = encoded.sample(fraction=1.0, shuffle=True, seed=42)
    assert algo.decode(shuffled) == payload


def test_row_deletion(df: pl.DataFrame):
    payload = b"half gone"
    algo = BitVote()
    encoded = algo.encode(df, payload)
    assert algo.decode(encoded.sample(fraction=0.5, seed=1)) == payload


def test_sparse_cell_edits(df: pl.DataFrame):
    """Overwriting a fraction of the carrier cells only costs a few votes."""
    payload = b"resilient"
    algo = BitVote()
    encoded = algo.encode(df, payload)

    rng = np.random.default_rng(7)
    values = encoded["a"].to_list()
    for i in rng.choice(len(values), size=1000, replace=False):
        values[int(i)] = float(rng.random())
    edited = encoded.with_columns(pl.Series("a", values))
    assert algo.decode(edited) == payload


@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_roundtrip_through_disk(df: pl.DataFrame, tmp_path, suffix):
    """encode -> write file -> read file -> decode must reproduce the mutated
    float LSB exactly."""
    payload = b"on disk"
    algo = BitVote(password="secret")
    path = tmp_path / f"stego{suffix}"

    encoded = algo.encode(df, payload)
    if suffix == ".csv":
        encoded.write_csv(path)
        reloaded = pl.read_csv(path)
    else:
        encoded.write_parquet(path)
        reloaded = pl.read_parquet(path)

    assert BitVote(password="secret").decode(reloaded) == payload


def test_with_password(df: pl.DataFrame):
    payload = b"secret"
    encoded = BitVote(password="pw").encode(df, payload)
    assert BitVote(password="pw").decode(encoded) == payload


def test_wrong_password_fails(df: pl.DataFrame):
    encoded = BitVote(password="pw").encode(df, b"secret")
    result = BitVote(password="bad").decode_details(encoded)
    assert result["success"] is False
    assert result["payload"] == b""


def test_column_reordering_is_survived(df: pl.DataFrame):
    algo = BitVote()
    encoded = algo.encode(df, b"hello")
    assert algo.decode(encoded.select(["b", "a"])) == b"hello"


def test_explicit_column(df: pl.DataFrame):
    payload = b"pick b"
    algo = BitVote(column="b")
    encoded = algo.encode(df, payload)
    assert algo.decode(encoded) == payload
    # only the chosen carrier column changed
    assert encoded["a"].to_list() == df["a"].to_list()


def test_integer_carrier():
    rng = np.random.default_rng(0)
    frame = pl.DataFrame({"a": rng.integers(0, 1_000_000, 10000), "b": rng.random(10000)})
    algo = BitVote(column="a")
    encoded = algo.encode(frame, b"int carrier")
    assert encoded.schema["a"] == pl.Int64
    assert algo.decode(encoded) == b"int carrier"


def test_null_and_nan_carrier_preserved():
    rng = np.random.default_rng(0)
    a = rng.random(5000).tolist()
    a[0] = None
    a[1] = float("nan")
    frame = pl.DataFrame({"a": a, "b": rng.random(5000)})
    algo = BitVote(column="a", data_size=8)
    encoded = algo.encode(frame, b"hi")
    assert encoded["a"][0] is None
    assert math.isnan(encoded["a"][1])
    assert algo.decode(encoded) == b"hi"


def test_row_order_and_other_columns_unchanged(df: pl.DataFrame):
    algo = BitVote()
    encoded = algo.encode(df, b"unchanged")
    assert len(encoded) == len(df)
    assert encoded["b"].to_list() == df["b"].to_list()


def test_no_numeric_column():
    frame = pl.DataFrame({"a": ["x", "y"], "b": ["u", "v"]})
    with pytest.raises(AlgorithmError):
        BitVote().encode(frame, b"nope")


def test_dataframe_too_small():
    frame = pl.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    with pytest.raises(AlgorithmError):
        BitVote().encode(frame, b"too big")


def test_unknown_argument_is_rejected():
    with pytest.raises(AlgorithmError):
        BitVote(foo=1)


def test_public_api(df: pl.DataFrame):
    import steganodf as st

    encoded = st.encode(df, b"api", algorithm="bitvote")
    assert st.decode(encoded, algorithm="bitvote") == b"api"
