# Xilinx IO Capacity Visualization Tool

This script can be used to synthesize an interactive pin map of your AMD/Xilinx FPGA using a combination of the package data file (provided by AMD) and your custom .xdc.

The script generates a html webpage in the output directory that can be opened with your browser (chrome recommended). This HTML page consists of two sections: the lefthand sidebar and main display. The main display shows the pinout diagram (note: this tool assumes a uniform square pinout structure with letter codes indicating rows and numbers indicating columns). 

The user can select 2 different display modes via a checkbox at the top of the display:
- All Pins:  All pins are color coded by their pin type (similar to how xilinx's package documentation shows them)
- Unused Pins Dimmed: If this is selected, only used pins are colored per the same scheme as in the All Pins mode. All others a a dim grey

As the user moves their mouse over individual pins the lefthand sidebar displays various pin details from the package data & constraints file (signal name, IO standard, pin name, byte group, bank, IO type, etc)