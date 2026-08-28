
# Steganodf 

[![PyPi Version](https://img.shields.io/pypi/v/steganodf.svg)](https://pypi.python.org/pypi/steganodf/)
[![PyPi Python Versions](https://img.shields.io/pypi/pyversions/yt2mp3.svg)](https://pypi.python.org/pypi/steganodf/)


A steganography tool for hiding a message in a dataset, such as csv or parquet files.

This tool hides a payload by permuting the rows of the dataset. The is tolerant
to modification thanks to a [Reed-Solomon code](https://en.wikipedia.org/wiki/Reed%E2%80%93Solomon_error_correction) and a [Luby-s LT fontain code](https://en.wikipedia.org/wiki/Luby_transform_code).

# Demo 

You can  experiment with the Python API using this [Google Colab notebook](https://colab.research.google.com/drive/1cp0WaIOO7Xj3ObwR9vr4Nae5KSwyW61e?usp=sharing). 


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
 
df = pl.read_parquet("my_dataset.parquet")

# The payload is bytes, not str
new_df = steganodf.encode(df, b"made by steganodf", password="secret")

# Extract your message from the watermarked dataframe
message = steganodf.decode(new_df, password="secret")

```

## How much data can I hide?

The payload is written as packets of `header + data + crc + correction` bytes, each
packet spanning `packet_size * 8 / bit_per_row` rows. With the default settings a
packet is 46 bytes, so the dataframe needs **at least 368 rows** to hold anything at
all (184 rows with `bit_per_row=2`, 92 with `bit_per_row=4`). `encode` raises an
`AlgorithmError` when the dataframe is too small.

`bit_per_row` can be any value from 1 to 16: the packets are written as a
continuous bit stream, so it does not need to divide 8. Each row carries
`bit_per_row` bits, but each of the `2**bit_per_row` hash values must occur often
enough in the dataframe, which caps the useful range around
`log2(row_count) - 4` (e.g. `bit_per_row=8` for 10 000 rows, an ~8x capacity
gain over the default).

```python
from steganodf.algorithms import BitPool

algorithm = BitPool(bit_per_row=2, password="secret")
algorithm.get_max_payload_size(df)   # safe payload size, in bytes
```

`decode` returns empty bytes when no complete message could be recovered. Use
`BitPool.decode_details(df)` to tell "no watermark" apart from a successful read.

## Limitations

- The message lives in the **order of the rows**. Sorting, deduplicating or
  repartitioning the dataset erases it — no password needed, no data lost.
- The row fingerprint is computed from the concatenation of the columns **in their
  current order**, so reordering, adding or renaming columns also erases it.
- Without a `password` the fingerprint is a plain MD5: anyone can read the message
  and rewrite their own.

## Citation
Sacha Schutz, Meganne Souprayen. Watermark tabular datasets with rows permutations and fountain code. TechRxiv. April 28, 2025.
DOI: 10.36227/techrxiv.174585796.61215338/v1
[Watermark tabular datasets with rows permutations and fountain code
computing and processing](https://www.techrxiv.org/doi/full/10.36227/techrxiv.174585796.61215338/v1)



