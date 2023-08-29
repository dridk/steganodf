"""A dumb method"""


def encode(df: pd.DataFrame, writer: callable, message: str, password: None | str = None):
    encoded_df = df
    writer(encoded_df)


def decode(df: pd.DataFrame, password: None | str) -> str:
    return "all your bases are belong to us"

