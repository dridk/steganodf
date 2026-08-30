import inspect
import logging
from contextlib import contextmanager
from typing import Dict, List, Optional, Sequence

import polars as pl

from steganodf.algorithms.algorithm import Algorithm, AlgorithmError
from .algorithms import ALGORITHMS, BitPool, BitSync, BitVote, BitGhost

# Order in which try_decode tries the algorithms: cheapest decoder first, so the
# expensive ones only run once the cheap ones have all failed. BitVote and
# BitGhost read the frame once, BitPool tries a Reed-Solomon decode per row
# offset, and BitSync runs a forward-backward pass over the whole stream.
AUTO_ORDER = ("bitvote", "bitghost", "bitpool", "bitsync")

def encode(df: pl.DataFrame, payload: bytes, algorithm: str = "bitpool", **kwargs) -> pl.DataFrame:

    if algorithm == "auto":
        raise AlgorithmError(
            "'auto' only works for decoding. Pick an algorithm to encode with: "
            + ", ".join(ALGORITHMS)
        )

    Algo = ALGORITHMS[algorithm]
    algo = Algo(**kwargs)
    return algo.encode(df, payload)

def decode(df: pl.DataFrame, algorithm: str = "bitpool", **kwargs) -> bytes:

    if algorithm == "auto":
        return try_decode(df, **kwargs)["payload"]

    Algo = ALGORITHMS[algorithm]
    algo = Algo(**kwargs)
    return algo.decode(df)

def try_decode(df: pl.DataFrame, algorithms: Optional[Sequence[str]] = None, **kwargs) -> Dict:
    """
    Decode without knowing which algorithm was used, by trying them all.

    Every algorithm validates what it reads with a CRC32, so a candidate that
    was not the one used to encode reports `success = False` instead of
    returning garbage. The candidates are tried cheapest first and the search
    stops at the first success.

    Only the default framing parameters are tried. `bit_per_row`, `data_size`
    and `redundancy` must match between encoding and decoding, and cannot be
    guessed, so a dataframe encoded with non-default values will not be found.

    Args:
        df(pl.DataFrame): The host dataframe
        algorithms(Sequence[str], optional): Names of the algorithms to try, in
            order. Defaults to `AUTO_ORDER`.
        **kwargs: Passed on to each candidate that accepts them, so `password`
            reaches all four while `column` only reaches bitvote and bitghost.

    Return:
        The `decode_details` dict of the algorithm that succeeded, with two
        extra keys: the `algorithm` that matched (None if none did) and the
        list of algorithms actually `tried`. Candidates that cannot run on this
        dataframe at all, such as bitghost without a Float64 column, are left
        out of `tried`.

    >>> import polars as pl
    >>> df = pl.DataFrame({"a": [0.1, 0.2, 0.3], "b": ["x", "y", "z"]})
    >>> try_decode(df)["success"]
    False
    """
    names = list(AUTO_ORDER) if algorithms is None else list(algorithms)

    unknown = sorted(name for name in names if name not in ALGORITHMS)
    if unknown:
        raise AlgorithmError(f"Unknown algorithm(s): {', '.join(unknown)}")

    # An argument no candidate knows is a typo, and silently ignoring it would
    # mean decoding without the password the caller meant to pass.
    accepted = set()
    for name in names:
        accepted |= _accepted_arguments(ALGORITHMS[name])
    unexpected = sorted(set(kwargs) - accepted)
    if unexpected:
        raise AlgorithmError(f"Unexpected argument(s) for auto decoding: {', '.join(unexpected)}")

    tried: List[str] = []

    with _quiet():
        for name in names:
            Algo = ALGORITHMS[name]
            arguments = {
                key: value for key, value in kwargs.items() if key in _accepted_arguments(Algo)
            }
            try:
                result = Algo(**arguments).decode_details(df)
            except AlgorithmError:
                # This algorithm cannot run here at all, typically because the
                # dataframe has no column it can carry a watermark in.
                continue
            tried.append(name)
            if result["success"]:
                return {**result, "algorithm": name, "tried": tried}

    logging.warning(
        "No complete message could be decoded with any of: %s. The dataframe may not be "
        "watermarked, the password may be wrong, or it may have been encoded with "
        "non-default parameters, which auto decoding cannot guess.",
        ", ".join(tried) if tried else "none of the algorithms",
    )
    return {"payload": b"", "success": False, "algorithm": None, "tried": tried}

def _accepted_arguments(Algo) -> set:
    """
    Named parameters of an algorithm constructor, without `self` and `**kwargs`.

    Every algorithm rejects arguments it does not know, so the kwargs of
    `try_decode` have to be filtered down per candidate.

    >>> sorted(_accepted_arguments(BitGhost) & {"column", "password", "bit_per_row"})
    ['column', 'password']
    """
    parameters = inspect.signature(Algo.__init__).parameters
    return {
        name
        for name, parameter in parameters.items()
        if name != "self"
        and parameter.kind not in (parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL)
    }

@contextmanager
def _quiet():
    """
    Silence the warning each losing candidate logs. When several algorithms are
    tried in a row, most of them failing is the expected outcome, not a problem
    worth reporting; try_decode logs one summary warning instead.
    """
    previous = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        yield
    finally:
        logging.disable(previous)
