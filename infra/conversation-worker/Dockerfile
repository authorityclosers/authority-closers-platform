# Pinned official Python image index, verified 2026-09-13 from Docker Hub's library/python API.
# This is a candidate image, not proof that the required runtime sandbox has been exercised.
FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS native-build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/packages/python

WORKDIR /app

# Exact top-level Debian package version; transitive packages need an SBOM and vulnerability gate.
RUN apt-get update && \
    apt-get install --no-install-recommends --yes g++=4:12.2.0-3 && \
    rm -rf /var/lib/apt/lists/*

COPY packages/python/ac_platform/__init__.py /app/packages/python/ac_platform/__init__.py
COPY packages/python/ac_platform/conversation_intelligence/__init__.py \
     packages/python/ac_platform/conversation_intelligence/__main__.py \
     packages/python/ac_platform/conversation_intelligence/signals.py \
     /app/packages/python/ac_platform/conversation_intelligence/
COPY native/audioatlas/atlas_dsp.cpp \
     native/audioatlas/LICENSE \
     native/audioatlas/source_provenance.json \
     /app/native/audioatlas/

# No patching/replacement of the preserved kernel. The helper also verifies the source digest.
RUN python -c "from pathlib import Path; import hashlib; assert hashlib.sha256(Path('/app/native/audioatlas/atlas_dsp.cpp').read_bytes()).hexdigest() == '40b8b05256986da5eb5d49c3b3cb48c52d511117ecf2e59d56849457cb12fae3'" && \
    python -c "from ac_platform.conversation_intelligence.signals import build_native; build_native()"

FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/packages/python \
    TMPDIR=/tmp

RUN apt-get update && \
    apt-get install --no-install-recommends --yes ffmpeg=7:5.1.9-0+deb12u1 && \
    rm -rf /var/lib/apt/lists/* && \
    python -m pip uninstall --yes pip && \
    python -c "import importlib.metadata; assert not list(importlib.metadata.distributions())" && \
    groupadd --gid 10001 ac-signal && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin ac-signal && \
    mkdir /input /output /work && \
    chmod 0555 /input /output /work

WORKDIR /app
COPY --from=native-build /app /app
RUN chmod -R a-w /app && \
    test ! -e /usr/bin/g++ && \
    test ! -e /app/packages/python/ac_platform/conversation_intelligence/application.py

USER 10001:10001
STOPSIGNAL SIGTERM
HEALTHCHECK NONE
ENTRYPOINT ["python", "-m", "ac_platform.conversation_intelligence"]
CMD ["doctor"]
