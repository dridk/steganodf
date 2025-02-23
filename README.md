
# Steganodf 

[![PyPi Version](https://img.shields.io/pypi/v/steganodf.svg)](https://pypi.python.org/pypi/steganodf/)
[![PyPi Python Versions](https://img.shields.io/pypi/pyversions/yt2mp3.svg)](https://pypi.python.org/pypi/steganodf/)


A steganography tool for hiding a message in a dataset, such as csv or parquet files.

This tool hides a payload by permuting the rows of the dataset. The is tolerant
to modification thanks to a [Reed-Solomon code](https://en.wikipedia.org/wiki/Reed%E2%80%93Solomon_error_correction) and a [Luby-s LT fontain code](https://en.wikipedia.org/wiki/Luby_transform_code).

# Online demo 

Steganodf is available as a static web page thanks to webAssemby.     
[https://dridk.github.io/steganodf/](https://dridk.github.io/steganodf/)

# Installation 

```
pip install steganodf
```

# Usage 

## From command line 
```bash 

# Encoding 
steganodf encode -m hello host.csv stegano.csv
steganodf encode -m hello host.parquet stegano.parquet 
steganodf encode -m hello -p password host.parquet stegano.parquet 

# Decoding 
steganodf decode stegano.csv
steganodf decode stegano.csv -p password

```

## From Python

```python
import steganodf 
import polars as pl
 
df = pl.read_csv("https://gist.githubusercontent.com/netj/8836201/raw/6f9306ad21398ea43cba4f7d537619d0e07d5ae3/iris.csv")

new_df = steganodf.encode(df, "made by steganodf", password="secret")

# Extract your message 
message = steganodf.decode(df, password="secret")

```




