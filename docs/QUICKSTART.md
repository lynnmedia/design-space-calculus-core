# Quickstart — DSC Core RC1 bounded developer preview

This guide uses the source archive or wheel from the versioned release. It does not need a checkout of the research repository or the Novum package. Use Python 3.12; see the validation record for tested versions.

```sh
tar -xzf design-space-calculus-0.2.0rc1.tar.gz
cd design-space-calculus-0.2.0rc1
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --no-index --no-deps ../design_space_calculus-0.2.0rc1-py3-none-any.whl
dsc --version
```

Validate and compile a synthetic success case:

```sh
dsc check examples/success.dsc --json
dsc-plc examples/success.dsc -o success.ir.json
```

Observe a controlled syntax failure (exit code `3` and a `PL-SYNTAX` diagnostic):

```sh
dsc check examples/failure.dsc
```

Import a synthetic `novum-dsc/0.1` exchange, then inspect `imported/invention.dsc` and `imported/preservation-ledger.json`:

```sh
dsc import-novum examples/novum-success.json --workspace imported --json
dsc check imported --json
```

The ledger retains unsupported entity kinds, non-executable relations, obligations, evidence, provenance, and the complete source snapshot. A zero-loss reconciliation means those records were accounted for; it does not mean every source meaning executes in DSC. See [the reference](REFERENCE.md) for malformed-record and collision failures.
