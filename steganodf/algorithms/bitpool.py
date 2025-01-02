from typing import Callable, List, Dict
import polars as pl
import hashlib
from reedsolo import RSCodec, ReedSolomonError
import lt
import hmac
import io
import copy
from steganodf.algorithms.algorithm import AlgorithmError
from steganodf.algorithms.permutation_algorithm import PermutationAlgorithm


class NotEnoughBitException(Exception):
    pass


class BitPool(PermutationAlgorithm):

    def __init__(
        self,
        bit_per_row: int = 2,
        hash_function: Callable = hashlib.md5,
        password: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self._hash_function = hash_function
        self._password = password
        self._bit_per_row = bit_per_row

        self._block_size = 20
        self._corr_size = 30

        # Replace separator from payload to avoid collision
        self._separator = b"\xFF"
        self._separator_mask = b"\xF1"
        self._separator_replacement = {
            self._separator: self._separator_mask + b"\xF2",
            self._separator_mask: self._separator_mask + b"\xF3",
        }

        if self._bit_per_row not in (1, 2, 4):
            raise AlgorithmError("bit_per_row must be 1,2 or 4")

    def hash(self, text: str) -> int:
        """
        Compute a fingerprint of a string comming from the concatenation of a row.
        The result depend of the `bit_per_row`. For instance, using 2 bit per row, the result
        must be a value between 0 and 3.

        Args:
            text(str): a string data to hash

        Returns:
            a integer value encoded using `bit_per_row` bits.

        Example:
        >>> algo = BitPool(bit_per_row = 2)
        >>> algo.hash("hello") in (0,1,2,3)
        True

        """

        if self._password:
            # Use HMAC if password is set
            hash = hmac.new(self._password.encode(), text.encode(), self._hash_function)
        else:
            hash = self._hash_function(text.encode())

        digest = hash.digest()[0]
        digest = digest >> (8 - self._bit_per_row)
        return digest

    def mask_separator(self, data: bytes) -> bytes:
        """
        Mask separator symbol by replacing it by 2 new bytes A,B.
        A must also be replace by A and C.

        Args:
            data(bytes) : Unmask bytes sequence

        Returns:
            A byte sequence without separator symbol


        """

        m = self._separator_replacement

        mask_data = data.replace(self._separator_mask, m[self._separator_mask])
        mask_data = mask_data.replace(self._separator, m[self._separator])

        return mask_data

    def unmask_separator(self, data: bytes) -> bytes:
        """
        Unmask separator symbol by replacing the two replacement bytes by the separator

        Args:
            data(bytes) : Mask bytes sequence

        Returns:
            A byte sequence with separator symbol

        """

        m = self._separator_replacement

        mask_data = data.replace(m[self._separator], self._separator)
        mask_data = mask_data.replace(m[self._separator_mask], self._separator_mask)

        return mask_data

    def compute_hash(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Add a 'hash' column containing the hash fingerprint of the row
        The result depend on the bit_per_row.

        Args:
            df (pl.DataFrame): a a Dataframe

        Return:
            A new dataframe with the 'hash' column computed.

        >>> algo = BitPool()
        >>> df = pl.DataFrame({"a": range(10)})
        >>> df = algo.compute_hash(df)
        >>> "hash" in df.columns
        True

        """

        df = df.with_columns(df.cast(pl.Utf8()).sum_horizontal().map_elements(self.hash, return_dtype=pl.UInt32).alias("hash"))
        return df

    def create_pool(self, hashes: List[int]) -> Dict[int, int]:
        """
        From a list of value, create a dictionnary using list index as key and list value as values

        Args:
            hashes(list) : this is the hash column from the dataframe

        >>> algo = BitPool()
        >>> res = algo.create_pool([0,0,1,2,2,3])
        >>> res[0] == [0,1]
        True
        >>> res[1] == [2]
        True
        >>> res[2] == [3,4]
        True
        >>> res[3] == [5]
        True
        """
        pool = {i: list() for i in range(2**self._bit_per_row)}
        for i, v in enumerate(hashes):
            pool[v].append(i)

        # for key in pool.keys():
        #     random.shuffle(pool[key])
        return pool

    def get_remaining_indexes(self, pool: Dict[int, int]) -> List[int]:
        """
        Return row indices which have not been consuming by the encoder
        """
        indexes = []
        for i in pool.values():
            indexes += i

        return indexes

    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        """
        Override method

        Encode a payload in dataframe by permutation
        """

        new_df = self.compute_hash(df)
        # payload = self.mask_separator(payload)
        pool = self.create_pool(new_df["hash"].to_list())

        indexes = []
        rsc = RSCodec(self._corr_size)
        data = io.BytesIO(payload)
        for block in lt.encode.encoder(data, self._block_size):

            # Add reed solomon error corection code
            block = rsc.encode(block)

            # Hide separator
            block = self.mask_separator(block)

            # Add seperator
            block += self._separator
            # consume block until not enough bits
            try:
                backup_pool = copy.deepcopy(pool)
                bloc_indexes = self.encode_chunk(block, pool)
                indexes += bloc_indexes

            except NotEnoughBitException:
                pool = backup_pool
                break

        remains = self.get_remaining_indexes(pool)
        indexes += remains

        return df[indexes]

    def decode(self, df: pl.DataFrame) -> bytes:
        """
        Override method

        Decode a payload in dataframe by permutation

        """
        new_df = self.compute_hash(df)
        raw = self.decode_chunk(new_df["hash"].to_list())

        # Recuperation des block
        blocks = []
        rsc = RSCodec(self._corr_size)

        for block in raw.split(self._separator):
            if block:
                block = self.unmask_separator(block)
                check = rsc.check(block)[0]
                if check is True:
                    block = rsc.decode(block)[0]
                    blocks.append(block)

        blocks = b"".join(blocks)
        data = io.BytesIO(blocks)

        decoder = lt.decode.LtDecoder()
        # print(data, len(data.read()))
        for block in lt.decode.read_blocks(data):
            decoder.consume_block(block)

            if decoder.is_done():
                break

        payload = decoder.bytes_dump()

        return payload

    def encode_chunk(self, chunk: bytes, pool: Dict[int, List[int]]) -> List[int]:
        """
        Encode a chunk of bytes in row permutation.
        This methods consumes bytes from the pool and return row indexes.

        >>> algo = BitPool()
        >>> algo.encode_chunk(b'hi', {0:[1,3,4,12,13,14,15,16], 1:[0,2,5,17,18,19], 2:[6,7,8,20,21,22], 3:[9,10,11,23,24]})
        [1, 6, 7, 0, 2, 8, 20, 5]
        """

        # List of row indexes to returnes
        indexes = []
        for byte in chunk:
            # For each bytes, extract bit to use for encoding
            # For example, using bit_per_row=2, split 1 bytes into 4 part
            # 00101101 ==> 00 , 10, 11, 01 ==> 0, 2, 3, 1

            mask = 2 ** (self._bit_per_row) - 1
            for i in range(0, 8, self._bit_per_row):
                m = mask << i
                v = (byte & m) >> i
                try:
                    indexes.append(pool[v].pop(0))
                except Exception as e:
                    raise NotEnoughBitException("Not enough bits to encode data ")
        return indexes

    def decode_chunk(self, hashes: List[int]) -> bytes:
        """
        Decode chunk from row hashes values.

        Args:
            hashes(list): the hash list comming from the hash column in encoded dataframe

        """
        data = bytearray()
        chunk_size = 8 // self._bit_per_row

        for i in range(0, len(hashes), chunk_size):
            chunk = hashes[i : i + chunk_size]
            byte = 0
            for j, val in enumerate(chunk):
                shift = self._bit_per_row * (j + 1) - self._bit_per_row
                byte |= val << shift
            data.append(byte)

        return data
