import polars as pl


class AlgorithmError(Exception):
    pass


class Algorithm:

    def __init__(self, **kwargs):
        # Subclasses forward the keyword arguments they did not consume. Anything
        # reaching this point is a typo or an option that does not exist: fail loudly
        # instead of silently ignoring it.
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise AlgorithmError(f"Unexpected argument(s) for {self.name()}: {unexpected}")

    @classmethod
    def name(cls):
        return cls.__name__
    
    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        raise NotImplementedError()

    def decode(self, df: pl.DataFrame) -> bytes:
        raise NotImplementedError()

    
