from typing import Callable, Iterable
import more_itertools as more
from numpy import remainder
import pandas as pd
import hashlib
import hmac


class WatermarkingError(Exception):
    pass


def _is_duplicated(indexes: list) -> bool:
    """Check is there are duplicated elements"""
    return len(indexes) != len(set(indexes))


def _create_hash_fct(
    hash_algorithm: str = "sha256", password: str | None = None
) -> Callable:
    """Create a hash fuction

    Args:
        hash_algorithm(str): Any string name supported by hashlib
        password(str): If defined, use HMAC hash methods

    Return:
        A hash function
    """
    if password is None:
        # Create a standard hash function
        hash_function = lambda x: hashlib.new(
            hash_algorithm, str(x).encode()
        ).hexdigest()

    else:
        # Create a hmac hash function
        hash_function = lambda x: hmac.new(
            password.encode(), msg=str(x).encode(), digestmod=hash_algorithm
        ).hexdigest()

    return hash_function


def encode_index(indexes: list, message: str) -> list:
    """Encode a message by permutation

    This function read the list in block of 6 lines.
    With 6 items, you have 6!=720 possible permutation which is enough to store
    1 byte = 256 first permutations.
    For each block of 6, it encode the message as a bytearray.

    Todo :
        Add blocksize as argument

    Args:
        indexes(list): a list of unique index
        message(str): the message to store
    Return:
        A new indexes with message encoded
    """

    if _is_duplicated(indexes):
        raise IndexError("No duplicated elements are allowed")

    size = len(list(indexes))
    msg = message.encode()

    block_size = 6
    msg_index = 0
    output_list = []

    n_block = size // block_size

    if len(msg) > n_block:
        raise WatermarkingError(f"Cannot store a message more than {n_block} bytes ")

    i = 0
    for i in range(0, size // block_size * block_size, block_size):
        block = indexes[i : i + block_size]

        if msg_index < len(msg):
            a_bytes = msg[msg_index]
            transform_block = more.nth_permutation(block, block_size, a_bytes)
            msg_index += 1

        else:
            transform_block = block

        output_list += transform_block

    # Add remainder
    output_list += indexes[i + block_size : size]

    return output_list


def decode_index(indexes: list, sort_indexes: list | None = None) -> str:
    """
    Differential decoding by comparing indexes and sorted indexes

    Args:
        indexes(list): a list of unique index values
        sort_indexes(list): Same list with a different order

    Return:
        The watermark message
    """
    if sort_indexes is None:
        sort_indexes = sorted(indexes)

    size = len(indexes)
    block_size = 6
    message = ""

    for i in range(0, size // block_size * block_size, block_size):
        u_block = indexes[i : i + block_size]
        s_block = sort_indexes[i : i + block_size]
        a_byte = more.permutation_index(u_block, s_block)

        if a_byte != 0:
            message += chr(a_byte)

    return message


def encode_pandas(
    df: pd.DataFrame,
    message: str,
    password: str | None = None,
    hash_algorithm: str = "sha256",
) -> pd.DataFrame:
    """
    Store a secret message in dataframe by row permutation.

    This function use encode_index to store a message in a dataframe.
    The dataframe is sorted by hash value of each row with a user defined algorithm.
    Then it uses this sorted dataframe as reference and computed a new sorted
    dataframe with the message encoded inside.

    Args:
        df(pd.DataFrame): dataframe to watermark
        message: message to encode
        password(str): If defined, use a HMAC hash function.
        hash_algorithm(str): Algorithm name supported by hashlib
    Return:
        watermarked dataframe

    """

    hash_function = _create_hash_fct(hash_algorithm, password)
    hash_df = df.copy()
    hash_df["hash"] = hash_df.applymap(str).sum(axis=1).apply(hash_function)
    hash_df = hash_df.sort_values("hash").reset_index(drop=True)

    h = hash_df[hash_df["hash"].duplicated()]["hash"].squeeze()

    new_index = encode_index(hash_df.index.to_list(), message)

    hash_df.iloc[new_index].to_csv("/tmp/test.csv")
    return hash_df.iloc[new_index].drop("hash", axis=1).reset_index(drop=True)


def decode_pandas(
    df: pd.DataFrame, hash_algorithm: str = "sha256", password=None
) -> str:
    """
    Extract watermark from a dataframe

    Args:
        df(pd.DataFrame): DataFrame with a watermark
        hash_algorithm(str): hashlib algorithm name
        password(str): hmac password if required

    Raise:
        NoWatermarkFound
    Return:
        The watermark message


    """
    hash_function = _create_hash_fct(hash_algorithm, password)
    hash_df = df.copy()
    hash_df["hash"] = hash_df.applymap(str).sum(axis=1).apply(hash_function)
    hash_df = hash_df.sort_values("hash").reset_index(names="origin_index")

    try:
        message = decode_index(
            hash_df.index.to_list(), hash_df["origin_index"].to_list()
        )
    except:
        raise WatermarkingError("Cannot find a watermark")

    return message
