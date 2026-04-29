"""Shared filesystem paths used by both ingest and app processes."""
import os
from pathlib import Path


def get_log_dir() -> Path:
    """Return the absolute log directory, honoring the LOG_DIR env var."""
    return Path(
        os.environ.get("LOG_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"))
    ).resolve()


LOG_DIR: Path = get_log_dir()
