"""Raw file storage. Local disk for now - swap this module for an S3-backed one later,
the rest of the codebase only ever calls `save` and gets back a storage_uri back.
"""

import hashlib
import os
import uuid

from core.config import get_settings

settings = get_settings()


def _ensure_storage_dir() -> None:
    os.makedirs(settings.storage_dir, exist_ok=True)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(data: bytes, original_filename: str) -> str:
    """Writes the raw bytes to disk and returns a storage_uri to persist on the File row."""
    _ensure_storage_dir()
    ext = os.path.splitext(original_filename)[1]
    disk_name = f"{uuid.uuid4()}{ext}"
    path = os.path.join(settings.storage_dir, disk_name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def read(storage_uri: str) -> bytes:
    with open(storage_uri, "rb") as f:
        return f.read()


def delete(storage_uri: str) -> None:
    try:
        os.remove(storage_uri)
    except FileNotFoundError:
        pass  # already gone - nothing left to do
