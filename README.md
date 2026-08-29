# Steganodf

[![PyPi Version](https://img.shields.io/pypi/v/steganodf.svg)](https://pypi.python.org/pypi/steganodf/)
[![PyPi Python Versions](https://img.shields.io/pypi/pyversions/steganodf.svg)](https://pypi.python.org/pypi/steganodf/)

**Steganodf hides a secret message inside a dataframe.**

Give it a dataframe and a few bytes to hide, steganodf gives you back a dataframe that still looks and reads like the original but
carries your secret message. Anyone with the password (or with none, if you did not set one) can read
the message back out. Typical use: watermarking a dataset you are about to share, so that a leaked
copy can be traced back to the recipient it was issued to.

Hiding data in a table is a trade-off between three properties, and no single scheme wins on all
three at once:

- **Capacity** — how many bytes fit in the dataset.
- **Robustness** — does the message survive what happens to data
- **Invisibility** — how much the original data is distorted, and how easily an observer can tell
  that a watermark is there at all.

Steganodf ships **four algorithms** that sit at different points of that trade-off. 

## Choosing an algorithm

**The three methods:**

- **permutation** — the message lives in the *order of the rows*. Nothing is written to the data
  itself, so the dataset is bit-for-bit the same multiset of rows. The price is that any operation
  that re-orders the table erases the message.
- **alteration** — the message lives in the *least significant bits* of one numeric column. The
  values change, by one unit in the last place, and the row order becomes irrelevant.
- **synthesis** — the message lives in *extra rows* that steganodf fabricates and inserts. Existing
  values are never touched, but the dataset gains records that were not in it.


## Benchmark

Measured on a 100 000-row, 4-column frame (`Int64`, `Utf8`, two `Float64`) with a 16-byte payload.


| Algorithm and settings | Method | Destroys original data  | Max capacity (100k rows) | Tolerates cell edits | Tolerates row deletion | Survives sorting | Invisibility |
|---|---|---|---|---|---|---|---|
| **`bitpool`** `bit_per_row=1`  | permutation | no — rows are only reordered | 4.4 kB | 2 % | 2 % | ❌ | perfect — not one cell changed |
| **`bitpool`** `bit_per_row=8` | permutation | no — rows are only reordered | **29 kB** | 12 % | 20 % | ❌ | perfect — not one cell changed |
| **`bitsync`** default `max_drift` (44 s decode) | permutation | no — rows are only reordered | 2.1 kB | 1.5 % | 4 % | ❌ | perfect — not one cell changed |
| **`bitsync`** `max_drift=256` (5.7 s decode) | permutation | no — rows are only reordered | 2.1 kB | 2 % | 3 % | ❌ | perfect — not one cell changed |
| **`bitvote`** `data_size=24` | alteration | 1 ULP on one numeric column | 19 B | **45 %** | **95 %** | ✅ | very high — relative change of 2.2e-16 |
| **`bitvote`** `data_size=260` | alteration | 1 ULP on one numeric column | 255 B | 15 % | 85 % | ✅ | very high — relative change of 2.2e-16 |
| **`bitghost`** `redundancy=8` | synthesis | +168 fabricated rows | 250 B | 18 % | 50 % | ✅ | low — the fake rows are visible |
| **`bitghost`** `redundancy=32` | synthesis | +672 fabricated rows | 250 B | 40 % | 80 % | ✅ | low — the fake rows are visible |


## Python API

### Installation

```bash
pip install steganodf
```

You can also try the library without installing anything, in this
[Google Colab notebook](https://colab.research.google.com/drive/1cp0WaIOO7Xj3ObwR9vr4Nae5KSwyW61e?usp=sharing).

### Encode and decode

```python
import steganodf
import polars as pl

df = pl.read_parquet("my_dataset.parquet")

# The payload is bytes, not str
watermarked = steganodf.encode(df, b"made by steganodf", password="secret")

# Extract your message from the watermarked dataframe
message = steganodf.decode(watermarked, password="secret")
```

`decode` returns empty bytes when no complete message could be recovered. To tell "this dataframe
carries no watermark" apart from "the watermark was read successfully", use `decode_details`:

```python
from steganodf.algorithms import BitPool

BitPool(password="secret").decode_details(df)
# {'payload': b'made by steganodf', 'success': True, 'block_count': 1, 'mode': 'short'}
```

### Picking an algorithm

Pass `algorithm=` to `encode` and `decode`. Both sides must agree on the algorithm and on every
parameter that affects the framing (`password`, `bit_per_row`, `data_size`, `sort_columns`…).

```python
# A shuffle-resistant watermark
watermarked = steganodf.encode(df, b"made by steganodf", algorithm="bitvote")
shuffled = watermarked.sample(fraction=1.0, shuffle=True)

steganodf.decode(shuffled, algorithm="bitvote")   # b'made by steganodf'
```

For anything beyond the defaults, instantiate the class directly:

```python
from steganodf.algorithms import BitPool, BitSync, BitVote, BitGhost

# 8 bits per row instead of 1: ~7x the capacity on a large dataframe
algorithm = BitPool(bit_per_row=8, password="secret")
algorithm.get_max_payload_size(df)          # conservative estimate, in bytes
watermarked = algorithm.encode(df, b"a much longer message ...")
```

These are the tuned settings of the second row of each algorithm in the table above:

```python
BitPool(bit_per_row=8, password="secret")     # 29 kB instead of 4.4 kB
BitSync(max_drift=256, password="secret")     # 5.7 s instead of 44 s to decode
BitVote(data_size=260, password="secret")     # 255 B instead of 19 B
BitGhost(redundancy=32, password="secret")    # tolerates 80 % of rows being deleted
```

### Decoding without knowing the algorithm

If you receive a watermarked dataframe without being told which algorithm wrote it, pass
`algorithm="auto"`. Every algorithm validates what it reads with a CRC32, so one that was not
used to encode reports a failure rather than returning garbage; steganodf tries them in turn and
stops at the first success.

```python
steganodf.decode(df, algorithm="auto", password="secret")   # b'made by steganodf'
```

`try_decode` does the same thing but also tells you which algorithm matched:

```python
steganodf.try_decode(df, password="secret")
# {'payload': b'made by steganodf', 'success': True, 'votes': 100000,
#  'margin_min': 469, 'algorithm': 'bitvote', 'tried': ['bitvote']}
```

Only the **default** parameters are tried. `bit_per_row`, `data_size` and `redundancy` must match
between encoding and decoding and cannot be guessed, so a dataframe watermarked with
`BitPool(bit_per_row=8)` will not be found by auto decoding — but everything the command line
produces will, since it always uses the defaults. The password is not guessed either.

The candidates are tried cheapest first (`bitvote`, `bitghost`, `bitpool`, `bitsync`), so the slow
ones only run once the fast ones have failed.

### From the command line

```bash
# Encoding
steganodf encode -m hello host.csv stegano.csv
steganodf encode -m hello host.parquet stegano.parquet
steganodf encode -m hello -p password host.parquet stegano.parquet

# Decoding
steganodf decode stegano.csv
steganodf decode stegano.csv -p password

# Choosing an algorithm, and the carrier column for bitvote / bitghost
steganodf encode -m hello -a bitvote -c price host.csv stegano.csv
steganodf decode -a bitvote -c price stegano.csv

# Decoding without knowing the algorithm: tries all four, names the one that matched
steganodf decode -a auto stegano.csv
```

The CLI reads and writes `.csv` and `.parquet`, and exposes `--password`, `--column` and
`--algorithm`. Tuning parameters such as `bit_per_row` or `data_size` are Python-only.

## Algorithms in detail

[DETAIL.md](DETAIL.md) covers each algorithm in turn — what it is built on, what it is good at,
where it breaks — plus the threat model.

## Citation

Sacha Schutz, Meganne Souprayen. *Watermark tabular datasets with rows permutations and fountain
code.* TechRxiv. April 28, 2025. DOI:
[10.36227/techrxiv.174585796.61215338/v1](https://www.techrxiv.org/doi/full/10.36227/techrxiv.174585796.61215338/v1)

```bibtex
@article{schutz2025steganodf,
  title   = {Watermark tabular datasets with rows permutations and fountain code},
  author  = {Schutz, Sacha and Souprayen, Meganne},
  year    = {2025},
  month   = {4},
  journal = {TechRxiv},
  doi     = {10.36227/techrxiv.174585796.61215338/v1},
  url     = {https://www.techrxiv.org/doi/full/10.36227/techrxiv.174585796.61215338/v1}
}
```
