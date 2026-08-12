import can
import time

CHANNEL = "vcan0"
BUSTYPE = "socketcan"

def main():
    bus = can.interface.Bus(channel=CHANNEL, interface=BUSTYPE)
    print(f"[publisher] sending fixed-rate frames on {CHANNEL}")

    ids = [0x100, 0x200]
    counter = 0

    try:
        while True:
            for arb_id in ids:
                data = [counter % 256, (counter * 2) % 256, 0, 0, 0, 0, 0, 0]
                msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=False)
                bus.send(msg)
                print(f"[publisher] sent id=0x{arb_id:X} data={data}")
            counter += 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[publisher] stopped")
    finally:
        bus.shutdown()

if __name__ == "__main__":
    main()
