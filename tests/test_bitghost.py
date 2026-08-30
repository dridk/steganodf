import random
import string
from collections import Counter

import numpy as np
import polars as pl
import pytest

from steganodf.algorithms.algorithm import AlgorithmError
from steganodf.algorithms.bitghost import BitGhost


def generate_payload(n: int) -> bytes:
    return "".join(random.choice(string.ascii_letters) for _ in range(n)).encode()


def test_roundtrip(df: pl.DataFrame):
    payload = b"leak-id-42"
    algo = BitGhost(seed=1)
    encoded = algo.encode(df, payload)
    assert algo.decode(encoded) == payload


def test_ghost_count(df: pl.DataFrame):
    """redundancy ghosts are added per message byte (len + payload + CRC32)."""
    payload = b"leak-id-42"
    algo = BitGhost(seed=1, redundancy=8)
    encoded = algo.encode(df, payload)
    assert len(encoded) - len(df) == 8 * (1 + len(payload) + 4)


def test_shuffle_survives(df: pl.DataFrame):
    payload = b"leak-id-42"
    algo = BitGhost(seed=1)
    encoded = algo.encode(df, payload)
    shuffled = encoded.sample(fraction=1.0, shuffle=True, seed=9)
    assert algo.decode(shuffled) == payload


def test_all_real_rows_edited(df: pl.DataFrame):
    """BitGhost's signature property: every real row can be rewritten and the
    message still decodes, because only the synthetic ghost rows are read."""
    payload = b"leak-id-42"
    algo = BitGhost(seed=1)
    encoded = algo.encode(df, payload)

    tag = algo._tag()
    rng = np.random.default_rng(5)
    a, b = encoded["a"].to_list(), encoded["b"].to_list()
    for i, row in enumerate(encoded.iter_rows(named=True)):
        if not algo._matches_tag(row, tag):  # a real (non-ghost) row
            a[i], b[i] = float(rng.random()), float(rng.random())
    edited = encoded.with_columns([pl.Series("a", a), pl.Series("b", b)])

    assert algo.decode(edited) == payload


def test_row_deletion(df: pl.DataFrame):
    payload = b"leak-id-42"
    algo = BitGhost(seed=1)
    encoded = algo.encode(df, payload)
    assert algo.decode(encoded.sample(fraction=0.7, seed=3)) == payload


def test_deduplication(df: pl.DataFrame):
    """Ghost copies use distinct nonces, so deduplication does not remove them."""
    payload = b"leak-id-42"
    algo = BitGhost(seed=1)
    encoded = algo.encode(df, payload)
    assert algo.decode(encoded.unique()) == payload


@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_roundtrip_through_disk(df: pl.DataFrame, tmp_path, suffix):
    payload = b"on disk"
    algo = BitGhost(seed=1, password="secret")
    path = tmp_path / f"stego{suffix}"

    encoded = algo.encode(df, payload)
    if suffix == ".csv":
        encoded.write_csv(path)
        reloaded = pl.read_csv(path)
    else:
        encoded.write_parquet(path)
        reloaded = pl.read_parquet(path)

    assert BitGhost(password="secret").decode(reloaded) == payload


def test_wrong_password_fails(df: pl.DataFrame):
    encoded = BitGhost(seed=1, password="pw").encode(df, b"secret")
    result = BitGhost(password="bad").decode_details(encoded)
    assert result["success"] is False
    assert result["payload"] == b""


def test_real_rows_are_untouched(df: pl.DataFrame):
    """The original rows survive verbatim; encoding only adds ghost rows."""
    algo = BitGhost(seed=1)
    encoded = algo.encode(df, b"leak-id-42")

    # every original row is still present in the encoded frame, unaltered
    original = Counter(map(tuple, df.iter_rows()))
    result = Counter(map(tuple, encoded.iter_rows()))
    assert (original & result) == original


def test_column_reordering_is_survived(df: pl.DataFrame):
    algo = BitGhost(seed=1)
    encoded = algo.encode(df, b"reorder")
    assert algo.decode(encoded.select(["b", "a"])) == b"reorder"


def test_no_float_column():
    frame = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    with pytest.raises(AlgorithmError):
        BitGhost(seed=1).encode(frame, b"nope")


def test_unknown_argument_is_rejected():
    with pytest.raises(AlgorithmError):
        BitGhost(foo=1)


def test_public_api(df: pl.DataFrame):
    import steganodf as st

    encoded = st.encode(df, b"api", algorithm="bitghost", seed=1)
    assert st.decode(encoded, algorithm="bitghost") == b"api"
