# TelemOps BENCHMARKS

## Stage 1, Task 4 — Multi-stage build image size

Measured on the `can-publisher` image (`python:3.11-slim` base), before and after converting to a multi-stage build.

| Metric | Single-stage | Multi-stage | Change |
|---|---|---|---|
| Disk usage | 219MB | 202MB | -17MB (~8%) |
| Content size | 53.7MB | 49.6MB | -4.1MB (~8%) |

Startup time (`time docker run --rm --network host <image> timeout 2 python can_publisher.py`) was effectively unchanged (2.293s vs. 2.299s) - expected, since the multi-stage refactor only removes pip's own build-time bookkeeping from the final image, not anything on the actual runtime import/execution path.

**Why the reduction is modest, honestly:** `python:3.11-slim` is already a fairly trimmed base image, and this service's dependencies (`python-can`, `psycopg2-binary`) are both small, pure-wheel installs with no compiled build step. Multi-stage builds show their biggest gains when the builder stage needs heavy build tooling (compilers, dev headers) that the runtime image doesn't - that wasn't the case here, so the win is real but small. Measured, not assumed.

## Stage 2, Task 8 — Ingestion load test

Ramped `load_test.py` through increasing send rates against the batched `ingest.py` service, measuring actual frames landed in `can_frames` vs. frames sent, and write-span vs. send-window duration.

| Requested rate | Actual send rate | Frames sent | Frames landed | Loss | Write span vs. send window |
|---|---|---|---|---|---|
| 10 Hz | 19.8/s | 398 | 398 | 0% | matched |
| 50 Hz | 95.6/s | 1,914 | 1,914 | 0% | matched |
| 200 Hz | 351.6/s | 7,034 | 7,034 | 0% | matched |
| 1000 Hz | 1,463.5/s | 29,270 | 29,270 | 0% | matched |
| 5000 Hz | 5,195.8/s | 77,938 | 77,938 | 0% | matched |
| 20000 Hz (uncapped) | ~9,738-10,992/s | 97,386-109,924 | 68,903-72,042 | 26-37% | matched (writer kept pace with what it received) |

**Finding:** the batching/write layer built in Task 7 never lost a single frame it received, at any rate tested, including bursts nearly 3 orders of magnitude above realistic CAN telemetry rates. The actual ceiling — real, measured frame loss starting around ~9,700 frames/sec — was isolated to `ingest.py`'s single-threaded, blocking `bus.recv()` call, not the database or batching layer. Confirmed with an independent measurement: running `candump -c` on `vcan0` during the same load test showed a frame count matching `load_test.py`'s reported send count exactly, proving every frame reached the bus and the loss happens strictly in how `ingest.py` reads from it.

**Honest interpretation:** at realistic vehicle CAN bus rates (typically well under 1000 frames/sec even on busy buses), this pipeline has no measurable ceiling. The ~9,700 frames/sec threshold is a genuine architectural limit of the current single-threaded receive loop, not a database bottleneck — and a concrete, well-understood target for a future improvement (e.g. a dedicated reader thread decoupled from the batch-write thread, or `python-can`'s buffered `Notifier`/listener pattern instead of a blocking `recv()` loop).
