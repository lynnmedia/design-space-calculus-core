from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from dsc_compiler import CompileError, compile_file


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dsc-plc")
    ap.add_argument("source")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--metadata")
    ap.add_argument("--diagnostic-json")
    args = ap.parse_args(argv)

    try:
        rt, metadata = compile_file(args.source)
    except CompileError as exc:
        print(exc.format_diagnostic(filename=args.source), file=sys.stderr)
        if args.diagnostic_json:
            Path(args.diagnostic_json).write_text(
                json.dumps(exc.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
            )
        return 2

    Path(args.output).write_text(rt.export_canonical_json(), encoding="utf-8")
    if args.metadata:
        Path(args.metadata).write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        )

    proof = metadata["conformance"]
    print("COMPILE PASS")
    print("target:", metadata["target"])
    print("payload_sha256:", proof["payload_sha256"])
    print("trace_sha256:", proof["trace_sha256"])
    print("semantic_state_sha256:", proof["semantic_state_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
