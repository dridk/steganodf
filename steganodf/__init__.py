import pandas as pd 
import polars as pl

from steganodf.algorithms.algorithm import Algorithm 
from .algorithms import ALGORITHMS, BitPool


ALGORITHMS = {
    "bitpool" : BitPool
}




def encode_polars(df:pl.DataFrame, payload:bytes, algorithm:str = "bitpool", **kwargs)-> pl.DataFrame:

    Algo = ALGORITHMS[algorithm]
    algo = Algo(**kwargs)
    return algo.encode(df, payload)


def decode_polars(df:pl.DataFrame, algorithm: str = "bitpool", **kwargs)-> bytes:
    
    Algo = ALGORITHMS[algorithm]
    algo = Algo(**kwargs)
    return algo.decode(df)
    
def encode_pandas(df:pd.DataFrame, payload:bytes, algorithm:str = "bitpool", **kwargs)-> pd.DataFrame:

    Algo = ALGORITHMS[algorithm]
    algo = Algo(**kwargs)
    return algo.encode(pl.from_pandas(df), payload).to_pandas()


def decode_pandas(df:pd.DataFrame, algorithm: str = "bitpool", **kwargs)-> bytes:
    
    Algo = ALGORITHMS[algorithm]
    algo = Algo(**kwargs)
    return algo.decode(pl.from_pandas(df))
