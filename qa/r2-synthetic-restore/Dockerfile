FROM docker.io/library/postgres:18-bookworm
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends age python3 \
    && rm -rf /var/lib/apt/lists/*
