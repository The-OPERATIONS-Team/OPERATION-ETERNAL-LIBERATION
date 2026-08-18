# RPCN server with the OEL TSS-server patch applied.
# Build context is the repo root (see BIN/docker-compose.yml).

# --- builder ------------------------------------------------------------
FROM rust:1-bookworm AS builder

ARG RPCN_REPO=https://github.com/RipleyTom/rpcn.git
ARG RPCN_COMMIT=871332d2e

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        git ca-certificates protobuf-compiler && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src
RUN git clone "$RPCN_REPO" rpcn && \
    cd rpcn && git checkout "$RPCN_COMMIT"

COPY SRC/PATCH/RPCN/tss-server.patch /tmp/tss-server.patch
RUN cd /usr/src/rpcn && git apply /tmp/tss-server.patch

RUN cd /usr/src/rpcn && cargo build --release

# --- runtime ------------------------------------------------------------
FROM debian:bookworm-slim

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /defaults /rpcn /rpcn/tss_data/NPWR04428_00

COPY --from=builder /usr/src/rpcn/target/release/rpcn /usr/local/bin/rpcn
COPY --from=builder /usr/src/rpcn/*.cfg /defaults/
COPY --from=builder /usr/src/rpcn/*.pem /defaults/

COPY BIN/docker/rpcn/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /rpcn
EXPOSE 31313 31315
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/usr/local/bin/rpcn"]
