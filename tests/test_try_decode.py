import logging

import polars as pl
import pytest

import steganodf as st
from steganodf.algorithms.algorithm import AlgorithmError


PAYLOAD = b"made by steganodf"


@pytest.fixture
def text_df() -> pl.DataFrame:
    """A frame bitvote and bitghost cannot carry a watermark in: no numeric column."""
    return pl.DataFrame({"name": [f"row-{i}" for i in range(100)], "tag": ["x"] * 100})


@pytest.mark.parametrize("algorithm", ["bitpool", "bitsync", "bitvote", "bitghost"])
def test_finds_the_algorithm_used(df: pl.DataFrame, algorithm):
    """The whole point: recover the message without being told which of the four
    algorithms wrote it."""
    encoded = st.encode(df, PAYLOAD, algorithm=algorithm)

    result = st.try_decode(encoded)

    assert result["success"] is True
    assert result["payload"] == PAYLOAD
    assert result["algorithm"] == algorithm


@pytest.mark.parametrize("algorithm", ["bitpool", "bitsync", "bitvote", "bitghost"])
def test_decode_auto(df: pl.DataFrame, algorithm):
    encoded = st.encode(df, PAYLOAD, algorithm=algorithm)
    assert st.decode(encoded, algorithm="auto") == PAYLOAD


def test_password_is_passed_to_every_candidate(df: pl.DataFrame):
    encoded = st.encode(df, PAYLOAD, algorithm="bitghost", password="secret")

    result = st.try_decode(encoded, password="secret")

    assert result["payload"] == PAYLOAD
    assert result["algorithm"] == "bitghost"


def test_unwatermarked_frame_fails(df: pl.DataFrame):
    result = st.try_decode(df)

    assert result["success"] is False
    assert result["payload"] == b""
    assert result["algorithm"] is None
    assert result["tried"] == list(st.AUTO_ORDER)


def test_wrong_password_fails(df: pl.DataFrame):
    encoded = st.encode(df, PAYLOAD, algorithm="bitvote", password="secret")

    result = st.try_decode(encoded, password="wrong")

    assert result["success"] is False
    assert result["algorithm"] is None


def test_only_one_warning_is_logged(df: pl.DataFrame, caplog):
    """Each losing candidate logs an alarming warning of its own, which is noise
    when failing is the expected outcome of three tries out of four."""
    with caplog.at_level(logging.WARNING):
        st.try_decode(df)

    assert len(caplog.records) == 1


def test_candidates_that_cannot_run_are_skipped(text_df: pl.DataFrame):
    """bitvote needs a numeric column and bitghost a Float64 one; on a text-only
    frame they must be left out rather than raise."""
    result = st.try_decode(text_df)

    assert result["success"] is False
    assert result["tried"] == ["bitpool", "bitsync"]


def test_arguments_are_filtered_per_algorithm(df: pl.DataFrame):
    """`column` is a bitvote/bitghost argument; bitpool would reject it outright."""
    encoded = st.encode(df, PAYLOAD, algorithm="bitpool")

    result = st.try_decode(encoded, column="a")

    assert result["payload"] == PAYLOAD
    assert result["algorithm"] == "bitpool"


def test_restricted_candidate_list(df: pl.DataFrame):
    encoded = st.encode(df, PAYLOAD, algorithm="bitpool")

    result = st.try_decode(encoded, algorithms=["bitvote", "bitghost"])

    assert result["success"] is False
    assert result["tried"] == ["bitvote", "bitghost"]


def test_unknown_argument_is_refused(df: pl.DataFrame):
    """Swallowing a typo would mean decoding without the password the caller meant."""
    with pytest.raises(AlgorithmError):
        st.try_decode(df, passwrod="secret")


def test_unknown_algorithm_name_is_refused(df: pl.DataFrame):
    with pytest.raises(AlgorithmError):
        st.try_decode(df, algorithms=["bitpool", "nawak"])


def test_encoding_with_auto_is_refused(df: pl.DataFrame):
    with pytest.raises(AlgorithmError):
        st.encode(df, PAYLOAD, algorithm="auto")
