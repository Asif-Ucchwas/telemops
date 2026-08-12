import can
import psycopg2
import time

CHANNEL = "vcan0"
BUSTYPE = "socketcan"
FRAMES_TO_CAPTURE = 10

conn = psycopg2.connect(
    host="localhost", port=5432,
    dbname="telemops", user="telemops", password="telemops_dev"
)
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS can_frames_test (
        id SERIAL PRIMARY KEY,
        arbitration_id INTEGER,
        data BYTEA,
        received_at TIMESTAMPTZ DEFAULT now()
    )
""")
print("[verify] table ready")

bus = can.interface.Bus(channel=CHANNEL, interface=BUSTYPE)
print(f"[verify] listening on {CHANNEL} for {FRAMES_TO_CAPTURE} frames")

count = 0
while count < FRAMES_TO_CAPTURE:
    msg = bus.recv(timeout=5.0)
    if msg is None:
        print("[verify] no frame received in 5s, still waiting...")
        continue
    cur.execute(
        "INSERT INTO can_frames_test (arbitration_id, data) VALUES (%s, %s)",
        (msg.arbitration_id, bytes(msg.data))
    )
    print(f"[verify] inserted id=0x{msg.arbitration_id:X} data={list(msg.data)}")
    count += 1

bus.shutdown()
cur.close()
conn.close()
print("[verify] done")
