FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        apt-transport-https software-properties-common wget gnupg ca-certificates && \
    wget -q -O /usr/share/keyrings/grafana.key https://apt.grafana.com/gpg.key && \
    gpg --dearmor -o /usr/share/keyrings/grafana-archive-keyring.gpg /usr/share/keyrings/grafana.key && \
    echo "deb [signed-by=/usr/share/keyrings/grafana-archive-keyring.gpg] https://apt.grafana.com stable main" > /etc/apt/sources.list.d/grafana.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends grafana && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

EXPOSE 3000
ENTRYPOINT ["/usr/sbin/grafana-server", "--homepath=/usr/share/grafana", "--config=/etc/grafana/grafana.ini"]
