"""
BitVote: a shuffle-resistant watermark based on majority voting.

Unlike BitPool, the message does not live in the order of the rows but in the
least significant bit of one numeric column (the carrier). Each row is
addressed by a fingerprint of its other columns: the fingerprint selects which
bit of the message the row carries (its slot) and a mask bit, and the carrier
LSB is set to `message_bit XOR mask`. Decoding recomputes the fingerprint of
every row and lets each row vote for its slot; a majority vote per slot
rebuilds the message, which is validated by a CRC32.

The message layout is fixed-size, so the decoder needs no length information:

    LENGTH (1 byte) | PAYLOAD + zero padding (data_size - 5 bytes) | CRC32 (4 bytes)

that is `data_size` bytes = `data_size * 8` voting slots in total.

Because no row position is ever used, the watermark survives any reordering of
the rows (shuffle, ORDER BY), row deletion or sampling (votes degrade
gracefully), insertion of foreign rows (their votes are unbiased noise), and
sparse edits of cells (an edited row is one lost vote, not a misleading one).
Like every LSB scheme it does not survive a global requantization of the
carrier column (rounding, float32 conversion, normalization).
"""

import binascii
import hashlib
import hmac
import logging
import math
import struct
from typing import Callable, Dict, List

import polars as pl

from steganodf.algorithms.algorithm import AlgorithmError
from steganodf.algorithms.alteration_algorithm import AlterationAlgorithm


class BitVote(AlterationAlgorithm):

    def __init__(
        self,
        column: str = None,
        data_size: int = 24,
        hash_function: Callable = hashlib.md5,
        password: str = None,
        sort_columns: bool = True,
        **kwargs,
    ):
        """
        Initialize an instance of BitVote.

        Encoding is fully deterministic (there is no randomness), so there is
        no seed argument.

        Args:
            column (str, optional): Name of the numeric column carrying the bits.
                By default the first numeric column in alphabetical order is used,
                so the choice survives a reordering of the columns.
            data_size (int): Size in bytes of the fixed voting frame. The maximum
                payload is `data_size - 5` bytes (1 length byte and 4 CRC bytes).
                Encoding and decoding must use the same value. Default is 24.
            hash_function (Callable): Hash function to use. Default is MD5.
            password (str, optional): Password used for the fingerprint with a
                HMAC algorithm.
            sort_columns (bool): Sort the columns by name before fingerprinting
                each row, so the watermark survives a reordering of the columns.
                Default is True. Encoding and decoding must use the same value.
        """
        super().__init__(**kwargs)

        self._column = column
        self._data_size = data_size
        self._hash_function = hash_function
        self._password = password
        self._sort_columns = sort_columns
        self._crc_size = 4

        if self._data_size < 6:
            raise AlgorithmError("data_size must be at least 6 bytes")

    @property
    def slot_count(self) -> int:
        """
        Number of voting slots, one per message bit.

        >>> BitVote(data_size=24).slot_count
        192
        """
        return self._data_size * 8

    def get_max_payload_size(self) -> int:
        """
        Return the maximum payload size in bytes.

        >>> BitVote().get_max_payload_size()
        19
        """
        return self._data_size - 1 - self._crc_size

    def select_column(self, df: pl.DataFrame) -> str:
        """
        Return the name of the carrier column.

        This is the column given at construction time, or the first numeric
        column in alphabetical order. At least one non-carrier column must
        remain, because the fingerprint is computed on the other columns.

        >>> df = pl.DataFrame({"name": ["x", "y"], "b": [1.0, 2.0], "a": [1, 2]})
        >>> BitVote().select_column(df)
        'a'
        >>> BitVote(column="b").select_column(df)
        'b'
        """
        if self._column is not None:
            if self._column not in df.columns:
                raise AlgorithmError(f"Column '{self._column}' does not exist")
            if not df.schema[self._column].is_numeric():
                raise AlgorithmError(f"Column '{self._column}' is not numeric")
            column = self._column
        else:
            numerics = sorted(name for name in df.columns if df.schema[name].is_numeric())
            if not numerics:
                raise AlgorithmError("No numeric column available to carry the watermark")
            column = numerics[0]

        if df.schema[column] == pl.Float32:
            raise AlgorithmError(
                "Float32 columns cannot carry the watermark reliably (a CSV round trip "
                "reads them back as Float64). Cast the column to Float64 first."
            )

        if len(df.columns) < 2:
            raise AlgorithmError(
                "At least one column beside the carrier is required to fingerprint the rows"
            )
        return column

    def compute_slots(self, df: pl.DataFrame, column: str) -> List[int]:
        """
        Compute, for each row, its voting slot and mask bit, packed as
        `slot * 2 + mask`.

        The fingerprint is computed on every column except the carrier, with
        the same canonical string as BitPool: columns sorted by name (unless
        sort_columns is False), cells joined with a separator, and nulls
        distinguished from empty strings. Excluding the carrier is what makes
        the fingerprint immune to the LSB writes.
        """
        others = [name for name in df.columns if name != column]
        columns = sorted(others) if self._sort_columns else others

        return (
            df.select(
                pl.concat_str(
                    [pl.col(name).cast(pl.Utf8()).fill_null("\x00") for name in columns],
                    separator="\x1f",
                )
                .map_elements(self._slot_of, return_dtype=pl.UInt32)
                .alias("slot")
            )["slot"]
            .to_list()
        )

    def _slot_of(self, text: str) -> int:
        """
        Map the canonical string of a row to `slot * 2 + mask`.
        """
        if self._password:
            digest = hmac.new(self._password.encode(), text.encode(), self._hash_function).digest()
        else:
            digest = self._hash_function(text.encode()).digest()

        slot = int.from_bytes(digest[:8], "big") % self.slot_count
        mask = digest[8] & 1
        return slot * 2 + mask

    def _build_message(self, payload: bytes) -> bytes:
        """
        Frame the payload into the fixed-size voting frame.
        """
        if len(payload) > self.get_max_payload_size():
            raise AlgorithmError(
                f"Payload of {len(payload)} bytes exceeds the maximum of "
                f"{self.get_max_payload_size()} bytes. Raise data_size on both sides."
            )
        body = bytes([len(payload)]) + payload
        body += b"\x00" * (self._data_size - self._crc_size - len(body))
        return body + binascii.crc32(body).to_bytes(self._crc_size, "big")

    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        """
        Encode a payload by writing one message bit in the carrier LSB of
        every usable row. The row order and every other column are unchanged.

        Args:
            df(pl.DataFrame): The host dataframe
            payload(bytes): the payload message to hide in the host dataframe

        Return:
            Return the stego dataframe
        """
        column = self.select_column(df)
        message = self._build_message(payload)
        slots = self.compute_slots(df, column)

        dtype = df.schema[column]
        is_float = dtype == pl.Float64
        values = df[column].to_list()

        usable = sum(1 for v in values if is_usable(v, is_float))
        if usable < self.slot_count:
            raise AlgorithmError(
                f"The dataframe has {usable} usable carrier values for "
                f"{self.slot_count} voting slots. Use a larger dataframe or a "
                "smaller data_size. A reliable decoding needs several votes per "
                "slot, so at least ~10 rows per slot are recommended."
            )

        new_values = []
        for value, packed in zip(values, slots):
            if not is_usable(value, is_float):
                new_values.append(value)
                continue
            slot, mask = packed >> 1, packed & 1
            bit = message_bit(message, slot) ^ mask
            new_values.append(write_lsb(value, bit, is_float))

        return df.with_columns(pl.Series(column, new_values, dtype=dtype))

    def decode(self, df: pl.DataFrame) -> bytes:
        """
        Decode the payload from the cover dataframe.

        Args:
            df(pl.DataFrame): The host dataframe

        Return:
            Return the payload in bytes, or an empty bytes object if no valid
            message could be recovered. Use `decode_details` to know which one it is.
        """
        return self.decode_details(df)["payload"]

    def decode_details(self, df: pl.DataFrame) -> Dict:
        """
        Decode the payload and report how the voting went.

        Return:
            A dict with the `payload` (bytes), whether a CRC-valid message was
            rebuilt (`success`), the number of voting rows (`votes`), and the
            smallest absolute vote margin over the slots (`margin_min`, a
            robustness diagnostic: 0 means at least one slot was decided by a
            coin flip).
        """
        column = self.select_column(df)
        slots = self.compute_slots(df, column)

        is_float = df.schema[column] == pl.Float64
        values = df[column].to_list()

        tally = [0] * self.slot_count
        votes = 0
        for value, packed in zip(values, slots):
            if not is_usable(value, is_float):
                continue
            slot, mask = packed >> 1, packed & 1
            bit = read_lsb(value, is_float) ^ mask
            tally[slot] += 1 if bit else -1
            votes += 1

        bits = [1 if t > 0 else 0 for t in tally]
        message = bytes(
            sum(bits[i * 8 + j] << j for j in range(8)) for i in range(self._data_size)
        )

        body, crc = message[: -self._crc_size], message[-self._crc_size :]
        length = body[0]
        success = (
            binascii.crc32(body).to_bytes(self._crc_size, "big") == crc
            and length <= len(body) - 1
        )

        result = {
            "payload": body[1 : 1 + length] if success else b"",
            "success": success,
            "votes": votes,
            "margin_min": min(abs(t) for t in tally),
        }

        if not success:
            logging.warning(
                "No valid message could be decoded from the votes of %d row(s). "
                "The dataframe may not be watermarked, the password or data_size "
                "may be wrong, or the carrier column may have been requantized.",
                votes,
            )
        return result


def is_usable(value, is_float: bool) -> bool:
    """
    Return whether a carrier value can hold a bit. Nulls are excluded, and so
    are non-finite floats: a NaN loses its mantissa in a CSV round trip and
    flipping the LSB of an infinity turns it into a NaN.

    >>> is_usable(1.5, True), is_usable(None, True), is_usable(float("nan"), True)
    (True, False, False)
    """
    if value is None:
        return False
    if is_float and not math.isfinite(value):
        return False
    return True


def message_bit(message: bytes, position: int) -> int:
    """
    Bit at `position` in the message, least significant bit of each byte first.

    >>> message_bit(b"\\x01", 0), message_bit(b"\\x01", 1)
    (1, 0)
    """
    return (message[position // 8] >> (position % 8)) & 1


def write_lsb(value, bit: int, is_float: bool):
    """
    Return `value` with its least significant bit set to `bit`. For floats this
    is the IEEE-754 mantissa LSB, a change of 1 ULP.

    >>> write_lsb(4, 1, False)
    5
    >>> write_lsb(1.5, 0, True)
    1.5
    """
    if is_float:
        u = struct.unpack("<Q", struct.pack("<d", value))[0]
        return struct.unpack("<d", struct.pack("<Q", (u & ~1) | bit))[0]
    return (value & ~1) | bit


def read_lsb(value, is_float: bool) -> int:
    """
    Return the least significant bit of `value`.

    >>> read_lsb(5, False), read_lsb(write_lsb(1.5, 1, True), True)
    (1, 1)
    """
    if is_float:
        return struct.unpack("<Q", struct.pack("<d", value))[0] & 1
    return value & 1
