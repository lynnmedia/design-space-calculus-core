# Bounded CLI and validator reference

The installed `dsc` entry point provides only these commands:

| Command | Behavior |
| --- | --- |
| `dsc --version` | Print the candidate CLI version. |
| `dsc new WORKSPACE [--name NAME] [--template minimal\|rainvent] [--force] [--json]` | Initialize a source and workspace metadata. |
| `dsc check SOURCE_OR_WORKSPACE [--json]` | Parse, compile, and validate a `DSC-IR-v0.1` package in memory. |
| `dsc compile SOURCE_OR_WORKSPACE -o OUTPUT [--json]` | Write canonical IR JSON. |
| `dsc import-novum EXCHANGE [--workspace WORKSPACE] [--force] [--json]` | Validate a `novum-dsc/0.1` exchange, lower its supported subset, and atomically install a workspace and preservation ledger. |

`dsc-plc SOURCE -o OUTPUT [--metadata FILE] [--diagnostic-json FILE]` is the compiler entry point. No search controller, generator, scoring, Pareto, or model-provider command is included in this bounded CLI.

## Exit status and controlled failure

`dsc` returns `0` on success, `2` for argument errors, `3` for compiler errors, and `4` for contract/workspace errors. `dsc-plc` returns `0` on success and `2` for compiler errors. A malformed consumed record or lowered identity collision returns `4` without a traceback or partially installed workspace. An existing workspace remains intact on failed `--force` import.

To reproduce two importer failures using only the synthetic example:

```sh
python - <<'PY'
import json
from pathlib import Path
base = json.loads(Path('examples/novum-success.json').read_text())
bad = dict(base)
bad['entities'] = [{'kind': 'need', 'body': []}]
Path('malformed.json').write_text(json.dumps(bad))
collision = json.loads(Path('examples/novum-success.json').read_text())
collision['entities'] += [
    {'id': 'X', 'kind': 'goal', 'body': []},
    {'id': 'goal_X', 'kind': 'function', 'body': []},
]
Path('collision.json').write_text(json.dumps(collision))
PY
dsc import-novum malformed.json --workspace malformed-workspace
dsc import-novum collision.json --workspace collision-workspace
```

The first diagnostic names the missing `entities[0].id`; the second names both source records and their shared lowered `function goal_X` identity. Neither command creates its requested workspace or success ledger.

## Preservation ledger

`preservation-ledger.json` records `source_contract_snapshot`, `entity_mappings`, `relation_mappings`, `sidecar_entities`, `sidecar_relations`, `sidecar_sections`, and reconciliation counts. Inspect the classifications `EXACT`, `STRUCTURALLY_EQUIVALENT`, `SIDECAR_PRESERVED`, and `UNMAPPED_LOSS`. Only `satisfies` from a declared mechanism creates an executable substitution branch. Other relations are sidecar-preserved. The importer validates consumed fields and sections, not an arbitrary graph or a universal JSON Schema.
