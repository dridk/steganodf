import pytest
import numpy as np
import polars as pl
import string
import random


@pytest.fixture
def df() -> pl.DataFrame:
    N = 10000
    # Créer un DataFrame Polars à partir des données, avec une graine fixe pour
    # que la suite de tests soit déterministe
    rng = np.random.default_rng(0)
    df = pl.DataFrame({"a": rng.random(N), "b": rng.random(N)})

    return df
