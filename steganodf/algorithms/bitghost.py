"""
BitGhost: a shuffle-resistant watermark based on synthetic self-identifying rows.

Unlike BitPool and BitVote, BitGhost never alters an existing value. It appends
a few synthetic ("ghost") rows sampled from the real column distributions, each
one self-identifying through an HMAC tag and carrying a fragment of the message
in the low mantissa bits of one float column.

A ghost row is recognised at decode time because the HMAC of its canonical
string starts with a secret tag; the low 32 bits of its carrier value hold:

    DATA (8 bits) | FRAGMENT INDEX (8 bits) | NONCE (16 bits)

The message `LENGTH (1 byte) | PAYLOAD | CRC32 (4 bytes)` is split into 1-byte
fragments, and each fragment is written to `redundancy` ghost rows with distinct
nonces, so the copies stay unique (deduplication does not remove them) and the
message survives the loss of some ghosts.

Because every ghost self-identifies, the watermark survives any reordering of
the rows (shuffle), the editing of every real row (they are never read),
sampling (ghosts are lost in proportion), and deduplication. It does not
survive edits to a ghost row (its HMAC no longer matches, the fragment is lost),
a global requantization of the carrier column, or business filters that drop or
flag the fabricated rows. The cost is that fake records are injected into the
data set, which any downstream consumer will see.
"""

import binascii
import hashlib
import hmac
import logging
import math
import random
import struct
from collections import Counter
from typing import Callable, Dict, List

import polars as pl

from steganodf.algorithms.algorithm import Algorithm, AlgorithmError

# The default key used when no password is given, so a watermark is readable
# (and rewritable) by anyone, like BitPool's password-less MD5 fingerprint.
DEFAULT_KEY = b"steganodf-bitghost"


class BitGhost(Algorithm):

    def __init__(
        self,
        column: str = None,
        redundancy: int = 8,
        tag_bits: int = 12,
        hash_function: Callable = hashlib.sha256,
        password: str = None,
        sort_columns: bool = True,
        seed: int = None,
        **kwargs,
    ):
        """
        Initialize an instance of BitGhost.

        Args:
            column (str, optional): Name of the Float64 column carrying the
                fragments. By default the first Float64 column in alphabetical
                order is used, so the choice survives a reordering of the columns.
            redundancy (int): Number of ghost rows written per message fragment.
                Higher values survive more row deletion at the cost of more
                injected rows. Default is 8.
            tag_bits (int): Number of leading HMAC bits a ghost row must match to
                be recognised. Higher values lower the odds of a real row being
                mistaken for a ghost (roughly `row_count / 2**tag_bits` false
                positives, which the majority vote and CRC absorb), at the cost
                of an encoding time growing as `2**tag_bits`. Default is 12.
            hash_function (Callable): Hash function used for the HMAC tag.
                Default is SHA-256.
            password (str, optional): Password keying the HMAC tag. Without one a
                default key is used, so anyone can read the watermark.
            sort_columns (bool): Sort the columns by name before building the
                canonical string, so the tag survives a reordering of the
                columns. Default is True. Encoding and decoding must use the same
                value.
            seed (int, optional): Seed of the random generator used to sample the
                ghost rows. Encoding is random by default; a seed makes it
                reproducible.
        """
        super().__init__(**kwargs)

        self._column = column
        self._redundancy = redundancy
        self._tag_bits = tag_bits
        self._hash_function = hash_function
        self._password = password
        self._sort_columns = sort_columns
        self._random = random.Random(seed)

        if not 1 <= self._tag_bits <= 48:
            raise AlgorithmError("tag_bits must be between 1 and 48")
        if self._redundancy < 1:
            raise AlgorithmError("redundancy must be at least 1")

    def select_column(self, df: pl.DataFrame) -> str:
        """
        Return the name of the carrier column: the one given at construction
        time, or the first Float64 column in alphabetical order.

        >>> df = pl.DataFrame({"b": [1.0], "a": [2.0], "i": [1]})
        >>> BitGhost().select_column(df)
        'a'
        """
        if self._column is not None:
            if self._column not in df.columns:
                raise AlgorithmError(f"Column '{self._column}' does not exist")
            if df.schema[self._column] != pl.Float64:
                raise AlgorithmError(f"Column '{self._column}' is not a Float64 column")
            return self._column

        floats = sorted(name for name in df.columns if df.schema[name] == pl.Float64)
        if not floats:
            raise AlgorithmError("No Float64 column available to carry the watermark")
        return floats[0]

    def _tag(self) -> int:
        """
        The secret tag a ghost's HMAC must start with, derived from the key.
        """
        return self._prefix(self._primed().copy(), b"tag")

    def _key(self) -> bytes:
        return self._password.encode() if self._password else DEFAULT_KEY

    def _primed(self):
        """
        A keyed HMAC object primed with the key, to be `.copy()`-ed per message.
        Copying a primed HMAC is faster than building a fresh `hmac.new`.
        """
        return hmac.new(self._key(), None, self._hash_function)

    def _prefix(self, mac, message: bytes) -> int:
        """
        The leading `tag_bits` of `HMAC(message)`, from a copied primed HMAC.
        """
        mac.update(message)
        return int.from_bytes(mac.digest()[:6], "big") >> (48 - self._tag_bits)

    def _cells(self, row: Dict) -> List[str]:
        """
        Canonical cell strings of a row, matching BitPool's construction:
        columns sorted by name (unless sort_columns is False), nulls distinct
        from empty strings.
        """
        columns = sorted(row) if self._sort_columns else list(row)
        return ["\x00" if row[name] is None else str(row[name]) for name in columns]

    def _matches_tag(self, row: Dict, tag: int) -> bool:
        canonical = "\x1f".join(self._cells(row)).encode()
        return self._prefix(self._primed().copy(), canonical) == tag

    def _build_message(self, payload: bytes) -> bytes:
        if len(payload) > 250:
            raise AlgorithmError(
                f"Payload of {len(payload)} bytes exceeds the maximum of 250 bytes "
                "(the fragment index is a single byte)."
            )
        body = bytes([len(payload)]) + payload
        return body + binascii.crc32(body).to_bytes(4, "big")

    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        """
        Encode a payload by appending self-identifying ghost rows. Every real
        row is left untouched.

        Args:
            df(pl.DataFrame): The host dataframe
            payload(bytes): the payload message to hide in the host dataframe

        Return:
            The stego dataframe, with ghost rows inserted at random positions.
        """
        column = self.select_column(df)
        message = self._build_message(payload)
        tag = self._tag()

        # Sampling pools: the observed values of each column, to keep the ghost
        # marginals plausible (column correlations are not preserved).
        pools = {name: df[name].to_list() for name in df.columns}

        columns = sorted(df.columns) if self._sort_columns else list(df.columns)
        carrier_pos = columns.index(column)

        ghosts = []
        for index, data in enumerate(message):
            for _ in range(self._redundancy):
                ghosts.append(
                    self._make_ghost(columns, carrier_pos, column, pools, tag, data, index)
                )

        ghost_df = pl.DataFrame(ghosts, schema=df.schema)

        # Insert the ghosts at random positions rather than in a block at the end.
        combined = pl.concat([df, ghost_df])
        order = list(range(len(combined)))
        self._random.shuffle(order)
        return combined[order]

    def _make_ghost(
        self,
        columns: List[str],
        carrier_pos: int,
        column: str,
        pools: Dict,
        tag: int,
        data: int,
        index: int,
    ) -> Dict:
        """
        Build one ghost row carrying `(data, index)`, searching a nonce so its
        HMAC matches the tag.

        The non-carrier cells are sampled once per attempt-context; only the
        carrier value (holding the nonce in its low bits) varies across the
        2**16 nonce space, so the canonical string is rebuilt cheaply.
        """
        primed = self._primed()

        # A whole 2**16 nonce space has ~2**16 / 2**tag_bits expected matches; a
        # few resamples make a failure astronomically unlikely.
        for _ in range(64):
            row = {name: self._random.choice(pools[name]) for name in columns}
            base = row[column]
            if base is None or not _is_finite(base):
                base = 1.0
            cells = self._cells(row)

            for nonce in range(1 << 16):
                value = _pack_low(base, data, index, nonce)
                cells[carrier_pos] = str(value)
                if self._prefix(primed.copy(), "\x1f".join(cells).encode()) == tag:
                    row[column] = value
                    return row

        raise AlgorithmError(
            "Could not forge a ghost row matching the tag; lower tag_bits."
        )

    def decode(self, df: pl.DataFrame) -> bytes:
        """
        Decode the payload from the cover dataframe.

        Return:
            Return the payload in bytes, or an empty bytes object if no valid
            message could be recovered. Use `decode_details` for details.
        """
        return self.decode_details(df)["payload"]

    def decode_details(self, df: pl.DataFrame) -> Dict:
        """
        Decode the payload and report how many ghost rows were found.

        Return:
            A dict with the `payload` (bytes), whether a CRC-valid message was
            rebuilt (`success`), and the number of ghost rows found (`ghost_count`).
        """
        column = self.select_column(df)
        tag = self._tag()

        # Per fragment index, a majority vote over the data bytes read from the
        # ghosts, so a false positive or a corrupted copy does not win.
        votes: Dict[int, Counter] = {}
        ghost_count = 0
        for row in df.iter_rows(named=True):
            value = row[column]
            if value is None or not _is_finite(value):
                continue
            if not self._matches_tag(row, tag):
                continue
            ghost_count += 1
            data, index, _ = _unpack_low(value)
            votes.setdefault(index, Counter())[data] += 1

        payload, success = self._reassemble(votes)

        if not success:
            logging.warning(
                "No valid message could be decoded from %d ghost row(s). "
                "The dataframe may not be watermarked, the password may be wrong, "
                "or the ghost rows may have been altered or removed.",
                ghost_count,
            )
        return {"payload": payload, "success": success, "ghost_count": ghost_count}

    def _reassemble(self, votes: Dict[int, Counter]):
        """
        Rebuild the message from the per-index winning bytes and validate the CRC.
        """
        if not votes or 0 not in votes:
            return b"", False
        length = votes[0].most_common(1)[0][0]
        total = 1 + length + 4  # length byte + payload + CRC32
        if any(i not in votes for i in range(total)):
            return b"", False
        message = bytes(votes[i].most_common(1)[0][0] for i in range(total))

        body, crc = message[:-4], message[-4:]
        if binascii.crc32(body).to_bytes(4, "big") != crc:
            return b"", False
        return body[1 : 1 + length], True


def _is_finite(value: float) -> bool:
    return math.isfinite(value)


def _pack_low(base: float, data: int, index: int, nonce: int) -> float:
    """
    Write `data (8 bits) | index (8 bits) | nonce (16 bits)` into the low 32
    mantissa bits of `base`.

    >>> data, index, nonce = _unpack_low(_pack_low(3.14, 0x41, 0x02, 0x1234))
    >>> data, index, nonce
    (65, 2, 4660)
    """
    payload = (data << 24) | (index << 16) | nonce
    u = struct.unpack("<Q", struct.pack("<d", base))[0]
    u = (u & ~0xFFFFFFFF) | payload
    return struct.unpack("<d", struct.pack("<Q", u))[0]


def _unpack_low(value: float):
    """
    Read back `(data, index, nonce)` from the low 32 mantissa bits.
    """
    u = struct.unpack("<Q", struct.pack("<d", value))[0]
    low = u & 0xFFFFFFFF
    return (low >> 24) & 0xFF, (low >> 16) & 0xFF, low & 0xFFFF
