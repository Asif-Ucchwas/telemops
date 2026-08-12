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
