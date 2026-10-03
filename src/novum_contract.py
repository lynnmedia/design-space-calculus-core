from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SUPPORTED_CONTRACT_VERSIONS = {"novum-dsc/0.1"}

class ContractValidationError(ValueError):
    pass


def _mapping(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise ContractValidationError(f"{path} must be an array")
    return value


def _string(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        qualifier = "non-empty " if nonempty else ""
        raise ContractValidationError(f"{path} must be a {qualifier}string")
    return value


def _strings(value: Any, path: str) -> None:
    for index, item in enumerate(_list(value, path)):
        if not isinstance(item, str):
            raise ContractValidationError(f"{path}[{index}] must be a string")


def _records(value: Any, path: str, required: tuple[str, ...],
             strings: tuple[str, ...] = (), arrays: tuple[str, ...] = ()) -> None:
    for index, item in enumerate(_list(value, path)):
        where = f"{path}[{index}]"
        record = _mapping(item, where)
        for field in required:
            if field not in record:
                raise ContractValidationError(f"{where}.{field} is required")
        for field in strings:
            if field in record:
                _string(record[field], f"{where}.{field}",
                        nonempty=field in {"id", "kind", "source", "relation", "target"})
        for field in arrays:
            if field in record:
                _strings(record[field], f"{where}.{field}")


def _validate_structure(data: dict) -> None:
    problem = _mapping(data["problem"], "problem")
    _string(problem.get("name"), "problem.name")
    if "novum_version" in problem:
        _string(problem["novum_version"], "problem.novum_version", nonempty=False)
    for field in ("needs", "goals", "functions", "constraints"):
        if field in problem:
            _strings(problem[field], f"problem.{field}")

    _records(data["entities"], "entities", ("id", "kind"),
             ("id", "kind", "status"), ("body",))
    _records(data["relations"], "relations", ("source", "relation", "target"),
             ("source", "relation", "target"))
    _records(data["tensions"], "tensions", ("id",), ("id", "description"))
    _records(data["mechanisms"], "mechanisms", ("id",),
             ("id", "description"), ("satisfies", "activates_tensions"))

    if "obligations" in data:
        _records(data["obligations"], "obligations", ("id",),
                 ("id", "kind", "status"), ("dependents",))
    if "evidence" in data:
        _records(data["evidence"], "evidence", ("id",),
                 ("id",), ("body", "supports", "contradicts"))
    if "provenance" in data:
        provenance = _mapping(data["provenance"], "provenance")
        for field in ("source_file", "exporter_version"):
            if field in provenance:
                _string(provenance[field], f"provenance.{field}", nonempty=False)
        for field in ("entity_count", "relation_count"):
            if field in provenance:
                count = provenance[field]
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ContractValidationError(f"provenance.{field} must be a non-negative integer")


def load_and_validate_contract(path_or_dict: str | Path | dict) -> dict:
    if isinstance(path_or_dict, dict):
        data = path_or_dict
    elif isinstance(path_or_dict, (str, Path)):
        p = Path(path_or_dict)
        if not p.exists():
            raise ContractValidationError(f"contract file does not exist: {p}")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as e:
            raise ContractValidationError(f"invalid JSON in contract file: {e}") from e
    else:
        raise ContractValidationError("contract root must be a JSON object")

    if not isinstance(data, dict):
        raise ContractValidationError("contract root must be a JSON object")

    version = data.get("contract")
    if not isinstance(version, str) or version not in SUPPORTED_CONTRACT_VERSIONS:
        raise ContractValidationError(f"unsupported contract version: {version!r}; supported: {SUPPORTED_CONTRACT_VERSIONS}")

    for req in ("problem", "entities", "relations", "tensions", "mechanisms"):
        if req not in data:
            raise ContractValidationError(f"contract missing required top-level section: {req!r}")

    _validate_structure(data)
    return data


def _validate_lowering_identities(contract: dict) -> None:
    """Use the compiler's declaration type/name and branch-name identities.

    This is a read-only plan. It runs before text rendering or workspace writes.
    """
    entities = contract["entities"]
    seen_targets: dict[tuple[str, str], str] = {}

    def register(target_kind: str, target_name: str, source: str) -> None:
        target = (target_kind, target_name)
        previous = seen_targets.get(target)
        if previous is not None:
            raise ContractValidationError(
                f"lowered identity collision at {target_kind} {target_name!r}: "
                f"{previous} and {source}"
            )
        seen_targets[target] = source

    def matches(kind: str):
        return ((index, entity) for index, entity in enumerate(entities)
                if entity["kind"] == kind)

    needs = list(matches("need"))
    if needs:
        index, entity = needs[0]
        register("need", entity["id"], f"entities[{index}] need {entity['id']!r}")
    else:
        register("need", "PrimaryNeed", "synthesized primary need")

    for kind, target_kind, prefix in (
        ("goal", "function", "goal_"),
        ("function", "function", ""),
        ("constraint", "constraint", ""),
        ("assumption", "resource", "assumption_"),
        ("unknown", "resource", "unknown_"),
    ):
        for index, entity in matches(kind):
            register(target_kind, prefix + entity["id"],
                     f"entities[{index}] {kind} {entity['id']!r}")

    for section, kind, prefix in (
        ("tensions", "tension", "tension_"),
        ("mechanisms", "mechanism", "mech_"),
    ):
        for index, record in enumerate(contract[section]):
            register("resource", prefix + record["id"],
                     f"{section}[{index}] {kind} {record['id']!r}")

    mechanism_ids = {record["id"] for record in contract["mechanisms"]}
    for index, relation in enumerate(contract["relations"]):
        if relation["relation"] == "satisfies" and relation["source"] in mechanism_ids:
            register("branch", "branch_" + relation["source"],
                     f"relations[{index}] satisfies from {relation['source']!r}")

    # Entity IDs are graph identities even when their kinds are sidecar-only.
    # Reject ambiguity instead of using a set that could silently merge records.
    seen_source_ids: dict[str, int] = {}
    for index, entity in enumerate(entities):
        previous = seen_source_ids.get(entity["id"])
        if previous is not None:
            raise ContractValidationError(
                f"duplicate source entity id {entity['id']!r}: "
                f"entities[{previous}] and entities[{index}]"
            )
        seen_source_ids[entity["id"]] = index


def translate_contract_to_dsc(contract: dict) -> Tuple[str, dict]:
    """
    Translates a validated novum-dsc/0.1 contract object into canonical DSC-PL surface text
    and returns (dsc_pl_text, preservation_ledger).

    Entities and relations without a normative executable DSC-PL lowering are retained verbatim
    in sidecar preservation state rather than being silently dropped or mislabeled as executable.
    """
    contract = load_and_validate_contract(contract)
    _validate_lowering_identities(contract)
    problem = contract["problem"]
    entities = contract["entities"]
    relations = contract["relations"]
    tensions = contract["tensions"]
    mechanisms = contract["mechanisms"]
    obligations = contract.get("obligations", [])
    evidence_list = contract.get("evidence", [])

    prob_name = problem.get("name", "ImportedInvention")
    dsc_name = f"Novum_{prob_name}"

    ledger = {
        "contract_version": contract["contract"],
        "source_problem": prob_name,
        "source_contract_snapshot": copy.deepcopy(contract),
        "entity_mappings": [],
        "relation_mappings": [],
        "sidecar_entities": [],
        "sidecar_relations": [],
        "sidecar_sections": {
            "obligations": copy.deepcopy(obligations),
            "evidence": copy.deepcopy(evidence_list),
            "provenance": copy.deepcopy(contract.get("provenance", {})),
        },
        "summary": {
            "total_entities": len(entities),
            "total_relations": len(relations),
            "preservation_counts": {
                "EXACT": 0,
                "STRUCTURALLY_EQUIVALENT": 0,
                "SIDECAR_PRESERVED": 0,
                "UNMAPPED_LOSS": 0,
            },
            "relation_preservation_counts": {
                "STRUCTURALLY_EQUIVALENT": 0,
                "SIDECAR_PRESERVED": 0,
                "UNMAPPED_LOSS": 0,
            },
            "unmapped_critical_entities": 0,
            "unmapped_critical_tensions": 0,
            "unmapped_critical_constraints": 0,
            "silent_semantic_losses": 0,
        }
    }

    mapped_entities = set()

    def map_entity(source_id: str, source_kind: str, dsc_target: str, preservation: str) -> None:
        ledger["entity_mappings"].append({
            "source_id": source_id,
            "source_kind": source_kind,
            "dsc_target": dsc_target,
            "preservation": preservation,
        })
        mapped_entities.add((source_id, source_kind))
        ledger["summary"]["preservation_counts"][preservation] += 1

    lines = [
        "language dsc 0.1",
        "target DSC-IR-v0.1",
        "",
        f"invention {dsc_name} {{",
        "  problem {"
    ]

    # Needs. DSC-PL v0.1 lowers one primary need; any additional needs are sidecar-preserved.
    needs = [e for e in entities if e["kind"] == "need"]
    primary_need_id = "PrimaryNeed"
    if needs:
        n = needs[0]
        primary_need_id = n["id"]
        body_text = " ".join(n.get("body", [])) or "unmet problem need"
        lines.append(f"    need {n['id']}:")
        lines.append(f'      actual "{body_text}"')
        lines.append(f'      desired "satisfy {n["id"]} without conflict"')
        map_entity(n["id"], "need", "need", "EXACT")
    else:
        lines.append("    need PrimaryNeed:")
        lines.append('      actual "unmet need"')
        lines.append('      desired "satisfied functional requirement"')

    # Goals -> High-level functions
    goals = [e for e in entities if e["kind"] == "goal"]
    for g in goals:
        lines.append(f"    function goal_{g['id']}")
        map_entity(g["id"], "goal", "function", "STRUCTURALLY_EQUIVALENT")

    # Functions
    funcs = [e for e in entities if e["kind"] == "function"]
    for f in funcs:
        lines.append(f"    function {f['id']}")
        map_entity(f["id"], "function", "function", "EXACT")

    # Constraints
    constraints = [e for e in entities if e["kind"] == "constraint"]
    for c in constraints:
        lines.append(f"    constraint {c['id']} = true")
        map_entity(c["id"], "constraint", "constraint", "EXACT")

    # Assumptions & Unknowns
    assumptions = [e for e in entities if e["kind"] == "assumption"]
    for a in assumptions:
        lines.append(f"    resource assumption_{a['id']}")
        map_entity(a["id"], "assumption", "resource", "STRUCTURALLY_EQUIVALENT")

    unknowns = [e for e in entities if e["kind"] == "unknown"]
    for u in unknowns:
        lines.append(f"    resource unknown_{u['id']}")
        map_entity(u["id"], "unknown", "resource", "STRUCTURALLY_EQUIVALENT")

    # Tensions
    for t in tensions:
        lines.append(f"    resource tension_{t['id']}")
        map_entity(t["id"], "tension", "resource", "STRUCTURALLY_EQUIVALENT")

    # Mechanisms
    for m in mechanisms:
        lines.append(f"    resource mech_{m['id']}")
        map_entity(m["id"], "mechanism", "resource", "STRUCTURALLY_EQUIVALENT")

    # Preserve all entity kinds that do not currently have an executable lowering.
    for e in entities:
        source_id = e.get("id")
        if (source_id, e["kind"]) in mapped_entities:
            continue
        ledger["sidecar_entities"].append(copy.deepcopy(e))
        ledger["entity_mappings"].append({
            "source_id": source_id,
            "source_kind": e.get("kind"),
            "dsc_target": "preservation-ledger.sidecar_entities",
            "preservation": "SIDECAR_PRESERVED",
        })
        ledger["summary"]["preservation_counts"]["SIDECAR_PRESERVED"] += 1

    lines.append("  }")
    lines.append("")
    lines.append("  search {")
    lines.append("    seed base")

    mech_ids = {m["id"] for m in mechanisms}
    for r in relations:
        s, rel, t = r["source"], r["relation"], r["target"]
        if rel == "satisfies" and s in mech_ids:
            preservation = "STRUCTURALLY_EQUIVALENT"
            dsc_target = "search substitution branch"
            lines.append("")
            lines.append(f"    from base substitute branch_{s} {{")
            lines.append(f"      old generic_{t}")
            lines.append(f"      new mechanism_{s}")
            lines.append(f"      preserve {primary_need_id}")
            lines.append("    }")
        else:
            preservation = "SIDECAR_PRESERVED"
            dsc_target = "preservation-ledger.sidecar_relations"
            ledger["sidecar_relations"].append(copy.deepcopy(r))

        ledger["relation_mappings"].append({
            "source": s,
            "relation": rel,
            "target": t,
            "dsc_target": dsc_target,
            "preservation": preservation,
        })
        ledger["summary"]["relation_preservation_counts"][preservation] += 1

    lines.append("  }")
    lines.append("}")

    # Reconcile preservation from actual mappings; zero loss is earned, not assumed.
    mapped_keys = Counter((m["source_id"], m["source_kind"])
                          for m in ledger["entity_mappings"])
    source_keys = Counter((e["id"], e["kind"]) for e in entities)
    missing_entity_ids = [source_id for source_id, _ in (source_keys - mapped_keys).elements()]
    extra_mapping_ids = [source_id for source_id, _ in (mapped_keys - source_keys).elements()]
    mapping_id_counts = Counter(m["source_id"] for m in ledger["entity_mappings"])
    duplicate_mapping_ids = sorted(source_id for source_id, count in mapping_id_counts.items()
                                   if count > 1)

    unmapped_loss_count = len(missing_entity_ids)
    ledger["summary"]["preservation_counts"]["UNMAPPED_LOSS"] = unmapped_loss_count
    ledger["summary"]["unmapped_critical_entities"] = unmapped_loss_count
    ledger["summary"]["unmapped_critical_tensions"] = len([
        e for e in entities if e.get("kind") == "tension" and e.get("id") in missing_entity_ids
    ])
    ledger["summary"]["unmapped_critical_constraints"] = len([
        e for e in entities if e.get("kind") == "constraint" and e.get("id") in missing_entity_ids
    ])
    ledger["summary"]["silent_semantic_losses"] = unmapped_loss_count
    ledger["summary"]["preservation_counts"].update({
        status: sum(m["preservation"] == status for m in ledger["entity_mappings"])
        for status in ("EXACT", "STRUCTURALLY_EQUIVALENT", "SIDECAR_PRESERVED")
    })
    ledger["summary"]["relation_preservation_counts"].update({
        status: sum(m["preservation"] == status for m in ledger["relation_mappings"])
        for status in ("STRUCTURALLY_EQUIVALENT", "SIDECAR_PRESERVED")
    })
    source_relations = Counter((r["source"], r["relation"], r["target"])
                               for r in relations)
    mapped_relations = Counter((m["source"], m["relation"], m["target"])
                               for m in ledger["relation_mappings"])
    ledger["summary"]["reconciliation"] = {
        "mapped_or_sidecar_entity_count": sum((source_keys & mapped_keys).values()),
        "missing_entity_ids": missing_entity_ids,
        "extra_mapping_ids": extra_mapping_ids,
        "duplicate_mapping_ids": duplicate_mapping_ids,
        "all_entities_accounted_for": source_keys == mapped_keys and not duplicate_mapping_ids,
        "all_relations_accounted_for": source_relations == mapped_relations,
    }

    dsc_text = "\n".join(lines) + "\n"
    return dsc_text, ledger
