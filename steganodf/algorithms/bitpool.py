import polars as pl

from steganodf.algorithms.permutation_algorithm import PermutationAlgorithm

class BitPool(PermutationAlgorithm):


    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        return df

        
    def decode(self, df: pl.DataFrame) -> bytes:

        return b"hello"
