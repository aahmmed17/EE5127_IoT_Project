import time
import struct
from adafruit_ble import BLERadio
from adafruit_ble.advertising import Advertisement
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services import Service
from adafruit_ble.uuid import VendorUUID
from adafruit_ble.characteristics import Characteristic

# ---------- settings ----------
DATA_FILE = "node_setA.csv"
PERIOD = 60.0        # seconds per sample: 1.0 for debugging, 60.0 for the real-rate run
LOOP = False       # True = repeat the file forever (stress tests)
START_DELAY = 20             # seconds after connecting before the first sample is sent
RESTART_ON_CONNECT = True    # True: every new connection starts again at row 0
NAME = "OccNode"
# ------------------------------

class OccService(Service):
    uuid = VendorUUID("12345678-1234-5678-1234-56789abcdef0")
    sample = Characteristic(
        uuid=VendorUUID("12345678-1234-5678-1234-56789abcdef1"),
        properties=Characteristic.NOTIFY | Characteristic.READ,
        max_length=10,
        fixed_length=True,
        initial_value=bytes(10),
    )

def load_rows(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                t, h, lux, c = (int(x) for x in line.split(","))
                rows.append((t, h, lux, c))
    return rows

rows = load_rows(DATA_FILE)
print("loaded", len(rows), "rows from", DATA_FILE)

svc = OccService()
ble = BLERadio()
adv = ProvideServicesAdvertisement(svc)
scan = Advertisement()
scan.complete_name = NAME

seq = 0   # packet counter; kept across reconnects so gaps stay visible
while True:
    print("advertising as", NAME)
    ble.start_advertising(adv, scan_response=scan)
    while not ble.connected:
        time.sleep(0.1)
    ble.stop_advertising()
    print("connected")
     print("connected: first sample in", START_DELAY, "s")
    if RESTART_ON_CONNECT:
        seq = 0
    time.sleep(START_DELAY)             # time for the receiver to subscribe
    next_t = time.monotonic()
    next_t = time.monotonic()
    while ble.connected:
        if seq >= len(rows) and not LOOP:
            time.sleep(1)               # finished: idle (reset the board to rerun)
            continue
        t, h, lux, c = rows[seq % len(rows)]
        packet = struct.pack("<Hhhhh", seq & 0xFFFF, t, h, lux, c)   # 10 bytes
        svc.sample = packet             # writing the value sends a notification
        print(seq, t, h, lux, c, packet.hex())
        seq += 1
        next_t += PERIOD                # fixed schedule, so timing doesn't drift
        delay = next_t - time.monotonic()
        if delay > 0:
            time.sleep(delay)