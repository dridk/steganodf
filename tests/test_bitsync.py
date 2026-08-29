import pandas as pd
import polars as pl
import pytest

from steganodf.algorithms.algorithm import AlgorithmError
from steganodf.algorithms.bitsync import BitSync


PAYLOAD_LONG = bytes(i % 251 for i in range(100))


def test_short_mode_roundtrip(df: pl.DataFrame):
    payload = b"hello"
    algorithm = BitSync(seed=1)
    df_encoded = algorithm.encode(df, payload=payload)

    result = algorithm.decode_details(df_encoded)
    assert result["success"] is True
    assert result["mode"] == "short"
    assert result["payload"] == payload


def test_standard_mode_roundtrip(df: pl.DataFrame):
    algorithm = BitSync(seed=1)
    df_encoded = algorithm.encode(df, payload=PAYLOAD_LONG)

    result = algorithm.decode_details(df_encoded)
    assert result["success"] is True
    assert result["mode"] == "standard"
    assert result["payload"] == PAYLOAD_LONG


def test_encode_preserves_rows(df: pl.DataFrame):
    df_encoded = BitSync(seed=1).encode(df, payload=b"hello")
    assert len(df_encoded) == len(df)
    assert df_encoded.sort("a").equals(df.sort("a"))


def test_estimate_payload_size(df: pl.DataFrame):
    algorithm = BitSync(seed=1)
    size = algorithm.get_max_payload_size(df)
    payload = bytes(i % 251 for i in range(size))

    assert algorithm.decode(algorithm.encode(df, payload)) == payload


def test_without_correction(df: pl.DataFrame):
    payload = b"hello"
    algorithm = BitSync(correction_size=0, seed=1)
    df_encoded = algorithm.encode(df, payload=payload)
    assert algorithm.decode(df_encoded) == payload


def test_with_password(df: pl.DataFrame):
    payload = b"hello"
    algorithm = BitSync(password="password", seed=1)
    df_encoded = algorithm.encode(df, payload=payload)
    assert algorithm.decode(df_encoded) == payload


def test_wrong_password_fails(df: pl.DataFrame):
    encoded = BitSync(password="secret", seed=1).encode(df, payload=b"hello")

    result = BitSync(password="wrong").decode_details(encoded)
    assert result["success"] is False
    assert result["payload"] == b""


@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_roundtrip_through_disk(df: pl.DataFrame, tmp_path, suffix):
    """The advertised workflow is encode -> write file -> read file -> decode."""
    payload = b"made by steganodf"
    algorithm = BitSync(password="secret", seed=1)
    path = tmp_path / f"stego{suffix}"

    encoded = algorithm.encode(df, payload=payload)
    if suffix == ".csv":
        encoded.write_csv(path)
        reloaded = pl.read_csv(path)
    else:
        encoded.write_parquet(path)
        reloaded = pl.read_parquet(path)

    assert BitSync(password="secret").decode(reloaded) == payload


def test_column_reordering_survives(df: pl.DataFrame):
    encoded = BitSync(seed=1).encode(df, payload=b"hello")
    assert BitSync().decode(encoded.select(["b", "a"])) == b"hello"


def test_encoding_is_reproducible_with_a_seed(df: pl.DataFrame):
    first = BitSync(seed=42).encode(df, payload=b"hello")
    second = BitSync(seed=42).encode(df, payload=b"hello")
    assert first.equals(second)


def test_decode_does_not_depend_on_the_seed(df: pl.DataFrame):
    encoded = BitSync(seed=7, password="s").encode(df, payload=b"hello")
    assert BitSync(password="s").decode(encoded) == b"hello"


@pytest.mark.parametrize("error_count", [10, 40, 80, 120])
def test_with_scattered_deletions(df, error_count):
    """The showcase test: the HMM re-synchronizes after every deleted row, so a
    deletion costs a couple of locally corrupted bytes (repaired by
    Reed-Solomon) instead of destroying the whole packet spanning it. At the
    default settings the envelope is ~1.2% of deleted rows; BitPool at the same
    1 bit per row dies well below 1%.
    """
    algorithm = BitSync(seed=error_count)
    df_encoded = algorithm.encode(df, payload=PAYLOAD_LONG).to_pandas()

    index = df_encoded.sample(error_count, random_state=error_count).index
    df_encoded = df_encoded.drop(index)

    assert algorithm.decode(pl.from_pandas(df_encoded)) == PAYLOAD_LONG, (
        f"with {error_count} deleted rows"
    )


def test_with_head_crop(df):
    """A head crop is the worst contiguous deletion: the decoder must walk the
    full drift down before the first packet. The default drift budget covers
    10% of the rows; 5% leaves margin for the walk itself.
    """
    algorithm = BitSync(seed=1)
    df_encoded = algorithm.encode(df, payload=PAYLOAD_LONG)

    cropped = df_encoded[len(df_encoded) // 20 :]
    assert algorithm.decode(cropped) == PAYLOAD_LONG


def test_with_tail_crop(df):
    algorithm = BitSync(seed=1)
    df_encoded = algorithm.encode(df, payload=PAYLOAD_LONG)

    cropped = df_encoded[: len(df_encoded) * 9 // 10]
    assert algorithm.decode(cropped) == PAYLOAD_LONG


def test_with_inserted_rows(df):
    """Foreign rows are modelled as insertions: the HMM steps over them."""
    import numpy as np

    algorithm = BitSync(seed=1)
    df_encoded = algorithm.encode(df, payload=PAYLOAD_LONG).to_pandas()

    rng = np.random.default_rng(1)
    foreign = pd.DataFrame({"a": rng.random(60), "b": rng.random(60)})
    positions = sorted(rng.choice(len(df_encoded), 60, replace=False))

    parts, last = [], 0
    for row, position in enumerate(positions):
        parts.append(df_encoded.iloc[last:position])
        parts.append(foreign.iloc[[row]])
        last = position
    parts.append(df_encoded.iloc[last:])
    mixed = pd.concat(parts, ignore_index=True)

    assert algorithm.decode(pl.from_pandas(mixed)) == PAYLOAD_LONG


def test_with_edited_cells(df):
    """An edited cell flips the bit of its row: a substitution for the HMM."""
    import numpy as np

    algorithm = BitSync(seed=1)
    df_encoded = algorithm.encode(df, payload=PAYLOAD_LONG).to_pandas()

    rng = np.random.default_rng(2)
    for row in rng.choice(len(df_encoded), 100, replace=False):
        df_encoded.iat[row, 0] = -10.0

    assert algorithm.decode(pl.from_pandas(df_encoded)) == PAYLOAD_LONG


def test_dataframe_too_small():
    small = pl.DataFrame({"a": range(100)})
    with pytest.raises(AlgorithmError):
        BitSync().encode(small, payload=b"hello")


def test_unknown_argument_is_rejected():
    with pytest.raises(AlgorithmError):
        BitSync(parity_size=0)


def test_invalid_parameters_are_rejected():
    with pytest.raises(AlgorithmError):
        BitSync(data_size=1)
    with pytest.raises(AlgorithmError):
        BitSync(p_delete=0.0)
    with pytest.raises(AlgorithmError):
        BitSync(max_drift=0)
