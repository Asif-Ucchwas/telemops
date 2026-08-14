import logging
import math
import os
import sys
import time
from pathlib import Path

import can
import cantools

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("can_publisher")

CHANNEL = os.environ.get("CAN_CHANNEL", "vcan0")
BUSTYPE = os.environ.get("CAN_BUSTYPE", "socketcan")
SEND_INTERVAL_S = float(os.environ.get("CAN_SEND_INTERVAL_S", "0.5"))
# Default: vehicle.dbc next to this script (matches the Docker image layout,
# where can_publisher.py and vehicle.dbc are copied to the same /app dir).
# Override via DBC_PATH for other layouts (e.g. local dev against dbc/vehicle.dbc).
DBC_PATH = os.environ.get("DBC_PATH", str(Path(__file__).resolve().parent / "vehicle.dbc"))


def load_dbc(path):
    try:
        return cantools.database.load_file(path)
    except FileNotFoundError:
        logger.error(
            "DBC file not found at '%s'. Set DBC_PATH to the correct location "
            "(e.g. DBC_PATH=../dbc/vehicle.dbc for local dev outside Docker).",
            path,
        )
        sys.exit(1)


db = load_dbc(DBC_PATH)
vehicle_status = db.get_message_by_name("VehicleStatus")
engine_status = db.get_message_by_name("EngineStatus")


def main():
    try:
        bus = can.interface.Bus(channel=CHANNEL, interface=BUSTYPE)
    except OSError as e:
        logger.error(
            "Failed to open CAN interface '%s' (bustype=%s): %s. "
            "Is the interface up? Try: sudo ip link set %s up type vcan",
            CHANNEL, BUSTYPE, e, CHANNEL,
        )
        sys.exit(1)

    logger.info("Sending realistic signals on %s (DBC: %s)", CHANNEL, DBC_PATH)

    t = 0
    try:
        while True:
            speed = round(60 + 40 * math.sin(t / 20))
            rpm = round(1500 + speed * 30)
            battery_temp = round(35 + 35 * math.sin(t / 60))

            vs_data = vehicle_status.encode({"VehicleSpeed": speed})
            es_data = engine_status.encode({"EngineRPM": rpm, "BatteryTemp": battery_temp})

            try:
                bus.send(can.Message(arbitration_id=vehicle_status.frame_id, data=vs_data, is_extended_id=False))
                bus.send(can.Message(arbitration_id=engine_status.frame_id, data=es_data, is_extended_id=False))
            except can.CanError as e:
                logger.warning("Failed to send frame(s) at t=%d: %s", t, e)
                t += 1
                time.sleep(SEND_INTERVAL_S)
                continue

            logger.debug("speed=%dkm/h rpm=%d battery_temp=%dC", speed, rpm, battery_temp)

            t += 1
            time.sleep(SEND_INTERVAL_S)
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
