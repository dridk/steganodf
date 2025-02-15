from typing import Callable, List, Dict, Tuple
import polars as pl
import logging
import hashlib
from reedsolo import RSCodec
import hmac
from struct import unpack
import io
import copy
import random
import binascii
from steganodf.algorithms.algorithm import AlgorithmError
from steganodf.algorithms.permutation_algorithm import PermutationAlgorithm
from steganodf import lt

"""
This algorithm encode bits on each row of a dataframe by permutation.
The payload is split into multiple data packet and write into the row using a
fontain code LT. A Reed solomon error correction code is also added.  
This ensure the tolerence to error and cropping.

A packet is composed as follow : 

 +--------------+----------------------------+------------------+
 |   HEADER     |      DATA (user)    | CRC  | CORRECTION (user) |
 |   12 bytes   |       20 bytes      | 4 b  | 10 bytes          |
 +--------------+----------------------------+-------------------+

"""


class NotEnoughBitException(Exception):
    pass


class BitPool(PermutationAlgorithm):

    def __init__(
        self,
        bit_per_row: int = 1,
        data_size: int = 20,
        correction_size: int = 10,
        hash_function: Callable = hashlib.md5,
        password: str = None,
        reverse_reading: bool = False,
        **kwargs,
    ):
        """
        Initialize an instance of PermutationAlgorithm

        Args:
            bit_per_row (int): Number of bits per line. Default is 1.
            data_size (int): Data size of the packet in byte. Defaut is 20.
            correction_size (int): Correction size of the packet in byte. Default is 10.
            hash_function (Callable): Hash function to use. Default is MD5.
            password (str, optional) : Password used for hashing function with a HMAC algorithm.
            reverse_reading (bool): Read the dataframe also in the reverse direction. It doubles the computation time.
        """
        super().__init__(**kwargs)

        self._hash_function = hash_function
        self._password = password
        self._bit_per_row = bit_per_row

        self._data_size = data_size
        self._correction_size = correction_size
        # cannot be change.. Value from lt-decode
        self._header_size = 12
        # cannot be change .. Value from CRC32
        self._crc_size = 4

        # Read also in reverse
        self._reverse_reading = reverse_reading

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

    def get_packet_size(self) -> int:
        """
        Return size of a complete packet
        """
        return self._header_size + self._data_size + self._crc_size + self._correction_size

    def get_max_theoretical_payload_size(self, df: pl.DataFrame) -> int:
        """
        Return the maximum payload size.
        This is theorically if all bit from the pool are consume by the payload

        Args:
            df (pl.DataFrame) : The host dataframe

        Returns:
            The size in bytes

        """
        max_size = (self.get_total_size_available(df) * self._data_size) / (self.get_packet_size())
        return max_size

    def get_max_payload_size(self, df: pl.DataFrame) -> int:
        """
        Return an empirical estimation of the maximum payload size.

        Args:
            df (pl.DataFrame) : The cover dataframe

        Returns:
            The size in bytes

        """
        max_size = self.get_max_theoretical_payload_size(df)
        estimate_size = int(max_size // 3)
        return estimate_size

    def find_packet(self, df: pl.DataFrame, max_window=100) -> Tuple[int, int, int]:
        """
        TODO
        """
        pass

    def compute_hash(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Add a 'hash' column containing the hash fingerprint of the row
        The result depend on the bit_per_row.

        Args:
            df (pl.DataFrame): a a cover Dataframe

        Return:
            A new dataframe with the 'hash' column computed.

        >>> algo = BitPool()
        >>> df = pl.DataFrame({"a": range(10)})
        >>> df = algo.compute_hash(df)
        >>> "hash" in df.columns
        True

        """

        df = df.with_columns(
            df.cast(pl.Utf8())
            .sum_horizontal()
            .map_elements(self.hash, return_dtype=pl.UInt32)
            .alias("hash")
        )
        return df

    def create_pool(self, hashes: List[int]) -> Dict[int, int]:
        """
        From a list, create a dictionnary using value as key and index as dict value.
        This is the pool of bit.
        Args:
            hashes(list) : this is the hash column from the dataframe

        >>> algo = BitPool(bit_per_row=2)
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
        Return row indices from the pool which have not been consuming by the encoder
        """
        indexes = []
        for i in pool.values():
            indexes += i

        random.shuffle(indexes)
        return indexes

    def bytes_to_rows_count(self, data: bytes) -> int:
        """
        Return line count required for N bytes
        """

        return len(data) * 8 // self._bit_per_row

    def _encode(self, df: pl.DataFrame, payload: bytes) -> Tuple[pl.DataFrame, int]:
        """
        Override method
        Encode a payload in dataframe by permutation

        Args:
            df(pl.DataFrame): The host dataframe
            payload(bytes): the payload message to hide in the host dataframe

        Return:
            Return the stego dataframe


        """

        if len(payload) < self._data_size:
            logging.info("payload size is smaller than data_size. You will lost capacity")

        new_df = self.compute_hash(df)
        pool = self.create_pool(new_df["hash"].to_list())
        indexes = []
        rsc = RSCodec(self._correction_size)
        data = io.BytesIO(payload)
        block_count = 0
        valid_blocks = []
        for i, block in enumerate(lt.encode.encoder(data, self._data_size)):

            # Add CRC code
            crc = binascii.crc32(block).to_bytes(self._crc_size)
            block += crc
            # Add reed solomon error corection code
            if self._correction_size > 0:
                block = rsc.encode(block)

            try:
                backup_pool = copy.deepcopy(pool)
                bloc_indexes = self.encode_chunk(block, pool)
                indexes += bloc_indexes
                block_count += 1
                valid_blocks.append(block)
            except NotEnoughBitException:
                pool = backup_pool
                break

        remains = self.get_remaining_indexes(pool)
        indexes += remains
        return df[indexes], block_count

    def _decode(self, df: pl.DataFrame) -> bytes:
        """
        Override method

        Decode a payload in dataframe by permutation

        Args:
            df(pl.Dataframe): The host dataframe containing the secret payload

        Returns:
            The secret message as bytes

        """
        # read hash rows
        new_df = self.compute_hash(df)

        # concat with reverse orientation
        # This is same than reading a second time the dataframe from bottom to up
        if self._reverse_reading:
            new_df = pl.concat([new_df, new_df.reverse()])

        hash = new_df["hash"].to_list()

        rsc = RSCodec(self._correction_size)
        decoder = lt.decode.LtDecoder()

        window = (self.get_packet_size()) * 8 // self._bit_per_row
        success = False
        valid_blocks = []
        count = 0
        for i in range(0, len(hash) - window):
            chunk = hash[i : i + window]
            block = self.decode_chunk(chunk)

            try:
                if self._correction_size > 0:
                    packet = rsc.decode(block)[0]
                else:
                    packet = block
            except Exception:
                continue

            header = packet[:12]
            data = packet[12:-4]
            # Check header

            crc = packet[-4:]
            read_crc = binascii.crc32(packet[:-4]).to_bytes(self._crc_size)

            block_count, data_size, uuid = unpack("!III", header)

            if data_size == len(data) and crc == read_crc:
                valid_blocks.append(packet)
                count += 1
                stream = io.BytesIO(packet)
                header = lt.decode._read_header(stream)
                block = lt.decode._read_block(header[1], stream)
                decoder.consume_block((header, block))

                if decoder.is_done():
                    success = True
                    break

        if count == 0:
            payload = b""
        else:
            payload = decoder.bytes_dump()

        return {"payload": payload, "success": success, "block_count": len(valid_blocks)}

    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        """
        Encode a payload in dataframe by permutation

        Args:
            df(pl.DataFrame): The host dataframe
            payload(bytes): the payload message to hide in the host dataframe

        Return:
            Return the stego dataframe
        """
        df, _ = self._encode(df, payload)
        return df

    def decode(self, df: pl.DataFrame) -> bytes:
        """
        Decode the payload from the cover dataframe

        Args:
            df(pl.DataFrame): The host dataframe
            payload(bytes): the payload message to hide in the host dataframe

        Return:
            Return the payload in bytes
        """
        result = self._decode(df)
        return result["payload"]

    def encode_chunk(self, chunk: bytes, pool: Dict[int, List[int]]) -> List[int]:
        """
        Encode a chunk of bytes in row permutation.
        This methods consumes bytes from the pool and return row indexes.

        >>> algo = BitPool(bit_per_row=2)
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

    def get_data_size_available(self, df: pl.DataFrame) -> int:
        """
        Return data part available in bytes
        """

        total = self.get_total_size_available(df)
        packet_count = total // self.get_packet_size()
        return packet_count * self._data_size

    def get_total_size_available(self, df: pl.DataFrame) -> int:
        """
        Return all bytes available

        """
        new_df = self.compute_hash(df)
        count = len(new_df)

        return count * self._bit_per_row // 8

    def get_packet_count(self, payload: str) -> int:
        """
        Return how many packet are required for a payload
        """

        total = len(payload) // self._data_size
        if total <= 0:
            return 1
        else:

            return int(total)

    def get_payload_size(self, payload: str) -> int:
        """
        Return bytes required for the payload
        """

        count = self.get_packet_count(payload)

        return count * self.get_packet_size()
