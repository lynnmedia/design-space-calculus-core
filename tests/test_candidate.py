"""Synthetic, standalone checks for the bounded review artifact."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class CandidateChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsc-candidate-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.dsc = Path(sys.executable).parent / "dsc"
        self.plc = Path(sys.executable).parent / "dsc-plc"
        self.assertTrue(self.dsc.is_file())
        self.assertTrue(self.plc.is_file())

    def run_cli(self, *args):
        return subprocess.run([self.dsc, *map(str, args)], cwd=self.work,
                              text=True, capture_output=True)

    def test_success_and_controlled_source_failure(self):
        success = self.run_cli("check", EXAMPLES / "success.dsc", "--json")
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertTrue(json.loads(success.stdout)["conformant"])

        compiled = self.work / "compiled.json"
        plc = subprocess.run([self.plc, str(EXAMPLES / "success.dsc"), "-o", str(compiled)],
                             text=True, capture_output=True)
        self.assertEqual(plc.returncode, 0, plc.stderr)
        self.assertEqual(json.loads(compiled.read_text())["payload"]["compiler_target"],
                         "DSC-IR-v0.1")

        failure = self.run_cli("check", EXAMPLES / "failure.dsc")
        self.assertEqual(failure.returncode, 3)
        self.assertIn("PL-SYNTAX-021", failure.stderr)
        self.assertNotIn("Traceback", failure.stderr)

    def test_import_ledger_and_controlled_rejections(self):
        exchange = EXAMPLES / "novum-success.json"
        destination = self.work / "imported"
        valid = self.run_cli("import-novum", exchange, "--workspace", destination, "--json")
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["contract"], "novum-dsc/0.1")
        ledger = json.loads((destination / "preservation-ledger.json").read_text())
        self.assertTrue(ledger["summary"]["reconciliation"]["all_entities_accounted_for"])
        self.assertTrue(ledger["summary"]["reconciliation"]["all_relations_accounted_for"])
        self.assertEqual(ledger["summary"]["silent_semantic_losses"], 0)
        self.assertEqual({row["id"] for row in ledger["sidecar_entities"]},
                         {"N2", "E1", "CL1", "TEST1"})
        self.assertEqual(len(ledger["sidecar_relations"]), 2)
        self.assertIn("function F1", (destination / "invention.dsc").read_text())

        base = json.loads(exchange.read_text())
        malformed = copy.deepcopy(base)
        malformed["entities"] = [{"kind": "need", "body": []}]
        collision = copy.deepcopy(base)
        collision["entities"].extend([
            {"id": "X", "kind": "goal", "body": []},
            {"id": "goal_X", "kind": "function", "body": []},
        ])
        for name, data, diagnostic in (
            ("malformed", malformed, "entities[0].id is required"),
            ("collision", collision, "lowered identity collision at function 'goal_X'"),
        ):
            with self.subTest(name=name):
                path = self.work / f"{name}.json"
                path.write_text(json.dumps(data))
                failed_workspace = self.work / name
                result = self.run_cli("import-novum", path, "--workspace", failed_workspace)
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(failed_workspace.exists())
                self.assertFalse(list(self.work.glob(f".{name}.import-*")))

    def test_bounded_command_surface(self):
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("{new,import-novum,check,compile}", help_result.stdout)
        for excluded in ("invent", "continue", "candidates", "prune", "reopen"):
            self.assertNotIn(f"\n    {excluded} ", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
