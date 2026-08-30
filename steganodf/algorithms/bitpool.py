from typing import Callable, List, Dict, Tuple
import polars as pl
import logging
import hashlib
from reedsolo import RSCodec
import hmac
from struct import unpack
import io
import math
import random
import binascii
from collections import Counter
from steganodf.algorithms.algorithm import AlgorithmError
from steganodf.algorithms.permutation_algorithm import PermutationAlgorithm
from steganodf import lt

"""
This algorithm encode bits on each row of a dataframe by permutation.
The payload is split into multiple data packet and write into the row using a
fontain code LT. A Reed solomon error correction code is also added.  
This ensure the tolerence to error and cropping.

A standard packet is composed as follow :

 +--------------+----------------------------+------------------+
 |   HEADER     |      DATA (user)    | CRC  | CORRECTION (user) |
 |   12 bytes   |       20 bytes      | 4 b  | 10 bytes          |
 +--------------+----------------------------+-------------------+

A payload that fits in a single data block skips the LT fountain entirely and
uses the short-mode packet instead, where a single valid packet recovers the
whole message :

 +---------+-------+--------------------+------+-------------------+
 |  NONCE  |  LEN  |   DATA (user)      | CRC  | CORRECTION (user) |
 |  2 bytes|  1 b  |   19 bytes         | 4 b  | 10 bytes          |
 +---------+-------+--------------------+------+-------------------+

In both modes the block is scrambled with a pad derived from its own varying
field (blockseed or nonce) before the CRC and correction code are computed, so
that every packet consumes the pool queues uniformly (see scramble_block). The
packet is then written as a continuous bit stream, bit_per_row bits per row.
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
        seed: int = None,
        sort_columns: bool = True,
        **kwargs,
    ):
        """
        Initialize an instance of PermutationAlgorithm

        Args:
            bit_per_row (int): Number of bits per line, between 1 and 16. Default is 1.
                The practical upper bound is set by the dataframe: each of the
                2**bit_per_row hash values must occur often enough, which caps it
                around log2(row_count) - 3.
            data_size (int): Data size of the packet in byte. Defaut is 20.
            correction_size (int): Correction size of the packet in byte. Default is 10.
            hash_function (Callable): Hash function to use. Default is MD5.
            password (str, optional) : Password used for hashing function with a HMAC algorithm.
            reverse_reading (bool): Read the dataframe also in the reverse direction. It doubles the computation time.
            seed (int, optional): Seed of the random generator used at encoding time. Encoding
                is random by default; setting a seed makes it reproducible. Decoding never
                depends on it.
            sort_columns (bool): Sort the columns by name before hashing each row, so the
                watermark survives a reordering of the columns. Default is True. Set it to
                False to keep the fingerprint sensitive to the physical column order.
                Encoding and decoding must use the same value.
        """
        super().__init__(**kwargs)

        self._hash_function = hash_function
        self._password = password
        self._bit_per_row = bit_per_row
        self._random = random.Random(seed)

        self._data_size = data_size
        self._correction_size = correction_size
        # cannot be change.. Value from lt-decode
        self._header_size = 12
        # cannot be change .. Value from CRC32
        self._crc_size = 4
        # short-mode packets: random nonce feeding the scrambling
        self._nonce_size = 2

        # Read also in reverse
        self._reverse_reading = reverse_reading

        self._sort_columns = sort_columns

        if not 1 <= self._bit_per_row <= 16:
            raise AlgorithmError("bit_per_row must be between 1 and 16")

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

        nbytes = (self._bit_per_row + 7) // 8
        digest = int.from_bytes(hash.digest()[:nbytes], "big")
        return digest >> (nbytes * 8 - self._bit_per_row)

    def get_packet_size(self, short: bool = False) -> int:
        """
        Return size of a complete packet.

        Args:
            short (bool): Size of a short-mode packet (nonce + length + data)
                instead of a standard LT packet. See `_encode`.
        """
        if short:
            data = self._nonce_size + 1 + (self._data_size - 1)
        else:
            data = self._header_size + self._data_size
        return data + self._crc_size + self._correction_size

    def scramble_block(self, block: bytes, seed_start: int = 8, seed_size: int = 4) -> bytes:
        """
        XOR the whole block with a pad derived from its own seed field — the LT
        blockseed (bytes 8 to 11) for a standard packet, the nonce (bytes 0 to 1)
        for a short-mode packet — which changes with every packet. The seed field
        itself is left in clear so the decoder can regenerate the pad. The
        operation is its own inverse.

        Without it, packets repeat themselves: the header fields (filesize,
        blocksize) are identical in every packet, and with a small payload the data
        field only takes a handful of values (XORs of a few source blocks). Repeated
        bytes always consume the same pool queues, and the smallest of those queues
        caps the number of packets that fit — the limiting factor at high
        bit_per_row values. Scrambling makes every packet pseudo-random, so the
        queues are consumed uniformly.
        """
        seed_end = seed_start + seed_size
        pad = b""
        counter = 0
        while len(pad) < len(block):
            pad += hashlib.sha256(block[seed_start:seed_end] + counter.to_bytes(4, "big")).digest()
            counter += 1
        return (
            bytes(a ^ b for a, b in zip(block[:seed_start], pad))
            + block[seed_start:seed_end]
            + bytes(a ^ b for a, b in zip(block[seed_end:], pad[seed_end:]))
        )

    def get_max_theoretical_payload_size(self, df: pl.DataFrame) -> int:
        """
        Return the maximum payload size.
        This is theorically if all bit from the pool are consume by the payload

        Args:
            df (pl.DataFrame) : The host dataframe

        Returns:
            The size in bytes

        """
        max_size = (self.get_total_size_available(df) * self._data_size) // self.get_packet_size()
        return max_size

    @staticmethod
    def _log_poisson_cdf(s: int, lam: float) -> float:
        """
        Return log(P(Poisson(lam) <= s)), computed in log space to avoid underflow.
        """
        if lam <= 0:
            return 0.0
        log_term = -lam  # k = 0
        total = log_term
        for k in range(1, s + 1):
            log_term += math.log(lam) - math.log(k)
            high = max(total, log_term)
            total = high + math.log(math.exp(total - high) + math.exp(log_term - high))
        return min(total, 0.0)

    def estimate_packet_count(self, df: pl.DataFrame, confidence: float = 0.95) -> int:
        """
        Compute how many packets fit in the dataframe before a pool queue runs dry.

        Thanks to the packet scrambling the written symbols are uniformly
        distributed, so after t symbols each of the 2**bit_per_row queues has
        received a Poisson(t / 2**bit_per_row) number of hits. A queue of size s
        survives with probability P(Poisson <= s), and the whole encoding survives
        with the product of those probabilities over the real queue sizes of the
        dataframe. The returned packet count is the largest t (found by binary
        search) for which this survival probability stays above `confidence` —
        a fully deterministic computation, no sampling involved.

        Args:
            df (pl.DataFrame) : The cover dataframe
            confidence (float): Survival probability the estimate guarantees under
                the Poisson model. Default is 0.95.

        Returns:
            The packet count
        """
        pool_count = 2**self._bit_per_row
        sizes = [count for _, count in self.compute_hash(df)["hash"].value_counts().iter_rows()]
        size_frequency = Counter(sizes)
        # hash values that never occur in the dataframe are empty queues
        size_frequency[0] += pool_count - len(sizes)

        log_confidence = math.log(confidence)

        def survives(t: int) -> bool:
            lam = t / pool_count
            total = 0.0
            for size, frequency in size_frequency.items():
                total += frequency * self._log_poisson_cdf(size, lam)
                if total < log_confidence:
                    return False
            return True

        lo, hi = 0, len(df)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if survives(mid):
                lo = mid
            else:
                hi = mid - 1

        symbols_per_packet = (self.get_packet_size() * 8 + self._bit_per_row - 1) // self._bit_per_row
        return lo // symbols_per_packet

    def get_max_payload_size(self, df: pl.DataFrame) -> int:
        """
        Return an empirical estimation of the maximum payload size.

        The packet count is computed against the real pool of the dataframe (see
        `estimate_packet_count`), so the estimate accounts for queue exhaustion at
        high bit_per_row values. The LT fountain then needs noticeably more encoded
        packets than source blocks to converge, and the sliding window at decoding
        time cannot use the very last rows of the file: the division by 3 is an
        empirical safety margin for that, not a bound (measured at 0 failures over
        125 random dataframes across bit_per_row 1 to 10).

        Args:
            df (pl.DataFrame) : The cover dataframe

        Returns:
            The size in bytes

        """
        packets = self.estimate_packet_count(df)
        return packets * self._data_size // 3

    def compute_hash(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Add a 'hash' column containing the hash fingerprint of the row
        The result depend on the bit_per_row.

        The fingerprint is canonical: the cells are joined with a separator (so
        ("ab", "c") and ("a", "bc") differ), a null is distinguished from an empty
        string, and the columns are sorted by name first unless sort_columns is
        False (so reordering the columns preserves the watermark).

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

        columns = sorted(df.columns) if self._sort_columns else df.columns
        df = df.with_columns(
            pl.concat_str(
                [pl.col(name).cast(pl.Utf8()).fill_null("\x00") for name in columns],
                separator="\x1f",
            )
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

        return pool

    def get_remaining_indexes(self, pool: Dict[int, int], indexes: List[int] = None) -> List[int]:
        """
        Return row indices from the pool which have not been consuming by the encoder
        """
        rows = []
        for k, v in pool.items():
            i = indexes[k]
            rows += v[i:]

        self._random.shuffle(rows)
        return rows

    def bytes_to_rows_count(self, data: bytes) -> int:
        """
        Return line count required for N bytes
        """

        return (len(data) * 8 + self._bit_per_row - 1) // self._bit_per_row

    def is_short_payload(self, payload: bytes) -> bool:
        """
        Return whether the payload fits in a single short-mode packet.
        """
        return len(payload) <= self._data_size - 1

    def _short_blocks(self, payload: bytes):
        """
        Yield an infinite stream of scrambled short-mode blocks.

        When the payload fits in one data block the LT fountain degenerates into
        plain repetition, so its 12-byte header is dead weight. A short-mode block
        replaces it with a 2-byte random nonce (which feeds the scrambling, so the
        repeated packets still consume the pool queues uniformly) and a length
        byte: `nonce + length + payload + zero padding`, one packet is enough to
        recover the whole message.
        """
        body = bytes([len(payload)]) + payload
        body += b"\x00" * (self._data_size - len(body))
        while True:
            nonce = self._random.randrange(1 << (8 * self._nonce_size))
            block = nonce.to_bytes(self._nonce_size, "big") + body
            yield self.scramble_block(block, seed_start=0, seed_size=self._nonce_size)

    def _encode(self, df: pl.DataFrame, payload: bytes) -> Tuple[pl.DataFrame, int]:
        """
        Override method
        Encode a payload in dataframe by permutation

        A payload that fits in a single data block (`is_short_payload`) is written
        as short-mode packets (see `_short_blocks`); a larger one goes through the
        LT fountain.

        Args:
            df(pl.DataFrame): The host dataframe
            payload(bytes): the payload message to hide in the host dataframe

        Return:
            Return the stego dataframe


        """

        new_df = self.compute_hash(df)
        pool = self.create_pool(new_df["hash"].to_list())
        rows = []
        rsc = RSCodec(self._correction_size) if self._correction_size > 0 else None
        block_count = 0
        encode_indexes = [0] * 2 ** (self._bit_per_row)

        short = self.is_short_payload(payload)
        if short:
            blocks = self._short_blocks(payload)
        else:
            lt_seed = self._random.randint(0, (1 << 31) - 2)
            blocks = (
                self.scramble_block(block)
                for block in lt.encode.encoder(io.BytesIO(payload), self._data_size, seed=lt_seed)
            )

        for block in blocks:

            # Add CRC code
            crc = binascii.crc32(block).to_bytes(self._crc_size, "big")
            block += crc
            # Add reed solomon error corection code
            if rsc is not None:
                block = rsc.encode(block)

            old_indexes = encode_indexes.copy()
            try:
                bloc_rows = self.encode_chunk(block, pool, indexes=encode_indexes)
            except NotEnoughBitException:
                encode_indexes = old_indexes
                break

            rows += bloc_rows
            block_count += 1

        if block_count == 0:
            packet_size = self.get_packet_size(short=short)
            packet_bits = packet_size * 8
            required = (packet_bits + self._bit_per_row - 1) // self._bit_per_row
            raise AlgorithmError(
                f"Not a single {packet_size} bytes packet could be encoded. "
                f"At bit_per_row={self._bit_per_row} a packet spans {required} rows, and the "
                f"dataframe has {len(df)} — each of the {2 ** self._bit_per_row} hash values "
                "must also occur often enough. Lower correction_size/data_size, raise "
                "bit_per_row, or use a larger dataframe."
            )

        remains = self.get_remaining_indexes(pool, encode_indexes)
        rows += remains
        return df[rows], block_count

    def _iter_packets(self, hashes: List[int], rsc, packet_size: int):
        """
        Slide a packet-sized window over the symbol stream and yield every
        candidate that passes Reed-Solomon and CRC32, still scrambled and
        stripped of its CRC.
        """
        window = (packet_size * 8 + self._bit_per_row - 1) // self._bit_per_row
        for i in range(0, len(hashes) - window + 1):
            # The window is rounded up in rows, so drop the padding bytes
            block = self.decode_chunk(hashes[i : i + window])[:packet_size]

            try:
                packet = rsc.decode(block)[0] if rsc is not None else block
            except Exception:
                continue

            crc = packet[-self._crc_size :]
            read_crc = binascii.crc32(packet[: -self._crc_size]).to_bytes(self._crc_size, "big")

            # The CRC covers the scrambled block; unscramble only after checking it
            if crc == read_crc:
                yield packet[: -self._crc_size]

    def _decode_short(self, hashes: List[int], rsc) -> Dict:
        """
        Look for short-mode packets. A single valid packet carries the whole
        message, so the first hit wins.
        """
        for body in self._iter_packets(hashes, rsc, self.get_packet_size(short=True)):
            body = self.scramble_block(body, seed_start=0, seed_size=self._nonce_size)
            length = body[self._nonce_size]
            data = body[self._nonce_size + 1 :]

            # The zero padding doubles as a validity check on top of the CRC
            if length <= len(data) and not any(data[length:]):
                return {
                    "payload": data[:length],
                    "success": True,
                    "block_count": 1,
                    "mode": "short",
                }

        return {"payload": b"", "success": False, "block_count": 0, "mode": None}

    def _decode_standard(self, hashes: List[int], rsc) -> Dict:
        """
        Look for standard LT packets and feed them to the fountain decoder.
        """
        decoder = lt.decode.LtDecoder()
        success = False
        valid_blocks = 0
        for body in self._iter_packets(hashes, rsc, self.get_packet_size()):
            body = self.scramble_block(body)

            # The LT header is (filesize, blocksize, blockseed); see lt/encode/__init__.py
            filesize, blocksize, blockseed = unpack("!III", body[: self._header_size])
            data = body[self._header_size :]

            if blocksize == len(data):
                valid_blocks += 1
                stream = io.BytesIO(body)
                header = lt.decode._read_header(stream)
                block = lt.decode._read_block(header[1], stream)
                decoder.consume_block((header, block))

                if decoder.is_done():
                    success = True
                    break

        # A partially filled LT decoder cannot produce a partial message: its
        # `bytes_dump` would silently concatenate the blocks it did resolve, yielding
        # shifted, corrupted output. Only dump it once belief propagation converged.
        payload = decoder.bytes_dump() if success else b""

        return {
            "payload": payload,
            "success": success,
            "block_count": valid_blocks,
            "mode": "standard" if success else None,
        }

    def _decode(self, df: pl.DataFrame) -> bytes:
        """
        Override method

        Decode a payload in dataframe by permutation.

        The short-mode pass runs first (its first valid packet ends the search);
        the standard LT pass only runs when it found nothing.

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

        rsc = RSCodec(self._correction_size) if self._correction_size > 0 else None

        result = self._decode_short(hash, rsc)
        if result["success"]:
            return result

        return self._decode_standard(hash, rsc)

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

        Return:
            Return the payload in bytes, or an empty bytes object if no complete
            message could be recovered. Use `decode_details` to know which one it is.
        """
        result = self.decode_details(df)
        return result["payload"]

    def decode_details(self, df: pl.DataFrame) -> Dict:
        """
        Decode the payload and report how the decoding went.

        Args:
            df(pl.DataFrame): The host dataframe

        Return:
            A dict with the `payload` (bytes), whether the message was fully
            reconstructed (`success`), how many valid packets were read
            (`block_count`), and the packet `mode` used ("short" for a payload
            that fits in one packet, "standard" for the LT fountain, None on
            failure).
        """
        result = self._decode(df)
        if not result["success"]:
            logging.warning(
                "No complete message could be decoded (%d valid packet(s) read). "
                "The dataframe may not be watermarked, the password may be wrong, "
                "or the rows may have been reordered.",
                result["block_count"],
            )
        return result

    def encode_chunk(
        self, chunk: bytes, pool: Dict[int, List[int]], indexes: List[int] = None
    ) -> List[int]:
        """
        Encode a chunk of bytes in row permutation.
        This methods consumes bytes from the pool and return row indexes.

        The chunk is read as one continuous bit stream, least significant bit
        of each byte first, cut into groups of `bit_per_row` bits. A group may
        straddle two bytes, so `bit_per_row` does not need to divide 8; the
        last group is zero-padded.

        >>> algo = BitPool(bit_per_row=2)
        >>> algo.encode_chunk(b'hi', {0:[1,3,4,12,13,14,15,16], 1:[0,2,5,17,18,19], 2:[6,7,8,20,21,22], 3:[9,10,11,23,24]})
        [1, 6, 7, 0, 2, 8, 20, 5]
        >>> algo = BitPool(bit_per_row=3)
        >>> algo.encode_chunk(b'h', {0:[10], 1:[11], 2:[], 3:[], 4:[], 5:[12], 6:[], 7:[]})
        [10, 12, 11]
        """

        # List of row indexes to returnes
        #
        if indexes is None:
            indexes = [0] * (2**self._bit_per_row)

        rows = []
        bits = int.from_bytes(chunk, "little")
        mask = 2 ** (self._bit_per_row) - 1
        for pos in range(0, len(chunk) * 8, self._bit_per_row):
            v = (bits >> pos) & mask
            try:
                rows.append(pool[v][indexes[v]])
                indexes[v] += 1
            except Exception:
                raise NotEnoughBitException("Not enough bits to encode data ")
        return rows

    def decode_chunk(self, hashes: List[int]) -> bytes:
        """
        Decode chunk from row hashes values.

        Args:
            hashes(list): the hash list comming from the hash column in encoded dataframe

        >>> algo = BitPool(bit_per_row=3)
        >>> algo.decode_chunk([0, 5, 1])
        b'h'
        """
        bits = 0
        for i, value in enumerate(hashes):
            bits |= value << (i * self._bit_per_row)

        # Keep complete bytes only, dropping the trailing padding bits
        nbytes = len(hashes) * self._bit_per_row // 8
        bits &= (1 << (nbytes * 8)) - 1
        return bits.to_bytes(nbytes, "little")

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
