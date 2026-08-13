import pytest
from decode import decode_can_frame, should_flush, build_signal_rows


class FakeSignal:
    def __init__(self, unit):
        self.unit = unit


class FakeMessageDef:
    def __init__(self, signal_units):
        self._signal_units = signal_units

    def get_signal_by_name(self, name):
        return FakeSignal(self._signal_units[name])


class FakeDB:
    """Minimal stand-in for a cantools Database, only implementing what
    decode_can_frame actually calls."""
    def __init__(self, known_ids):
        self._known_ids = known_ids  # {arb_id: {"decoded": {...}, "units": {...}}}

    def decode_message(self, arbitration_id, data):
        if arbitration_id not in self._known_ids:
            raise KeyError(f"unknown id {arbitration_id}")
        return self._known_ids[arbitration_id]["decoded"]

    def get_message_by_frame_id(self, arbitration_id):
        return FakeMessageDef(self._known_ids[arbitration_id]["units"])


def test_decode_known_frame_returns_signals():
    db = FakeDB({100: {"decoded": {"EngineSpeed": 2500.0}, "units": {"EngineSpeed": "rpm"}}})
    result = decode_can_frame(db, 100, b"\x00" * 8)
    assert result == [("EngineSpeed", 2500.0, "rpm")]


def test_decode_multiple_signals_in_one_frame():
    db = FakeDB({
        200: {
            "decoded": {"VehicleSpeed": 88.5, "FuelLevel": 75.0},
            "units": {"VehicleSpeed": "km/h", "FuelLevel": "%"},
        }
    })
    result = decode_can_frame(db, 200, b"\x00" * 8)
    assert set(result) == {("VehicleSpeed", 88.5, "km/h"), ("FuelLevel", 75.0, "%")}


def test_decode_unknown_arbitration_id_returns_empty():
    db = FakeDB({100: {"decoded": {"EngineSpeed": 2500.0}, "units": {"EngineSpeed": "rpm"}}})
    result = decode_can_frame(db, 999, b"\x00" * 8)
    assert result == []


def test_decode_no_unit_becomes_none():
    db = FakeDB({100: {"decoded": {"RawByte": 5.0}, "units": {"RawByte": ""}}})
    result = decode_can_frame(db, 100, b"\x00" * 8)
    assert result == [("RawByte", 5.0, None)]


def test_should_flush_true_at_batch_size_boundary():
    assert should_flush(buffer_len=20, batch_size=20, has_buffer=True,
                         elapsed_since_flush=0.1, flush_interval=2.0) is True


def test_should_flush_false_below_batch_size_and_interval():
    assert should_flush(buffer_len=19, batch_size=20, has_buffer=True,
                         elapsed_since_flush=0.5, flush_interval=2.0) is False


def test_should_flush_true_on_elapsed_interval_with_nonempty_buffer():
    assert should_flush(buffer_len=3, batch_size=20, has_buffer=True,
                         elapsed_since_flush=2.5, flush_interval=2.0) is True


def test_should_flush_false_on_elapsed_interval_with_empty_buffer():
    # This is the exact edge case the original `frame_buffer and ...` guards -
    # an idle bus shouldn't trigger a flush of nothing every interval.
    assert should_flush(buffer_len=0, batch_size=20, has_buffer=False,
                         elapsed_since_flush=5.0, flush_interval=2.0) is False


def test_build_signal_rows_flattens_correctly():
    frame_ids = [1, 2]
    signal_buffer = [
        [("EngineSpeed", 2500.0, "rpm")],
        [("VehicleSpeed", 88.5, "km/h"), ("FuelLevel", 75.0, "%")],
    ]
    rows = build_signal_rows(frame_ids, signal_buffer)
    assert rows == [
        (1, "EngineSpeed", 2500.0, "rpm"),
        (2, "VehicleSpeed", 88.5, "km/h"),
        (2, "FuelLevel", 75.0, "%"),
    ]


def test_build_signal_rows_skips_frames_with_no_signals():
    frame_ids = [1, 2, 3]
    signal_buffer = [[("A", 1.0, None)], [], [("B", 2.0, None)]]
    rows = build_signal_rows(frame_ids, signal_buffer)
    assert rows == [(1, "A", 1.0, None), (3, "B", 2.0, None)]
