#!/usr/bin/env python3
"""
xcap.py -- Xilinx IO Capacity Visualization Tool

Generates an interactive HTML pin map from an AMD/Xilinx package data file
and a Vivado .xdc constraints file.

Usage:
    python xcap.py <package_data.txt> <constraints.xdc> [output.html]
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


def classify_pin(pin_name, io_type):
    n = pin_name.upper()
    if io_type in ("HR", "HP", "HD"):
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


def parse_package_data(path):
    pins = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("Pin") and "Pin Name" in s:
                continue
            if s.startswith("Total Number"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            loc, pin_name = parts[0], parts[1]
            def _f(i, default="NA", _p=parts):
                return _p[i] if len(_p) > i else default
            pins[loc] = {
                "name":       pin_name,
                "byte_group": _f(2),
                "bank":       _f(3),
                "vccaux":     _f(4),
                "slr":        _f(5),
                "io_type":    _f(6),
                "no_connect": _f(7),
                "color_key":  classify_pin(pin_name, _f(6)),
            }
    return pins


def parse_xdc(path):
    used = {}
    pin_re = re.compile(r"PACKAGE_PIN\s+(\S+)",             re.IGNORECASE)
    std_re = re.compile(r"IOSTANDARD\s+(\S+)",              re.IGNORECASE)
    sig_re = re.compile(r"\[get_ports\s*\{\s*([^}]+?)\s*\}", re.IGNORECASE)
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("#"):
                continue
            pm = pin_re.search(line)
            if not pm:
                continue
            loc = pm.group(1).upper().rstrip(";")
            std = std_re.search(line)
            sig = sig_re.search(line)
            used[loc] = {
                "signal":     sig.group(1).strip() if sig else "--",
                "iostandard": std.group(1)          if std else "--",
            }
    return used


def infer_grid(pins):
    rows, cols = set(), set()
    pat = re.compile(r"^([A-Z]+)(\d+)$")
    for loc in pins:
        m = pat.match(loc)
        if m:
            rows.add(m.group(1))
            cols.add(int(m.group(2)))
    return sorted(rows), sorted(cols)


def generate_html(pkg_pins, used_pins, output_path, pkg_file, xdc_file):
    rows, cols = infer_grid(pkg_pins)
    io_types = {"HR", "HP", "HD"}
    n_io   = sum(1 for d in pkg_pins.values()  if d["color_key"] in io_types)
    n_used = sum(1 for p, d in pkg_pins.items()
                 if d["color_key"] in io_types and p in used_pins)
    pct = "{:.1f}".format(n_used / n_io * 100) if n_io else "0.0"

    js_pkg    = json.dumps(pkg_pins,  ensure_ascii=False)
    js_used   = json.dumps(used_pins, ensure_ascii=False)
    js_rows   = json.dumps(rows)
    js_cols   = json.dumps(cols)
    js_colors = json.dumps(PIN_COLORS)
    pkg_base  = os.path.basename(pkg_file)
    xdc_base  = os.path.basename(xdc_file)

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
</style>
</head>
<body>
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
  <div id="stats">
    I/O used: <b>""")
    parts.append(str(n_used))
    parts.append("</b> / <b>")
    parts.append(str(n_io))
    parts.append("</b> &nbsp;(<b>")
    parts.append(pct)
    parts.append("""%</b>)
  </div>
  <div id="legend">
    <h3>Legend</h3>
    <div id="leg"></div>
    <div class="leg"><div class="sw-used"></div> Assigned in XDC</div>
  </div>
</div>
<div id="main">
  <div id="tb">
    <h1>&#128204; """)
    parts.append(pkg_base)
    parts.append("""</h1>
    <label class="ck"><input type="checkbox" id="chk-dim"> Unused Pins Dimmed</label>
    <label class="ck"><input type="checkbox" id="chk-lbl"> Pin Labels</label>
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
    var color  = COLORS[data.color_key] || COLORS['OTHER'];
    var cell   = mk('div','pin'+(isUsed?' used':''),loc);
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

// Label toggle
document.getElementById('chk-lbl').addEventListener('change', function(e) {
  document.body.classList.toggle('show-lbl', e.target.checked);
});

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
  panel.innerHTML = rows.map(function(pair) {
    var label = pair[0], val = pair[1];
    var cls = '';
    if (label === 'Signal') cls = 'sig';
    else if (val === 'NA' || val === '--') cls = 'na';
    return '<div class="dr"><div class="dl">'+label+'</div><div class="dv '+cls+'">'+val+'</div></div>';
  }).join('');
}
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
    xdc_file = sys.argv[2]
    out_file = sys.argv[3] if len(sys.argv) > 3 else "pinmap.html"

    print("Parsing package data : " + pkg_file)
    pkg_pins = parse_package_data(pkg_file)
    print("  -> " + str(len(pkg_pins)) + " pins loaded")

    print("Parsing XDC          : " + xdc_file)
    used_pins = parse_xdc(xdc_file)
    print("  -> " + str(len(used_pins)) + " assigned pins found")

    missing = [p for p in used_pins if p not in pkg_pins]
    if missing:
        print("  WARNING: " + str(len(missing)) + " XDC pin(s) not in package data: " + ", ".join(missing))

    print("Generating HTML      : " + out_file)
    generate_html(pkg_pins, used_pins, out_file, pkg_file, xdc_file)

    io_types = {"HR", "HP", "HD"}
    n_io   = sum(1 for d in pkg_pins.values()  if d["color_key"] in io_types)
    n_used = sum(1 for p, d in pkg_pins.items()
                 if d["color_key"] in io_types and p in used_pins)
    if n_io:
        print("  I/O capacity used  : " + str(n_used) + "/" + str(n_io) +
              " (" + "{:.1f}".format(n_used/n_io*100) + "%)")
    print("Done.")


if __name__ == "__main__":
    main()
