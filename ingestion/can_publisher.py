import can
import cantools
import time
import math

CHANNEL = "vcan0"
BUSTYPE = "socketcan"
DBC_PATH = "/app/vehicle.dbc"

db = cantools.database.load_file(DBC_PATH)
vehicle_status = db.get_message_by_name("VehicleStatus")
engine_status = db.get_message_by_name("EngineStatus")

def main():
    bus = can.interface.Bus(channel=CHANNEL, interface=BUSTYPE)
    print(f"[publisher] sending realistic signals on {CHANNEL}")

    t = 0
    try:
        while True:
            speed = round(60 + 40 * math.sin(t / 20))
            rpm = round(1500 + speed * 30)
            battery_temp = round(25 + 5 * math.sin(t / 200))

            vs_data = vehicle_status.encode({"VehicleSpeed": speed})
            es_data = engine_status.encode({"EngineRPM": rpm, "BatteryTemp": battery_temp})

            bus.send(can.Message(arbitration_id=vehicle_status.frame_id, data=vs_data, is_extended_id=False))
            bus.send(can.Message(arbitration_id=engine_status.frame_id, data=es_data, is_extended_id=False))

            print(f"[publisher] speed={speed}km/h rpm={rpm} battery_temp={battery_temp}C")

            t += 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[publisher] stopped")
    finally:
        bus.shutdown()

if __name__ == "__main__":
    main()
