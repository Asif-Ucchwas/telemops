FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim

WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY can_publisher.py .
COPY verify_data_flow.py .

ENV PATH=/root/.local/bin:$PATH

CMD ["python", "can_publisher.py"]
