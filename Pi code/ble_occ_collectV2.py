# Gateway V2.0

"""
Receive packets from Sensor Node and decode them to their original RAW integer values.

Two modes for testing Gateway operation and BLE link quality:

  bleLinkTest()        - Decodes packets to RAW integers which are saved along with 
                         arrival times to CSV so that packet loss and sampling rate can be determined using Excel. 
  bleFeatureExtract()  - Decodes packets to RAW integer values converting them to their respective SI units,
                         reject outliers and save clean records as JSON Lines, ready to be sent
                         to Azure IoT Hub.
"""

import asyncio
import csv
import json
import math
import struct
import time
from datetime import datetime, timezone


from bleak import BleakClient, BleakScanner

# BLE link settings 
GROUP_ID = "G003"
DEVICE_NAME = "EE5127-" + GROUP_ID + "-EDD"
SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
SAMPLE_UUID = "12345678-1234-5678-1234-56789abcdef1"

LINK_TEST_FILE = "bleLinkTest.csv"       # raw integers + timing (link analysis)
FE_FILE = "filteredData.jsonl"       # filtered SI-unit records 
SECONDS = None          # defines how long to stay connected; None = run until Node is disabled

# Outlier filter settings
#Probable ranges of accepted values for each field, based on expected indoor conditions.
#Values outside of these ranges are rejected.
LIMITS = {
    "temperatureC": (-10.0, 40),
    "humidityPct": (0.0, 100.0),
    "lightLux": (0, 30000),     
    "co2ppm": (300, 10000),
}


# Magnus formula coefficients 
MAGNUS_A = 17.62
MAGNUS_B = 243.12

PRESSURE_HPA = 1013.25   # assumed ambient pressure

PACKET_FORMAT = "<Hhhhh"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)  # Uncorrupted packets will always be 10 bytes
FIELDS = ["temperatureC", "humidityPct", "lightLux", "co2ppm"]


#------------------------------#
# Helper functions             #
#------------------------------#
def decode_packet(data):
    if len(data) != PACKET_SIZE:
        return None #if packet length is not correct assume it is corrupted and return None
    return struct.unpack(PACKET_FORMAT, data)



#------------------------------------------------------------------------#
# Track packet loss from the previous and current sequence numbers.      #
# The sequence number is a 16-bit unsigned integer that wraps at 0-65535.#
# Wrapping is handled as duplicate packets rather than a gap.            #
#------------------------------------------------------------------------#
def track_sequence(seq, state):
    #Loading previous sequence number from state dictionary
    last = state["last_seq"]
    if last is not None: 
        expected = (last + 1) & 0xFFFF #The expected sequence number is the last sequence number + 1, wrapped to 16 bits.
        if seq != expected:
            gap = (seq - expected) & 0xFFFF #caluculating forward gap
            if gap < 0x8000: #if the forward gap is less than 32768, it is considered a gap and the number of missed packets is incremented.
                state["missed"] += gap
                state["last_seq"] = seq #update the last sequence number to the current sequence number
                print(f"Gap: expected seq {expected}, got {seq} ({gap} missing)")
            else: #if the forward gap is greater than or equal to 32768, 
                  #it is considered an out-of-order or duplicate packet and the out_of_order counter is incremented.
                state["out_of_order"] += 1
                print(f"Out-of-order/duplicate: expected {expected}, got {seq}")
    #This is the first packet received, store the sequence number for the next packet to compare against.
    state["last_seq"] = seq 



#Finding the Sensor Node by its BLE name or service UUID. If the node is not found, a RuntimeError is raised.
async def find_node():
    print(f"Scanning for {DEVICE_NAME}...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=20.0)
    if device is None:
        device = await BleakScanner.find_device_by_filter(
            lambda d, adv: SERVICE_UUID in [u.lower() for u in adv.service_uuids],
            timeout=10.0,
        )
    if device is None:
        raise RuntimeError(
            f"Could not find {DEVICE_NAME}."
        )
    return device




#--------------------------------------------------------------------------------------------------------------#
#Connect to the Sensor Node, subscribe to notifications, and run the provided handler for each received packet.
#--------------------------------------------------------------------------------------------------------------#
async def run_session(handler):
    #locate sensor node
    device = await find_node()
    #flag if link is disconnected
    disconnected = asyncio.Event()

    #Connect to the sensor node and fire disconnected event if the link is lost
    async with BleakClient(
        device, disconnected_callback=lambda _c: disconnected.set()
    ) as client:
        
        print(f"Connected to {DEVICE_NAME}")
        # Subscribe to notifications from the sensor node now before the first packet is sent 
        await client.start_notify(SAMPLE_UUID, handler)
        started = time.monotonic()
        #Idle until the link is disconnected or the connection period (SECONDS) has elapsed
        try:
            while not disconnected.is_set():
                if SECONDS is not None and time.monotonic() - started >= SECONDS:
                    break
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
        #Calculate the duration of the connection and stop notifications if still connected
        duration = time.monotonic() - started
        if client.is_connected:
            await client.stop_notify(SAMPLE_UUID)
    return duration



#-----------------------------------------------------------------------------------------------------------------#
#  bleLinkTest()        - Decodes packets to RAW integers which are saved along with                              #
#                        arrival times to CSV so that packet loss and sampling rate can be determined using Excel.# 
#-----------------------------------------------------------------------------------------------------------------#
async def bleLinkTest():
    state = {"saved": 0, "bad": 0, "missed": 0, "out_of_order": 0,
             "last_seq": None, "last_time": None, "intervals": []}

    with open(LINK_TEST_FILE, "w", newline="", encoding="utf-8") as log:
        writer = csv.writer(log)
        writer.writerow(["receivedAt", "seq", "t_raw", "h_raw", "lux", "c", "dt_ms"])
        log.flush()

        def handle(_sender, data):
            #Get the timestamp of the packet arrival
            now = time.monotonic()
            fields = decode_packet(data)

            #If the packet is the wrong size, increment bad packet counter
            if fields is None:
                state["bad"] += 1
                print(f"Skipped packet with {len(data)} bytes (expected {PACKET_SIZE})")
                return

            #Check for packet loss and out-of-order packets by tracking the sequence number
            seq = fields[0]
            track_sequence(seq, state)

            #Calculate the time difference between the current and last packet arrival
            dt_ms = ""
            if state["last_time"] is not None:
                dt = (now - state["last_time"]) * 1000.0
                state["intervals"].append(dt)
                dt_ms = f"{dt:.1f}"
            state["last_time"] = now

            #Convert to UTC format for readability
            received_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            #Write packet data to CSV file 
            writer.writerow([received_at, *fields, dt_ms])
            log.flush()
            state["saved"] += 1 #increment saved packet counter
            print(*fields) #print what was saved

        #Await next packet 
        duration = await run_session(handle)

    # ---- summary ----
    total_expected = state["saved"] + state["missed"]
    loss_pct = 100.0 * state["missed"] / total_expected if total_expected else 0.0
    print(f"\nObservation duration: {duration:.1f} s")
    print(f"Saved packets: {state['saved']}; Missing packets: {state['missed']} "
          f"({loss_pct:.2f} %); out-of-order: {state['out_of_order']}; "
          f"Corrupted packets: {state['bad']}")
    print(f"Saved to {LINK_TEST_FILE}")



#----------------------------------------------------------------#
# Helper method for SI unit conversion.                          #
#----------------------------------------------------------------#
def to_si_units(t_raw, h_raw, lux, c):
    temp_c = t_raw / 100.0
    rh_pct = h_raw / 100.0
    return {
        "temperatureC": temp_c,
        "humidityPct": rh_pct,
        "lightLux": lux,
        "co2ppm": c,
        "humidityRatioGkg": humidity_ratio(temp_c, rh_pct),
    }

def humidity_ratio(temp_c, rh_pct):
    if not (0.0 <= rh_pct <= 100.0) or not (-45.0 <= temp_c <= 60.0):
        return None
    satPressure = 6.112 * math.exp(MAGNUS_A * temp_c / (MAGNUS_B + temp_c))  # saturation pressure, hPa
    vapPressure = rh_pct / 100.0 * satPressure                                         # actual vapour pressure, hPa
    return round(1000.0 * 0.622 * vapPressure / (PRESSURE_HPA - vapPressure), 3)




#------------------------------------------------------------------------------------------------------------#
# Filter values using Hampel filter and probable ranges. Rejects outliers and returns a reason for rejection.#
#------------------------------------------------------------------------------------------------------------#
def filter_outliers():

    def reject_reason(values):
        #returns a readable string explaining why a packet was rejected
        #returns None if the packet passed all tests 
        for field in FIELDS:
            x = values[field]
            lo, hi = LIMITS[field]
            #Checking if the values are within the probable ranges
            if not lo <= x <= hi:
                return f"{field}={x} outside {lo}..{hi}"
        return None
    return reject_reason



# ===================================================================================================================#
# Mode 2: feature extraction and outlier filtering                                                                   #
#                                                                                                                    #
#   bleFeatureExtract()  - Decodes packets to RAW integer values converting them to their respective SI units,       #
#                          reject outliers and save clean records as JSON Lines, ready to be sent to Azure IoT Hub.  #
#                                                                                                                    #
# ===================================================================================================================#
async def bleFeatureExtract():

    state = {"saved": 0, "bad": 0, "rejected": 0, "missed": 0,
             "out_of_order": 0, "last_seq": None}
    reject_reason = filter_outliers()

    with open(FE_FILE, "w", encoding="utf-8") as out:

        def handle(_sender, data):
            fields = decode_packet(data)
            #If the packet is the wrong size, increment bad packet counter
            if fields is None:
                state["bad"] += 1
                print(f"Skipped packet with {len(data)} bytes (expected {PACKET_SIZE})")
                return

            #Track the sequence number to detect gaps and out-of-order packets
            seq, t_raw, h_raw, lux, c = fields
            track_sequence(seq, state)

            #Convert the raw integer values to their respective SI units and check for outliers
            values = to_si_units(t_raw, h_raw, lux, c)
            reason = reject_reason(values)
            if reason:
                state["rejected"] += 1
                print(f"Rejected seq {seq}: {reason}")
                return

            #If the packet passed all tests, save it as a JSON record with timestamp and sequence number  
            record = {
                "deviceId": DEVICE_NAME,
                "seq": seq,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                **values,
            }
            out.write(json.dumps(record) + "\n")
            out.flush()
            state["saved"] += 1
            print(record)

        duration = await run_session(handle)

    print(f"\nObservation duration: {duration:.1f} s")
    print(f"Saved: {state['saved']}; Rejected packets: {state['rejected']}; "
          f"Missing packets: {state['missed']}; out-of-order: {state['out_of_order']}; "
          f"Corrupted packets: {state['bad']}")
    print(f"Saved to {FE_FILE}")


#----------------------------------------------------------------#
# Tests run through main()
#----------------------------------------------------------------#
async def main():
    """Run the selected mode. Enable one line at a time."""
    # await bleLinkTest()          # raw CSV for link analysis (uncomment to use)
    await bleFeatureExtract()      # SI units + outlier filter -> JSONL for Azure


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user")
