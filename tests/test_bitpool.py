import polars as pl
from steganodf.algorithms.bitpool import BitPool

def test_encode():

	payload = b"hello"
	df = pl.DataFrame({"a": range(10)})

	model = BitPool()
	
	df_encoded = model.encode(df, payload=payload)


	#assert model.decode(df_encoded) == payload

