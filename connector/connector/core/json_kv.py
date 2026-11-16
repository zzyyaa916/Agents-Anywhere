from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from connector.paths import connector_data_dir

JSON_KV_FILE_VERSION = 1


class JsonKeyValueStore:
    """Small connector-local JSON key/value store.

    Side effects:
    - reads and writes one JSON file on local disk
    - writes use a temporary file and atomic replace
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @classmethod
    def default_path(cls) -> Path:
        configured = os.environ.get("AGENT_CONNECTOR_KV_FILE")
        if configured:
            return Path(configured).expanduser().resolve(strict=False)
        return connector_data_dir() / "connector-kv.json"

    @classmethod
    def default(cls) -> JsonKeyValueStore:
        return cls(cls.default_path())

    @contextmanager
    def _file_lock(self, *, exclusive: bool) -> Iterator[None]:
        """Serialize cooperating Connector processes sharing this KV file."""
        fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def get(self, key: str) -> Mapping[str, Any] | None:
        with self._lock, self._file_lock(exclusive=False):
            document = self.read_document()
            value = document["values"].get(key)
        if not isinstance(value, Mapping):
            return None
        return dict(value)

    def set(self, key: str, value: Mapping[str, Any]) -> None:
        with self._lock, self._file_lock(exclusive=True):
            document = self.read_document()
            document["values"][key] = dict(value)
            self.write_document(document)

    def delete(self, key: str) -> None:
        with self._lock, self._file_lock(exclusive=True):
            document = self.read_document()
            if key not in document["values"]:
                return
            del document["values"][key]
            self.write_document(document)

    def read_document(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": JSON_KV_FILE_VERSION, "values": {}}
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid connector JSON KV file: {self.path}") from exc
        if (
            not isinstance(document, dict)
            or document.get("version") != JSON_KV_FILE_VERSION
            or not isinstance(document.get("values"), dict)
        ):
            raise RuntimeError(f"unsupported connector JSON KV file: {self.path}")
        return document

    def write_document(self, document: Mapping[str, Any]) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(document, temporary, ensure_ascii=False, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
