import can
import cantools
import time
import sys

CHANNEL = "vcan0"
BUSTYPE = "socketcan"
DBC_PATH = "/app/vehicle.dbc"

rate_hz = float(sys.argv[1]) if len(sys.argv) > 1 else 10
duration_sec = float(sys.argv[2]) if len(sys.argv) > 2 else 20

db = cantools.database.load_file(DBC_PATH)
vehicle_status = db.get_message_by_name("VehicleStatus")
engine_status = db.get_message_by_name("EngineStatus")

bus = can.interface.Bus(channel=CHANNEL, interface=BUSTYPE)
interval = 1.0 / rate_hz
print(f"[load_test] sending at {rate_hz}Hz for {duration_sec}s (interval={interval:.4f}s)")

start = time.monotonic()
sent = 0
while time.monotonic() - start < duration_sec:
    speed = sent % 120
    rpm = 1500 + speed * 30
    battery_temp = 25

    vs_data = vehicle_status.encode({"VehicleSpeed": speed})
    es_data = engine_status.encode({"EngineRPM": rpm, "BatteryTemp": battery_temp})

    bus.send(can.Message(arbitration_id=vehicle_status.frame_id, data=vs_data, is_extended_id=False))
    bus.send(can.Message(arbitration_id=engine_status.frame_id, data=es_data, is_extended_id=False))
    sent += 2

    time.sleep(interval)

elapsed = time.monotonic() - start
print(f"[load_test] done: sent {sent} frames in {elapsed:.2f}s ({sent/elapsed:.1f} frames/sec actual)")
bus.shutdown()
