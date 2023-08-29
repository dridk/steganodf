"""A dumb method"""
import pandas as pd


def encode(df: pd.DataFrame, message: str, password: None | str = None) -> pd.DataFrame:
    encoded_df = df
    return encoded_df


def decode(df: pd.DataFrame, password: None | str) -> str:
    return "all your bases are belong to us"

