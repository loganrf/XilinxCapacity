# Xilinx IO Capacity Visualization Tool

This script can be used to synthesize an interactive pin map of your AMD/Xilinx FPGA using a combination of the package data file (provided by AMD) and your custom .xdc.

The script generates a html webpage in the output directory that can be opened with your browser (chrome recommended). This HTML page consists of two sections: the lefthand sidebar and main display. The main display shows the pinout diagram (note: this tool assumes a uniform square pinout structure with letter codes indicating rows and numbers indicating columns).

## Installation

Installing the package puts an `xcap` command on your `PATH`, so you can run the
tool from any directory without needing a copy of `xcap.py`.

**Install directly from this repository (no clone needed):**

```
pip install git+https://github.com/loganrf/XilinxCapacity.git
```

**Install a released wheel** (attached to each [GitHub Release](https://github.com/loganrf/XilinxCapacity/releases)):

```
pip install xilinx_capacity-<version>-py3-none-any.whl
```

If/when the package is published to PyPI you can also `pip install xilinx-capacity`.

To install from a local clone:

```
git clone https://github.com/loganrf/XilinxCapacity.git
cd XilinxCapacity
pip install .          # add -e for an editable/development install
```

> Tip: `pipx install git+https://github.com/loganrf/XilinxCapacity.git` installs
> the command into an isolated environment while keeping it on your `PATH`.

### Running without installing

From a source checkout you can use the bundled wrapper script directly — add the
`bin/` directory to your `PATH` (or symlink `bin/xcap` somewhere on it):

```
export PATH="$PWD/bin:$PATH"
xcap <package_data.txt> <constraints.xdc | xdc_dir/> [output.html]
```

## Usage

Once installed, invoke the tool as a terminal command from anywhere:

```
xcap <package_data.txt> <constraints.xdc | xdc_dir/> [output.html]
```

Or, running directly from a source checkout:

```
python xcap.py <package_data.txt> <constraints.xdc | xdc_dir/> [output.html]
```

Use `xcap --help` for usage and `xcap --version` to print the version.

The constraints argument may be either a single `.xdc` file or a directory; if a directory is given it is searched recursively and all `.xdc` files are merged.

## Display modes

The user can select different display modes via checkboxes at the top of the display:
- **All Pins** (default): All pins are color coded by their pin type (similar to how Xilinx's package documentation shows them).
- **Unused Pins Dimmed**: Only used pins are colored per the same scheme; all others are a dim grey.
- **Pin Labels** / **Bank Labels**: Overlay each pin with its package location or its bank number.

## Interacting with the diagram

- **Hover** a pin to preview its details in the lefthand sidebar (signal name, IO standard, pin name, byte group, bank, IO type, etc).
- **Click** a pin to *lock* its details so they stay pinned while you move the mouse — useful for reading or copying values. Click the pin again, click empty grid space, press `Esc`, or use the × in the lock banner to release it.
- When a pin is selected, its **differential-pair partner** (the matching `L##P`/`L##N` pin in the same bank) is ringed in cyan and listed in the detail panel.
- **Click `Pin`, `Pin Name`, or `Signal`** in the detail panel to copy that value to the clipboard.
- **Click a bank** in the "PL I/O Utilization by Bank" list to highlight every pin in that bank on the diagram. Click again to clear.
- **Click a legend swatch** to hide/show that whole pin class on the diagram.

## Search & filter

A search box in the toolbar filters the diagram live. Type any pin location, signal name, bank, IO type, byte group, or IO standard — matching pins are ringed and everything else fades back, with a running match count. `Esc` clears the search.

## Design-rule checks

The tool flags two classes of real Vivado constraint errors directly on the diagram and in the sidebar:

- **Pin collisions** — the same `PACKAGE_PIN` assigned to more than one distinct signal (red ring).
- **Bank VCCO conflicts** — signals within a single I/O bank whose `IOSTANDARD`s demand different VCCO rail voltages (e.g. `LVCMOS33` at 3.3 V and `SSTL135` at 1.35 V in the same bank). Because a bank has one VCCO supply, such a mix cannot be routed; affected banks are marked with a ⚠ in the bank list and detailed when you inspect an offending pin.

## Export

The **Export CSV** button downloads a `pinmap_report.csv` containing every assigned pin (with its bank, IO standard, derived VCCO voltage, and collision/conflict flags) plus the per-bank PL I/O utilization summary — handy for spreadsheets, reviews, or diffing between builds.

## Releasing

Releases are automated by GitHub Actions:

- **CI** (`.github/workflows/ci.yml`) builds the package and smoke-tests the
  installed `xcap` command on every push and pull request.
- **Release** (`.github/workflows/release.yml`) runs when a version tag is
  pushed. It builds the wheel + sdist and attaches them to a GitHub Release so
  they can be installed with `pip`.

To cut a release, bump `version` in both `pyproject.toml` and `xcap.py`, then:

```
git tag v1.0.0
git push origin v1.0.0
```

Publishing to PyPI is optional: configure [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/)
for this repository and set the repository variable `PUBLISH_TO_PYPI` to `true`.
The release workflow's PyPI job is skipped unless that variable is set, so
GitHub Releases work out of the box without any secrets.
