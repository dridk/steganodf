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
import io
import sys

from struct import unpack, error
from random import random
from collections import defaultdict

from math import ceil
from .. import sampler


# Check node in graph
class CheckNode(object):

    def __init__(self, src_nodes, check):
        self.check = check
        self.src_nodes = src_nodes


class BlockGraph(object):
    """Graph on which we run Belief Propagation to resolve
    source node data
    """

    def __init__(self, num_blocks):
        self.checks = defaultdict(list)
        self.num_blocks = num_blocks
        self.eliminated = {}

    def add_block(self, nodes, data):
        """Adds a new check node and edges between that node and all
        source nodes it connects, resolving all message passes that
        become possible as a result.
        """

        # We can eliminate this source node
        if len(nodes) == 1:
            to_eliminate = list(self.eliminate(next(iter(nodes)), data))

            # Recursively eliminate all nodes that can now be resolved
            while len(to_eliminate):
                other, check = to_eliminate.pop()
                to_eliminate.extend(self.eliminate(other, check))
        else:

            # Pass messages from already-resolved source nodes
            for node in list(nodes):
                if node in self.eliminated:
                    nodes.remove(node)
                    data ^= self.eliminated[node]

            # Resolve if we are left with a single non-resolved source node
            if len(nodes) == 1:
                return self.add_block(nodes, data)
            else:

                # Add edges for all remaining nodes to this check
                check = CheckNode(nodes, data)
                for node in nodes:
                    self.checks[node].append(check)

        # Are we done yet?
        return len(self.eliminated) >= self.num_blocks

    def eliminate(self, node, data):
        """Resolves a source node, passing the message to all associated checks"""

        # Cache resolved value
        self.eliminated[node] = data
        others = self.checks[node]
        del self.checks[node]

        # Pass messages to all associated checks
        for check in others:
            check.check ^= data
            check.src_nodes.remove(node)

            # Yield all nodes that can now be resolved
            if len(check.src_nodes) == 1:
                yield (next(iter(check.src_nodes)), check.check)


class LtDecoder(object):

    def __init__(self, c=sampler.DEFAULT_C, delta=sampler.DEFAULT_DELTA):
        self.c = c
        self.delta = delta
        self.K = 0
        self.filesize = 0
        self.blocksize = 0

        self.block_graph = None
        self.prng = None
        self.initialized = False

    def is_done(self):
        return self.done

    def consume_block(self, lt_block):
        (filesize, blocksize, blockseed), block = lt_block

        # first time around, init things
        if not self.initialized:
            self.filesize = filesize
            self.blocksize = blocksize

            self.K = ceil(filesize / blocksize)
            self.block_graph = BlockGraph(self.K)
            self.prng = sampler.PRNG(params=(self.K, self.delta, self.c))
            self.initialized = True

        # Run PRNG with given seed to figure out which blocks were XORed to make received data
        _, _, src_blocks = self.prng.get_src_blocks(seed=blockseed)

        # If BP is done, stop
        self.done = self._handle_block(src_blocks, block)
        return self.done

    def bytes_dump(self):
        buffer = io.BytesIO()
        self.stream_dump(buffer)
        return buffer.getvalue()

    def stream_dump(self, out_stream):

        # Iterate through blocks, stopping before padding junk
        for ix, block_bytes in enumerate(
            map(
                lambda p: int.to_bytes(p[1], self.blocksize, "big"),
                sorted(self.block_graph.eliminated.items(), key=lambda p: p[0]),
            )
        ):
            if ix < self.K - 1 or self.filesize % self.blocksize == 0:
                out_stream.write(block_bytes)
            else:
                out_stream.write(block_bytes[: self.filesize % self.blocksize])

    def _handle_block(self, src_blocks, block):
        """What to do with new block: add check and pass
        messages in graph
        """
        return self.block_graph.add_block(src_blocks, block)


def _read_header(stream):
    """Read block header from network"""
    header_bytes = stream.read(12)
    return unpack("!III", header_bytes)


def _read_block(blocksize, stream):
    """Read block data from network into integer type"""
    blockdata = stream.read(blocksize)
    return int.from_bytes(blockdata, "big")


def read_blocks(stream):
    """Generate parsed blocks from input stream"""
    while True:
        header = _read_header(stream)
        block = _read_block(header[1], stream)
        yield (header, block)


# TODO: NO validation here that the bytes consist of a *single* block
def block_from_bytes(bts):
    return next(read_blocks(io.BytesIO(bts)))


def decode(in_stream, out_stream=None, **kwargs):

    decoder = LtDecoder(**kwargs)

    # Begin forever loop
    for lt_block in read_blocks(in_stream):
        decoder.consume_block(lt_block)
        if decoder.is_done():
            break

    if out_stream:
        decoder.stream_dump(out_stream)
    else:
        return decoder.bytes_dump()
