
# Steganodf 

A python package for steganography on tabulated data like CSV files.  

# Installation 

```
pip install steganodf
```

# Usage 

## From command line 
```bash 

steganodf encode -i iris.csv -o iris.w.csv -m hello -p password -a bitpool
steganodf decode -i iris.w.csv -p password -a bitpool

```

## From Python

```python
import steganodf 
import pandas as pd
 
df = pd.read_csv("https://gist.githubusercontent.com/netj/8836201/raw/6f9306ad21398ea43cba4f7d537619d0e07d5ae3/iris.csv")

new_df = steganodf.encode_pandas(df, "made by steganodf", password="secret", algorithm="bitpool")

# Extract your message 
message = steganodf.decode_pandas(df, password="secret")

```


## Algorithms 


### Permutation Methods 
The payload is hidden in the line permutation. There is no data modification.

- BitPool 
an algorithm that assigns a bit to each line with Reed Solomon error correction

- BitBlock 
an algorithm that permutes each block of 6 lines to encode a byte.

### Alteration methods 
The payload is hidden by minimally alternating the data.

In progress
