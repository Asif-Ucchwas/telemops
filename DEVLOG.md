# TelemOps DEVLOG

## Stage 1 — Containerization Foundations

### Task 1: Containerize `can_publisher.py`

- Docker installed via the `docker.io` apt package. Group membership (`usermod -aG docker`) did not take effect after simply closing and reopening the terminal — required a full `wsl --shutdown` from PowerShell before the new group was recognized.
- `vcan0` does not persist across WSL2 restarts (consistent with the CAN-Net finding, but this machine never had CAN-Net's `setup_vcan.sh`, so it had to be recreated from scratch: `modprobe vcan` + `ip link add`/`set up`). Wrote a dedicated `setup_vcan.sh` for this repo rather than depending on CAN-Net's copy on a different machine.
- Verified the containerized publisher byte-for-byte against `candump` on the host — confirmed the container (`--network host`, required since `vcan0` is a host-level SocketCAN device Docker's bridge network can't reach) was driving real traffic onto the bus, not just running silently.

### Task 2: Compose with Postgres — CDN pull failure and workaround

- `docker-compose` (the `docker compose` plugin isn't available via the `docker.io` apt package's default repo; installed the standalone `docker-compose` v1.29.2 instead — hyphenated syntax, not the newer `docker compose` subcommand).
- `docker-compose up` on `postgres:16` repeatedly failed with `net/http: TLS handshake timeout`, always on a different image layer each retry. Diagnosed methodically before working around it:
  - Ruled out MTU mismatch (checked both `eth0` and `docker0`, both a normal 1500).
  - Found and fixed a real, separate issue along the way: WSL2's auto-generated resolver (`nameserver 10.255.255.254`, the WSL DNS proxy) was itself timing out under repeated lookups. Fixed by setting `generateResolvConf = false` in `/etc/wsl.conf` and pointing `/etc/resolv.conf` at `8.8.8.8`/`8.8.4.4` directly. (Caution: overwriting `/etc/wsl.conf` with `sudo tee` instead of appending silently dropped an existing `[boot] systemd=true` section, which broke `systemctl` until restored — worth remembering that `tee` replaces the whole file.)
  - Ruled out Windows Defender real-time scanning (disabled temporarily, pull still failed the same way).
  - Ruled out download concurrency (set `max-concurrent-downloads: 1` in Docker's daemon config, pull still failed).
  - Confirmed via `curl -v` that a direct TLS handshake to the CDN host (`production.cloudfront.docker.com`) succeeds cleanly, and that small image pulls (`hello-world`, `python:3.11-slim`, `debian:bookworm-slim`) all succeed without issue. This isolated the problem to sustained/large downloads specifically from Docker Hub's official-image CDN on this network — not DNS, not MTU, not Defender, not Docker itself.
- **Workaround:** rather than keep fighting the CDN, built a custom Postgres image from `debian:bookworm-slim` + `apt-get install postgresql` (Debian's own mirrors, which had already proven reliable) instead of pulling the official `postgres:16` image. This pulled Postgres 15 (Debian bookworm's default), not 16 — functionally fine for this project's needs, documented here rather than mislabeled.
- Wrote a custom `entrypoint.sh` replicating the official image's first-run init behavior (create cluster, open `listen_addresses`, create the app user/db) since none of that comes for free outside the official image.
- Found and fixed a follow-on permissions bug: Compose's named volume (`pgdata`) mounts as root-owned by default, which broke `chown`/`initdb` when the container ran as a non-root `postgres` user (`USER postgres` in the Dockerfile). Fixed by keeping the container as root and having the entrypoint itself `chown` the data directory before dropping to `su postgres` for all actual database commands — the same pattern the official image uses internally.

### Task 3: Verified real data flow

- Wrote a throwaway `verify_data_flow.py` (separate from `can_publisher.py`, which only publishes) that reads real live frames off `vcan0` and inserts them into a `can_frames_test` table in Postgres.
- `docker-compose run` failed with `conflicting options: host type networking can't be used with links` — a known incompatibility between `network_mode: host` and Compose v1.29's legacy container-linking behavior. Worked around by using plain `docker run --network host <image> python verify_data_flow.py` directly against the image Compose built, instead of going through `docker-compose run`.
- Verified end-to-end: 10 frames sent by the (separately running) publisher container were read off the live bus and landed correctly in Postgres, confirmed by directly querying the table (not just trusting the script's own print statements) — arbitration IDs and raw byte payloads matched exactly.
- Note: `can_frames_test` is a proof-of-concept table only. Stage 2's ingestion service needs its own proper, normalized schema — this is not that.

### Task 4: Trimmed and documented the image

- Converted `ingestion/Dockerfile` to a multi-stage build (`pip install --user` in a `builder` stage, then `COPY --from=builder` only the installed packages into a fresh `python:3.11-slim` final stage).
- Verified functionality was unaffected after the refactor — confirmed with `python -u` after an initial false alarm where `timeout`'s SIGTERM combined with Python's default stdout buffering made the container appear to produce no output, even though it ran correctly. Not a real regression — a measurement artifact of using `timeout` to bound a long-running process.
- See BENCHMARKS.md for the before/after size numbers and an honest note on why the reduction was modest.

## Stage 2 — Data Pipeline

### Task 5: Schema design

- Rejected pulling an external/public dataset for this stage — TelemOps's whole premise is a live container-to-cloud pipeline, and a static downloaded dataset would remove the actual thing being demonstrated (continuous ingestion, load testing, live dashboards later). Kept everything self-generated.
- Realized the original synthetic counter-based publisher had nothing meaningful to decode. Rebuilt `can_publisher.py` to emit realistic vehicle telemetry (VehicleSpeed, EngineRPM, BatteryTemp) encoded via a real DBC file (`dbc/vehicle.dbc`), with values that move plausibly (sine-wave speed, RPM loosely tracking speed) instead of arbitrary noise.
- Split the schema into two tables by design, not accident: `can_frames` (raw bytes, ground truth, nothing ever lost even if decoding has a bug) and `can_signals` (decoded values, denormalized with its own `received_at` specifically so future Grafana queries don't need a join on the hot path). `ON DELETE CASCADE` from frames to signals.

### Task 6: Ingestion service

- Wrote `ingest.py` as a real always-on service (its own Compose service, `ingestor`), decoding live `vcan0` traffic via `cantools` and writing into the Task 5 schema — distinct from the earlier one-shot `verify_data_flow.py` proof-of-concept.
- `docker-compose run` failed again with the same `network_mode: host` + legacy links bug from Task 3; same workaround (plain `docker run --network host`) applied.
- Verified against `docker-compose logs` returning nothing due to Python's default stdout buffering — the third time this exact issue appeared (also hit in Task 4 and briefly here again before the permanent fix). Fixed for good this time by adding `ENV PYTHONUNBUFFERED=1` to the Dockerfile, rather than continuing to pass `-u` or diagnose it fresh each time.

### Task 7: Batching/buffering

- Rewrote `ingest.py` to buffer frames/signals in memory and flush on whichever comes first: `BATCH_SIZE` (20) reached, or `FLUSH_INTERVAL` (2.0s) elapsed — the time-based trigger matters so a slow trickle of data never sits unwritten indefinitely.
- Switched from one-row-at-a-time `INSERT`s to `psycopg2.extras.execute_values` for true multi-row batch inserts, with `autocommit` off and an explicit `conn.commit()` per flush.
- Handled the FK-ordering problem inherent to batching: frames are batch-inserted first with `RETURNING id` to get their generated IDs back in order, then those IDs are used to batch-insert the associated signals.

### Task 8: Load testing

- Built `load_test.py`, a standalone traffic generator independent of `can_publisher.py`, parameterized by rate and duration, to push `vcan0` far beyond realistic rates.
- Instrumented `ingest.py` with an `oldest_lag` metric (time between a frame's receipt and its actual flush to Postgres) to detect backlog forming, not just watch for crashes.
- Ramped through 10Hz -> 50Hz -> 200Hz -> 1000Hz -> 5000Hz (all measured by actual achieved rate, not requested rate, since `load_test.py` sends 2 frames per loop iteration): zero frame loss at every stage up to ~5,195 real frames/sec, with the batching layer holding up cleanly throughout.
- Found a genuine breaking point at ~9,700+ frames/sec: significant frame loss (26-37% across two runs). Isolated the root cause with an independent measurement — ran `candump -c` on the bus at the same time as the load test, and its count matched `load_test.py`'s reported send count exactly, proving every frame genuinely reached `vcan0`. The loss is therefore confirmed to happen inside `ingest.py`'s own single-threaded, blocking `bus.recv()` loop (the kernel's SocketCAN receive buffer overflows because the process isn't calling `recv()` fast enough while it's busy decoding/buffering/occasionally flushing) - not a Postgres or batching-layer problem, since the batching logic never lost anything it actually received.
- See BENCHMARKS.md for the full staged results table and the honest conclusion on where the ceiling is and why.

## Stage 3 — Dashboards

### Task 9: Grafana + Postgres connection

- Attempted to pull the official `grafana/grafana:11.2.0` image and hit the same Docker Hub CDN timeout pattern diagnosed in Stage 1 (`registry-1.docker.io`, TLS handshake timeout on large layers). Applied the same known workaround: built a custom Grafana image from `debian:bookworm-slim` + Grafana's own official APT repository (`apt.grafana.com`, a different host than Docker Hub's CDN) rather than re-diagnosing from scratch. Second time this exact fix has been needed and applied cleanly.
- Grafana runs on Compose's default private network (not `network_mode: host`, unlike the publisher/ingestor) since it only needs to reach Postgres by service name (`postgres:5432`), not `vcan0`.
- Verified the data source connection with a live query against `can_signals` via Grafana's Explore view before building any dashboard panels.

### Task 10: Live dashboard panels

- Built "TelemOps Live Telemetry" dashboard with three live time-series panels (Vehicle Speed, Engine RPM, Battery Temp), each querying `can_signals` directly with Grafana's `$__timeFilter()` macro so panels follow the dashboard's selected time range dynamically.
- Set dashboard auto-refresh to 10s so panels genuinely update live rather than only on manual refresh.
- Screenshot: `docs/screenshots/dashboard-live-panels.png`.

### Task 11: Alerting

- Added a Grafana alert rule ("Battery Temp High") querying the most recent BatteryTemp reading, firing when it exceeds 60C.
- The original battery_temp simulation (25 + 5*sin(t/200), gentle 20-30C drift) never approached a realistic danger threshold, so a literal alert would never fire — a weak, untested demo. Deliberately widened the simulated swing to `35 + 35*sin(t/60)` (roughly 0-70C, ~3 minute cycle) specifically so the alert could be observed actually firing against real data, not just configured-but-unverified. This is a documented, intentional trade-off (realism sacrificed for demonstrability), not an oversight - the wider swing is clearly unrealistic for a real battery and is kept for portfolio/demo purposes.
- Confirmed the alert genuinely transitions between Normal and Firing states as BatteryTemp crosses 60C in real time - firing was directly observed during testing.
- Screenshot: `docs/screenshots/alert-battery-temp.png` (shows the alert rule's query, condition, and evaluation state).

### Task 12: Documentation

- Captured and committed dashboard and alert-rule screenshots (see above) to `docs/screenshots/`.
- Fixed panel titles that had reverted to Grafana's default "New panel" label after initial creation - final panel titles are "Vehicle Speed (km/h)", "Engine RPM", "Battery Temp (°C)".

## Stage 4 — Orchestration (Kubernetes)

### Task 13: Local cluster setup

- Installed minikube (v1.38.1) with the Docker driver and a conservative resource allocation (`--memory=2200 --cpus=2`), after checking actual headroom first (WSL2 caps itself at ~half the host's 16GB RAM by default; confirmed ~6.6GB genuinely free before committing to minikube's footprint).
- Installed `kubectl` directly (minikube doesn't bundle it).

### Task 14: Converting Compose services to K8s manifests

- Discovered minikube runs as its own Docker container with its own separate network namespace - `vcan0`, which exists on the WSL host, does not automatically exist inside minikube. Verified this directly via `minikube ssh` before assuming, then created `vcan0` a second time, inside minikube's own environment - a real, separate instance of the same gotcha first hit in Stage 1, now recurring one layer deeper.
- Built images directly into minikube's own Docker daemon via `eval $(minikube docker-env)` rather than pulling from a registry, combined with `imagePullPolicy: Never` on every Deployment - this sidesteps the Docker Hub CDN issue entirely for K8s workloads, since nothing is ever pulled from Docker Hub inside the cluster.
- Real networking distinction, found empirically rather than assumed: pods using `hostNetwork: true` (can-publisher, ingestor - both need host-level `vcan0` access) cannot reach other services via Kubernetes' internal Service DNS (`postgres:5432`), because `hostNetwork` bypasses the pod network entirely and uses the node's network directly instead. Fixed by exposing Postgres via a `NodePort` Service (fixed port 30432) and pointing `ingest.py` at `<minikube-ip>:30432` via new `DB_HOST`/`DB_PORT` environment variables (defaulting to `localhost:5432` so Docker Compose keeps working unchanged from the same codebase).
- By contrast, confirmed Grafana - deployed *without* `hostNetwork`, since it never needs `vcan0` - connects cleanly via plain internal Service DNS (`postgres:5432`), no NodePort needed. This contrast is a good, precise illustration of when host networking trades away Kubernetes' normal service discovery, and when it doesn't.
- Discovered the K8s-hosted Postgres is a genuinely separate Postgres instance from the Compose-hosted one (different PVC, different storage entirely) - had to recreate the `can_frames`/`can_signals` schema manually on the K8s instance before the ingestor could write to it.
- A mid-session Windows update forced a full machine restart. Recovered cleanly: `vcan0` had to be recreated in both WSL and minikube again (expected, matches the established pattern), and both Compose (`restart: unless-stopped`) and K8s (`CrashLoopBackOff` on the `can-publisher`/`ingestor` pods, until `vcan0` existed again and the pods were manually deleted to break the backoff timer) needed a nudge to fully recover.
- Found that minikube's node IP (`192.168.49.2`) is only reachable from inside WSL, not from the Windows browser directly - a distinct network layer from the simple container port-mapping Compose used. Fixed with `kubectl port-forward deploy/grafana 3001:3000`, which tunnels through `localhost` (which Windows *can* reach automatically into WSL) - the correct, general-purpose way to reach into a cluster from outside, documented here since it applies to any future K8s service, not just Grafana.

### Task 15: Persistent storage

- Added PersistentVolumeClaims for both Postgres (1Gi) and Grafana (500Mi), replacing Compose's named volumes.
- Persistence was proven twice, not just assumed: once accidentally (the mid-session reboot - Postgres's pod restarted and all prior data was still present), and once deliberately (`kubectl delete pod -l app=postgres` on a running system, followed immediately by a query against the brand-new replacement pod, which correctly returned all 14,237 existing frames). The deliberate test is the more rigorous proof, since it isolates exactly what a PVC is supposed to guarantee - that pod deletion does not equal data loss - rather than relying on a coincidental recovery.

### Task 16: End-to-end verification

- Consolidated final check: all 4 pods (`postgres`, `can-publisher`, `ingestor`, `grafana`) running, both PVCs bound, fresh live data confirmed landing within the last minute via direct SQL query, and the ingestor's batching behavior (`oldest_lag` steady at ~2.0s) matching the same healthy pattern established back in Stage 2 - now proven to hold under Kubernetes, not just Docker Compose.

## Stage 5 — Infrastructure as Code (Terraform)

### Task 17: Terraform setup

- Installed Terraform via HashiCorp's official apt repository (not Ubuntu's default repos, which don't carry it).
- Configured the `hashicorp/kubernetes` provider pointed at the same kubeconfig `kubectl` already uses (`~/.kube/config`), so Terraform manages the exact same minikube cluster used throughout Stage 4, not a separate one.

### Task 18: Converting manifests to Terraform resources

- Deleted the manually-applied `kubectl apply -f k8s/` resources first, so Terraform would own everything it manages from a clean slate rather than "adopting" resources it didn't create.
- Rewrote all four services (Postgres, can-publisher, ingestor, Grafana) plus their PVCs and Services as Terraform `.tf` resources, mirroring the Stage 4 YAML manifests. Added `dns_policy = "ClusterFirstWithHostNet"` on the two `hostNetwork` pods explicitly - not present in the original YAML, but good practice, since `hostNetwork` pods silently default to node DNS otherwise, a subtle trap if cluster DNS is ever needed later.
- **Real bug found and fixed:** `terraform apply` hung for 9+ minutes waiting on the Postgres Deployment, which was actually crash-looping. Root cause: minikube's hostpath PVC provisioner had reused the exact same on-disk path from an earlier, unrelated PVC that was never actually wiped when its Kubernetes object was deleted - so the "fresh" PVC started with stale files owned by unrelated OS users. The entrypoint's `chown` call ran correctly, but Postgres refused to start anyway with "invalid permissions" - because `chown` only fixes ownership, never permission bits, and the stale directory was `0777`. Postgres requires `0700`/`0750` regardless of ownership. Fixed by adding an explicit `chmod 700 "$PGDATA"` alongside the existing `chown` in `entrypoint.sh` - a real, previously-latent gap in the Stage 1 entrypoint script that a normal (non-Terraform, always-same-volume) workflow had never exposed.
- **Second real issue:** after fixing Postgres and re-running `terraform apply`, Terraform itself errored with "Unexpected Identity Change" - a genuine provider-level state corruption caused by the earlier apply failing partway through, before Terraform finished writing that resource's tracking metadata. Fixed with `terraform state rm` (removes only Terraform's own bookkeeping, not the real Kubernetes resource) followed by `terraform import` (re-attaches tracking to the resource that was already running correctly in the cluster) - a real lesson that partial `apply` failures can corrupt Terraform's own state, independent of whether the underlying infrastructure is fine.

### Task 19: Idempotency - full destroy/recreate

- Ran `terraform destroy` (all 8 resources removed cleanly) followed by a fresh `terraform apply` from nothing but the `.tf` files. Proactively cleaned minikube's hostpath directories first, applying the Task 18 lesson rather than hoping for the best.
- First `apply` after the fix succeeded cleanly with no manual intervention - direct proof the `chmod 700` fix was the real, complete root cause, not a one-off workaround.
- Hit one more genuine, self-resolving race condition during recreation: the ingestor pod started crash-looping (schema didn't exist yet on the brand-new Postgres PVC) before the schema-creation command could run manually. Rather than intervene, let Kubernetes' crash-loop backoff run its course - the pod's next scheduled retry succeeded once the schema existed, self-healing without any manual pod deletion this time. Documented as expected, correct behavior of the retry/backoff model, not a bug.
- Full pipeline reverified end-to-end post-recreation: ingestor batching cleanly at the same `oldest_lag~2.0s` baseline established back in Stage 2.

### Task 20: Documentation

- This DEVLOG entry, plus `terraform/` directory (provider.tf, postgres.tf, ingestion.tf, grafana.tf) committed alongside the Stage 4 `k8s/` manifests - both approaches (raw kubectl and Terraform) remain in the repo as a deliberate before/after comparison.

## Stage 6 — Packaging

### Task 21: README

- Wrote a top-level README.md: architecture overview, stage-by-stage summary table, quick-start instructions for both Docker Compose and Kubernetes/Terraform deployment paths, and a "notable engineering decisions" section highlighting the real, non-obvious problems solved (CDN workarounds, hostNetwork vs. Service DNS, proven persistence).

### Task 22: Repo cleanup

- Verified .gitignore correctly excludes large/environment-specific files (kubectl and minikube binaries that were accidentally downloaded into the repo directory, Terraform's .terraform/ provider cache and tfstate files).
- Added a one-line clarifying note on the intentional dbc/vehicle.dbc + ingestion/vehicle.dbc duplication, so it reads as a deliberate Docker build-context constraint rather than an accidental leftover.

### Task 23: Architecture diagram

- Created docs/architecture.svg, a clean visual pipeline diagram (CAN publisher -> ingestor -> Postgres -> Grafana), embedded in the README.

### Task 24: Documentation honesty check

- Reviewed the whole project against the skill-honesty standard used throughout: only claim what was actually built and tested. This is a single-node minikube cluster, not multi-node production Kubernetes. The battery-temp alert threshold was deliberately widened for demo purposes and does not represent realistic vehicle telemetry ranges. Both are stated plainly in DEVLOG rather than glossed over.

### Task 25: Final commit and release tag

- Tagged v1.0 marking all 6 stages complete.

## DevOps-Rigor Retrofit — Unit Testing & Coverage Snapshot (Bundle 5, Tasks 3-4)

Added a pytest suite (`tests/test_decode.py`, 10 tests) targeting the pure
decoding logic in `ingestion/ingest.py`. Extracted three functions
(`decode_can_frame`, `should_flush`, `build_signal_rows`) into a new
`ingestion/decode.py` module, since the original script connected to
Postgres and a CAN interface at import time and wasn't testable as-is -
same pattern as the ControlLoop-RT and CAN-Net retrofits in this bundle.

Ran pytest-cov against `ingestion/`: `decode.py` at 100% (16/16
statements, all 10 tests passing). Blended directory total: 10%
(159 statements, 143 uncovered) - misleading without the breakdown below.

**Unit-tested:**
- `ingestion/decode.py` - 100% - the pure frame-decode, batching-trigger,
  and row-flattening logic

**Verified by other means, not unit-tested (4 files, 0% by design):**
- `ingestion/ingest.py` - the live ingestion service; its pure logic now
  lives in and is tested via decode.py, the remaining code is Postgres
  connection handling and the CAN receive loop, verified via the
  documented load test (10Hz->20,000Hz, ~9,700 frames/sec ceiling
  root-caused to the single-threaded receive loop, per BENCHMARKS.md)
- `ingestion/can_publisher.py` - the DBC-encoded signal simulator;
  verified by producing the live traffic the whole pipeline was tested
  against, not by unit tests
- `ingestion/load_test.py` - the load-testing harness itself; verified by
  its own documented results, not meta-tested
- `ingestion/verify_data_flow.py` - a one-off manual verification script
  (confirms the node actually writes into Postgres); by nature a live
  integration check, not something to unit test

**Bottom line:** the one file that's pure, deterministic logic
(decode.py) is fully unit-tested. Everything else in ingestion/ is either
live I/O (Postgres, CAN) verified through the repo's own load-testing and
PVC-durability work, or a one-off verification/harness script whose
correctness is inherently about live system behavior, not something a
mocked unit test would meaningfully prove.

Also created `requirements.txt` (python-can, cantools, psycopg2-binary)
and `requirements-dev.txt` (pytest, pytest-cov, coverage) for this repo,
neither of which existed before this retrofit - derived from actual
imports in ingestion/*.py rather than assumed from the skills summary.

## DevOps-Rigor Stage 3 — Production-Grade Practices (Tasks 9-11)

Hardened ingestion/can_publisher.py, covering all three tasks:

- Structured logging: replaced print() with Python's logging module,
  LOG_LEVEL env var, timestamped output.
- Error handling: the real brittle spot here was DBC_PATH -
  cantools.database.load_file(DBC_PATH) ran at bare module import time
  with zero error handling, so just importing this module with a wrong
  path crashed immediately with a raw FileNotFoundError traceback,
  before main() even ran. Wrapped it in load_dbc() with a clear error
  message and exit(1). Also wrapped the bus.send() calls to log and
  skip a bad send rather than crashing the loop.
- Config externalization: CHANNEL, BUSTYPE, send interval, and
  critically DBC_PATH (previously hardcoded to the Docker-only
  "/app/vehicle.dbc", which doesn't exist outside the container) are
  now CAN_CHANNEL/CAN_BUSTYPE/CAN_SEND_INTERVAL_S/DBC_PATH env vars.
  Default DBC_PATH now resolves relative to the script's own location
  (Path(__file__).resolve().parent / "vehicle.dbc"), which correctly
  matches both the Docker layout (can_publisher.py and vehicle.dbc
  copied to the same /app dir) and local dev, without requiring the
  env var to be set at all in either case.

Verified both paths live: default DBC_PATH correctly resolved
ingestion/vehicle.dbc with zero configuration, and a genuinely wrong
DBC_PATH failed cleanly (ERROR log with a concrete fix suggestion,
exit code 1) instead of a raw traceback at import time.
