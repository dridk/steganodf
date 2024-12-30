import polars as pl

from steganodf.algorithms.algorithm import Algorithm
from .algorithms import ALGORITHMS, BitPool


def encode(df: pl.DataFrame, payload: bytes, algorithm: str = "bitpool", **kwargs) -> pl.DataFrame:

    Algo = ALGORITHMS[algorithm]
    algo = Algo(**kwargs)
    return algo.encode(df, payload)


def decode(df: pl.DataFrame, algorithm: str = "bitpool", **kwargs) -> bytes:

    Algo = ALGORITHMS[algorithm]
    algo = Algo(**kwargs)
    return algo.decode(df)
