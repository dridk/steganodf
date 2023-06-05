
# Steganodf 

This is a tool for hiding a secret message in a tabulated file.
It works by swapping blocks of 6 lines ( 1 bytes ), thus preserving data integrity.

The dataframe is first sorted by the computed hash of each line. HMAC is also supported if you provide a password.
This method does not alter the data, but the watermark is easily sterilized.


# Installation 

```
pip install steganodf
```

# Usage 

## From command line 
```bash 

steganodf encode -i iris.csv -o iris.w.csv -p hello
steganodf decode -i iris.w.csv 

```

## From Python

```python
import steganodf 

 
df = pd.read_csv("https://gist.githubusercontent.com/netj/8836201/raw/6f9306ad21398ea43cba4f7d537619d0e07d5ae3/iris.csv")

# Encode a message
new_df = steganodf.encode_pandas(df, "made by steganodf", password="secret")

# Decode a message 
message = steganodf.decode_pandas(df, password="secret")

```
