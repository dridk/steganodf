import pytest
import numpy as np
import polars as pl


@pytest.fixture
def df() -> pl.DataFrame:
    N = 10000
    # Créer un DataFrame Polars à partir des données
    df = pl.DataFrame({"a": np.random.rand(N), "b": np.random.rand(N)})

    return df
