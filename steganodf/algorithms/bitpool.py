from typing import List
import polars as pl
from steganodf.algorithms.algorithm import Algorithm, AlgorithmError
from reedsolo import RSCodec, ReedSolomonError
import logging
import hashlib

class BitPool(Algorithm):


    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._hash_function = hashlib.md5
        
    def string_to_bit(self, text:str) -> bool:
        """
        convert a string to bit using hash function 

        Args:
            text: a string input 

        Returns:
            bool: a bit representation

        """
        return bool(self._hash_function(text.encode()).digest()[0] % 2)

    def find_reed_solo_size(self, bits:List[bool], payload:bytes) -> int:
        """
        Find the number of redundancy bytes to use in reed solomon

        Args:
            bits: pool of bits 
            payload: any message

        Returns:
            int: the size used by RSCodec

        """    
        total_bytes = len(bits) // 8

        while total_bytes > 0:
            rsc = RSCodec(total_bytes)
            solo_payload = rsc.encode(payload)

            try:
                indexes = self.encode_permutation(bits, solo_payload)
            except:
                total_bytes -= 1 
                continue
            break

        return total_bytes
    
    
        
    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        """
        Override method 

        Encode a payload in dataframe by permutation 

        
        """
        df = df.with_columns(df.cast(pl.Utf8()).sum_horizontal().map_elements(self.string_to_bit).alias("bit"))
        bits = [bool(i) for i in df["bit"].to_list()]
   
        size = self.find_reed_solo_size(bits,payload)
        size = len(df) // 8 // 2
        rsc = RSCodec(size)
        solo_payload = rsc.encode(payload)

        logging.info(size)
        logging.info(solo_payload)
        logging.info(len(solo_payload))
    
        all_indexes = range(len(df))
        encode_indexes = self.encode_permutation(bits, solo_payload)
        empty_indexes = list(set(all_indexes) - set(encode_indexes))

        encoded_df = pl.concat((df[encode_indexes], df[empty_indexes]))
    
        return encoded_df.select(pl.exclude("bit"))


    
        
    def decode(self, df: pl.DataFrame) -> bytes:

        """
        Override method 

        Decode a payload in dataframe by permutation 

        
        """
        df = df.with_columns(df.cast(pl.Utf8()).sum_horizontal().map_elements(self.string_to_bit).alias("bit"))
        bits = [bool(i) for i in df["bit"].to_list()]

        S = len(df) // 8 // 2
        rsc = RSCodec( S )
        message = self.decode_permutation(bits)    

    
        for i in range(S, len(df) // 8):
            try:
                message = rsc.decode(message[:i])[0]
                break

            except:
                pass

        return message


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
