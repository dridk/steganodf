# MIT License

# Copyright (c) [2015] [Anson Rosenthal]

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import sys
from random import randint
from struct import pack

from .. import sampler


def _split_file(f, blocksize):
    """Block file byte contents into blocksize chunks, padding last one if necessary"""

    f_bytes = f.read()
    blocks = [
        int.from_bytes(f_bytes[i : i + blocksize].ljust(blocksize, b"0"), sys.byteorder)
        for i in range(0, len(f_bytes), blocksize)
    ]
    return len(f_bytes), blocks


def encoder(f, blocksize, seed=None, c=sampler.DEFAULT_C, delta=sampler.DEFAULT_DELTA):
    """Generates an infinite sequence of blocks to transmit
    to the receiver
    """

    # Generate seed if not provided
    if seed is None:
        seed = randint(0, 1 << 31 - 1)

    # get file blocks
    filesize, blocks = _split_file(f, blocksize)

    # init stream vars
    K = len(blocks)
    prng = sampler.PRNG(params=(K, delta, c))
    prng.set_seed(seed)

    # block generation loop
    while True:
        blockseed, d, ix_samples = prng.get_src_blocks()
        block_data = 0
        for ix in ix_samples:
            block_data ^= blocks[ix]

        # Generate blocks of XORed data in network byte order
        block = (filesize, blocksize, blockseed, int.to_bytes(block_data, blocksize, sys.byteorder))
        yield pack("!III%ss" % blocksize, *block)
