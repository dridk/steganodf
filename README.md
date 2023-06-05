
# Steganodf 

Steganodf is a tool to hide a secret message in a pandas dataframe by swapping lines. 
It works with permutation of block of 6 lines (720 combinaisons) to store 1 byte. 

The dataframe is first sorted by the computed hash of each line. You can also use HMAC 
if you give a password. This prevents the attacker from finding the secret message. 
Indexes of each block of 6 lines are used as the source of permutation. A byte is then encoded 
as the n-th permutation. 


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
new_df = steganodf.encode_pandas(df, "made by steganodf")

# Decode a message 
message = steganodf.decode_pandas(df)

```
