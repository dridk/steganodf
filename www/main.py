"""
Browser side of steganodf: read a table, hide a message in it, read it back.

The DOM chrome lives in ui.js. This module only does what needs steganodf
itself — measuring capacity, encoding and decoding — and reports results
through the `window.steg` bridge that ui.js installs.
"""

import asyncio
import inspect
import io
from pathlib import Path

import polars as pl
from js import Uint8Array, document, window
from pyodide.ffi import to_js
from pyodide.ffi.wrappers import add_event_listener

import steganodf as st
from steganodf.algorithms.algorithm import AlgorithmError

# The table currently loaded, and the name it came in under. Both are reset by
# the Remove button.
dataframe = None
source_name = "data.csv"


def field(selector: str) -> str:
    return document.querySelector(selector).value


def status(message: str, kind: str = "error") -> None:
    window.steg.setStatus(message, kind)


def build_algorithm():
    """
    Instantiate the selected algorithm with the parameters the form exposes.

    Every algorithm takes a password; the rest are per-algorithm, and ui.js
    only shows the fields the current one accepts.
    """
    name = field("#algo-select")
    kwargs = {}

    password = field("#password")
    if password:
        kwargs["password"] = password

    if name == "bitpool":
        kwargs["bit_per_row"] = int(field("#bit-select"))

    if name in ("bitvote", "bitghost"):
        column = field("#column-select")
        if column:
            kwargs["column"] = column

    return name, st.ALGORITHMS[name](**kwargs)


def max_payload_size(algorithm) -> int:
    """
    Maximum payload in bytes for the current settings.

    BitPool and BitSync carry the message in the rows themselves, so their
    limit depends on the table and their `get_max_payload_size` takes it.
    BitVote and BitGhost have a fixed frame and take no argument.
    """
    if inspect.signature(algorithm.get_max_payload_size).parameters:
        return algorithm.get_max_payload_size(dataframe)
    return algorithm.get_max_payload_size()


async def busy(label: str) -> None:
    """
    Raise the spinner and hand the browser a chance to paint it, since
    everything that follows blocks the only thread there is.
    """
    window.steg.setBusy(True, label)
    await asyncio.sleep(0)


async def load_file(event) -> None:
    """Read the dropped or browsed file into a polars dataframe."""
    global dataframe, source_name

    files = event.target.files
    if not files.length:
        return

    file = files.item(0)
    source_name = file.name
    await busy("Reading…")

    try:
        buffer = await file.arrayBuffer()
        stream = io.BytesIO(buffer.to_bytes())
        if source_name.lower().endswith(".parquet"):
            dataframe = pl.read_parquet(stream)
        else:
            dataframe = pl.read_csv(stream)
    except Exception as error:
        dataframe = None
        window.steg.setCapacity(None)
        status(f"Could not read {source_name}: {error}")
        return
    finally:
        window.steg.setBusy(False)

    # The carrier picker only offers what each algorithm can actually use:
    # BitVote takes any numeric column but not Float32, BitGhost only Float64.
    numeric = [
        name
        for name, dtype in dataframe.schema.items()
        if dtype.is_numeric() and dtype != pl.Float32
    ]
    floats = [name for name, dtype in dataframe.schema.items() if dtype == pl.Float64]
    window.steg.setDataset(
        len(dataframe),
        len(dataframe.columns),
        to_js(numeric),
        to_js(floats),
    )
    status("")
    await refresh_capacity()


async def clear_dataset(event=None) -> None:
    """Drop the table when the Remove button empties the UI."""
    global dataframe
    dataframe = None


async def refresh_capacity(event=None) -> None:
    """Re-measure capacity after a change to the algorithm or its parameters."""
    if dataframe is None:
        window.steg.setCapacity(None)
        return

    await busy("Measuring capacity…")
    try:
        _, algorithm = build_algorithm()
        window.steg.setCapacity(max_payload_size(algorithm))
    except AlgorithmError as error:
        window.steg.setCapacity(None)
        status(str(error))
    finally:
        window.steg.setBusy(False)


def encoded_file(df: pl.DataFrame):
    """Serialise the watermarked table in the format it arrived in."""
    source = Path(source_name)
    stream = io.BytesIO()

    if source.suffix.lower() == ".parquet":
        df.write_parquet(stream)
        mime = "application/vnd.apache.parquet"
    else:
        df.write_csv(stream)
        mime = "text/csv"

    data = stream.getvalue()
    array = Uint8Array.new(len(data))
    array.assign(data)
    return f"{source.stem}-encoded{source.suffix or '.csv'}", array, mime


async def encode(event=None) -> None:
    if dataframe is None:
        return

    payload = document.querySelector("#payload").value.encode()
    if not payload:
        status("Type a message to encode.")
        return

    await busy("Encoding…")
    try:
        name, algorithm = build_algorithm()
        watermarked = algorithm.encode(dataframe, payload)
    except AlgorithmError as error:
        status(str(error))
        return
    except Exception as error:
        status(f"Encoding failed: {error}")
        return
    finally:
        window.steg.setBusy(False)

    window.steg.download(*encoded_file(watermarked))
    status(f"Encoded {len(payload)} bytes with {name}.", "info")


async def decode(event=None) -> None:
    if dataframe is None:
        return

    await busy("Decoding…")
    try:
        name, algorithm = build_algorithm()
        details = algorithm.decode_details(dataframe)
    except AlgorithmError as error:
        status(str(error))
        return
    except Exception as error:
        status(f"Decoding failed: {error}")
        return
    finally:
        window.steg.setBusy(False)

    # decode() returns empty bytes on failure just as it does for an empty
    # message, so the success flag is the only way to tell the two apart.
    if not details["success"]:
        status(
            "No message found. Check the algorithm, the parameters "
            "and the password."
        )
        return

    payload = details["payload"]
    try:
        window.steg.setPayload(payload.decode())
    except UnicodeDecodeError:
        window.steg.setPayload(payload.decode("utf-8", errors="replace"))
        status(f"Decoded {len(payload)} bytes that are not valid UTF-8.")
        return

    status(f"Decoded {len(payload)} bytes with {name}.", "info")


window.steg.setVersion(st.__version__)

add_event_listener(document.getElementById("file-upload"), "change", load_file)
add_event_listener(document.getElementById("remove-file"), "click", clear_dataset)
for selector in ("#algo-select", "#bit-select", "#password"):
    add_event_listener(document.querySelector(selector), "change", refresh_capacity)
