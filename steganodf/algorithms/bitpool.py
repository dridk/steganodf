from typing import Callable, List
import polars as pl
import logging
import hashlib
from reedsolo import RSCodec, ReedSolomonError
import hmac
from steganodf.algorithms.algorithm import AlgorithmError
from steganodf.algorithms.permutation_algorithm import PermutationAlgorithm

class BitPool(PermutationAlgorithm):


    def __init__(self, hash_function : Callable = hashlib.md5, password:str = None, **kwargs):
        super().__init__(**kwargs)

        self._hash_function = hash_function
        self._password = password

        
    
    def string_to_bit(self, text:str) -> bool:
        """
        Hash a string and return the first bit as boolean. 
        This method is used to associate a bit for each row

        Args:
            text: a string input 

        Returns:
            bool: a bit representation

        >>> algo = BitPool()
        >>> algo.string_to_bit("hi")
        True

        """

        if self._password:
            # Use HMAC if password is set
            hash = hmac.new(self._password.encode(), text.encode(), self._hash_function)
        else:
            hash = self._hash_function(text.encode())

        return bool(hash.digest()[0] % 2)


    def __add_bit_columns(self,df: pl.DataFrame) -> pl.DataFrame:
        """
        Compute bit representation of each row and add it to the dataframe
        """ 

        df = df.with_columns(df.cast(pl.Utf8()).sum_horizontal().map_elements(self.string_to_bit, return_dtype=pl.Boolean).alias("bit"))
        return df
        
    

    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        """
        Override method 

        Encode a payload in dataframe by permutation 

        
        """

        rsc = RSCodec(100)
        payload = rsc.encode(b"hellosacha" + b"\x00")
        print(payload)
        
        df = self.__add_bit_columns(df)
        bits = [bool(i) for i in df["bit"].to_list()]
   
        all_indexes = range(len(df))
        encode_indexes = self.encode_permutation(bits, payload)
        empty_indexes = list(set(all_indexes) - set(encode_indexes))

        encoded_df = pl.concat((df[encode_indexes], df[empty_indexes]))
    
        return encoded_df.select(pl.exclude("bit"))
    

        
    def decode(self, df: pl.DataFrame) -> bytes:

        """
        Override method 

        Decode a payload in dataframe by permutation 

        
        """
        df = self.__add_bit_columns(df)
        bits = [bool(i) for i in df["bit"].to_list()]

        payload = self.decode_permutation(bits)    
        rsc = RSCodec(100)
        payload = rsc.decode(payload)
        
        
        return b"hello"
    


    def encode_permutation(self, bits:List[bool], payload: bytes) -> List[int]:
        '''
        From a random list of bits, returns the indices used to encode the payload

        Args:
            bits: a random list of boolean representing bits 
            payload: any messages
        
        Args: 
            A list of indices 

        Raised: 
            AlgorithmError if bits is not enough

        Examples: 
        We want to reorder a list of bit to encode the payload b'hi' which is written in binary: 01101000 01101001.
        
        >>> algo = BitPool()
        >>> algo.encode_permutation([1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0,1,0], b'hi')
        [1, 0, 2, 3, 4, 5, 7, 9, 11, 6, 8, 13, 10, 15, 17, 12]

       '''
        pool = [(i, v) for i,v in enumerate(bits)]

        def take(pool:list, bit: bool):
            for i, (index, val) in enumerate(pool):
                if val == bit:
                    pool.remove((index,val))
                    return index

        indexes = []
        for byte in payload:    
            bits = [(byte<<i & 128) == 128 for i in range(8)]
            for bit in bits:
                index = take(pool, bit)
                if index is None:
                    raise AlgorithmError("Not enough bits to encode the payload")

                indexes.append(index)
        return indexes


    def decode_permutation(self,bits:List[bool]) -> bytes:
        '''
        Convert a list of boolean to the payload as a bytearray 

        Args:
            bits: a list of boolean representing bits 

        Returns : 
            A payload as a bytearray

        Examples:
        We want to decode the list of bit '01101000 01101001' to the ASCII messsage b'hi'

        >>> algo = BitPool()
        >>> algo.decode_permutation([False,True,True,False,True, False, False, False, False, True, True, False, True, False , False, True])
        b'hi'
            
        '''
        payload = bytearray()
        for i in range(0,len(bits), 8):
            byte = 0
            for j, v in enumerate(bits[i:i+8]):
                byte = byte | (v << (7-j))
            
            payload.append(byte)
        return bytes(payload)                


        
