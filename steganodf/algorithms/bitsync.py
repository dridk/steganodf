"""
BitSync: a permutation watermark with Davey-MacKay synchronization.

Like BitPool the message lives only in the order of the rows (zero distortion):
each row carries one bit, derived from a fingerprint of its content, and the
encoder writes a bit by emitting the next row from the matching FIFO queue.
What changes is how the decoder finds the packets back.

BitPool slides a packet-sized window over every offset and attempts a
Reed-Solomon decoding at each one; a deleted row also destroys the whole packet
spanning it. BitSync instead uses the Davey-MacKay construction (Davey &
MacKay, "Reliable communication over channels with insertions, deletions, and
substitutions", IEEE Trans. Inf. Theory, 2001):

1. The packet stream is *sparsified*: every 4 data bits become an 8-bit
   codeword holding mostly zeros (density ~0.17), so the transmitted stream
   mostly equals...
2. ...a pseudo-random *watermark* sequence, derived from the password and known
   to both sides, XORed in. The receiver can therefore recognize where it is in
   the stream by locking onto the watermark, like recognizing a familiar tune.
3. At decoding time a hidden Markov model tracks the *drift* (how many rows
   have been deleted or inserted so far) with a forward-backward pass, and
   outputs for every transmitted position the probability that its sparse bit
   was set. A row deletion is re-synchronized within a few rows and costs a
   couple of corrupted bytes (repaired by Reed-Solomon) instead of a packet.

The packet framing above the synchronization layer mirrors BitPool: a payload
that fits in one data block is framed as a repeated short packet, a larger one
goes through the LT fountain of `steganodf.lt`; both get a CRC32 and a
Reed-Solomon code. Packets sit at known byte offsets of the recovered stream,
so the decoder validates `n / packet_size` candidates instead of `n`.

Unlike BitPool no scrambling is needed: the watermark XOR already makes the
transmitted stream uniform, so the two row queues are consumed evenly even when
the same short packet is repeated verbatim.

The price of the synchronization layer is the sparse code rate of 1/2: a
packet spans twice as many rows as in BitPool, so the capacity is roughly
halved. Like every permutation watermark, sorting or shuffling the rows erases
the message.
"""

import binascii
import hashlib
import hmac
import io
import logging
import random
from struct import unpack
from typing import Callable, Dict, Iterator, List

import numpy as np
import polars as pl
from reedsolo import RSCodec

from steganodf.algorithms.algorithm import AlgorithmError
from steganodf.algorithms.permutation_algorithm import PermutationAlgorithm
from steganodf import lt

# Sparse code: every DATA_BITS data bits are expanded into a SPARSE_BITS-bit
# codeword of low Hamming weight. The codebook is the 2**DATA_BITS byte values
# of lowest weight, in a deterministic order (weight, then value).
DATA_BITS = 4
SPARSE_BITS = 8
SPARSE_CODEBOOK = tuple(
    sorted(range(256), key=lambda v: (bin(v).count("1"), v))[: 1 << DATA_BITS]
)
# Mean fraction of ones in a codeword: this is the flip density the HMM expects.
SPARSE_DENSITY = sum(bin(v).count("1") for v in SPARSE_CODEBOOK) / (
    len(SPARSE_CODEBOOK) * SPARSE_BITS
)

# Codeword bit matrix (16 x 8), least significant bit first, used by desparsify.
_CODEWORD_BITS = np.array(
    [[(cw >> j) & 1 for j in range(SPARSE_BITS)] for cw in SPARSE_CODEBOOK],
    dtype=np.float64,
)

# Framing constants shared with the LT fountain (filesize, blocksize, blockseed).
LT_HEADER_SIZE = 12
CRC_SIZE = 4


def sparsify(data: bytes) -> np.ndarray:
    """
    Expand bytes into the sparse bit stream, one codeword per nibble, low
    nibble first, codeword bits least significant first.

    >>> sparsify(b"\\x00").tolist()
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    >>> int(sparsify(b"\\x21").sum())  # two weight-1 codewords
    2
    """
    bits = np.zeros(len(data) * 2 * SPARSE_BITS, dtype=np.uint8)
    pos = 0
    for byte in data:
        for nibble in (byte & 0x0F, byte >> DATA_BITS):
            codeword = SPARSE_CODEBOOK[nibble]
            for j in range(SPARSE_BITS):
                bits[pos] = (codeword >> j) & 1
                pos += 1
    return bits


def desparsify(posteriors: np.ndarray) -> bytes:
    """
    Rebuild bytes from the per-position probabilities that each sparse bit is
    set: every chunk of SPARSE_BITS posteriors is matched against the codebook
    by log-likelihood and the best codeword gives the nibble back.

    >>> bits = sparsify(b"\\x5a\\x00\\xff")
    >>> desparsify(bits.astype(float) * 0.98 + 0.01)
    b'Z\\x00\\xff'
    """
    chunks = len(posteriors) // SPARSE_BITS
    p = np.clip(
        np.asarray(posteriors[: chunks * SPARSE_BITS], dtype=np.float64), 1e-9, 1 - 1e-9
    ).reshape(chunks, SPARSE_BITS)
    scores = np.log(p) @ _CODEWORD_BITS.T + np.log(1.0 - p) @ (1.0 - _CODEWORD_BITS.T)
    nibbles = np.argmax(scores, axis=1)
    pairs = (len(nibbles) // 2) * 2
    low, high = nibbles[0:pairs:2], nibbles[1:pairs:2]
    return bytes(((high << DATA_BITS) | low).astype(np.uint8).tolist())


def watermark_bits(count: int, password: str = None) -> np.ndarray:
    """
    Return `count` pseudo-random watermark bits, derived from the password with
    a SHA-256 counter stream. Both sides regenerate the exact same sequence.

    >>> len(watermark_bits(20))
    20
    >>> watermark_bits(16, "a").tolist() == watermark_bits(16, "a").tolist()
    True
    >>> watermark_bits(64, "a").tolist() == watermark_bits(64, "b").tolist()
    False
    """
    key = f"bitsync:{password or ''}".encode()
    blocks = [
        hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        for counter in range((count + 255) // 256)
    ]
    raw = np.frombuffer(b"".join(blocks), dtype=np.uint8)
    return np.unpackbits(raw)[:count]


class BitSync(PermutationAlgorithm):

    def __init__(
        self,
        data_size: int = 20,
        correction_size: int = 10,
        hash_function: Callable = hashlib.md5,
        password: str = None,
        seed: int = None,
        sort_columns: bool = True,
        max_drift: int = None,
        p_delete: float = 0.03,
        p_insert: float = 0.01,
        p_sub: float = 0.02,
        **kwargs,
    ):
        """
        Initialize an instance of BitSync.

        Args:
            data_size (int): Data size of a packet in bytes. Default is 20.
            correction_size (int): Reed-Solomon code size of a packet in bytes.
                Default is 10.
            hash_function (Callable): Hash function for the row fingerprint.
                Default is MD5.
            password (str, optional): Password used both for the row fingerprint
                (HMAC) and to derive the watermark sequence.
            seed (int, optional): Seed of the random generator used at encoding
                time (LT block seeds and final shuffle). Encoding is random by
                default; setting a seed makes it reproducible. Decoding never
                depends on it.
            sort_columns (bool): Sort the columns by name before hashing each
                row, so the watermark survives a reordering of the columns.
                Default is True. Encoding and decoding must use the same value.
            max_drift (int, optional): Largest net row insertion/deletion count
                the decoder can track. Default is `max(64, row_count // 10)`,
                i.e. 10% of the rows. Decoding costs O(rows * max_drift) in
                time and memory, so raise it only when more than 10% of the
                rows may have been cropped.
            p_delete (float): Row deletion probability assumed by the decoder
                model. Default is 0.03.
            p_insert (float): Row insertion probability assumed by the decoder
                model. Default is 0.01.
            p_sub (float): Row substitution (edited cell) probability assumed by
                the decoder model. Default is 0.02.
        """
        super().__init__(**kwargs)

        self._data_size = data_size
        self._correction_size = correction_size
        self._hash_function = hash_function
        self._password = password
        self._random = random.Random(seed)
        self._sort_columns = sort_columns
        self._max_drift = max_drift
        self._p_delete = p_delete
        self._p_insert = p_insert
        self._p_sub = p_sub

        if self._data_size < 2:
            raise AlgorithmError("data_size must be at least 2 bytes")
        if self._correction_size < 0:
            raise AlgorithmError("correction_size must be positive")
        for name, value in (("p_delete", p_delete), ("p_insert", p_insert), ("p_sub", p_sub)):
            if not 0.0 < value < 0.5:
                raise AlgorithmError(f"{name} must be strictly between 0 and 0.5")
        if self._max_drift is not None and self._max_drift < 1:
            raise AlgorithmError("max_drift must be at least 1")

        self._rsc = RSCodec(self._correction_size) if self._correction_size > 0 else None

    # ------------------------------------------------------------------ rows

    def _bit_of(self, text: str) -> int:
        """
        Map the canonical string of a row to its bit: the most significant bit
        of the digest, or of the HMAC digest when a password is set.
        """
        if self._password:
            digest = hmac.new(self._password.encode(), text.encode(), self._hash_function).digest()
        else:
            digest = self._hash_function(text.encode()).digest()
        return digest[0] >> 7

    def compute_bits(self, df: pl.DataFrame) -> List[int]:
        """
        Return the bit carried by each row, in row order.

        The fingerprint is the same canonical string as the other algorithms:
        columns sorted by name (unless sort_columns is False), cells joined
        with a separator, and nulls distinguished from empty strings.

        >>> algo = BitSync()
        >>> bits = algo.compute_bits(pl.DataFrame({"a": range(8)}))
        >>> len(bits), set(bits) <= {0, 1}
        (8, True)
        """
        columns = sorted(df.columns) if self._sort_columns else df.columns
        return (
            df.select(
                pl.concat_str(
                    [pl.col(name).cast(pl.Utf8()).fill_null("\x00") for name in columns],
                    separator="\x1f",
                )
                .map_elements(self._bit_of, return_dtype=pl.UInt32)
                .alias("bit")
            )["bit"]
            .to_list()
        )

    # --------------------------------------------------------------- packets

    def get_packet_size(self, short: bool = False) -> int:
        """
        Return the size in bytes of a finished packet.

        >>> BitSync().get_packet_size(), BitSync().get_packet_size(short=True)
        (46, 34)
        """
        data = self._data_size if short else LT_HEADER_SIZE + self._data_size
        return data + CRC_SIZE + self._correction_size

    def rows_per_packet(self, short: bool = False) -> int:
        """
        Return how many rows one packet spans, sparse expansion included.

        >>> BitSync().rows_per_packet()
        736
        """
        return self.get_packet_size(short) * 8 * SPARSE_BITS // DATA_BITS

    def is_short_payload(self, payload: bytes) -> bool:
        """
        Return whether the payload fits in a single short-mode packet.
        """
        return len(payload) <= self._data_size - 1

    def _framed_blocks(self, payload: bytes) -> Iterator[bytes]:
        """
        Yield an infinite stream of finished packets (CRC and Reed-Solomon
        applied). A short payload is framed as `length + payload + zero
        padding` and repeated verbatim — the watermark XOR takes care of making
        every copy look different on the channel. A larger payload goes through
        the LT fountain.
        """
        if self.is_short_payload(payload):
            body = bytes([len(payload)]) + payload
            body += b"\x00" * (self._data_size - len(body))
            blocks = iter(lambda: body, None)
        else:
            lt_seed = self._random.randint(0, (1 << 31) - 2)
            blocks = lt.encode.encoder(io.BytesIO(payload), self._data_size, seed=lt_seed)

        for block in blocks:
            block += binascii.crc32(block).to_bytes(CRC_SIZE, "big")
            if self._rsc is not None:
                block = bytes(self._rsc.encode(block))
            yield block

    # ---------------------------------------------------------------- encode

    def encode(self, df: pl.DataFrame, payload: bytes) -> pl.DataFrame:
        """
        Encode a payload in the dataframe by permutation.

        Args:
            df(pl.DataFrame): The host dataframe
            payload(bytes): the payload message to hide in the host dataframe

        Return:
            Return the stego dataframe
        """
        bits = self.compute_bits(df)
        queues = {0: [], 1: []}
        for index, bit in enumerate(bits):
            queues[bit].append(index)
        consumed = [0, 0]

        watermark = watermark_bits(len(bits), self._password)

        rows = []
        position = 0
        block_count = 0
        for block in self._framed_blocks(payload):
            sparse = sparsify(block)
            if position + len(sparse) > len(watermark):
                break
            coded = sparse ^ watermark[position : position + len(sparse)]

            saved = consumed.copy()
            packet_rows = []
            for bit in coded.tolist():
                queue = queues[bit]
                if consumed[bit] >= len(queue):
                    packet_rows = None
                    break
                packet_rows.append(queue[consumed[bit]])
                consumed[bit] += 1

            if packet_rows is None:
                consumed = saved
                break

            rows += packet_rows
            position += len(sparse)
            block_count += 1

        if block_count == 0:
            raise AlgorithmError(
                f"Not a single {self.get_packet_size(short=self.is_short_payload(payload))} "
                f"bytes packet could be encoded. A packet spans "
                f"{self.rows_per_packet(short=self.is_short_payload(payload))} rows (sparse "
                f"expansion included) and the dataframe has {len(df)}, with "
                f"{len(queues[0])} rows of bit 0 and {len(queues[1])} of bit 1. Lower "
                "correction_size/data_size or use a larger dataframe."
            )

        leftovers = queues[0][consumed[0] :] + queues[1][consumed[1] :]
        self._random.shuffle(leftovers)
        return df[rows + leftovers]

    # ------------------------------------------------------------------ HMM

    def _posteriors(
        self, received: np.ndarray, watermark: np.ndarray, max_drift: int
    ) -> np.ndarray:
        """
        Davey-MacKay forward-backward pass.

        The hidden state is the drift d = (received index) - (transmitted
        index), tracked in [-max_drift, +max_drift]. At every transmitted
        position the lattice allows a deletion (the row disappeared, d - 1), a
        plain emission (d unchanged), or one insertion followed by the emission
        (a foreign row slipped in, d + 1). Emissions compare the received bit
        with the watermark bit, the sparse data bit acting as a
        Bernoulli(SPARSE_DENSITY) flip.

        Returns, for every transmitted position, P(sparse bit = 1 | received):
        the alignment is marginalized out, which is what removes the sliding
        window — and the O(rows) Reed-Solomon attempts — of BitPool.
        """
        n_received = len(received)
        n_transmitted = len(watermark)
        width = 2 * max_drift + 1

        density = SPARSE_DENSITY
        p_sub, p_del, p_ins = self._p_sub, self._p_delete, self._p_insert
        p_trans = 1.0 - p_del - p_ins
        # P(received == watermark) with the sparse bit marginalized out
        q_match = (1.0 - density) * (1.0 - p_sub) + density * p_sub

        drifts = np.arange(-max_drift, max_drift + 1)

        def emission(i: int):
            """Match mask and validity mask of the received window at position i."""
            idx = i + drifts
            valid = (idx >= 0) & (idx < n_received)
            match = received[np.clip(idx, 0, n_received - 1)] == watermark[i]
            return match, valid

        def shift_left(v: np.ndarray) -> np.ndarray:
            out = np.empty_like(v)
            out[:-1] = v[1:]
            out[-1] = 0.0
            return out

        def shift_right(v: np.ndarray) -> np.ndarray:
            out = np.empty_like(v)
            out[1:] = v[:-1]
            out[0] = 0.0
            return out

        # Forward pass, storing the (normalized) alpha of every position. The
        # normalization constants cancel in the posterior ratio, so float32 is
        # plenty.
        alphas = np.empty((n_transmitted, width), dtype=np.float32)
        forward = np.zeros(width, dtype=np.float64)
        forward[max_drift] = 1.0
        for i in range(n_transmitted):
            alphas[i] = forward
            match, valid = emission(i)
            e_marginal = np.where(match, q_match, 1.0 - q_match)
            e_marginal[~valid] = 0.0
            forward = p_del * shift_left(forward) + e_marginal * (
                p_trans * forward + 0.5 * p_ins * shift_right(forward)
            )
            total = forward.sum()
            if total <= 0.0:
                forward[:] = 1.0 / width
            else:
                forward /= total

        # Backward pass, combined on the fly with the stored alphas to emit the
        # posterior of every sparse bit without storing the betas.
        posteriors = np.empty(n_transmitted, dtype=np.float64)
        backward = np.ones(width, dtype=np.float64)
        for i in range(n_transmitted - 1, -1, -1):
            match, valid = emission(i)
            e_zero = np.where(match, 1.0 - p_sub, p_sub)  # sparse bit = 0
            e_one = np.where(match, p_sub, 1.0 - p_sub)  # sparse bit = 1
            e_zero[~valid] = 0.0
            e_one[~valid] = 0.0

            alpha = alphas[i].astype(np.float64)
            deletion = p_del * (alpha * shift_right(backward)).sum()

            def observed(e: np.ndarray) -> float:
                product = e * backward
                return (alpha * (p_trans * product + 0.5 * p_ins * shift_left(product))).sum()

            score_one = density * (deletion + observed(e_one))
            score_zero = (1.0 - density) * (deletion + observed(e_zero))
            total = score_zero + score_one
            posteriors[i] = score_one / total if total > 0.0 else density

            e_marginal = (1.0 - density) * e_zero + density * e_one
            product = e_marginal * backward
            backward = (
                p_del * shift_right(backward) + p_trans * product + 0.5 * p_ins * shift_left(product)
            )
            total = backward.sum()
            if total <= 0.0:
                backward[:] = 1.0 / width
            else:
                backward /= total

        return posteriors

    # ---------------------------------------------------------------- decode

    def _validate_block(self, block: bytes):
        """
        Reed-Solomon decode a candidate packet and check its CRC32. Return the
        packet body without CRC, or None.
        """
        try:
            packet = bytes(self._rsc.decode(block)[0]) if self._rsc is not None else bytes(block)
        except Exception:
            return None

        body, crc = packet[:-CRC_SIZE], packet[-CRC_SIZE:]
        if binascii.crc32(body).to_bytes(CRC_SIZE, "big") != crc:
            return None
        return body

    def _iter_packets(self, stream: bytes, short: bool) -> Iterator[bytes]:
        """
        Cut the recovered stream at the known packet boundaries — packets are
        written back to back from position 0, so no sliding window is needed —
        and yield every body that passes Reed-Solomon and CRC32.
        """
        size = self.get_packet_size(short)
        for i in range(0, len(stream) - size + 1, size):
            body = self._validate_block(stream[i : i + size])
            if body is not None:
                yield body

    def _decode_short(self, stream: bytes) -> Dict:
        """
        Look for short-mode packets: a single valid packet carries the whole
        message, so the first hit wins.
        """
        for body in self._iter_packets(stream, short=True):
            length = body[0]
            data = body[1:]

            # The zero padding doubles as a validity check on top of the CRC
            if length <= len(data) and not any(data[length:]):
                return {
                    "payload": bytes(data[:length]),
                    "success": True,
                    "block_count": 1,
                    "mode": "short",
                }

        return {"payload": b"", "success": False, "block_count": 0, "mode": None}

    def _decode_standard(self, stream: bytes) -> Dict:
        """
        Look for standard LT packets and feed them to the fountain decoder.
        """
        decoder = lt.decode.LtDecoder()
        success = False
        valid_blocks = 0
        for body in self._iter_packets(stream, short=False):
            # The LT header is (filesize, blocksize, blockseed)
            filesize, blocksize, blockseed = unpack("!III", body[:LT_HEADER_SIZE])
            data = body[LT_HEADER_SIZE:]

            if blocksize == len(data):
                valid_blocks += 1
                buffer = io.BytesIO(body)
                header = lt.decode._read_header(buffer)
                block = lt.decode._read_block(header[1], buffer)
                decoder.consume_block((header, block))

                if decoder.is_done():
                    success = True
                    break

        # A partially filled LT decoder cannot produce a partial message; only
        # dump it once belief propagation converged.
        payload = decoder.bytes_dump() if success else b""

        return {
            "payload": payload,
            "success": success,
            "block_count": valid_blocks,
            "mode": "standard" if success else None,
        }

    def _decode(self, df: pl.DataFrame) -> Dict:
        received = np.array(self.compute_bits(df), dtype=np.uint8)
        if len(received) == 0:
            return {"payload": b"", "success": False, "block_count": 0, "mode": None}

        max_drift = self._max_drift or max(64, len(received) // 10)
        max_drift = min(max_drift, len(received))

        # The watermark is generated a little longer than the received stream,
        # so that deleted rows do not truncate the last packet's positions.
        watermark = watermark_bits(len(received) + max_drift, self._password)
        posteriors = self._posteriors(received, watermark, max_drift)
        stream = desparsify(posteriors)

        result = self._decode_short(stream)
        if result["success"]:
            return result
        return self._decode_standard(stream)

    def decode(self, df: pl.DataFrame) -> bytes:
        """
        Decode the payload from the cover dataframe.

        Args:
            df(pl.DataFrame): The host dataframe

        Return:
            Return the payload in bytes, or an empty bytes object if no
            complete message could be recovered. Use `decode_details` to know
            which one it is.
        """
        return self.decode_details(df)["payload"]

    def decode_details(self, df: pl.DataFrame) -> Dict:
        """
        Decode the payload and report how the decoding went.

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

    # -------------------------------------------------------------- capacity

    def get_max_payload_size(self, df: pl.DataFrame) -> int:
        """
        Return an empirical estimation of the maximum payload size in bytes.

        The transmitted stream is uniform (watermark XOR), so encoding stops
        when the smaller of the two row queues runs dry: about
        `2 * min(queue sizes)` bits fit. The division by 3 is the same
        empirical safety margin as BitPool: the LT fountain needs noticeably
        more packets than source blocks to converge.
        """
        bits = self.compute_bits(df)
        ones = sum(bits)
        usable_bits = 2 * min(ones, len(bits) - ones)
        packets = usable_bits // (self.get_packet_size() * 8 * SPARSE_BITS // DATA_BITS)
        return max(0, packets * self._data_size // 3)
