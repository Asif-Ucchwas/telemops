import os
import can
import cantools
import psycopg2
from psycopg2.extras import execute_values
import time

from decode import decode_can_frame, should_flush, build_signal_rows

CHANNEL = "vcan0"
BUSTYPE = "socketcan"
DBC_PATH = "/app/vehicle.dbc"
BATCH_SIZE = 20
FLUSH_INTERVAL = 2.0

db = cantools.database.load_file(DBC_PATH)

conn = psycopg2.connect(
    host=os.environ.get("DB_HOST", "localhost"), port=int(os.environ.get("DB_PORT", 5432)),
    dbname="telemops", user="telemops", password="telemops_dev"
)
conn.autocommit = False
cur = conn.cursor()

bus = can.interface.Bus(channel=CHANNEL, interface=BUSTYPE)
print(f"[ingest] listening on {CHANNEL}, batching writes to Postgres")

frame_buffer = []
signal_buffer = []
receive_times = []

def flush():
    if not frame_buffer:
        return
    oldest_lag = time.monotonic() - receive_times[0]

    frame_rows = execute_values(
        cur,
        "INSERT INTO can_frames (arbitration_id, raw_data) VALUES %s RETURNING id",
        frame_buffer,
        fetch=True
    )
    frame_ids = [row[0] for row in frame_rows]

    signal_rows = build_signal_rows(frame_ids, signal_buffer)

    if signal_rows:
        execute_values(
            cur,
            "INSERT INTO can_signals (frame_id, signal_name, value, unit) VALUES %s",
            signal_rows
        )

    conn.commit()
    print(f"[ingest] flushed {len(frame_buffer)} frames, {len(signal_rows)} signals, oldest_lag={oldest_lag:.2f}s")
    frame_buffer.clear()
    signal_buffer.clear()
    receive_times.clear()

last_flush = time.monotonic()

try:
    while True:
        msg = bus.recv(timeout=1.0)

        if msg is not None:
            frame_buffer.append((msg.arbitration_id, bytes(msg.data)))
            receive_times.append(time.monotonic())

            signals = decode_can_frame(db, msg.arbitration_id, msg.data)
            if not signals:
                print(f"[ingest] could not decode id=0x{msg.arbitration_id:X}")

            signal_buffer.append(signals)

        now = time.monotonic()
        if should_flush(len(frame_buffer), BATCH_SIZE, bool(frame_buffer), now - last_flush, FLUSH_INTERVAL):
            flush()
            last_flush = now

except KeyboardInterrupt:
    print("\n[ingest] stopped")
    flush()
finally:
    bus.shutdown()
    cur.close()
    conn.close()
