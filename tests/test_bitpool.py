import pytest
import string
import random
import polars as pl
from steganodf.algorithms.algorithm import AlgorithmError
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


def test_estimate_payload_size(df: pl.DataFrame):

    sdf = df
    algorithm = BitPool(correction_size=0, seed=1)
    size = algorithm.get_max_payload_size(sdf)
    print("size", size)
    payload = [string.ascii_letters[i % len(string.ascii_letters)] for i in range(size)]
    payload = "".join(payload).encode()

    df_encoded = algorithm.encode(sdf, payload)
    decoded_payload = algorithm.decode(df_encoded)
    assert decoded_payload == payload


def test_without_parity(df: pl.DataFrame):

    payload = b"hello"
    algorithm = BitPool(correction_size=0)
    df_encoded = algorithm.encode(df, payload=payload)
    decoded_payload = algorithm.decode(df_encoded)
    assert decoded_payload == payload


def test_without_password(df: pl.DataFrame):

    payload = b"hello"
    algorithm = BitPool()
    df_encoded = algorithm.encode(df, payload=payload)
    decoded_payload = algorithm.decode(df_encoded)
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


@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_roundtrip_through_disk(df: pl.DataFrame, tmp_path, suffix):
    """The advertised workflow is encode -> write file -> read file -> decode.

    It only works as long as writing and reading back reproduces every cell exactly
    as it was hashed, so this is the regression test that matters most.
    """
    payload = b"made by steganodf"
    algorithm = BitPool(bit_per_row=2, password="secret", seed=1)
    path = tmp_path / f"stego{suffix}"

    encoded = algorithm.encode(df, payload=payload)
    if suffix == ".csv":
        encoded.write_csv(path)
        reloaded = pl.read_csv(path)
    else:
        encoded.write_parquet(path)
        reloaded = pl.read_parquet(path)

    assert BitPool(bit_per_row=2, password="secret").decode(reloaded) == payload


def test_column_order_matters(df: pl.DataFrame):
    """The row fingerprint concatenates the columns in their current order, so
    reordering them destroys the message. Documented here so a future change of
    `compute_hash` shows up as a deliberate decision.
    """
    algorithm = BitPool(bit_per_row=2, seed=1)
    encoded = algorithm.encode(df, payload=b"hello")

    assert algorithm.decode(encoded.select(["b", "a"])) == b""


def test_encoding_is_reproducible_with_a_seed(df: pl.DataFrame):
    payload = b"hello"
    first = BitPool(seed=42).encode(df, payload=payload)
    second = BitPool(seed=42).encode(df, payload=payload)

    assert first.equals(second)


@pytest.mark.parametrize("bit_per_row", [3, 5, 6, 10])
def test_free_bit_per_row(df: pl.DataFrame, bit_per_row):
    """The packet is written as a continuous bit stream, so bit_per_row does not
    need to divide 8. Higher values pack a packet into fewer rows.
    """
    payload = b"free bit_per_row roundtrip"
    algorithm = BitPool(bit_per_row=bit_per_row, seed=1)
    df_encoded = algorithm.encode(df, payload=payload)

    assert len(df_encoded) == len(df)
    assert algorithm.decode(df_encoded) == payload


def test_capacity_grows_with_bit_per_row(df: pl.DataFrame):
    """A payload sized for bit_per_row=8 (~4x the bit_per_row=2 estimate) really
    fits and survives the roundtrip.
    """
    algorithm = BitPool(bit_per_row=8, seed=1)
    size = algorithm.get_max_payload_size(df)
    assert size > 3 * BitPool(bit_per_row=2).get_max_payload_size(df)

    payload = bytes(i % 256 for i in range(size))
    assert algorithm.decode(algorithm.encode(df, payload)) == payload


@pytest.mark.parametrize("bit_per_row", [0, 17])
def test_bit_per_row_out_of_bounds(bit_per_row):
    with pytest.raises(AlgorithmError):
        BitPool(bit_per_row=bit_per_row)


def test_unknown_argument_is_rejected():
    with pytest.raises(AlgorithmError):
        BitPool(parity_size=0)


def test_dataframe_too_small():
    small = pl.DataFrame({"a": range(20)})
    with pytest.raises(AlgorithmError):
        BitPool().encode(small, payload=b"hello")


def test_decode_details_reports_failure(df: pl.DataFrame):
    encoded = BitPool(password="secret", seed=1).encode(df, payload=b"hello")

    result = BitPool(password="wrong").decode_details(encoded)

    assert result["success"] is False
    assert result["payload"] == b""


@pytest.mark.parametrize("error_count", range(0, 100, 10))
def test_with_error(df, error_count):

    payload = b"hello"
    algorithm = BitPool(bit_per_row=2, seed=error_count)
    df_encoded = algorithm.encode(df, payload=payload)

    df_encoded = df_encoded.to_pandas()
    # Test with 10 errors

    size = df_encoded.shape[0] * df_encoded.shape[1]
    cells = list(range(0, size))
    cells = random.Random(error_count).sample(cells, error_count)
    for index in cells:
        x = index % df.shape[0]
        y = index // df.shape[0]
        df_encoded.iat[x, y] = -10

    assert payload == algorithm.decode(
        pl.from_pandas(df_encoded)
    ), f"with error count = {error_count}"


@pytest.mark.parametrize("error_count", range(1, 100))
def test_with_deletion(df, error_count):
    """A deletion shifts every following row, so it destroys the packet spanning it.

    `bit_per_row=4` is used on purpose: a packet then spans 92 rows instead of the
    368 rows of the default setting, so ~1% of deleted rows still leaves plenty of
    intact packets. At `bit_per_row=1` the same deletion rate leaves barely one
    surviving packet on average, which is what used to make this test flaky.
    """

    payload = b"hello"
    algorithm = BitPool(bit_per_row=4, seed=error_count)
    df_encoded = algorithm.encode(df, payload=payload)

    df_encoded = df_encoded.to_pandas()
    # Test with 10 errors
    index = df_encoded.sample(error_count, random_state=error_count).index
    df_encoded = df_encoded.drop(index)
    assert payload == algorithm.decode(
        pl.from_pandas(df_encoded)
    ), f"with error count = {error_count}"


@pytest.mark.parametrize("error_count", range(1, 100, 10))
def test_with_deletion_high_bit_per_row(df, error_count):
    """At bit_per_row=10 a packet spans only 37 rows, so deletions kill even
    fewer packets than in the bit_per_row=4 sweep above.
    """

    payload = b"hello"
    algorithm = BitPool(bit_per_row=10, seed=error_count)
    df_encoded = algorithm.encode(df, payload=payload)

    df_encoded = df_encoded.to_pandas()
    index = df_encoded.sample(error_count, random_state=error_count).index
    df_encoded = df_encoded.drop(index)
    assert payload == algorithm.decode(
        pl.from_pandas(df_encoded)
    ), f"with error count = {error_count}"
