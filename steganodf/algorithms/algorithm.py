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

    def decode_details(self, df: pl.DataFrame) -> dict:
        """
        Decode and report how the decoding went, as a dict with at least the
        `payload` (bytes) and whether it was fully recovered (`success`).
        Algorithms add their own diagnostic keys. This is what tells "no
        watermark" apart from "an empty message", and what `steganodf.try_decode`
        relies on to recognise the algorithm a dataframe was encoded with.
        """
        raise NotImplementedError()

    
