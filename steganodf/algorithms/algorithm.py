import polars as pl

class Algorithm:

    def __init__(self, **kwargs):
        pass 

    @classmethod
    def name(cls):
        return cls.__name__
    
    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        raise NotImplementedError()

    def decode(self, df: pl.DataFrame) -> bytes:
        raise NotImplementedError()

    
