from typing import Callable, Iterable
import more_itertools as more
from numpy import remainder
import pandas as pd
import hashlib
import hmac


class PayloadError(Exception):
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


def encode_index(indexes: list, payload: str) -> list:
    """Encode a payload by permutation

    This function read the list in block of 6 lines.
    With 6 items, you have 6!=720 possible permutation which is enough to store
    1 byte = 256 first permutations.
    For each block of 6, it encode the payload as a bytearray.

    Todo :
        Add blocksize as argument

    Args:
        indexes(list): a list of unique index
        payload(str): the payload to store
    Return:
        A new indexes with payload encoded
    """

    if _is_duplicated(indexes):
        raise IndexError("No duplicated elements are allowed")

    size = len(list(indexes))
    msg = payload.encode()

    block_size = 6
    msg_index = 0
    output_list = []

    n_block = size // block_size

    if len(msg) > n_block:
        raise PayloadError(f"Cannot store a payload more than {n_block} bytes ")

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
        The watermark payload
    """
    if sort_indexes is None:
        sort_indexes = sorted(indexes)

    size = len(indexes)
    block_size = 6
    payload = ""

    for i in range(0, size // block_size * block_size, block_size):
        u_block = indexes[i : i + block_size]
        s_block = sort_indexes[i : i + block_size]
        a_byte = more.permutation_index(u_block, s_block)

        if a_byte != 0:
            payload += chr(a_byte)

    return payload


def encode_pandas(
    df: pd.DataFrame,
    payload: str,
    password: str | None = None,
    hash_algorithm: str = "sha256",
) -> pd.DataFrame:
    """
    Store a secret payload in dataframe by row permutation.

    This function use encode_index to store a payload in a dataframe.
    The dataframe is sorted by hash value of each row with a user defined algorithm.
    Then it uses this sorted dataframe as reference and computed a new sorted
    dataframe with the payload encoded inside.

    Args:
        df(pd.DataFrame): dataframe to watermark
        payload: payload to encode
        password(str): If defined, use a HMAC hash function.
        hash_algorithm(str): Algorithm name supported by hashlib
    Return:
        watermarked dataframe

    """

    # Create hash function
    hash_function = _create_hash_fct(hash_algorithm, password)

    # Do not edit original
    source_df = df.copy()

    # Remove duplicated rows and keep it for later
    duplicated_df = source_df[source_df.duplicated()]

    # Keep only unique rows
    source_df = source_df[~source_df.duplicated()]

    # compute hash
    source_df["hash"] = source_df.applymap(str).sum(axis=1).apply(hash_function)

    # Sort by hash
    source_df = source_df.sort_values("hash").reset_index(drop=True)

    # Get new encoded index
    new_index = encode_index(source_df.index.to_list(), payload)

    # Get encoded dataframe
    new_df = source_df.iloc[new_index].drop("hash", axis=1)

    # Concat encoded dataframe with the remaining duplicates
    new_df = pd.concat((new_df, duplicated_df)).reset_index(drop=True)

    return new_df


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
        The watermark payload


    """

    # Compute hash function
    hash_function = _create_hash_fct(hash_algorithm, password)

    # keep a copy
    encoded_df = df.copy()

    # remove duplicated rows
    new_df = encoded_df[~encoded_df.duplicated()]

    # Reset index and keep as a new column named 'old'
    new_df = new_df.reset_index(names="old")

    # Compute hash
    new_df["hash"] = new_df.iloc[:, 1:].applymap(str).sum(axis=1).apply(hash_function)

    # Sort values by hash
    new_df = new_df.sort_values("hash").reset_index()

    # Extract payload
    try:
        payload = decode_index(new_df.index.to_list(), new_df["old"].to_list())

    except:
        raise PayloadError("Cannot extract a payload")

    return payload
