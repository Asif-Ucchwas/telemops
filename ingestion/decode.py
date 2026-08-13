"""
Pure, testable logic extracted from ingest.py's main loop.

ingest.py itself connects to Postgres and the CAN bus at import time,
which makes it untestable without live infrastructure. This module holds
the actual decision/decoding logic with zero I/O, so it can be unit
tested in isolation.
"""


def decode_can_frame(db, arbitration_id, data):
    """Decode a raw CAN frame into a list of (name, value, unit) tuples.

    Returns an empty list if the frame's arbitration ID isn't in the DBC
    or the payload can't be decoded against it - same fallback behavior
    as the original inline try/except in ingest.py.
    """
    try:
        decoded = db.decode_message(arbitration_id, data)
        message_def = db.get_message_by_frame_id(arbitration_id)
        signals = [
            (name, float(value), message_def.get_signal_by_name(name).unit or None)
            for name, value in decoded.items()
        ]
    except (KeyError, ValueError):
        signals = []
    return signals


def should_flush(buffer_len, batch_size, has_buffer, elapsed_since_flush, flush_interval):
    """Decide whether the batch buffer should be flushed now.

    True if the buffer has hit batch_size, OR the buffer is non-empty and
    flush_interval seconds have elapsed since the last flush - same
    condition as the original inline check in ingest.py's main loop.
    """
    return buffer_len >= batch_size or (has_buffer and elapsed_since_flush >= flush_interval)


def build_signal_rows(frame_ids, signal_buffer):
    """Flatten per-frame signal lists into (frame_id, signal_name, value, unit) rows.

    frame_ids and signal_buffer must be the same length and in matching
    order - frame_ids[i] corresponds to signal_buffer[i].
    """
    rows = []
    for frame_id, signals in zip(frame_ids, signal_buffer):
        for signal_name, value, unit in signals:
            rows.append((frame_id, signal_name, value, unit))
    return rows
