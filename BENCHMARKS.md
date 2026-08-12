# TelemOps BENCHMARKS

## Stage 1, Task 4 — Multi-stage build image size

Measured on the `can-publisher` image (`python:3.11-slim` base), before and after converting to a multi-stage build.

| Metric | Single-stage | Multi-stage | Change |
|---|---|---|---|
| Disk usage | 219MB | 202MB | -17MB (~8%) |
| Content size | 53.7MB | 49.6MB | -4.1MB (~8%) |

Startup time (`time docker run --rm --network host <image> timeout 2 python can_publisher.py`) was effectively unchanged (2.293s vs. 2.299s) - expected, since the multi-stage refactor only removes pip's own build-time bookkeeping from the final image, not anything on the actual runtime import/execution path.

**Why the reduction is modest, honestly:** `python:3.11-slim` is already a fairly trimmed base image, and this service's dependencies (`python-can`, `psycopg2-binary`) are both small, pure-wheel installs with no compiled build step. Multi-stage builds show their biggest gains when the builder stage needs heavy build tooling (compilers, dev headers) that the runtime image doesn't - that wasn't the case here, so the win is real but small. Measured, not assumed.
