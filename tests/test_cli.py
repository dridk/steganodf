from steganodf import PayloadError
from steganodf.__main__ import cli 
import pytest


def test_cli(capfd):
    args = ["encode", "-i", "./examples/iris.csv", "-o", "/tmp/iris.w.csv", "-m", "hello"]
    cli(args)

    args = ["decode", "-i", "/tmp/iris.w.csv"]
    cli(args)
    out, _ = capfd.readouterr()

    assert  out.strip() == "hello"



def test_cli_password(capfd):

    message = "hello"
    secret = "secret"

    args = ["encode", "-i", "./examples/iris.csv", "-o", "/tmp/iris.w.csv", "-m",message, "-p", secret]
    cli(args)
    
    # Good password 
    args = ["decode", "-i", "/tmp/iris.w.csv", "-p",secret]
    cli(args)
    out, _ = capfd.readouterr()
    assert out.strip() == message
    
    # Wrong password
    with pytest.raises(PayloadError):
        args = ["decode", "-i", "/tmp/iris.w.csv", "-p", "wrong_secret"]
        cli(args)

