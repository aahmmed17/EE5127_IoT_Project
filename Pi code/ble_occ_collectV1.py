#Gate V1.0

"""Receive OccupancyNode BLE packets on a Raspberry Pi and save them as CSV.

Packet layout (10 bytes, little-endian), matching the node's
struct.pack("<Hhhhh", seq, t, h, lux, c):
    seq  uint16  packet counter (wraps at 65535)
    t    int16
    h    int16
    lux  int16
    c    int16
"""

import asyncio
import csv
import struct
import time
from datetime import datetime, timezone

from bleak import BleakClient, BleakScanner

# ---------- settings ----------
GROUP_ID = "G003"
DEVICE_NAME = "EE5127-" + GROUP_ID + "-EDD"
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
SAMPLE_UUID = "12345678-1234-5678-1234-56789abcdef1"
OUTPUT_FILE = "received_packets.csv"
SECONDS = 300          # how long to stay connected; None = run until Ctrl+C
# ------------------------------

PACKET_FORMAT = "<Hhhhh"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)  # 10
COLUMNS = ["receivedAt", "seq", "t", "h", "lux", "c"]


def make_handler(writer, log, state):
    """Return a notification callback that decodes and saves each packet."""

    def handle(_sender, data):
        if len(data) != PACKET_SIZE:
            state["bad"] += 1
            print(f"Skipped packet with {len(data)} bytes (expected {PACKET_SIZE})")
            return

        seq, t, h, lux, c = struct.unpack(PACKET_FORMAT, data)

        # Gap detection (seq wraps at 16 bits).
        last = state["last_seq"]
        if last is not None:
            expected = (last + 1) & 0xFFFF
            if seq != expected:
                lost = (seq - expected) & 0xFFFF
                state["missed"] += lost
                print(f"Gap: expected seq {expected}, got {seq} ({lost} missing)")
        state["last_seq"] = seq

        received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        writer.writerow([received_at, seq, t, h, lux, c])
        log.flush()
        state["saved"] += 1
        print(seq, t, h, lux, c)

    return handle


async def find_node():
    """Find the node by name, falling back to its service UUID."""
    print(f"Scanning for {DEVICE_NAME}...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=20.0)
    if device is None:
        device = await BleakScanner.find_device_by_filter(
            lambda d, adv: SERVICE_UUID in [u.lower() for u in adv.service_uuids],
            timeout=10.0,
        )
    if device is None:
        raise RuntimeError(
            f"Could not find {DEVICE_NAME}. Check the node is advertising "
            "and not already connected to a phone or another gateway."
        )
    return device


async def main():
    device = await find_node()
    state = {"saved": 0, "bad": 0, "missed": 0, "last_seq": None}
    disconnected = asyncio.Event()

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as log:
        writer = csv.writer(log)
        writer.writerow(COLUMNS)
        log.flush()

        async with BleakClient(
            device, disconnected_callback=lambda _c: disconnected.set()
        ) as client:
            print(f"Connected to {DEVICE_NAME}")
            # The node waits ~20 s after connecting before sending, so subscribe now.
            await client.start_notify(SAMPLE_UUID, make_handler(writer, log, state))
            started = time.monotonic()
            try:
                while not disconnected.is_set():
                    if SECONDS is not None and time.monotonic() - started >= SECONDS:
                        break
                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                pass
            duration = time.monotonic() - started
            if client.is_connected:
                await client.stop_notify(SAMPLE_UUID)

    print(f"Connected observation: {duration:.1f} s")
    print(
        f"Saved packets: {state['saved']}; missing (by seq gaps): {state['missed']}; "
        f"wrong-size packets: {state['bad']}"
    )
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user")
