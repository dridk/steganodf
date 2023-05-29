from steganodf import encode_index, decode_index, encode_pandas, decode_pandas
import pandas as pd
import os


def test_encode_and_decode():
    indexes = list(range(100))
    exp_msg = "hi"

    # test encoding
    encoded = encode_index(indexes, exp_msg)
    assert type(encoded) == list

    # test decoding
    obs_msg = decode_index(encoded)
    assert exp_msg == obs_msg


def test_encode_and_decode_pandas():
    exp_msg = "hi"
    df = pd.read_csv(
        "https://gist.githubusercontent.com/netj/8836201/raw/6f9306ad21398ea43cba4f7d537619d0e07d5ae3/iris.csv"
    )

    # Without password
    encoded = encode_pandas(df, exp_msg)
    msg = decode_pandas(encoded)
    assert exp_msg == msg

    # With password
    encoded = encode_pandas(df, exp_msg, password="secret")
    msg = decode_pandas(encoded, password="secret")
    assert exp_msg == msg


def test_decode_csv():
    path = os.path.join(os.getcwd(), "examples", "iris.watermark.csv")

    df = pd.read_csv(path)

    secret = decode_pandas(df)

    assert secret == "made by steganodf"
