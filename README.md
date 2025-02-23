
# Steganodf 

A steganography tool for hiding a message in a dataset, such as CSV or parquet file..

This tool hides a payload by permuting the rows of the dataset. The is tolerant
to modification thanks to a Reed-Solomon code and a Luby-s LT fontain code.

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

steganodf encode -i iris.csv -o iris.w.csv -m hello -p password
steganodf decode -i iris.w.csv -p password

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




