from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from dsc_compiler import compile_file
from dsc_ir import validate_conformance


__version__ = "0.2.0rc1"
CLI_VERSION = f"dsc-cli/{__version__}"


class CLIError(RuntimeError):
    pass


def source_for(target: str | Path) -> Path:
    p = Path(target)
    if p.is_dir():
        q = p / "invention.dsc"
        if not q.exists():
            raise CLIError(f"workspace has no invention.dsc: {p}")
        return q
    if not p.exists():
        raise CLIError(f"source/workspace does not exist: {p}")
    return p


def compile_summary(source: Path) -> Dict[str, Any]:
    rt, metadata = compile_file(source)
    proof = validate_conformance(rt.export_package())
    return {
        "source": str(source),
        "invention": rt.program_id,
        "target": metadata["target"],
        "branch_count": len(rt.branches),
        "event_count": len(rt.trace),
        "evidence_count": len(rt.evidence),
        "conformant": proof["conformant"],
        "semantic_state_sha256": rt.semantic_state_digest(),
        "trace_sha256": rt.trace_digest(),
    }
