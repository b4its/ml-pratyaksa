FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential libgomp1 git \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt requirements-dev.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/requirements-dev.txt

ARG USERNAME=pratyaksa-user
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME

USER $USERNAME
WORKDIR /workspace
