from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import hashlib
import json
import os
import uuid

from dsc_ir import canonical_json


WORKSPACE_SCHEMA = "dsc-workspace/0.1"


class WorkspaceError(RuntimeError):
    pass


class WorkspaceIntegrityError(WorkspaceError):
    pass


class ResumeCompatibilityError(WorkspaceError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _atomic_write_bytes(path: Path, data: bytes,
                        fail_before_replace: bool = False) -> None:
    """Write a file atomically within its destination directory.

    Failure before os.replace leaves any previously committed file untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if fail_before_replace:
            raise OSError("injected failure before atomic replace")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: Any,
                       fail_before_replace: bool = False) -> None:
    _atomic_write_bytes(
        path,
        _json_bytes(value),
        fail_before_replace=fail_before_replace,
    )


def _json_load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WorkspaceIntegrityError(f"invalid JSON: {path}") from exc


class StableInventionWorkspace:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.workspace_file = self.root / "workspace.json"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def initialize(self, source_path: str | Path,
                   workspace_name: Optional[str] = None) -> Dict[str, Any]:
        source_path = Path(source_path)
        if not source_path.exists():
            raise WorkspaceError(f"source does not exist: {source_path}")
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)
        (self.root / "evidence").mkdir(exist_ok=True)

        source_copy = self.root / "invention.dsc"
        _atomic_write_bytes(source_copy, source_path.read_bytes())

        meta = {
            "schema": WORKSPACE_SCHEMA,
            "name": workspace_name or source_path.stem,
            "source_file": "invention.dsc",
            "source_sha256": sha256_file(source_copy),
            "compiler_target": "DSC-IR-v0.1",
            "language": "dsc 0.1",
        }
        _atomic_write_json(self.workspace_file, meta)
        return meta

    def workspace_metadata(self) -> Dict[str, Any]:
        if not self.workspace_file.exists():
            raise WorkspaceError("workspace is not initialized")
        meta = _json_load(self.workspace_file)
        if meta.get("schema") != WORKSPACE_SCHEMA:
            raise ResumeCompatibilityError(
                f"unsupported workspace schema {meta.get('schema')!r}"
            )
        source = self.root / meta["source_file"]
        if not source.exists():
            raise WorkspaceIntegrityError("workspace source file missing")
        if sha256_file(source) != meta["source_sha256"]:
            raise WorkspaceIntegrityError("workspace source digest mismatch")
        return meta
