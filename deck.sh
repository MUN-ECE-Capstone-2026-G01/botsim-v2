#!/usr/bin/bash
# Startup script — runs on each Pi.
# Place this file at the same level as lighthouse-fpga/ on the Pi
# (same location as the original deck.sh).
#
# Changes from original:
#   - Last line now launches robot/agent.py instead of
#     Lighthouse-Deck/tools/decodeV2pos.py

source venv/bin/activate
cd lighthouse-fpga/
python3 tools/reboot.py /dev/ttyAMA2 && sleep 1 && ../lighthouse-bootloader/scripts/uart_bootloader.py /dev/ttyAMA2 lighthouse.bin
python3 ~/botsim/robot/agent.py /dev/ttyAMA2
