#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

from dsc_compiler import CompileError, compile_file, compile_text
from dsc_ir import validate_conformance
from workspace_core import (
    StableInventionWorkspace as PersistentInventionWorkspace,
    ResumeCompatibilityError, WorkspaceError, WorkspaceIntegrityError,
)
from cli_core import CLIError, CLI_VERSION, compile_summary, source_for


def emit(data, json_mode=False):
    if json_mode:
        print(json.dumps(data, indent=2, sort_keys=True))
    elif isinstance(data, str):
        print(data)
    elif isinstance(data, list):
        for item in data:
            print(item)
    else:
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                print(f"{key}: {json.dumps(value, sort_keys=True)}")
            else:
                print(f"{key}: {value}")


def template_source(name: str, template: str) -> str:
    if template == "rainvent":
        return f'''language dsc 0.1
target DSC-IR-v0.1

invention {name} {{
  problem {{
    need ventilation:
      actual "window closed during rain"
      desired "continuous passive ventilation during wind-driven rain"

    function ventilate
    function reject_rain

    constraint no_power = true
    constraint max_depth_mm <= 120

    resource gravity
    resource exterior_wind
  }}

  search {{
    seed base
  }}
}}
'''
    return f'''language dsc 0.1
target DSC-IR-v0.1

invention {name} {{
  problem {{
    need primary_need:
      actual "describe the current unsatisfactory state"
      desired "describe the desired state"

    function primary_function
    constraint example_constraint = true
    resource available_resource
  }}

  search {{
    seed base
  }}
}}
'''


def command_new(args):
    root = Path(args.workspace)
    if root.exists() and any(root.iterdir()) and not args.force:
        raise CLIError(f"workspace is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    source = root / "invention.dsc"
    source.write_text(template_source(args.name, args.template), encoding="utf-8")
    ws = PersistentInventionWorkspace(root)
    meta = ws.initialize(source, args.name)
    return {
        "command": "new", "workspace": str(root),
        "source": str(root / "invention.dsc"), "name": meta["name"],
        "language": meta["language"], "target": meta["compiler_target"],
    }


def command_import_novum(args):
    from novum_contract import load_and_validate_contract, translate_contract_to_dsc
    contract_data = load_and_validate_contract(args.contract_file)
    dsc_text, ledger = translate_contract_to_dsc(contract_data)

    ws_path = Path(args.workspace or f"./{contract_data['problem']['name']}-workspace")
    # Compile the complete in-memory plan before creating even a temporary workspace.
    compile_text(dsc_text, filename=str(ws_path / "invention.dsc"))
    if ws_path.is_symlink() or (ws_path.exists() and not ws_path.is_dir()):
        raise CLIError(f"workspace path is not a directory: {ws_path}")
    if ws_path.exists() and any(ws_path.iterdir()) and not args.force:
        raise CLIError(f"workspace directory already exists and is not empty: {ws_path}")

    stage = None
    backup = None
    try:
        ws_path.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{ws_path.name}.import-", dir=ws_path.parent))
        staged_source = stage / "invention.dsc"
        staged_source.write_text(dsc_text, encoding="utf-8")
        PersistentInventionWorkspace(stage).initialize(staged_source, contract_data["problem"]["name"])
        (stage / "preservation-ledger.json").write_text(
            json.dumps(ledger, indent=2), encoding="utf-8"
        )

        if ws_path.exists():
            backup = ws_path.with_name(f".{ws_path.name}.previous-{uuid.uuid4().hex}")
            os.replace(ws_path, backup)
        try:
            os.replace(stage, ws_path)
            stage = None
        except OSError:
            if backup is not None:
                os.replace(backup, ws_path)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
    except OSError as exc:
        raise CLIError(f"import workspace write failed: {exc}") from exc
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)

    dsc_file = ws_path / "invention.dsc"
    ledger_path = ws_path / "preservation-ledger.json"

    return {
        "command": "import-novum",
        "contract": contract_data["contract"],
        "problem": contract_data["problem"]["name"],
        "workspace": str(ws_path),
        "source": str(dsc_file),
        "ledger": str(ledger_path),
        "entities_mapped": len(ledger["entity_mappings"]),
        "relations_mapped": len(ledger["relation_mappings"])
    }


def command_check(args):
    out = compile_summary(source_for(args.target))
    out["command"] = "check"
    return out


def command_compile(args):
    source = source_for(args.target)
    rt, metadata = compile_file(source)
    proof = validate_conformance(rt.export_package())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rt.export_canonical_json(), encoding="utf-8")
    return {
        "command": "compile", "source": str(source), "output": str(output),
        "target": metadata["target"], "conformant": proof["conformant"],
        "branch_count": len(rt.branches), "event_count": len(rt.trace),
        "semantic_state_sha256": rt.semantic_state_digest(),
    }


def build_parser():
    p = argparse.ArgumentParser(prog="dsc", description="DSC Core CLI v0.1")
    p.add_argument("--version", action="version", version=CLI_VERSION)
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("new", help="create an invention workspace")
    q.add_argument("workspace"); q.add_argument("--name", default="NewInvention")
    q.add_argument("--template", choices=["minimal", "rainvent"], default="minimal")
    q.add_argument("--force", action="store_true"); q.add_argument("--json", action="store_true")
    q.set_defaults(func=command_new)

    q = sub.add_parser("import-novum", help="import a novum-dsc/0.1 contract JSON into a workspace")
    q.add_argument("contract_file"); q.add_argument("--workspace")
    q.add_argument("--force", action="store_true"); q.add_argument("--json", action="store_true")
    q.set_defaults(func=command_import_novum)

    q = sub.add_parser("check", help="parse, validate, and IR-check source")
    q.add_argument("target"); q.add_argument("--json", action="store_true"); q.set_defaults(func=command_check)

    q = sub.add_parser("compile", help="compile .dsc to canonical DSC-IR")
    q.add_argument("target"); q.add_argument("-o", "--output", required=True)
    q.add_argument("--json", action="store_true"); q.set_defaults(func=command_compile)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        emit(result, getattr(args, "json", False))
        return 0
    except CompileError as exc:
        print(exc.format_diagnostic(), file=sys.stderr)
        return 3
    except (CLIError, WorkspaceError, WorkspaceIntegrityError,
            ResumeCompatibilityError, ValueError, KeyError, RuntimeError) as exc:
        print(f"DSC-CLI-ERROR: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
