# Glowforge Serial Port Access
Older Glowforges have a Micro-USB serial port connector on the control board (J13 located in the lower left of the board picture below).  If you are fortunate enough to have one of those units, you can just plug that into your PC. It's a standard [FTDI FT230](https://ftdichip.com/products/ft230xq/) serial-to-USB adapter and the driver is included in most operating systems.

If you are not that fortunate, you can follow these instructions:

First, you will need a soldering iron.  No getting around that one.  Next, you need a FTDI [TTL-232RG-VREG1V8-WE](https://www.ftdichip.com/Products/Cables/USBTTLSerial.htm) USB to Serial Port adapter. It is important that you get the 1.8V model.  If you get a 3.3V or 5V version you will irreversibly destroy your control board.  You can purchase this directly from FTDI, Amazon, or most electronic supply shops.

When you receive your adapter, you'll need to prep it.  We only require three of the lead wires.  The others should be trimmed (to unequal lengths, lest they short out when you heatshrink/tape them up).

![CablePrep|690x218](https://raw.githubusercontent.com/ScottW514/forgefirm/master/docs/assets/CablePrep.jpg) 

We'll be connecting to the microprocessor's serial console port test points: RXD: D3B, TXD: D3D.

![Control_PCB_TestPoints|502x500](https://raw.githubusercontent.com/ScottW514/forgefirm/master/docs/assets/Control_PCB_TestPoints.jpg)

I recommend soldering the ground wire first to the ground pad located to the upper left of the microprocessor (see picture below).  Clip the leads for the TXD and RXD to be no longer a millimeter before soldering.  This helps to avoid unwanted contact with surrounding items.

![Connection|690x435](https://raw.githubusercontent.com/ScottW514/forgefirm/master/docs/assets/Connection.jpg)

After you've soldered all the leads, secure the cable to the PCB with a tie wrap, as pictured.  This is important.  The test points will not stand much mechanical stress, and will rip off the board easily.  Don't worry, if this happens to you, they are still accessible from the bottom of the board - second chance.

From there, connect the USB cable to your computer and fire up your favorite terminal (Putty works well).  The serial settings are 115,200 8N1.  Be sure to select a color terminal with UTF-8 encoding if you want the best experience from the OpenGlow firmware.

NOTE: You will need to keep the serial port adpater powered on at all times when you are operating the Glowforge. If it is not powered, it draws down the 1.8V bus on the control board and prevents it from booting. If you don't have always have a computer near by, you can plug it into a USB charging adapter.
