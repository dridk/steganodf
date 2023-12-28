import polars as pl 
from glob import glob
import os

def load_parameters():

    dfs = []
    ids = []
    
    for file in glob("examples/*.csv"):
        dfs.append(pl.read_csv(file))
        ids.append(os.path.basename(file))

    return dfs, ids

