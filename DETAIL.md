# Algorithms in detail

The four algorithms steganodf ships, what they are built on, and where each one breaks.
See the [README](README.md) for the comparison table and the measured figures quoted below.

## `bitpool` — permutation, LT fountain code

Every row is fingerprinted (MD5, or HMAC-MD5 when a password is given) and the top `bit_per_row`
bits of that fingerprint give the row a symbol. Rows are bucketed into `2**bit_per_row` FIFO
queues, and writing a symbol means emitting the next row from the matching queue — so the payload
is spelled out by the row order alone. Above that, the payload is cut into blocks by a
[Luby transform fountain code](https://en.wikipedia.org/wiki/Luby_transform_code) and each packet
gets a CRC32 and a [Reed-Solomon](https://en.wikipedia.org/wiki/Reed%E2%80%93Solomon_error_correction)
code, so damaged packets are repaired and lost ones are simply replaced by other packets. A payload
of 19 bytes or less skips the fountain entirely and uses a compact packet that a single surviving
copy is enough to decode. Decoding slides a packet-sized window over every offset.

**Good at:** zero distortion, the highest capacity of the four, and a capacity that grows with the
dataframe. `bit_per_row` goes from 1 to 16 — each row then carries that many bits — and raising it
is the single most effective knob in the library: from 1 to 8 the capacity went from 4.4 kB to
29 kB *and* the damage tolerance from 2 % to 12 % of cells edited and from 2 % to 20 % of rows
deleted, because a packet then spans 46 rows instead of 368 and the sliding window finds an intact
copy far more often. `bitpool` is also the fastest of the four to decode: 0.16 s on 100 000 rows.

The catch is that each of the `2**bit_per_row` queues must stay well populated, so there is a peak
rather than a ceiling. On our 100k-row frame we measured 29 kB at `bit_per_row=8`, 28 kB at 10, and
then a collapse — 14 kB at 12 and 1.2 kB at 13, where 8192 queues share 100 000 rows and run dry
mid-packet. Use `get_max_payload_size(df)` to get a conservative estimate for your own frame rather
than trusting a formula.

**Limited by:** the row order is the message, so a `SORT BY`, a shuffle or a repartition wipes it
out, no password needed and no data lost. A deleted row shifts everything after it and destroys the
packet spanning it.

```python
BitPool(bit_per_row=1, data_size=20, correction_size=10, password=None, seed=None)
```

## `bitsync` — permutation, Davey-MacKay synchronization

Same idea as `bitpool` — one bit per row, written by permutation — but a different decoder. The
packet stream is *sparsified* (every 4 data bits become an 8-bit codeword that is mostly zeros)
and XORed with a pseudo-random watermark sequence derived from the password. At decoding time a
hidden Markov model runs a forward-backward pass over the *drift*, that is, how many rows have been
inserted or deleted so far. This is the construction of Davey & MacKay, *"Reliable communication
over channels with insertions, deletions, and substitutions"*, IEEE Trans. Inf. Theory, 2001.

**Good at:** re-synchronizing. A deleted row costs a couple of locally corrupted bytes, repaired by
Reed-Solomon, instead of destroying the whole packet spanning it, so it degrades gracefully under
scattered deletions, insertions of foreign rows, and head or tail cropping. That advantage is
specific to *deletions*, and it is widest on smaller dataframes: on 10 000 rows it tolerated 3 % of
the rows being deleted where `bitpool` gave up at 1 %. On 100 000 rows the gap narrows to 4 %
against 2 %, because a bigger frame simply holds more packet copies for `bitpool`'s sliding window
to find intact. Against *cell edits*, which are substitutions rather than synchronization losses,
`bitpool` is in fact slightly ahead, at 2 % against 1.5 %. Because packets sit at known offsets,
decoding validates `n / packet_size` candidates instead of one per row.

**Limited by:** the sparse code has rate 1/2, so a packet spans twice as many rows as in `bitpool`
and the capacity is roughly halved — 2.1 kB against 4.4 kB on the same frame. Sorting still erases
the message. And the HMM costs `O(rows × max_drift)`: `max_drift` defaults to
`max(64, row_count // 10)`, which on 100 000 rows means a **44 s** decode. That wide window is what
buys the 4 % deletion tolerance; pinning it to the drift you actually expect (`max_drift=256`)
brings decoding down to **5.7 s** and costs one point of that tolerance, down to 3 %.

```python
BitSync(data_size=20, correction_size=10, password=None, max_drift=None, seed=None)
```

## `bitvote` — LSB alteration, majority vote

The message no longer lives in the row order but in the least significant bit of one numeric
carrier column. Each row is fingerprinted over its *other* columns, and that fingerprint picks
which message bit the row carries (its slot) and a mask bit; the carrier LSB is set to
`message_bit XOR mask`. Decoding recomputes every fingerprint, lets each row vote for its slot,
takes the majority, and checks a CRC32. This is the family of Agrawal & Kiernan (VLDB 2002) and of
QIM / dither modulation.

**Good at:** everything positional. No row position is ever used, so a shuffle, an `ORDER BY`, row
deletion, sampling and insertion of foreign rows all leave the message readable — it withstood 95 %
of the rows being deleted and 45 % of the cells being rewritten, by far the most robust of the four.
The distortion is one unit in the last place on about half the carrier values: a relative change of
2.2e-16, which no downstream statistic will notice.

**Limited by:** capacity, and it is a direct trade against that robustness. The frame is fixed-size
— `data_size - 5` bytes — and a one-byte length field caps the payload at **255 bytes** however
large `data_size` is. Raising `data_size` also spreads the same rows over more voting slots
(`data_size * 8` of them, and around ten rows per slot are recommended), so the votes thin out:
going from the default 19 bytes to the full 255 took the tolerance from 45 % to 15 % of cells
edited and from 95 % to 85 % of rows deleted. Like every LSB scheme, it does not survive a global
requantization of the carrier: rounding, a cast to `float32`, or a normalization pass all destroy
it. The carrier is the first numeric column in alphabetical order, or whatever `column=` names;
`Float32` columns are rejected.

```python
BitVote(column=None, data_size=24, password=None)
```

## `bitghost` — synthetic self-identifying rows

`bitghost` never alters an existing value. It fabricates a handful of "ghost" rows, sampled from
the marginal distribution of each column, and scatters them through the dataframe. Each ghost
self-identifies: a brute-forced nonce makes the HMAC of its canonical string start with a secret
tag, and the low 32 mantissa bits of its carrier value hold `DATA (8) | FRAGMENT INDEX (8) |
NONCE (16)`. The message is split into one-byte fragments and each fragment is written to
`redundancy` ghosts with distinct nonces, so the copies stay unique and a de-duplication pass does
not collapse them.

**Good at:** surviving what nothing else survives. Because only the ghosts are read, **every real
row can be rewritten** and the message still decodes. It also shrugs off shuffling, de-duplication,
and the loss of half the rows.

**Limited by:** the fabricated rows themselves — they are visible to anyone inspecting the data,
and because each column is sampled independently, the correlations between columns are not
preserved in them. Their number is `redundancy × (payload + 5)`, so a 16-byte payload adds 168 rows
at the default `redundancy=8`. That knob is the trade-off to make here: raising it to 32 took the
tolerance from 18 % to 40 % of cells edited and from 50 % to 80 % of rows deleted, for 672 injected
rows instead of 168 and a 4x slower encode (the nonce for each ghost is brute-forced). The payload
is capped at **250 bytes** by the one-byte fragment index, it needs a `Float64` carrier column, and
editing a ghost row breaks its HMAC and loses that fragment.

```python
BitGhost(column=None, redundancy=8, tag_bits=12, password=None, seed=None)
```

## Threat model

Without a `password`, the row fingerprint is a plain MD5 and `bitghost`'s tag uses a published
default key: anyone can read the message and rewrite their own. A password turns the fingerprint
into an HMAC and is what makes the watermark yours. Note that the CRC32 in every packet is an
integrity check, not a MAC — it detects accidental damage, not a deliberate forgery. And a
permutation watermark is detectable in one specific case: if the dataset you started from was
sorted, the watermarked copy no longer is.

The `auto` decoding mode (`steganodf.try_decode`, `steganodf decode -a auto`) makes it a one-liner
to ask "is this file watermarked at all?" without a password. This does not weaken anything that
was protected before — the same answer was already four commands away, and a password-protected
message stays unreadable — but it is worth knowing that the algorithm itself is not a secret.
Trying four algorithms instead of one also multiplies by four the chance of accepting a wrong
decoding on a CRC32 collision, which stays around `row_count / 2**32` in the least favourable case
(`bitpool`, which tests one window per row).
