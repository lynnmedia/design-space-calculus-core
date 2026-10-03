from __future__ import annotations

from dataclasses import dataclass, field, asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union
import copy
import hashlib
import json


SCHEMA_VERSION = "dsc-ir/0.1"
COMPILER_TARGET = "DSC-IR-v0.1"
CANONICALIZATION = "json-sort-keys-utf8-no-whitespace-v1"
BASIS = {
    "transformations": "DSC-T10-v0.3",
    "search_control": "DSC-SC7-v0.2",
    "ir": COMPILER_TARGET,
}


class DSCOperator(str, Enum):
    DECOMPOSE = "decompose"
    COMPOSE = "compose"
    SUBSTITUTE = "substitute"
    MODIFY = "modify"
    RECONFIGURE = "reconfigure"
    ABSTRACT = "abstract"
    INSTANTIATE = "instantiate"
    TRANSFER = "transfer"
    REFRAME = "reframe"
    EXPERIMENT = "experiment"


class SCOperator(str, Enum):
    EXPAND = "expand"
    EVALUATE = "evaluate"
    SELECT = "select"
    PRUNE = "prune"
    REOPEN = "reopen"
    ALLOCATE = "allocate"
    TERMINATE = "terminate"


class BranchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SELECTED = "SELECTED"
    PRUNED = "PRUNED"
    SUSPENDED = "SUSPENDED"
    TERMINAL = "TERMINAL"
    INVALID = "INVALID"


@dataclass(frozen=True)
class DecomposeArgs:
    target: str
    parts: List[str]


@dataclass(frozen=True)
class ComposeArgs:
    elements: List[str]
    whole: str


@dataclass(frozen=True)
class SubstituteArgs:
    old_realization: str
    new_realization: str
    preserved_role: str


@dataclass(frozen=True)
class ModifyArgs:
    target: str
    property_name: str
    from_value: Any
    to_value: Any


@dataclass(frozen=True)
class ReconfigureArgs:
    target: str
    prior_relations: List[str]
    new_relations: List[str]


@dataclass(frozen=True)
class AbstractArgs:
    source: str
    generalized_structure: str


@dataclass(frozen=True)
class InstantiateArgs:
    abstract_source: str
    realization: str


@dataclass(frozen=True)
class TransferArgs:
    source_domain: str
    target_domain: str
    transferred_structure: str


@dataclass(frozen=True)
class ReframeArgs:
    target_problem_element: str
    prior_frame: str
    new_frame: str
    preserved_need: str


@dataclass(frozen=True)
class ExperimentArgs:
    hypothesis: str
    intervention: str
    observation: str
    evidence_id: str
    confidence: float
    kind: str = "PHYSICAL_TEST"


TransformArgs = Union[
    DecomposeArgs, ComposeArgs, SubstituteArgs, ModifyArgs, ReconfigureArgs,
    AbstractArgs, InstantiateArgs, TransferArgs, ReframeArgs, ExperimentArgs
]


ARG_TYPES: Dict[DSCOperator, Type[Any]] = {
    DSCOperator.DECOMPOSE: DecomposeArgs,
    DSCOperator.COMPOSE: ComposeArgs,
    DSCOperator.SUBSTITUTE: SubstituteArgs,
    DSCOperator.MODIFY: ModifyArgs,
    DSCOperator.RECONFIGURE: ReconfigureArgs,
    DSCOperator.ABSTRACT: AbstractArgs,
    DSCOperator.INSTANTIATE: InstantiateArgs,
    DSCOperator.TRANSFER: TransferArgs,
    DSCOperator.REFRAME: ReframeArgs,
    DSCOperator.EXPERIMENT: ExperimentArgs,
}


@dataclass
class Evidence:
    id: str
    kind: str
    observation: str
    confidence: float
    supports: List[str] = field(default_factory=list)
    weakens: List[str] = field(default_factory=list)
    falsifies: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    id: str
    revision: int
    description: str
    properties: Dict[str, Any] = field(default_factory=dict)
    preserved: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    provenance: List[str] = field(default_factory=list)


@dataclass
class Evaluation:
    branch_id: str
    context: str
    metrics: Dict[str, float]
    evidence_refs: List[str] = field(default_factory=list)


@dataclass
class PruningRecord:
    reason: str
    context: Dict[str, Any]
    reopen_conditions: List[str]
    evidence_refs: List[str] = field(default_factory=list)


@dataclass
class Allocation:
    branch_id: str
    resources: Dict[str, float]
    reason: str


@dataclass
class Branch:
    id: str
    candidate: Candidate
    parent_ids: List[str] = field(default_factory=list)
    child_ids: List[str] = field(default_factory=list)
    lineage: List[str] = field(default_factory=list)
    status: BranchStatus = BranchStatus.ACTIVE
    evaluation: Optional[Evaluation] = None
    pruning: Optional[PruningRecord] = None
    reopen_history: List[Dict[str, Any]] = field(default_factory=list)
    allocations: List[Allocation] = field(default_factory=list)


@dataclass
class TraceEvent:
    seq: int
    layer: str
    operator: str
    targets: List[str]
    detail: Dict[str, Any]


@dataclass
class TransformationValidation:
    operator: str
    typed: bool
    preservation_valid: bool
    semantic_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.typed and self.preservation_valid and self.semantic_valid and not self.errors


@dataclass
class TransformSpec:
    operator: DSCOperator
    child_branch_id: str
    child_candidate_id: str
    description: str
    arguments: TransformArgs
    preserved: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)


class IRValidationError(RuntimeError):
    pass


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {k: _primitive(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _primitive(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_canonical(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class TransformationContract:
    @staticmethod
    def _nonempty(value: str, field_name: str, errors: List[str]) -> None:
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field_name} must be non-empty")

    @classmethod
    def validate(cls, operator: DSCOperator, arguments: TransformArgs,
                 preserved: Optional[List[str]] = None) -> TransformationValidation:
        errors: List[str] = []
        preserved = preserved or []
        expected = ARG_TYPES[operator]

        if not isinstance(arguments, expected):
            return TransformationValidation(
                operator=operator.value,
                typed=False,
                preservation_valid=False,
                semantic_valid=False,
                errors=[f"{operator.value} requires {expected.__name__}, got {type(arguments).__name__}"],
            )

        preservation_valid = True
        a = arguments

        if operator == DSCOperator.DECOMPOSE:
            cls._nonempty(a.target, "target", errors)
            if len(a.parts) < 2:
                errors.append("decompose requires at least two parts")
            if len(set(a.parts)) != len(a.parts):
                errors.append("decompose parts must be distinct")
            if a.target in a.parts:
                errors.append("decompose target may not also be one of its parts")

        elif operator == DSCOperator.COMPOSE:
            if len(a.elements) < 2:
                errors.append("compose requires at least two elements")
            if len(set(a.elements)) != len(a.elements):
                errors.append("compose elements must be distinct")
            cls._nonempty(a.whole, "whole", errors)
            if a.whole in a.elements:
                errors.append("compose whole must be distinct from constituent elements")

        elif operator == DSCOperator.SUBSTITUTE:
            cls._nonempty(a.old_realization, "old_realization", errors)
            cls._nonempty(a.new_realization, "new_realization", errors)
            cls._nonempty(a.preserved_role, "preserved_role", errors)
            if a.old_realization == a.new_realization:
                errors.append("substitute requires different realizations")
            if a.preserved_role not in preserved:
                errors.append("substitute preserved_role must appear in preserved[]")
                preservation_valid = False

        elif operator == DSCOperator.MODIFY:
            cls._nonempty(a.target, "target", errors)
            cls._nonempty(a.property_name, "property_name", errors)
            if a.from_value == a.to_value:
                errors.append("modify requires from_value != to_value")

        elif operator == DSCOperator.RECONFIGURE:
            cls._nonempty(a.target, "target", errors)
            if not a.prior_relations:
                errors.append("reconfigure requires prior_relations")
            if not a.new_relations:
                errors.append("reconfigure requires new_relations")
            if a.prior_relations == a.new_relations:
                errors.append("reconfigure requires a relational change")

        elif operator == DSCOperator.ABSTRACT:
            cls._nonempty(a.source, "source", errors)
            cls._nonempty(a.generalized_structure, "generalized_structure", errors)
            if a.source == a.generalized_structure:
                errors.append("abstract requires movement from specific to general")

        elif operator == DSCOperator.INSTANTIATE:
            cls._nonempty(a.abstract_source, "abstract_source", errors)
            cls._nonempty(a.realization, "realization", errors)
            if a.abstract_source == a.realization:
                errors.append("instantiate requires movement from abstract to concrete")

        elif operator == DSCOperator.TRANSFER:
            cls._nonempty(a.source_domain, "source_domain", errors)
            cls._nonempty(a.target_domain, "target_domain", errors)
            cls._nonempty(a.transferred_structure, "transferred_structure", errors)
            if a.source_domain == a.target_domain:
                errors.append("transfer requires distinct source and target domains")

        elif operator == DSCOperator.REFRAME:
            cls._nonempty(a.target_problem_element, "target_problem_element", errors)
            cls._nonempty(a.prior_frame, "prior_frame", errors)
            cls._nonempty(a.new_frame, "new_frame", errors)
            cls._nonempty(a.preserved_need, "preserved_need", errors)
            if a.prior_frame == a.new_frame:
                errors.append("reframe requires a materially different frame")
            if a.preserved_need not in preserved:
                errors.append("reframe preserved_need must appear in preserved[]")
                preservation_valid = False

        elif operator == DSCOperator.EXPERIMENT:
            cls._nonempty(a.hypothesis, "hypothesis", errors)
            cls._nonempty(a.intervention, "intervention", errors)
            cls._nonempty(a.observation, "observation", errors)
            cls._nonempty(a.evidence_id, "evidence_id", errors)
            if not (0.0 <= a.confidence <= 1.0):
                errors.append("experiment confidence must be between 0 and 1")

        return TransformationValidation(
            operator=operator.value,
            typed=True,
            preservation_valid=preservation_valid,
            semantic_valid=not errors,
            errors=errors,
        )


class InventionRuntime:
    def __init__(self, program_id: str, seed_candidate: Candidate,
                 budget: Optional[Dict[str, float]] = None):
        self.program_id = program_id
        self.initial_seed = copy.deepcopy(seed_candidate)
        self.branches: Dict[str, Branch] = {"B0": Branch(id="B0", candidate=copy.deepcopy(seed_candidate))}
        self.evidence: Dict[str, Evidence] = {}
        self.budget_initial = copy.deepcopy(budget or {})
        self.budget_remaining = copy.deepcopy(budget or {})
        self.trace: List[TraceEvent] = []
        self.transform_validations: List[TransformationValidation] = []
        self.terminated = False
        self.termination_reason: Optional[str] = None

    def _event(self, layer: str, operator: str, targets: List[str], **detail: Any) -> str:
        event_id = f"E{len(self.trace)+1:03d}"
        self.trace.append(TraceEvent(
            seq=len(self.trace)+1, layer=layer, operator=operator,
            targets=list(targets), detail={"event_id": event_id, **detail}
        ))
        return event_id

    def _branch(self, branch_id: str) -> Branch:
        if branch_id not in self.branches:
            raise IRValidationError(f"Unknown branch: {branch_id}")
        return self.branches[branch_id]

    def _apply_candidate_effect(self, candidate: Candidate, operator: DSCOperator,
                                args: TransformArgs) -> None:
        effects = candidate.properties.setdefault("dsc_effects", [])
        if operator == DSCOperator.DECOMPOSE:
            candidate.properties.setdefault("decompositions", {})[args.target] = list(args.parts)
        elif operator == DSCOperator.COMPOSE:
            candidate.properties.setdefault("compositions", {})[args.whole] = list(args.elements)
        elif operator == DSCOperator.SUBSTITUTE:
            candidate.properties.setdefault("substitutions", []).append({
                "old": args.old_realization, "new": args.new_realization,
                "preserved_role": args.preserved_role,
            })
        elif operator == DSCOperator.MODIFY:
            candidate.properties.setdefault("modifications", []).append({
                "target": args.target, "property": args.property_name,
                "from": args.from_value, "to": args.to_value,
            })
        elif operator == DSCOperator.RECONFIGURE:
            candidate.properties.setdefault("reconfigurations", []).append({
                "target": args.target,
                "prior_relations": list(args.prior_relations),
                "new_relations": list(args.new_relations),
            })
        elif operator == DSCOperator.ABSTRACT:
            candidate.properties.setdefault("abstractions", []).append({
                "source": args.source, "generalized_structure": args.generalized_structure,
            })
        elif operator == DSCOperator.INSTANTIATE:
            candidate.properties.setdefault("instantiations", []).append({
                "abstract_source": args.abstract_source, "realization": args.realization,
            })
        elif operator == DSCOperator.TRANSFER:
            candidate.properties.setdefault("transfers", []).append({
                "source_domain": args.source_domain, "target_domain": args.target_domain,
                "transferred_structure": args.transferred_structure,
            })
        elif operator == DSCOperator.REFRAME:
            candidate.properties.setdefault("reframes", []).append({
                "target_problem_element": args.target_problem_element,
                "prior_frame": args.prior_frame, "new_frame": args.new_frame,
                "preserved_need": args.preserved_need,
            })
        effects.append(operator.value)

    def execute_transform(self, source_ids: List[str], spec: TransformSpec,
                          reason: str = "") -> str:
        if spec.operator == DSCOperator.EXPERIMENT:
            raise IRValidationError("Use execute_experiment() for experiment")
        if not source_ids:
            raise IRValidationError("Transformation requires at least one source branch")
        if len(set(source_ids)) != len(source_ids):
            raise IRValidationError("Transformation source branches must be distinct")
        for source_id in source_ids:
            if self._branch(source_id).status not in {BranchStatus.ACTIVE, BranchStatus.SELECTED}:
                raise IRValidationError(f"Cannot transform inactive branch {source_id}")

        validation = TransformationContract.validate(spec.operator, spec.arguments, spec.preserved)
        self.transform_validations.append(validation)
        if not validation.valid:
            raise IRValidationError(f"Invalid {spec.operator.value}: " + "; ".join(validation.errors))
        if spec.child_branch_id in self.branches:
            raise IRValidationError(f"Duplicate branch id: {spec.child_branch_id}")

        base = copy.deepcopy(self._branch(source_ids[0]).candidate)
        child = Candidate(
            id=spec.child_candidate_id,
            revision=base.revision + 1,
            description=spec.description,
            properties=copy.deepcopy(base.properties),
            preserved=list(spec.preserved),
            changed=list(spec.changed),
            evidence_refs=list(base.evidence_refs),
            provenance=list(base.provenance),
        )
        self._apply_candidate_effect(child, spec.operator, spec.arguments)

        event_id = self._event(
            "DSC", spec.operator.value, source_ids,
            reason=reason,
            arguments=_primitive(spec.arguments),
            typed_arguments=type(spec.arguments).__name__,
            preserved=list(spec.preserved),
            changed=list(spec.changed),
            validation=_primitive(validation),
            output_branch=spec.child_branch_id,
            output_candidate=spec.child_candidate_id,
            output_description=spec.description,
            output_candidate_snapshot=_primitive(child),
        )
        child.provenance.append(event_id)

        new_branch = Branch(
            id=spec.child_branch_id,
            candidate=child,
            parent_ids=list(source_ids),
            lineage=list(self._branch(source_ids[0]).lineage) + [event_id],
        )
        self.branches[spec.child_branch_id] = new_branch
        for source_id in source_ids:
            self._branch(source_id).child_ids.append(spec.child_branch_id)
        return spec.child_branch_id

    def expand(self, source_ids: List[str], specs: List[TransformSpec], reason: str) -> List[str]:
        for source_id in source_ids:
            if self._branch(source_id).status not in {BranchStatus.ACTIVE, BranchStatus.SELECTED}:
                raise IRValidationError(f"Cannot expand inactive branch {source_id}")
        sc_event = self._event("SC", SCOperator.EXPAND.value, source_ids,
                               reason=reason, generated=len(specs))
        return [
            self.execute_transform(source_ids, spec, reason=f"caused_by:{sc_event}")
            for spec in specs
        ]

    def execute_experiment(self, branch_id: str, arguments: ExperimentArgs) -> str:
        branch = self._branch(branch_id)
        if branch.status not in {BranchStatus.ACTIVE, BranchStatus.SELECTED}:
            raise IRValidationError(f"Cannot experiment on inactive branch {branch_id}")
        validation = TransformationContract.validate(DSCOperator.EXPERIMENT, arguments, [])
        self.transform_validations.append(validation)
        if not validation.valid:
            raise IRValidationError("Invalid experiment: " + "; ".join(validation.errors))
        if arguments.evidence_id in self.evidence:
            raise IRValidationError(f"Duplicate evidence id: {arguments.evidence_id}")
        event_id = self._event(
            "DSC", DSCOperator.EXPERIMENT.value, [branch_id],
            arguments=_primitive(arguments),
            typed_arguments=type(arguments).__name__,
            validation=_primitive(validation),
        )
        ev = Evidence(
            id=arguments.evidence_id, kind=arguments.kind,
            observation=arguments.observation, confidence=arguments.confidence,
            supports=[branch.candidate.id],
            provenance={
                "transformation_event": event_id,
                "hypothesis": arguments.hypothesis,
                "intervention": arguments.intervention,
            },
        )
        self.evidence[ev.id] = ev
        branch.candidate.evidence_refs.append(ev.id)
        return ev.id

    def add_evidence(self, evidence: Evidence) -> None:
        if evidence.id in self.evidence:
            raise IRValidationError(f"Duplicate evidence id: {evidence.id}")
        self.evidence[evidence.id] = copy.deepcopy(evidence)
        self._event("EVIDENCE", "evidence_emergence",
                    evidence.supports + evidence.weakens + evidence.falsifies,
                    evidence_snapshot=_primitive(evidence))

    def evaluate(self, branch_id: str, context: str, metrics: Dict[str, float],
                 evidence_refs: Optional[List[str]] = None) -> None:
        refs = list(evidence_refs or [])
        for ref in refs:
            if ref not in self.evidence:
                raise IRValidationError(f"Unknown evidence ref: {ref}")
        evaluation = Evaluation(branch_id, context, dict(metrics), refs)
        self._branch(branch_id).evaluation = evaluation
        self._event("SC", SCOperator.EVALUATE.value, [branch_id],
                    evaluation_snapshot=_primitive(evaluation))

    def select(self, branch_ids: List[str], reason: str) -> None:
        for branch_id in branch_ids:
            branch = self._branch(branch_id)
            if branch.status != BranchStatus.ACTIVE:
                raise IRValidationError(f"Only ACTIVE branches may be selected: {branch_id}")
            branch.status = BranchStatus.SELECTED
        self._event("SC", SCOperator.SELECT.value, branch_ids,
                    reason=reason, resulting_status="SELECTED")

    def prune(self, branch_id: str, reason: str, context: Dict[str, Any],
              reopen_conditions: List[str],
              evidence_refs: Optional[List[str]] = None) -> None:
        branch = self._branch(branch_id)
        if branch.status not in {BranchStatus.ACTIVE, BranchStatus.SELECTED}:
            raise IRValidationError(f"Cannot prune branch {branch_id} from {branch.status}")
        record = PruningRecord(reason, dict(context), list(reopen_conditions),
                               list(evidence_refs or []))
        branch.status = BranchStatus.PRUNED
        branch.pruning = record
        self._event("SC", SCOperator.PRUNE.value, [branch_id],
                    resulting_status="PRUNED", pruning_snapshot=_primitive(record))

    def reopen(self, branch_id: str, trigger: str,
               evidence_refs: Optional[List[str]] = None) -> None:
        branch = self._branch(branch_id)
        if branch.status not in {BranchStatus.PRUNED, BranchStatus.SUSPENDED}:
            raise IRValidationError(f"Branch {branch_id} is not reopenable from {branch.status}")
        refs = list(evidence_refs or [])
        for ref in refs:
            if ref not in self.evidence:
                raise IRValidationError(f"Unknown evidence ref: {ref}")
        prior = branch.status.value
        record = {"trigger": trigger, "evidence_refs": refs, "prior_status": prior}
        branch.status = BranchStatus.ACTIVE
        branch.reopen_history.append(record)
        self._event("SC", SCOperator.REOPEN.value, [branch_id],
                    prior_status=prior, resulting_status="ACTIVE",
                    reopen_snapshot=record)

    def allocate(self, branch_id: str, resources: Dict[str, float], reason: str) -> None:
        branch = self._branch(branch_id)
        for key, amount in resources.items():
            if amount < 0:
                raise IRValidationError("Allocation cannot be negative")
            if key not in self.budget_remaining:
                raise IRValidationError(f"Unknown resource: {key}")
            if amount > self.budget_remaining[key]:
                raise IRValidationError(f"Insufficient {key}")
        for key, amount in resources.items():
            self.budget_remaining[key] -= amount
        allocation = Allocation(branch_id, dict(resources), reason)
        branch.allocations.append(allocation)
        self._event("SC", SCOperator.ALLOCATE.value, [branch_id],
                    allocation_snapshot=_primitive(allocation),
                    budget_after=copy.deepcopy(self.budget_remaining))

    def terminate(self, reason: str, selected_outputs: List[str]) -> None:
        for branch_id in selected_outputs:
            self._branch(branch_id).status = BranchStatus.TERMINAL
        self.terminated = True
        self.termination_reason = reason
        self._event("SC", SCOperator.TERMINATE.value, selected_outputs,
                    reason=reason, resulting_status="TERMINAL",
                    budget_remaining=copy.deepcopy(self.budget_remaining))

    def state_dict(self) -> Dict[str, Any]:
        return {
            "program_id": self.program_id,
            "branches": {k: _primitive(v) for k, v in self.branches.items()},
            "evidence": {k: _primitive(v) for k, v in self.evidence.items()},
            "budget_initial": copy.deepcopy(self.budget_initial),
            "budget_remaining": copy.deepcopy(self.budget_remaining),
            "terminated": self.terminated,
            "termination_reason": self.termination_reason,
        }

    def semantic_state_digest(self) -> str:
        return sha256_canonical(self.state_dict())

    def trace_digest(self) -> str:
        return sha256_canonical([_primitive(e) for e in self.trace])

    def validate_runtime(self) -> List[str]:
        return validate_state_dict(self.state_dict(), [_primitive(e) for e in self.trace])

    def export_package(self) -> Dict[str, Any]:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "compiler_target": COMPILER_TARGET,
            "canonicalization": CANONICALIZATION,
            "basis": copy.deepcopy(BASIS),
            "program_id": self.program_id,
            "initial_state": {
                "seed_branch_id": "B0",
                "seed_candidate": _primitive(self.initial_seed),
                "budget": copy.deepcopy(self.budget_initial),
            },
            "trace": [_primitive(e) for e in self.trace],
            "final_state": self.state_dict(),
            "digests": {
                "semantic_state_sha256": self.semantic_state_digest(),
                "trace_sha256": self.trace_digest(),
            },
        }
        return {
            "payload": payload,
            "integrity": {
                "algorithm": "sha256",
                "payload_sha256": sha256_canonical(payload),
            },
        }

    def export_canonical_json(self) -> str:
        return canonical_json(self.export_package())

    @classmethod
    def restore_snapshot(cls, package: Dict[str, Any]) -> "InventionRuntime":
        validate_package_integrity(package)
        _validate_headers(package["payload"])
        init = package["payload"]["initial_state"]
        rt = cls(package["payload"]["program_id"],
                 _candidate_from_dict(init["seed_candidate"]), init["budget"])
        final = package["payload"]["final_state"]
        rt.branches = {k: _branch_from_dict(v) for k, v in final["branches"].items()}
        rt.evidence = {k: _evidence_from_dict(v) for k, v in final["evidence"].items()}
        rt.budget_initial = copy.deepcopy(final["budget_initial"])
        rt.budget_remaining = copy.deepcopy(final["budget_remaining"])
        rt.terminated = bool(final["terminated"])
        rt.termination_reason = final["termination_reason"]
        rt.trace = [_trace_from_dict(e) for e in package["payload"]["trace"]]
        return rt

    @classmethod
    def replay_package(cls, package: Dict[str, Any], strict: bool = True) -> "InventionRuntime":
        validate_package_integrity(package)
        _validate_headers(package["payload"])
        init = package["payload"]["initial_state"]
        rt = cls(package["payload"]["program_id"],
                 _candidate_from_dict(init["seed_candidate"]), init["budget"])
        rt.trace = []
        for raw in package["payload"]["trace"]:
            event = _trace_from_dict(raw)
            _apply_replay_event(rt, event, strict=strict)
            rt.trace.append(event)
        return rt


def _candidate_from_dict(d: Dict[str, Any]) -> Candidate:
    return Candidate(
        id=d["id"], revision=int(d["revision"]), description=d["description"],
        properties=copy.deepcopy(d.get("properties", {})),
        preserved=list(d.get("preserved", [])),
        changed=list(d.get("changed", [])),
        evidence_refs=list(d.get("evidence_refs", [])),
        provenance=list(d.get("provenance", [])),
    )


def _evaluation_from_dict(d: Dict[str, Any]) -> Evaluation:
    return Evaluation(d["branch_id"], d["context"], copy.deepcopy(d["metrics"]),
                      list(d.get("evidence_refs", [])))


def _pruning_from_dict(d: Optional[Dict[str, Any]]) -> Optional[PruningRecord]:
    if d is None:
        return None
    return PruningRecord(d["reason"], copy.deepcopy(d["context"]),
                         list(d["reopen_conditions"]), list(d.get("evidence_refs", [])))


def _allocation_from_dict(d: Dict[str, Any]) -> Allocation:
    return Allocation(d["branch_id"], copy.deepcopy(d["resources"]), d["reason"])


def _branch_from_dict(d: Dict[str, Any]) -> Branch:
    return Branch(
        id=d["id"], candidate=_candidate_from_dict(d["candidate"]),
        parent_ids=list(d.get("parent_ids", [])),
        child_ids=list(d.get("child_ids", [])),
        lineage=list(d.get("lineage", [])),
        status=BranchStatus(d["status"]),
        evaluation=_evaluation_from_dict(d["evaluation"]) if d.get("evaluation") else None,
        pruning=_pruning_from_dict(d.get("pruning")),
        reopen_history=copy.deepcopy(d.get("reopen_history", [])),
        allocations=[_allocation_from_dict(x) for x in d.get("allocations", [])],
    )


def _evidence_from_dict(d: Dict[str, Any]) -> Evidence:
    return Evidence(
        id=d["id"], kind=d["kind"], observation=d["observation"],
        confidence=float(d["confidence"]), supports=list(d.get("supports", [])),
        weakens=list(d.get("weakens", [])), falsifies=list(d.get("falsifies", [])),
        provenance=copy.deepcopy(d.get("provenance", {})),
    )


def _trace_from_dict(d: Dict[str, Any]) -> TraceEvent:
    return TraceEvent(int(d["seq"]), d["layer"], d["operator"],
                      list(d.get("targets", [])), copy.deepcopy(d.get("detail", {})))


def _validate_headers(payload: Dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise IRValidationError("Unsupported schema_version")
    if payload.get("compiler_target") != COMPILER_TARGET:
        raise IRValidationError("Compiler target mismatch")
    if payload.get("canonicalization") != CANONICALIZATION:
        raise IRValidationError("Canonicalization mismatch")
    if payload.get("basis") != BASIS:
        raise IRValidationError("Basis lock mismatch")


def validate_package_integrity(package: Dict[str, Any]) -> None:
    if set(package.keys()) != {"payload", "integrity"}:
        raise IRValidationError("Package must contain exactly payload and integrity")
    if package["integrity"].get("algorithm") != "sha256":
        raise IRValidationError("Unsupported integrity algorithm")
    expected = package["integrity"].get("payload_sha256")
    actual = sha256_canonical(package["payload"])
    if expected != actual:
        raise IRValidationError("Payload SHA-256 mismatch")


def package_from_json(text: str) -> Dict[str, Any]:
    try:
        package = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IRValidationError(f"Invalid JSON: {exc}") from exc
    validate_package_integrity(package)
    _validate_headers(package["payload"])
    return package


def validate_state_dict(state: Dict[str, Any], trace: List[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    branches = state.get("branches", {})
    evidence = state.get("evidence", {})
    events = {e.get("detail", {}).get("event_id"): e for e in trace}
    event_ids = [e.get("detail", {}).get("event_id") for e in trace]

    if None in event_ids:
        errors.append("Trace event missing event_id")
    if len(event_ids) != len(set(event_ids)):
        errors.append("Duplicate trace event_id")
    seqs = [e.get("seq") for e in trace]
    if seqs != list(range(1, len(trace) + 1)):
        errors.append("Trace sequence is not contiguous")

    candidate_ids = {b["candidate"]["id"] for b in branches.values() if "candidate" in b}

    for bid, branch in branches.items():
        if branch.get("id") != bid:
            errors.append(f"{bid}: branch key/id mismatch")

        for pid in branch.get("parent_ids", []):
            if pid not in branches:
                errors.append(f"{bid}: missing parent {pid}")
            elif bid not in branches[pid].get("child_ids", []):
                errors.append(f"{bid}: parent {pid} missing reciprocal child link")

        for cid in branch.get("child_ids", []):
            if cid not in branches:
                errors.append(f"{bid}: missing child {cid}")
            elif bid not in branches[cid].get("parent_ids", []):
                errors.append(f"{bid}: child {cid} missing reciprocal parent link")

        status = branch.get("status")
        if status not in {x.value for x in BranchStatus}:
            errors.append(f"{bid}: invalid branch status {status}")
        if status == BranchStatus.PRUNED.value and branch.get("pruning") is None:
            errors.append(f"{bid}: PRUNED without pruning record")
        if branch.get("reopen_history") and branch.get("pruning") is None:
            errors.append(f"{bid}: reopen history without prior pruning record")

        for lineage_event in branch.get("lineage", []):
            if lineage_event not in events:
                errors.append(f"{bid}: lineage references missing event {lineage_event}")
            elif events[lineage_event].get("layer") != "DSC":
                errors.append(f"{bid}: lineage event {lineage_event} is not DSC")

        candidate = branch.get("candidate", {})
        for prov in candidate.get("provenance", []):
            if prov not in events:
                errors.append(f"{bid}: candidate provenance references missing event {prov}")
            elif events[prov].get("layer") != "DSC":
                errors.append(f"{bid}: candidate provenance {prov} is not DSC")

        ev_refs = list(candidate.get("evidence_refs", []))
        evaluation = branch.get("evaluation")
        if evaluation:
            ev_refs += list(evaluation.get("evidence_refs", []))
        pruning = branch.get("pruning")
        if pruning:
            ev_refs += list(pruning.get("evidence_refs", []))
        for ev in ev_refs:
            if ev not in evidence:
                errors.append(f"{bid}: references missing evidence {ev}")

    for eid, ev in evidence.items():
        if ev.get("id") != eid:
            errors.append(f"{eid}: evidence key/id mismatch")
        conf = ev.get("confidence")
        if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
            errors.append(f"{eid}: invalid evidence confidence")
        for cid in ev.get("supports", []) + ev.get("weakens", []) + ev.get("falsifies", []):
            if cid not in candidate_ids:
                errors.append(f"{eid}: references unknown candidate {cid}")
        trans_event = ev.get("provenance", {}).get("transformation_event")
        if trans_event:
            te = events.get(trans_event)
            if te is None:
                errors.append(f"{eid}: provenance references missing transformation event {trans_event}")
            elif not (te.get("layer") == "DSC" and te.get("operator") == "experiment"):
                errors.append(f"{eid}: provenance event {trans_event} is not DSC experiment")
            else:
                recorded = te.get("detail", {}).get("arguments", {}).get("evidence_id")
                if recorded != eid:
                    errors.append(f"{eid}: provenance experiment evidence_id mismatch")

    # Budget conservation against allocations.
    initial = state.get("budget_initial", {})
    remaining = state.get("budget_remaining", {})
    spent = {k: 0.0 for k in initial}
    for branch in branches.values():
        for allocation in branch.get("allocations", []):
            for key, amount in allocation.get("resources", {}).items():
                if key not in initial:
                    errors.append(f"Allocation references unknown resource {key}")
                else:
                    spent[key] += amount
    for key, start in initial.items():
        rem = remaining.get(key)
        if rem is None:
            errors.append(f"Missing remaining budget resource {key}")
        elif abs((start - spent[key]) - rem) > 1e-9:
            errors.append(f"Budget conservation failed for {key}")

    return errors


def _apply_replay_event(rt: InventionRuntime, event: TraceEvent, strict: bool = True) -> None:
    op, d = event.operator, event.detail

    if strict and event.seq != len(rt.trace) + 1:
        raise IRValidationError("Illegal trace sequence during replay")
    if strict and d.get("event_id") != f"E{event.seq:03d}":
        raise IRValidationError("Event id/sequence mismatch")

    if event.layer == "DSC" and op != DSCOperator.EXPERIMENT.value:
        out = d["output_branch"]
        parents = list(event.targets)
        if not parents:
            raise IRValidationError("Replay transform missing parent")
        if len(set(parents)) != len(parents):
            raise IRValidationError("Replay transform has duplicate parents")
        if out in rt.branches:
            raise IRValidationError(f"Replay duplicate branch {out}")
        for parent in parents:
            if parent not in rt.branches:
                raise IRValidationError(f"Replay missing parent {parent}")
            if strict and rt.branches[parent].status not in {BranchStatus.ACTIVE, BranchStatus.SELECTED}:
                raise IRValidationError(f"Illegal transform from inactive branch {parent}")

        child = _candidate_from_dict(d["output_candidate_snapshot"])
        child.provenance.append(d["event_id"])
        new_branch = Branch(
            id=out, candidate=child, parent_ids=parents,
            lineage=list(rt.branches[parents[0]].lineage) + [d["event_id"]],
        )
        rt.branches[out] = new_branch
        for parent in parents:
            rt.branches[parent].child_ids.append(out)
        return

    if event.layer == "DSC" and op == DSCOperator.EXPERIMENT.value:
        branch = rt._branch(event.targets[0])
        if strict and branch.status not in {BranchStatus.ACTIVE, BranchStatus.SELECTED}:
            raise IRValidationError("Illegal experiment on inactive branch")
        args = d["arguments"]
        if args["evidence_id"] in rt.evidence:
            raise IRValidationError("Duplicate experiment evidence id")
        ev = Evidence(
            id=args["evidence_id"], kind=args["kind"],
            observation=args["observation"], confidence=float(args["confidence"]),
            supports=[branch.candidate.id],
            provenance={
                "transformation_event": d["event_id"],
                "hypothesis": args["hypothesis"],
                "intervention": args["intervention"],
            },
        )
        rt.evidence[ev.id] = ev
        branch.candidate.evidence_refs.append(ev.id)
        return

    if event.layer == "EVIDENCE" and op == "evidence_emergence":
        ev = _evidence_from_dict(d["evidence_snapshot"])
        if ev.id in rt.evidence:
            raise IRValidationError("Duplicate evidence during replay")
        rt.evidence[ev.id] = ev
        return

    if event.layer == "SC" and op == SCOperator.EXPAND.value:
        for target in event.targets:
            if target not in rt.branches:
                raise IRValidationError("Expand targets missing branch")
            if strict and rt.branches[target].status not in {BranchStatus.ACTIVE, BranchStatus.SELECTED}:
                raise IRValidationError("Illegal expand on inactive branch")
        return

    if event.layer == "SC" and op == SCOperator.EVALUATE.value:
        e = _evaluation_from_dict(d["evaluation_snapshot"])
        if e.branch_id not in rt.branches:
            raise IRValidationError("Evaluation targets missing branch")
        for evref in e.evidence_refs:
            if evref not in rt.evidence:
                raise IRValidationError("Evaluation references missing evidence")
        rt.branches[e.branch_id].evaluation = e
        return

    if event.layer == "SC" and op == SCOperator.SELECT.value:
        for bid in event.targets:
            b = rt._branch(bid)
            if strict and b.status != BranchStatus.ACTIVE:
                raise IRValidationError("Illegal select transition")
            b.status = BranchStatus.SELECTED
        return

    if event.layer == "SC" and op == SCOperator.PRUNE.value:
        b = rt._branch(event.targets[0])
        if strict and b.status not in {BranchStatus.ACTIVE, BranchStatus.SELECTED}:
            raise IRValidationError("Illegal prune transition")
        b.status = BranchStatus.PRUNED
        b.pruning = _pruning_from_dict(d["pruning_snapshot"])
        return

    if event.layer == "SC" and op == SCOperator.REOPEN.value:
        b = rt._branch(event.targets[0])
        if strict and b.status not in {BranchStatus.PRUNED, BranchStatus.SUSPENDED}:
            raise IRValidationError("Illegal reopen transition")
        rec = copy.deepcopy(d["reopen_snapshot"])
        for evref in rec.get("evidence_refs", []):
            if evref not in rt.evidence:
                raise IRValidationError("Reopen references missing evidence")
        b.status = BranchStatus.ACTIVE
        b.reopen_history.append(rec)
        return

    if event.layer == "SC" and op == SCOperator.ALLOCATE.value:
        a = _allocation_from_dict(d["allocation_snapshot"])
        b = rt._branch(a.branch_id)
        for key, amount in a.resources.items():
            if key not in rt.budget_remaining or amount > rt.budget_remaining[key] or amount < 0:
                raise IRValidationError("Illegal allocation")
            rt.budget_remaining[key] -= amount
        if strict and rt.budget_remaining != d["budget_after"]:
            raise IRValidationError("Allocation budget_after mismatch")
        b.allocations.append(a)
        return

    if event.layer == "SC" and op == SCOperator.TERMINATE.value:
        if strict and rt.terminated:
            raise IRValidationError("Duplicate termination")
        for bid in event.targets:
            rt._branch(bid).status = BranchStatus.TERMINAL
        rt.terminated = True
        rt.termination_reason = d["reason"]
        if strict and rt.budget_remaining != d["budget_remaining"]:
            raise IRValidationError("Termination budget mismatch")
        return

    raise IRValidationError(f"Unsupported replay event {event.layer}/{event.operator}")


def validate_conformance(package: Dict[str, Any]) -> Dict[str, Any]:
    """Full compiler-target conformance gate.

    Raises IRValidationError on any failure. Returns a proof record on success.
    """
    validate_package_integrity(package)
    payload = package["payload"]
    _validate_headers(payload)

    declared_trace_digest = payload["digests"].get("trace_sha256")
    actual_trace_digest = sha256_canonical(payload["trace"])
    if declared_trace_digest != actual_trace_digest:
        raise IRValidationError("Declared trace digest mismatch")

    state_errors = validate_state_dict(payload["final_state"], payload["trace"])
    if state_errors:
        raise IRValidationError("Final-state conformance failed: " + " | ".join(state_errors))

    final_digest = sha256_canonical(payload["final_state"])
    if final_digest != payload["digests"].get("semantic_state_sha256"):
        raise IRValidationError("Declared semantic-state digest mismatch")

    # Strict replay validates legal event ordering/transitions.
    replayed = InventionRuntime.replay_package(package, strict=True)
    replay_errors = replayed.validate_runtime()
    if replay_errors:
        raise IRValidationError("Replayed-state conformance failed: " + " | ".join(replay_errors))
    if replayed.semantic_state_digest() != final_digest:
        raise IRValidationError("Replay/final-state semantic mismatch")

    restored = InventionRuntime.restore_snapshot(package)
    restore_errors = restored.validate_runtime()
    if restore_errors:
        raise IRValidationError("Restored-state conformance failed: " + " | ".join(restore_errors))
    if restored.semantic_state_digest() != final_digest:
        raise IRValidationError("Restore/final-state semantic mismatch")

    return {
        "conformant": True,
        "schema_version": SCHEMA_VERSION,
        "compiler_target": COMPILER_TARGET,
        "payload_sha256": package["integrity"]["payload_sha256"],
        "trace_sha256": actual_trace_digest,
        "semantic_state_sha256": final_digest,
        "event_count": len(payload["trace"]),
        "branch_count": len(payload["final_state"]["branches"]),
        "evidence_count": len(payload["final_state"]["evidence"]),
    }
