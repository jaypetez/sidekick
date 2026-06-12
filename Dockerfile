FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create a non-root user
RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app

WORKDIR /app

# Copy only what's needed to install first (better layer caching)
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# The package version is normally derived from the git tag (hatch-vcs), but this
# build context has no .git dir. The release workflow passes the tag via
# --build-arg VERSION=X.Y.Z; setuptools_scm (under hatch-vcs) honors this env var.
ARG VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

RUN pip install .

# Default config lives in the user's home and is mounted from a host volume
RUN mkdir -p /home/app/.config/sidekick && chown -R app:app /home/app

USER app
ENV SIDEKICK_CONFIG_DIR=/home/app/.config/sidekick \
    SIDEKICK_DB_PATH=/home/app/.config/sidekick/sidekick.db

ENTRYPOINT ["sidekick"]
