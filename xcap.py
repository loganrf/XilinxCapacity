#!/usr/bin/env python3
"""
xcap.py -- Xilinx IO Capacity Visualization Tool

Generates an interactive HTML pin map from an AMD/Xilinx package data file
and one or more Vivado .xdc constraints files.

The constraints argument may be either a single .xdc file or a directory.
If a directory is given, it is searched recursively for all .xdc files and
their constraints are merged together.

Usage:
    python xcap.py <package_data.txt> <constraints.xdc | xdc_dir/> [output.html]
"""

import sys
import re
import os
import json

PIN_COLORS = {
    "HR":     "#4CAF50",
    "HP":     "#2196F3",
    "HD":     "#9C27B0",
    "CONFIG": "#FF9800",
    "GND":    "#607D8B",
    "VCC":    "#F44336",
    "NC":     "#424242",
    "OTHER":  "#9E9E9E",
}

USED_BORDER  = "#FFD700"
DIMMED_COLOR = "#2a2a2a"


# I/O types that represent actual programmable-logic (PL) SelectIO on the
# device. These are the only pins counted toward I/O capacity -- PS pins
# (PSMIO/PSDDR/PSGTR/PSCONFIG), gigabit transceivers (GTH/GTR/GTY), power
# (GND/VCC), and config/JTAG are deliberately excluded.
PL_IO_TYPES = ("HR", "HP", "HD")


def classify_pin(pin_name, io_type):
    n = pin_name.upper()
    if io_type in PL_IO_TYPES:
        return io_type
    if io_type == "CONFIG":
        return "CONFIG"
    if n == "NC":
        return "NC"
    if n.startswith("GND"):
        return "GND"
    if n.startswith("VCC") or n.startswith("VCCO") or n.startswith("VREF"):
        return "VCC"
    return "OTHER"


# The package data files for different device families use different column
# layouts (e.g. 7-series has VCCAUX Group / No-Connect columns that
# UltraScale+ omits, and the I/O Type / SLR columns swap order). Rather than
# hardcoding column indices, the header row is parsed to map each column
# position to a known field. Phrases are ordered longest-first so that, e.g.,
# "Pin Name" is matched before the bare "Pin" location column.
_HEADER_PATTERNS = [
    (re.compile(r"Pin\s+Name", re.IGNORECASE),           "name"),
    (re.compile(r"Memory\s+Byte\s+Group", re.IGNORECASE), "byte_group"),
    (re.compile(r"Byte\s+Group", re.IGNORECASE),         "byte_group"),
    (re.compile(r"VCCAUX\s+Group", re.IGNORECASE),       "vccaux"),
    (re.compile(r"Super\s+Logic\s+Region", re.IGNORECASE), "slr"),
    (re.compile(r"I/O\s+Type", re.IGNORECASE),           "io_type"),
    (re.compile(r"No[-\s]*Connect", re.IGNORECASE),      "no_connect"),
    (re.compile(r"Bank", re.IGNORECASE),                 "bank"),
    (re.compile(r"Pin", re.IGNORECASE),                  "loc"),
]


def parse_header_columns(header):
    """Map the package-data header row to an ordered list of field names,
    one entry per whitespace-separated data column (None for unrecognized
    columns)."""
    cols = []
    i, n = 0, len(header)
    while i < n:
        if header[i].isspace():
            i += 1
            continue
        for pat, field in _HEADER_PATTERNS:
            m = pat.match(header, i)
            if m:
                cols.append(field)
                i = m.end()
                break
        else:
            j = i
            while j < n and not header[j].isspace():
                j += 1
            cols.append(None)
            i = j
    return cols


def parse_package_data(path):
    pins = {}
    columns = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("#") or s.startswith("--"):
                continue
            if "Pin Name" in s and re.match(r"\s*pin\b", s, re.IGNORECASE):
                columns = parse_header_columns(s)
                continue
            if s.startswith("Total Number"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            if columns:
                rec = {}
                for idx, field in enumerate(columns):
                    if field and idx < len(parts):
                        rec[field] = parts[idx]
                loc      = rec.get("loc", parts[0])
                pin_name = rec.get("name", parts[1])
            else:
                # No header seen yet -- fall back to positional defaults.
                rec, loc, pin_name = {}, parts[0], parts[1]
            def _g(field, _r=rec):
                return _r.get(field, "NA")
            pins[loc] = {
                "name":       pin_name,
                "byte_group": _g("byte_group"),
                "bank":       _g("bank"),
                "vccaux":     _g("vccaux"),
                "slr":        _g("slr"),
                "io_type":    _g("io_type"),
                "no_connect": _g("no_connect"),
                "color_key":  classify_pin(pin_name, _g("io_type")),
            }
    return pins


# Capture the get_ports argument: a braced {...} (may contain bus brackets),
# a quoted "...", or a bare token (stops before whitespace or closing bracket).
_GET_PORTS_RE = re.compile(
    r"get_ports\s+(\{[^}]*\}|\"[^\"]*\"|[^\s\]]+)", re.IGNORECASE)
_DICT_RE      = re.compile(r"-dict\s*\{([^}]*)\}",     re.IGNORECASE)
_SETPROP_RE   = re.compile(
    r"set_property\s+(?:-\w+\s+)*?([A-Za-z_]\w*)\s+(\S+)\s+\[get_ports", re.IGNORECASE)


def collect_xdc_files(path):
    """Return a list of .xdc files. If `path` is a directory, search it
    recursively; otherwise return the single file."""
    if os.path.isdir(path):
        found = []
        for root, _dirs, files in os.walk(path):
            for fn in files:
                if fn.lower().endswith(".xdc"):
                    found.append(os.path.join(root, fn))
        return sorted(found)
    return [path]


def _read_logical_lines(path):
    """Yield logical lines, joining Tcl backslash line continuations."""
    buf = ""
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.rstrip().endswith("\\"):
                buf += line.rstrip()[:-1] + " "
                continue
            buf += line
            yield buf
            buf = ""
    if buf:
        yield buf


def _clean_signal(token):
    token = token.strip()
    if token.startswith("{") and token.endswith("}"):
        token = token[1:-1].strip()
    return token.strip('"').strip()


def parse_xdc_into(path, signals):
    """Parse one .xdc file, accumulating set_property values per signal into
    the `signals` dict. Handles properties spread across multiple
    set_property lines for the same signal, as well as the -dict form."""
    for line in _read_logical_lines(path):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "set_property" not in s.lower():
            continue
        gm = _GET_PORTS_RE.search(s)
        if not gm:
            continue
        signal = _clean_signal(gm.group(1))
        props = signals.setdefault(signal, {})
        dm = _DICT_RE.search(s)
        if dm:
            toks = dm.group(1).split()
            for i in range(0, len(toks) - 1, 2):
                key = toks[i].upper()
                props[key] = toks[i + 1]
                if key == "PACKAGE_PIN":
                    props["__file__"] = path
        else:
            pm = _SETPROP_RE.search(s)
            if pm:
                props[pm.group(1).upper()] = pm.group(2)
                if pm.group(1).upper() == "PACKAGE_PIN":
                    props["__file__"] = path


def parse_xdc(paths):
    """Parse one or more .xdc files and return ``(used, collisions)`` where
    ``used`` is a dict keyed by package pin location
    ``{loc: {"signal": ..., "iostandard": ...}}`` and ``collisions`` is a dict
    ``{loc: [signal, ...]}`` listing every pin assigned to more than one
    distinct signal (a conflicting / colliding assignment)."""
    signals = {}
    for path in paths:
        parse_xdc_into(path, signals)

    used = {}
    loc_signals = {}  # loc -> ordered list of distinct signals on that pin
    loc_files   = {}  # loc -> ordered list of distinct source xdc files
    for signal, props in signals.items():
        loc = props.get("PACKAGE_PIN")
        if not loc:
            continue
        loc = _clean_signal(loc).upper().rstrip(";")
        std = props.get("IOSTANDARD", "--")
        src = props.get("__file__", "")
        sigs = loc_signals.setdefault(loc, [])
        if signal not in sigs:
            sigs.append(signal)
        files = loc_files.setdefault(loc, [])
        if src and src not in files:
            files.append(src)
        if loc not in used:
            used[loc] = {"signal": signal, "iostandard": std, "file": src}

    collisions = {}
    for loc, sigs in loc_signals.items():
        # The source file(s) that define this pin -- shown in the sidebar tooltip.
        used[loc]["file"] = "; ".join(loc_files.get(loc, [])) or used[loc].get("file", "")
        if len(sigs) > 1:
            # More than one signal assigned to the same physical pin --
            # surface every conflicting signal in the detail view.
            used[loc]["signal"] = ", ".join(sigs)
            collisions[loc] = sigs
    return used, collisions


def _row_key(label):
    # BGA row labels run A..Z, then AA, AB, ... -- so shorter labels sort
    # first, and labels of equal length sort alphabetically. Plain string
    # sorting would wrongly place "AA" right after "A".
    return (len(label), label)


def infer_grid(pins):
    rows, cols = set(), set()
    pat = re.compile(r"^([A-Z]+)(\d+)$")
    for loc in pins:
        m = pat.match(loc)
        if m:
            rows.add(m.group(1))
            cols.add(int(m.group(2)))
    return sorted(rows, key=_row_key), sorted(cols)


def compute_bank_utilization(pkg_pins, used_pins):
    """Return a list of per-bank PL I/O utilization records, sorted by bank,
    e.g. ``[{"bank": "47", "io_type": "HD", "total": 26, "used": 4}, ...]``.
    Only PL SelectIO banks (HR/HP/HD) are included."""
    banks = {}
    for loc, d in pkg_pins.items():
        if d["color_key"] not in PL_IO_TYPES:
            continue
        bank = d["bank"]
        entry = banks.setdefault(bank, {"bank": bank, "io_type": d["color_key"],
                                        "total": 0, "used": 0})
        entry["total"] += 1
        if loc in used_pins:
            entry["used"] += 1

    def _bank_key(rec):
        b = rec["bank"]
        return (0, int(b)) if b.isdigit() else (1, b)

    return sorted(banks.values(), key=_bank_key)


def generate_html(pkg_pins, used_pins, collisions, bank_util,
                  output_path, pkg_file, xdc_label):
    rows, cols = infer_grid(pkg_pins)
    n_io   = sum(1 for d in pkg_pins.values()  if d["color_key"] in PL_IO_TYPES)
    n_used = sum(1 for p, d in pkg_pins.items()
                 if d["color_key"] in PL_IO_TYPES and p in used_pins)
    pct = "{:.1f}".format(n_used / n_io * 100) if n_io else "0.0"

    js_pkg    = json.dumps(pkg_pins,  ensure_ascii=False)
    js_used   = json.dumps(used_pins, ensure_ascii=False)
    js_coll   = json.dumps(collisions, ensure_ascii=False)
    js_banks  = json.dumps(bank_util, ensure_ascii=False)
    js_rows   = json.dumps(rows)
    js_cols   = json.dumps(cols)
    js_colors = json.dumps(PIN_COLORS)
    pkg_base  = os.path.basename(pkg_file)
    xdc_base  = xdc_label

    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pin Map -- """)
    parts.append(pkg_base)
    parts.append("""</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --sb: 275px; --cell: 28px; --gap: 3px;
  --bg: #111827; --panel: #1f2937; --border: #374151;
  --text: #e5e7eb; --muted: #6b7280; --accent: #f59e0b;
}
html, body {
  height: 100%; overflow: hidden;
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: var(--bg); color: var(--text); font-size: 13px;
}
#app { display: flex; height: 100vh; }
#sb {
  width: var(--sb); min-width: var(--sb);
  background: var(--panel); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; overflow: hidden;
}
.sb-hd { padding: 12px 14px; border-bottom: 1px solid var(--border); background: #111827cc; }
.sb-hd h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .1em; color: var(--accent); font-weight: 700; }
.sb-hd .src { font-size: 10px; color: var(--muted); margin-top: 4px; word-break: break-all; }
#detail { flex: 1; overflow-y: auto; padding: 12px 14px; }
.ph { color: var(--muted); font-style: italic; font-size: 12px; margin-top: 8px; }
.dr { margin-bottom: 11px; }
.dl { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin-bottom: 2px; }
.dv { font-size: 13px; font-weight: 500; line-height: 1.3; word-break: break-all; }
.dv.sig { color: """)
    parts.append(USED_BORDER)
    parts.append("""; font-weight: 700; }
.dv.na  { color: var(--muted); }
#stats { padding: 10px 14px; border-top: 1px solid var(--border); font-size: 11px; color: var(--muted); line-height: 1.8; }
#stats b { color: var(--text); }
#legend { padding: 10px 14px 14px; border-top: 1px solid var(--border); }
#legend h3 { font-size: 10px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin-bottom: 7px; }
.leg { display: flex; align-items: center; gap: 7px; margin-bottom: 5px; font-size: 11px; }
.sw { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }
.sw-used { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; background: transparent; border: 2px solid """)
    parts.append(USED_BORDER)
    parts.append("""; }
#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#tb { padding: 9px 16px; background: var(--panel); border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 22px; flex-wrap: wrap; }
#tb h1 { font-size: 13px; font-weight: 600; color: var(--text); }
.ck { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 12px; user-select: none; }
.ck input { accent-color: var(--accent); width: 13px; height: 13px; cursor: pointer; }
#gs { flex: 1; overflow: auto; padding: 20px 24px; }
#grid { display: inline-block; }
.gr { display: flex; align-items: center; gap: var(--gap); margin-bottom: var(--gap); }
.ax { width: var(--cell); height: var(--cell); display: flex; align-items: center; justify-content: center;
  font-size: 9px; font-weight: 700; color: var(--muted); flex-shrink: 0; }
.pin { width: var(--cell); height: var(--cell); border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0; font-weight: 700; color: rgba(255,255,255,.75);
  cursor: pointer; flex-shrink: 0; border: 2px solid transparent;
  transition: transform .1s, box-shadow .1s; position: relative; user-select: none; }
.pin:hover, .pin.hi { transform: scale(1.45); z-index: 20; box-shadow: 0 0 10px rgba(255,255,255,.45); }
.pin.used { border: 2px solid """)
    parts.append(USED_BORDER)
    parts.append("""; box-shadow: 0 0 5px """)
    parts.append(USED_BORDER)
    parts.append("""55; }
.pin.used:hover, .pin.used.hi { box-shadow: 0 0 12px """)
    parts.append(USED_BORDER)
    parts.append("""cc; }
.pe { width: var(--cell); height: var(--cell); flex-shrink: 0; }
body.show-lbl .pin { font-size: 6px; }
.dv.sig { cursor: help; }
#tip { position: fixed; z-index: 100; max-width: 360px; pointer-events: none;
  background: #0b1220; border: 1px solid var(--accent); border-radius: 5px;
  padding: 7px 9px; font-size: 11px; color: var(--text); line-height: 1.4;
  box-shadow: 0 4px 14px rgba(0,0,0,.6); display: none; word-break: break-all; }
#tip .tip-lbl { color: var(--accent); font-size: 9px; text-transform: uppercase;
  letter-spacing: .07em; display: block; margin-bottom: 3px; }
.pin.collision { border: 2px solid #ff3b30 !important;
  box-shadow: 0 0 8px #ff3b30, 0 0 3px #ff3b30 inset !important; }
.pin.collision:hover, .pin.collision.hi { box-shadow: 0 0 14px #ff3b30 !important; }
.sw-coll { width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0;
  background: transparent; border: 2px solid #ff3b30; }
.dv.warn { color: #ff3b30; font-weight: 700; }
#banks { border-top: 1px solid var(--border); padding: 10px 14px 4px; max-height: 230px;
  overflow-y: auto; }
#banks h3 { font-size: 10px; text-transform: uppercase; letter-spacing: .07em;
  color: var(--muted); margin-bottom: 8px; }
.bk { margin-bottom: 7px; font-size: 11px; }
.bk-top { display: flex; justify-content: space-between; margin-bottom: 3px; }
.bk-name { color: var(--text); font-weight: 600; }
.bk-name .tag { color: var(--muted); font-weight: 400; margin-left: 5px; }
.bk-cnt { color: var(--muted); }
.bk-cnt b { color: var(--text); }
.bar { height: 5px; border-radius: 3px; background: #374151; overflow: hidden; }
.bar > span { display: block; height: 100%; background: """)
    parts.append(USED_BORDER)
    parts.append("""; }
</style>
</head>
<body>
<div id="tip"></div>
<div id="app">
<div id="sb">
  <div class="sb-hd">
    <h2>Pin Details</h2>
    <div class="src">&#128230; """)
    parts.append(pkg_base)
    parts.append("<br>&#128279; ")
    parts.append(xdc_base)
    parts.append("""</div>
  </div>
  <div id="detail"><p class="ph">Hover over a pin</p></div>
  <div id="banks">
    <h3>PL I/O Utilization by Bank</h3>
    <div id="bank-list"></div>
  </div>
  <div id="stats">
    PL I/O used: <b>""")
    parts.append(str(n_used))
    parts.append("</b> / <b>")
    parts.append(str(n_io))
    parts.append("</b> &nbsp;(<b>")
    parts.append(pct)
    parts.append("%</b>)")
    if collisions:
        parts.append("<br>&#9888; <b style=\"color:#ff3b30\">")
        parts.append(str(len(collisions)))
        parts.append("</b> pin collision(s)")
    parts.append("""
  </div>
  <div id="legend">
    <h3>Legend</h3>
    <div id="leg"></div>
    <div class="leg"><div class="sw-used"></div> Assigned in XDC</div>
    <div class="leg"><div class="sw-coll"></div> Pin collision</div>
  </div>
</div>
<div id="main">
  <div id="tb">
    <h1>&#128204; """)
    parts.append(pkg_base)
    parts.append("""</h1>
    <label class="ck"><input type="checkbox" id="chk-dim"> Unused Pins Dimmed</label>
    <label class="ck"><input type="checkbox" id="chk-lbl"> Pin Labels</label>
    <label class="ck"><input type="checkbox" id="chk-bank"> Bank Labels</label>
  </div>
  <div id="gs"><div id="grid"></div></div>
</div>
</div>
<script>
'use strict';
var PKG    = """)
    parts.append(js_pkg)
    parts.append(";\nvar USED   = ")
    parts.append(js_used)
    parts.append(";\nvar COLL   = ")
    parts.append(js_coll)
    parts.append(";\nvar BANKS  = ")
    parts.append(js_banks)
    parts.append(";\nvar ROWS   = ")
    parts.append(js_rows)
    parts.append(";\nvar COLS   = ")
    parts.append(js_cols)
    parts.append(";\nvar COLORS = ")
    parts.append(js_colors)
    parts.append(";\nvar DIMMED = '")
    parts.append(DIMMED_COLOR)
    parts.append("""';
var IO_TYPES = {HR:1,HP:1,HD:1};
var LABEL_MAP = {
  HR:'HR I/O', HP:'HP I/O', HD:'HD I/O',
  CONFIG:'Config / JTAG', GND:'Ground', VCC:'Power (VCC / VREF)',
  NC:'No-Connect', OTHER:'Other'
};

// Assign each distinct bank a unique label color. Hues are spread by the
// golden angle so adjacent banks stay visually distinct.
var BANK_COLORS = {};
(function() {
  var set = {};
  Object.values(PKG).forEach(function(p){ if (p.bank && p.bank !== 'NA') set[p.bank] = 1; });
  Object.keys(set).sort(function(a, b) {
    var na = parseInt(a, 10), nb = parseInt(b, 10);
    if (!isNaN(na) && !isNaN(nb)) return na - nb;
    return a < b ? -1 : a > b ? 1 : 0;
  }).forEach(function(bank, i) {
    BANK_COLORS[bank] = 'hsl(' + ((i * 137.5) % 360).toFixed(1) + ', 80%, 68%)';
  });
})();

// Legend
var usedKeys = {};
Object.values(PKG).forEach(function(p){ usedKeys[p.color_key] = 1; });
var legEl = document.getElementById('leg');
Object.keys(COLORS).forEach(function(key) {
  if (!usedKeys[key]) return;
  var d = document.createElement('div');
  d.className = 'leg';
  d.innerHTML = '<div class="sw" style="background:' + COLORS[key] + '"></div><span>' + (LABEL_MAP[key] || key) + '</span>';
  legEl.appendChild(d);
});

// PL I/O utilization by bank
var bankListEl = document.getElementById('bank-list');
if (!BANKS.length) {
  bankListEl.innerHTML = '<p class="ph">No PL I/O banks found</p>';
} else {
  BANKS.forEach(function(b) {
    var pct = b.total ? (b.used / b.total * 100) : 0;
    var div = document.createElement('div');
    div.className = 'bk';
    var bc = BANK_COLORS[b.bank] || 'var(--text)';
    div.innerHTML =
      '<div class="bk-top">' +
        '<span class="bk-name" style="color:' + bc + '">Bank ' + b.bank + '<span class="tag">' + b.io_type + '</span></span>' +
        '<span class="bk-cnt"><b>' + b.used + '</b> / ' + b.total + ' (' + pct.toFixed(0) + '%)</span>' +
      '</div>' +
      '<div class="bar"><span style="width:' + pct.toFixed(1) + '%"></span></div>';
    bankListEl.appendChild(div);
  });
}

// Build grid
var grid = document.getElementById('grid');
var hdr = mk('div','gr');
hdr.appendChild(mk('div','ax',''));
COLS.forEach(function(c){ hdr.appendChild(mk('div','ax',String(c))); });
grid.appendChild(hdr);

ROWS.forEach(function(r) {
  var row = mk('div','gr');
  row.appendChild(mk('div','ax',r));
  COLS.forEach(function(c) {
    var loc  = r + c;
    var data = PKG[loc];
    if (!data) { row.appendChild(mk('div','pe')); return; }
    var isUsed = !!USED[loc];
    var isColl = !!COLL[loc];
    var color  = COLORS[data.color_key] || COLORS['OTHER'];
    var cell   = mk('div','pin'+(isUsed?' used':'')+(isColl?' collision':''),loc);
    cell.style.background = color;
    cell.dataset.loc = loc;
    cell.addEventListener('mouseenter', (function(l,c){ return function(){ showDetail(l,c); }; })(loc,cell));
    cell.addEventListener('mouseleave', (function(c){ return function(){ clearHi(c); }; })(cell));
    row.appendChild(cell);
  });
  grid.appendChild(row);
});

// Dim mode
var dimmed = false;
document.getElementById('chk-dim').addEventListener('change', function(e) {
  dimmed = e.target.checked; applyDim();
});
function applyDim() {
  document.querySelectorAll('.pin').forEach(function(cell) {
    var d = PKG[cell.dataset.loc];
    if (dimmed && IO_TYPES[d.color_key] && !USED[cell.dataset.loc]) {
      cell.style.background = DIMMED;
      cell.style.opacity    = '0.25';
    } else {
      cell.style.background = COLORS[d.color_key] || COLORS['OTHER'];
      cell.style.opacity    = '1';
    }
  });
}

// Label toggles -- pin location labels and per-bank colored bank labels.
// When both are on, bank labels take precedence (one label fits per pin).
var chkLbl  = document.getElementById('chk-lbl');
var chkBank = document.getElementById('chk-bank');
function applyLabels() {
  var showPin = chkLbl.checked, showBank = chkBank.checked;
  document.body.classList.toggle('show-lbl', showPin || showBank);
  document.querySelectorAll('.pin').forEach(function(cell) {
    var loc = cell.dataset.loc, d = PKG[loc];
    if (showBank) {
      var b = d.bank;
      cell.textContent = (b && b !== 'NA') ? b : '';
      cell.style.color = BANK_COLORS[b] || 'rgba(255,255,255,.75)';
    } else {
      cell.textContent = loc;
      cell.style.color = '';
    }
  });
}
chkLbl.addEventListener('change', applyLabels);
chkBank.addEventListener('change', applyLabels);

// Detail panel
var hiCell = null;
var panel = document.getElementById('detail');
function showDetail(loc, cell) {
  if (hiCell) hiCell.classList.remove('hi');
  hiCell = cell;
  cell.classList.add('hi');
  var d    = PKG[loc] || {};
  var used = USED[loc];
  var rows = [
    ['Pin',        loc],
    ['Pin Name',   d.name       || '--'],
    ['I/O Type',   d.io_type    || '--'],
    ['Bank',       d.bank       || '--'],
    ['Byte Group', d.byte_group || '--'],
    ['VCCAUX Grp', d.vccaux     || '--'],
    ['SLR',        d.slr        || '--'],
    ['No-Connect', d.no_connect || '--']
  ];
  if (used) {
    rows.push(['Signal',      used.signal]);
    rows.push(['IO Standard', used.iostandard]);
  }
  var coll = COLL[loc];
  if (coll) {
    rows.push(['⚠ Collision', coll.length + ' signals on this pin: ' + coll.join(', ')]);
  }
  panel.innerHTML = rows.map(function(pair) {
    var label = pair[0], val = pair[1];
    var cls = '', attr = '';
    if (label === 'Signal') {
      cls = 'sig';
      if (used && used.file) attr = ' data-file="' + escAttr(used.file) + '"';
    }
    else if (label.indexOf('Collision') !== -1) cls = 'warn';
    else if (val === 'NA' || val === '--') cls = 'na';
    return '<div class="dr"><div class="dl">'+label+'</div><div class="dv '+cls+'"'+attr+'>'+val+'</div></div>';
  }).join('');
}

// Tooltip: hovering the signal name reveals the source .xdc file path(s).
var tip = document.getElementById('tip');
function escAttr(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
                  .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function positionTip(e) {
  var x = e.clientX + 14, y = e.clientY + 16;
  var w = tip.offsetWidth, h = tip.offsetHeight;
  if (x + w > window.innerWidth  - 8) x = e.clientX - w - 14;
  if (y + h > window.innerHeight - 8) y = e.clientY - h - 16;
  tip.style.left = x + 'px';
  tip.style.top  = y + 'px';
}
panel.addEventListener('mouseover', function(e) {
  var t = e.target.closest('[data-file]');
  if (!t) return;
  var f = t.getAttribute('data-file');
  if (!f) return;
  tip.innerHTML = '<span class="tip-lbl">XDC source</span>' +
    f.split('; ').map(escAttr).join('<br>');
  tip.style.display = 'block';
  positionTip(e);
});
panel.addEventListener('mousemove', function(e) {
  if (tip.style.display === 'block') positionTip(e);
});
panel.addEventListener('mouseout', function(e) {
  if (e.target.closest('[data-file]')) tip.style.display = 'none';
});
function clearHi(cell) {
  cell.classList.remove('hi');
  if (hiCell === cell) hiCell = null;
}
function mk(tag, cls, text) {
  var el = document.createElement(tag);
  if (cls)  el.className   = cls  || '';
  if (text) el.textContent = text || '';
  return el;
}
</script>
</body>
</html>
""")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    pkg_file = sys.argv[1]
    xdc_path = sys.argv[2]
    out_file = sys.argv[3] if len(sys.argv) > 3 else "pinmap.html"

    print("Parsing package data : " + pkg_file)
    pkg_pins = parse_package_data(pkg_file)
    print("  -> " + str(len(pkg_pins)) + " pins loaded")

    xdc_files = collect_xdc_files(xdc_path)
    if not xdc_files:
        print("ERROR: no .xdc files found in '" + xdc_path + "'")
        sys.exit(1)

    if os.path.isdir(xdc_path):
        print("Parsing XDC dir      : " + xdc_path +
              " (" + str(len(xdc_files)) + " file(s))")
        for p in xdc_files:
            print("    - " + p)
        xdc_label = os.path.basename(os.path.normpath(xdc_path)) + \
            "/ (" + str(len(xdc_files)) + " files)"
    else:
        print("Parsing XDC          : " + xdc_path)
        xdc_label = os.path.basename(xdc_path)

    used_pins, collisions = parse_xdc(xdc_files)
    print("  -> " + str(len(used_pins)) + " assigned pins found")

    missing = [p for p in used_pins if p not in pkg_pins]
    if missing:
        print("  WARNING: " + str(len(missing)) + " XDC pin(s) not in package data: " + ", ".join(missing))

    if collisions:
        print("  WARNING: " + str(len(collisions)) +
              " pin collision(s) detected -- conflicting pin assignments:")
        for loc in sorted(collisions):
            print("    - " + loc + ": " + ", ".join(collisions[loc]))

    bank_util = compute_bank_utilization(pkg_pins, used_pins)

    print("Generating HTML      : " + out_file)
    generate_html(pkg_pins, used_pins, collisions, bank_util,
                  out_file, pkg_file, xdc_label)

    n_io   = sum(1 for d in pkg_pins.values()  if d["color_key"] in PL_IO_TYPES)
    n_used = sum(1 for p, d in pkg_pins.items()
                 if d["color_key"] in PL_IO_TYPES and p in used_pins)
    if n_io:
        print("  PL I/O capacity used : " + str(n_used) + "/" + str(n_io) +
              " (" + "{:.1f}".format(n_used/n_io*100) + "%)")
        print("  PL I/O by bank:")
        for b in bank_util:
            bpct = b["used"] / b["total"] * 100 if b["total"] else 0.0
            print("    - Bank {0:>4} ({1}): {2}/{3} ({4:.1f}%)".format(
                b["bank"], b["io_type"], b["used"], b["total"], bpct))
    print("Done.")


if __name__ == "__main__":
    main()
