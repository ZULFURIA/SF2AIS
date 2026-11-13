FROM node:22-bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash git python3 python3-venv python3-pip build-essential \
    curl ca-certificates unzip zip pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
CMD ["/bin/sh", "-lc", "sleep infinity"]
