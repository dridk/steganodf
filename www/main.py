import polars as pl
import steganodf as st
import io
import os
from js import document, URL, Uint8Array, File, URL
from pyodide.ffi.wrappers import add_event_listener

dataframe = None

async def upload_encode(e):
    """
    Get data for encoding
    """
    global dataframe
    print("upload for encoding ...")
    print(e)
    file_list = e.target.files
    file = file_list.item(0)
    buffer = await file.arrayBuffer()
    data = buffer.to_bytes()
    stream = io.BytesIO(data)
    dataframe = pl.read_csv(stream)

    

    document.querySelector("#row-count").innerText = str(len(dataframe))


def encode(e):
    print("encode", e)
    payload = document.querySelector("#payload").value.encode()
    dl_button = document.querySelector("#download")
    bit_per_row = int(document.querySelector("#bit-select").value)
    password = document.querySelector("#password").value
    password = None if password == "" else password
    
    if dataframe is not None:
        df = st.encode(dataframe, payload, bit_per_row = bit_per_row, password=password)
        stream = io.BytesIO()
        df.write_csv(stream)
        size = len(stream.getvalue())
        js_array = Uint8Array.new(size)
        stream.seek(0)
        js_array.assign(stream.getbuffer())

        file = File.new([js_array], "encoded.csv", {type: "text/plain"})
        url = URL.createObjectURL(file)

        hidden_link = document.createElement("a")
        hidden_link.setAttribute("download", "data-encoded.csv")
        hidden_link.setAttribute("href", url)
        hidden_link.click()


def decode(e):
    print("decode")

    if dataframe is not None:
        payload = st.decode(dataframe)
        document.querySelector("#payload").value = payload.decode()


# Create event listener
add_event_listener(document.getElementById("file-upload"), "change", upload_encode)
