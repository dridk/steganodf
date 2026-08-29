// Presentation layer for the Steganodf page.
//
// Everything here is chrome: which controls a given algorithm shows, the
// payload counter, drag and drop. Anything that needs to know what steganodf
// actually does — capacity, encoding, decoding — lives in main.py and talks to
// this file through the `window.steg` bridge at the bottom.

(function () {
  "use strict";

  // Descriptions come from the design; the flags say which parameter fields an
  // algorithm actually accepts (see the constructors in steganodf/algorithms).
  var ALGORITHMS = {
    bitpool: {
      desc: "Message lives in the row order. No cell is changed. Highest capacity.",
      bits: true,
      column: false,
    },
    bitsync: {
      desc: "Row-order based, self-synchronizing. Robust to small edits.",
      bits: false,
      column: false,
    },
    bitvote: {
      desc: "Message lives in the last bit of one numeric column. Survives sorting.",
      bits: false,
      column: true,
      columnHelp: "Numeric column carrying the watermark bits.",
      floatsOnly: false,
      requires: "numeric",
    },
    bitghost: {
      desc: "Message lives in extra fabricated rows. Original values untouched.",
      bits: false,
      column: true,
      columnHelp: "Column used to fabricate the extra rows.",
      floatsOnly: true,
      requires: "Float64",
    },
  };

  var $ = function (id) { return document.getElementById(id); };

  var el = {
    sidebar: $("sidebar"),
    dropZone: $("drop-zone"),
    fileCard: $("file-card"),
    fileName: $("file-name"),
    fileInput: $("file-upload"),
    browseBtn: $("browse-btn"),
    removeBtn: $("remove-file"),
    algoSelect: $("algo-select"),
    algoDesc: $("algo-desc"),
    bitsField: $("bits-field"),
    columnField: $("column-field"),
    columnHelp: $("column-help"),
    columnSelect: $("column-select"),
    payload: $("payload"),
    counter: $("payload-counter"),
    overCapacity: $("over-capacity"),
    overCapacityText: $("over-capacity-text"),
    rowCount: $("row-count"),
    colCount: $("col-count"),
    capacity: $("capacity"),
    status: $("status"),
    statusText: $("status-text"),
    loading: $("loading"),
    loadingText: $("loading-text"),
  };

  // Carrier columns of the loaded frame, as reported by main.py: those BitVote
  // can use, and the narrower Float64 set BitGhost needs.
  var schema = { loaded: false, numeric: [], floats: [] };
  // Capacity in bytes for the current settings; null while unknown.
  var capacityBytes = null;

  function fmtBytes(bytes) {
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + " kB";
    return (bytes > 0 && bytes < 1 ? 1 : Math.round(bytes)) + " B";
  }

  function payloadBytes() {
    return new TextEncoder().encode(el.payload.value).length;
  }

  function currentAlgorithm() {
    return ALGORITHMS[el.algoSelect.value] ? el.algoSelect.value : "bitpool";
  }

  // ── Rendering ────────────────────────────────────────────────────────────

  function renderCounter() {
    var size = payloadBytes();
    var over = capacityBytes !== null && size > capacityBytes;

    el.counter.textContent =
      capacityBytes === null
        ? fmtBytes(size)
        : fmtBytes(size) + " / " + fmtBytes(capacityBytes);

    el.counter.classList.toggle("is-over", over);
    el.payload.classList.toggle("is-over", over);
    el.overCapacity.hidden = !over;
    if (over) {
      el.overCapacityText.textContent =
        "Message exceeds the estimated capacity for " + currentAlgorithm() + ".";
    }
  }

  function renderColumns() {
    var algo = ALGORITHMS[currentAlgorithm()];
    var names = algo.floatsOnly ? schema.floats : schema.numeric;
    var previous = el.columnSelect.value;

    el.columnSelect.textContent = "";
    el.columnSelect.appendChild(new Option("Default (auto)", ""));
    names.forEach(function (name) {
      el.columnSelect.appendChild(new Option(name, name));
    });

    // Keep the pick across an algorithm change when it is still offered.
    el.columnSelect.value = names.indexOf(previous) === -1 ? "" : previous;

    if (schema.loaded && !names.length) {
      el.columnHelp.textContent =
        "This file has no " + algo.requires + " column, which " +
        currentAlgorithm() + " requires.";
    } else {
      el.columnHelp.textContent = algo.columnHelp || "";
    }
  }

  function renderAlgorithm() {
    var algo = ALGORITHMS[currentAlgorithm()];
    el.algoDesc.textContent = algo.desc;
    el.bitsField.hidden = !algo.bits;
    el.columnField.hidden = !algo.column;
    if (algo.column) renderColumns();
  }

  function renderFile(name) {
    var loaded = Boolean(name);
    el.sidebar.hidden = !loaded;
    el.fileCard.hidden = !loaded;
    el.dropZone.hidden = loaded;
    el.fileName.textContent = name || "";
  }

  // ── Events ───────────────────────────────────────────────────────────────

  function openPicker() {
    el.fileInput.click();
  }

  el.browseBtn.addEventListener("click", function (event) {
    event.stopPropagation();
    openPicker();
  });

  el.dropZone.addEventListener("click", function (event) {
    if (!el.browseBtn.contains(event.target)) openPicker();
  });

  el.dropZone.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPicker();
    }
  });

  ["dragenter", "dragover"].forEach(function (name) {
    el.dropZone.addEventListener(name, function (event) {
      event.preventDefault();
      el.dropZone.classList.add("is-active");
    });
  });

  ["dragleave", "dragend", "drop"].forEach(function (name) {
    el.dropZone.addEventListener(name, function () {
      el.dropZone.classList.remove("is-active");
    });
  });

  el.dropZone.addEventListener("drop", function (event) {
    event.preventDefault();
    var files = event.dataTransfer.files;
    if (!files.length) return;
    // main.py reads e.target.files, so route the drop through the real input.
    var transfer = new DataTransfer();
    transfer.items.add(files[0]);
    el.fileInput.files = transfer.files;
    el.fileInput.dispatchEvent(new Event("change", { bubbles: true }));
  });

  el.fileInput.addEventListener("change", function () {
    if (!el.fileInput.files.length) return;
    renderFile(el.fileInput.files[0].name);
    steg.setStatus("");
    steg.setCapacity(null);
  });

  el.removeBtn.addEventListener("click", function () {
    // main.py listens on this button too, to drop its dataframe.
    el.fileInput.value = "";
    schema = { loaded: false, numeric: [], floats: [] };
    renderFile(null);
    steg.setCapacity(null);
    steg.setStatus("");
    // setCapacity renders "…" for "still measuring"; with no file there is
    // nothing to measure.
    el.rowCount.textContent = "—";
    el.colCount.textContent = "—";
    el.capacity.textContent = "—";
  });

  el.payload.addEventListener("input", renderCounter);

  el.algoSelect.addEventListener("change", function () {
    renderAlgorithm();
    // main.py recomputes on this same event; blank the tile until it answers.
    steg.setCapacity(null);
  });

  el.bitsField.addEventListener("change", function () {
    steg.setCapacity(null);
  });

  // ── Bridge used by main.py ───────────────────────────────────────────────

  var steg = {
    // Row and column counts, plus the schema behind the carrier-column picker.
    setDataset: function (rows, cols, numeric, floats) {
      schema = {
        loaded: true,
        numeric: Array.prototype.slice.call(numeric),
        floats: Array.prototype.slice.call(floats),
      };
      el.rowCount.textContent = Number(rows).toLocaleString("en-US");
      el.colCount.textContent = String(cols);
      renderColumns();
    },

    // `bytes` is null while unknown, which blanks the tile.
    setCapacity: function (bytes) {
      capacityBytes = bytes === null || bytes === undefined ? null : Number(bytes);
      el.capacity.textContent = capacityBytes === null ? "…" : fmtBytes(capacityBytes);
      el.capacity.dataset.bytes = capacityBytes === null ? "" : String(capacityBytes);
      renderCounter();
    },

    // kind is "error" or "info"; an empty message hides the box.
    setStatus: function (message, kind) {
      el.status.hidden = !message;
      el.statusText.textContent = message || "";
      el.status.classList.toggle("alert--info", kind === "info");
    },

    setPayload: function (text) {
      el.payload.value = text;
      renderCounter();
    },

    setBusy: function (busy, label) {
      el.loading.hidden = !busy;
      if (label) el.loadingText.textContent = label;
    },

    download: function (filename, bytes, mime) {
      var blob = new Blob([bytes], { type: mime || "application/octet-stream" });
      var url = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },
  };

  window.steg = steg;

  renderAlgorithm();
  renderFile(null);
  renderCounter();
})();
