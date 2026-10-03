from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import re

from dsc_ir import (
    AbstractArgs, Candidate, ComposeArgs, DecomposeArgs, DSCOperator, Evidence, ExperimentArgs,
    InstantiateArgs, InventionRuntime, ModifyArgs, ReconfigureArgs, ReframeArgs,
    SubstituteArgs, TransferArgs, TransformSpec, validate_conformance,
)

LANGUAGE_VERSION = "0.1"
COMPILER_TARGET = "DSC-IR-v0.1"
COMPILER_VERSION = "dsc-plc/0.1"


class CompileError(RuntimeError):
    def __init__(self, code: str, message: str, token: "Token | None" = None,
                 filename: str = "<memory>", source_text: str = ""):
        self.code = code
        self.message = message
        self.token = token
        self.filename = filename
        self.source_text = source_text
        loc = f" at {token.line}:{token.column}" if token else ""
        super().__init__(f"{code}{loc}: {message}")

    def format_diagnostic(self, filename: str = None, source_text: str = None) -> str:
        fn = filename or self.filename
        st = source_text or self.source_text
        lines = [f"{self.code}: {self.message}"]
        if self.token and self.token.line > 0:
            lines.append(f"  --> {fn}:{self.token.line}:{self.token.column}")
            if st:
                src_lines = st.splitlines()
                if 1 <= self.token.line <= len(src_lines):
                    line_str = src_lines[self.token.line - 1]
                    lines.append(f"   |")
                    lines.append(f"{self.token.line:2d} | {line_str}")
                    caret_col = max(1, self.token.column)
                    lines.append(f"   | {' ' * (caret_col - 1)}^")
        return "\n".join(lines)

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "line": self.token.line if self.token else None,
            "column": self.token.column if self.token else None,
            "filename": self.filename,
        }


@dataclass(frozen=True)
class Token:
    kind: str
    value: Any
    line: int
    column: int


@dataclass
class NeedDecl:
    name: str
    actual: str
    desired: str


@dataclass
class FunctionDecl:
    name: str
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConstraintDecl:
    name: str
    comparator: str
    value: Any


@dataclass
class ResourceDecl:
    name: str
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PrincipleDecl:
    name: str
    statement: str


@dataclass
class SeedStmt:
    name: str


@dataclass
class TransformStmt:
    sources: List[str]
    operator: str
    result: str
    fields: List[Tuple[str, Any]]


@dataclass
class EvaluateStmt:
    branch: str
    context: str
    evidence_refs: List[str]
    metrics: Dict[str, Any]


@dataclass
class SelectStmt:
    branches: List[str]
    reason: Optional[str]


@dataclass
class PruneStmt:
    branch: str
    reason: str
    context: Dict[str, Any]
    reopen_when: List[Any]


@dataclass
class EvidenceStmt:
    evidence_id: str
    kind: str
    observation: str
    confidence: float
    supports: Optional[str]


@dataclass
class ReopenStmt:
    branch: str
    evidence_id: str
    trigger: str


@dataclass
class AllocateStmt:
    branch: str
    resources: Dict[str, Any]
    reason: Optional[str]


@dataclass
class ExperimentStmt:
    branch: str
    name: str
    hypothesis: str
    intervention: str
    observations: Dict[str, Any]
    evidence_id: str
    evidence_kind: str
    confidence: float


@dataclass
class TerminateStmt:
    branches: List[str]
    reason: str


@dataclass
class Program:
    language_version: Optional[str]
    target: Optional[str]
    invention_name: str
    problem_decls: List[Any]
    search_stmts: List[Any]


TRANSFORM_OPS = {
    "decompose", "compose", "substitute", "modify", "reconfigure",
    "abstract", "instantiate", "transfer", "reframe"
}


def lex(text: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    line = 1
    col = 1

    def advance(raw: str):
        nonlocal line, col
        for ch in raw:
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1

    while i < len(text):
        ch = text[i]

        if ch.isspace():
            j = i
            while j < len(text) and text[j].isspace():
                j += 1
            advance(text[i:j])
            i = j
            continue

        if text.startswith("//", i):
            j = i
            while j < len(text) and text[j] != "\n":
                j += 1
            advance(text[i:j])
            i = j
            continue

        tok_line, tok_col = line, col

        if ch == '"':
            j = i + 1
            buf = []
            while j < len(text) and text[j] != '"':
                if text[j] == "\\" and j + 1 < len(text):
                    esc = text[j + 1]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, esc))
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            if j >= len(text):
                raise CompileError("PL-SYNTAX-002", "unterminated string",
                                   Token("STRING", "", tok_line, tok_col))
            raw = text[i:j + 1]
            tokens.append(Token("STRING", "".join(buf), tok_line, tok_col))
            i = j + 1
            advance(raw)
            continue

        matched_symbol = None
        for sym in ("<=", ">=", "=="):
            if text.startswith(sym, i):
                matched_symbol = sym
                break
        if matched_symbol:
            tokens.append(Token("SYMBOL", matched_symbol, tok_line, tok_col))
            i += len(matched_symbol)
            advance(matched_symbol)
            continue

        if ch in "{}[],:=<>":
            tokens.append(Token("SYMBOL", ch, tok_line, tok_col))
            i += 1
            advance(ch)
            continue

        m = re.match(r"-?(?:\d+\.\d+|\d+)", text[i:])
        if m:
            raw = m.group(0)
            value = float(raw) if "." in raw else int(raw)
            tokens.append(Token("NUMBER", value, tok_line, tok_col))
            i += len(raw)
            advance(raw)
            continue

        m = re.match(r"[A-Za-z_][A-Za-z0-9_.-]*", text[i:])
        if m:
            raw = m.group(0)
            if raw == "true":
                tokens.append(Token("BOOLEAN", True, tok_line, tok_col))
            elif raw == "false":
                tokens.append(Token("BOOLEAN", False, tok_line, tok_col))
            else:
                tokens.append(Token("IDENT", raw, tok_line, tok_col))
            i += len(raw)
            advance(raw)
            continue

        raise CompileError("PL-SYNTAX-003", f"unexpected character {ch!r}",
                           Token("UNKNOWN", ch, tok_line, tok_col))

    tokens.append(Token("EOF", None, line, col))
    return tokens


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> Token:
        return self.tokens[self.i]

    def take(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect_value(self, value: str) -> Token:
        tok = self.take()
        if tok.value != value:
            raise CompileError("PL-SYNTAX-010", f"expected {value!r}, got {tok.value!r}", tok)
        return tok

    def expect_ident(self) -> str:
        tok = self.take()
        if tok.kind != "IDENT":
            raise CompileError("PL-SYNTAX-011", f"expected identifier, got {tok.value!r}", tok)
        return tok.value

    def expect_string(self) -> str:
        tok = self.take()
        if tok.kind != "STRING":
            raise CompileError("PL-SYNTAX-012", "expected quoted string", tok)
        return tok.value

    def parse_value(self) -> Any:
        tok = self.peek()
        if tok.kind in {"STRING", "NUMBER", "BOOLEAN"}:
            return self.take().value
        if tok.kind == "IDENT":
            return self.take().value
        if tok.value == "[":
            return self.parse_list()
        if tok.value == "{":
            return self.parse_object()
        raise CompileError("PL-SYNTAX-013", f"expected value, got {tok.value!r}", tok)

    def parse_list(self) -> List[Any]:
        self.expect_value("[")
        out = []
        while self.peek().value != "]":
            out.append(self.parse_value())
            if self.peek().value == ",":
                self.take()
            elif self.peek().value != "]":
                raise CompileError("PL-SYNTAX-014", "expected ',' or ']'", self.peek())
        self.expect_value("]")
        return out

    def parse_object(self) -> Dict[str, Any]:
        self.expect_value("{")
        out = {}
        while self.peek().value != "}":
            key = self.expect_ident()
            if key in out:
                raise CompileError("PL-SYNTAX-015", f"duplicate field {key!r}", self.peek())
            out[key] = self.parse_value()
        self.expect_value("}")
        return out

    def parse_field_list(self) -> List[Tuple[str, Any]]:
        self.expect_value("{")
        out = []
        while self.peek().value != "}":
            key = self.expect_ident()
            if key == "preserve" and self.peek().value == "need":
                self.take()
                out.append(("preserve_need", self.expect_ident()))
            else:
                out.append((key, self.parse_value()))
        self.expect_value("}")
        return out

    def parse(self) -> Program:
        language_version = None
        target = None

        if self.peek().value == "language":
            self.take()
            self.expect_value("dsc")
            tok = self.take()
            if tok.kind not in {"NUMBER", "IDENT"}:
                raise CompileError("PL-SYNTAX-016", "expected language version", tok)
            language_version = str(tok.value)

        if self.peek().value == "target":
            self.take()
            target = self.expect_ident()

        self.expect_value("invention")
        invention_name = self.expect_ident()
        self.expect_value("{")

        self.expect_value("problem")
        problem = self.parse_problem()

        self.expect_value("search")
        search = self.parse_search()

        self.expect_value("}")
        if self.peek().kind != "EOF":
            raise CompileError("PL-SYNTAX-017", "unexpected trailing input", self.peek())

        return Program(language_version, target, invention_name, problem, search)

    def parse_problem(self) -> List[Any]:
        self.expect_value("{")
        out = []
        while self.peek().value != "}":
            head = self.expect_ident()
            if head == "need":
                name = self.expect_ident()
                self.expect_value(":")
                self.expect_value("actual")
                actual = self.expect_string()
                self.expect_value("desired")
                desired = self.expect_string()
                out.append(NeedDecl(name, actual, desired))
            elif head == "function":
                name = self.expect_ident()
                attrs = self.parse_object() if self.peek().value == "{" else {}
                out.append(FunctionDecl(name, attrs))
            elif head == "constraint":
                name = self.expect_ident()
                cmp_tok = self.take()
                if cmp_tok.value not in {"=", "<", "<=", ">", ">="}:
                    raise CompileError("PL-SYNTAX-020", "expected constraint comparator", cmp_tok)
                out.append(ConstraintDecl(name, cmp_tok.value, self.parse_value()))
            elif head == "resource":
                name = self.expect_ident()
                attrs = self.parse_object() if self.peek().value == "{" else {}
                out.append(ResourceDecl(name, attrs))
            elif head == "principle":
                name = self.expect_ident()
                self.expect_value(":")
                out.append(PrincipleDecl(name, self.expect_string()))
            else:
                raise CompileError("PL-SYNTAX-021", f"unknown problem declaration {head!r}", self.peek())
        self.expect_value("}")
        return out

    def parse_source_ref(self) -> List[str]:
        if self.peek().value == "[":
            vals = self.parse_list()
            if not all(isinstance(x, str) for x in vals):
                raise CompileError("PL-SYNTAX-030", "branch source list must contain identifiers", self.peek())
            return vals
        return [self.expect_ident()]

    def parse_search(self) -> List[Any]:
        self.expect_value("{")
        out = []
        while self.peek().value != "}":
            head = self.expect_ident()

            if head == "seed":
                out.append(SeedStmt(self.expect_ident()))
                continue

            if head == "from":
                sources = self.parse_source_ref()
                op = self.expect_ident()
                if op not in TRANSFORM_OPS:
                    raise CompileError("PL-SYNTAX-031", f"unknown transformation {op!r}", self.peek())
                result = self.expect_ident()
                out.append(TransformStmt(sources, op, result, self.parse_field_list()))
                continue

            if head == "evaluate":
                branch = self.expect_ident()
                self.expect_value("under")
                context = self.expect_ident()
                refs = []
                if self.peek().value == "using":
                    self.take()
                    refs = self.parse_list()
                out.append(EvaluateStmt(branch, context, refs, self.parse_object()))
                continue

            if head == "select":
                branches = self.parse_list()
                reason = None
                if self.peek().value == "because":
                    self.take()
                    reason = self.expect_string()
                out.append(SelectStmt(branches, reason))
                continue

            if head == "prune":
                branch = self.expect_ident()
                self.expect_value("because")
                reason = self.expect_string()
                context = {}
                reopen_when = []
                if self.peek().value == "under":
                    self.take()
                    context = self.parse_object()
                if self.peek().value == "reopen_when":
                    self.take()
                    reopen_when = self.parse_list()
                out.append(PruneStmt(branch, reason, context, reopen_when))
                continue

            if head == "evidence":
                evid = self.expect_ident()
                self.expect_value("{")
                kind = None
                observation = None
                confidence = None
                supports = None
                while self.peek().value != "}":
                    key = self.expect_ident()
                    if key == "kind":
                        kind = self.expect_ident()
                    elif key == "observation":
                        observation = self.expect_string()
                    elif key == "confidence":
                        confidence = float(self.parse_value())
                    elif key == "supports":
                        supports = self.expect_ident()
                    else:
                        raise CompileError("PL-SYNTAX-032", f"unknown evidence field {key!r}", self.peek())
                self.expect_value("}")
                if kind is None or observation is None or confidence is None:
                    raise CompileError("PL-SEMANTIC-020", "evidence requires kind, observation, confidence")
                out.append(EvidenceStmt(evid, kind, observation, confidence, supports))
                continue

            if head == "reopen":
                branch = self.expect_ident()
                self.expect_value("because")
                evid = self.expect_ident()
                self.expect_value("trigger")
                trigger = self.expect_string()
                out.append(ReopenStmt(branch, evid, trigger))
                continue

            if head == "allocate":
                branch = self.expect_ident()
                resources = self.parse_object()
                reason = None
                if self.peek().value == "because":
                    self.take()
                    reason = self.expect_string()
                out.append(AllocateStmt(branch, resources, reason))
                continue

            if head == "experiment":
                branch = self.expect_ident()
                self.expect_value("as")
                name = self.expect_ident()
                self.expect_value("{")
                hypothesis = None
                intervention = None
                observations = {}
                evidence_id = None
                evidence_kind = None
                confidence = None
                while self.peek().value != "}":
                    key = self.expect_ident()
                    if key == "hypothesis":
                        hypothesis = self.expect_string()
                    elif key == "intervention":
                        intervention = self.expect_string()
                    elif key == "observe":
                        obs_name = self.expect_ident()
                        self.expect_value("=")
                        observations[obs_name] = self.parse_value()
                    elif key == "evidence":
                        evidence_id = self.expect_ident()
                        self.expect_value("{")
                        while self.peek().value != "}":
                            ekey = self.expect_ident()
                            if ekey == "kind":
                                evidence_kind = self.expect_ident()
                            elif ekey == "confidence":
                                confidence = float(self.parse_value())
                            else:
                                raise CompileError("PL-SYNTAX-033", f"unknown experiment evidence field {ekey!r}", self.peek())
                        self.expect_value("}")
                    else:
                        raise CompileError("PL-SYNTAX-034", f"unknown experiment field {key!r}", self.peek())
                self.expect_value("}")
                if None in {hypothesis, intervention, evidence_id, evidence_kind, confidence}:
                    raise CompileError("PL-SEMANTIC-021", "experiment missing required fields")
                out.append(ExperimentStmt(
                    branch, name, hypothesis, intervention, observations,
                    evidence_id, evidence_kind, confidence
                ))
                continue

            if head == "terminate":
                self.expect_value("with")
                branches = self.parse_list() if self.peek().value == "[" else [self.expect_ident()]
                self.expect_value("because")
                out.append(TerminateStmt(branches, self.expect_string()))
                continue

            raise CompileError("PL-SYNTAX-035", f"unknown search statement {head!r}", self.peek())

        self.expect_value("}")
        return out


def parse_source(text: str, filename: str = "<memory>") -> Program:
    try:
        return Parser(lex(text)).parse()
    except CompileError as exc:
        exc.filename = filename
        exc.source_text = text
        raise exc


class Compiler:
    def __init__(self, filename: str = "<memory>"):
        self.filename = filename
        self.branch_ids: Dict[str, str] = {}
        self.candidate_ids: Dict[str, str] = {}
        self.evidence_ids: Dict[str, str] = {}
        self.branch_state: Dict[str, str] = {}
        self.next_branch = 0
        self.next_candidate = 0

    def alloc_branch(self, source_name: str) -> Tuple[str, str]:
        if source_name in self.branch_ids:
            raise CompileError("PL-NAME-002", f"duplicate branch {source_name!r}")
        bid = f"B{self.next_branch}"
        cid = f"C{self.next_candidate}"
        self.next_branch += 1
        self.next_candidate += 1
        self.branch_ids[source_name] = bid
        self.candidate_ids[source_name] = cid
        return bid, cid

    def resolve_branch(self, name: str) -> str:
        if name not in self.branch_ids:
            raise CompileError("PL-NAME-001", f"unknown branch {name!r}")
        return self.branch_ids[name]

    def resolve_candidate(self, branch_name: str) -> str:
        self.resolve_branch(branch_name)
        return self.candidate_ids[branch_name]

    def infer_budget(self, stmts: List[Any]) -> Dict[str, float]:
        budget = {}
        for stmt in stmts:
            if isinstance(stmt, AllocateStmt):
                for key, value in stmt.resources.items():
                    if not isinstance(value, (int, float)) or value < 0:
                        raise CompileError("PL-TYPE-001", f"allocation {key!r} must be non-negative numeric")
                    budget[key] = budget.get(key, 0.0) + float(value)
        return budget

    def compile(self, program: Program):
        if program.language_version is not None and program.language_version != LANGUAGE_VERSION:
            raise CompileError("PL-SEMANTIC-001", f"unsupported language version {program.language_version!r}")
        if program.target is not None and program.target != COMPILER_TARGET:
            raise CompileError("PL-SEMANTIC-002", f"unsupported target {program.target!r}")

        problem = {"needs": [], "functions": [], "constraints": [], "resources": [], "principles": []}
        seen = set()
        for decl in program.problem_decls:
            key = (type(decl).__name__, decl.name)
            if key in seen:
                raise CompileError("PL-NAME-003", f"duplicate problem declaration {decl.name!r}")
            seen.add(key)
            if isinstance(decl, NeedDecl):
                problem["needs"].append({"id": decl.name, "actual": decl.actual, "desired": decl.desired})
            elif isinstance(decl, FunctionDecl):
                problem["functions"].append({"id": decl.name, "attributes": decl.attributes})
            elif isinstance(decl, ConstraintDecl):
                problem["constraints"].append({"id": decl.name, "comparator": decl.comparator, "value": decl.value})
            elif isinstance(decl, ResourceDecl):
                problem["resources"].append({"id": decl.name, "attributes": decl.attributes})
            elif isinstance(decl, PrincipleDecl):
                problem["principles"].append({"id": decl.name, "statement": decl.statement})

        seeds = [s for s in program.search_stmts if isinstance(s, SeedStmt)]
        if len(seeds) != 1:
            raise CompileError("PL-SEMANTIC-003", "search requires exactly one seed")

        root_name = seeds[0].name
        bid, cid = self.alloc_branch(root_name)
        assert (bid, cid) == ("B0", "C0")
        self.branch_state[root_name] = "ACTIVE"

        rt = InventionRuntime(
            program.invention_name,
            Candidate(
                id="C0",
                revision=1,
                description=f"Seed branch {root_name}",
                properties={
                    "source_language": "dsc 0.1",
                    "compiler": COMPILER_VERSION,
                    "problem": problem,
                },
            ),
            budget=self.infer_budget(program.search_stmts),
        )

        for stmt in program.search_stmts:
            if isinstance(stmt, SeedStmt):
                continue

            if isinstance(stmt, TransformStmt):
                self.compile_transform(rt, stmt)

            elif isinstance(stmt, EvaluateStmt):
                bid = self.resolve_branch(stmt.branch)
                for ev in stmt.evidence_refs:
                    if ev not in self.evidence_ids:
                        raise CompileError("PL-NAME-004", f"unknown Evidence {ev!r}")
                try:
                    metrics = {k: float(v) for k, v in stmt.metrics.items()}
                except Exception as exc:
                    raise CompileError("PL-TYPE-002", "evaluation metrics must be numeric") from exc
                rt.evaluate(bid, stmt.context, metrics, stmt.evidence_refs)

            elif isinstance(stmt, SelectStmt):
                for branch in stmt.branches:
                    if self.branch_state.get(branch) != "ACTIVE":
                        raise CompileError("PL-STATE-001", f"branch {branch!r} is not ACTIVE")
                rt.select([self.resolve_branch(b) for b in stmt.branches], stmt.reason or "")
                for b in stmt.branches:
                    self.branch_state[b] = "SELECTED"

            elif isinstance(stmt, PruneStmt):
                state = self.branch_state.get(stmt.branch)
                if state not in {"ACTIVE", "SELECTED"}:
                    raise CompileError("PL-STATE-002", f"branch {stmt.branch!r} cannot be pruned from {state}")
                rt.prune(
                    self.resolve_branch(stmt.branch), stmt.reason,
                    stmt.context, [str(x) for x in stmt.reopen_when]
                )
                self.branch_state[stmt.branch] = "PRUNED"

            elif isinstance(stmt, EvidenceStmt):
                if stmt.evidence_id in self.evidence_ids:
                    raise CompileError("PL-NAME-005", f"duplicate Evidence {stmt.evidence_id!r}")
                supports = [self.resolve_candidate(stmt.supports)] if stmt.supports else []
                rt.add_evidence(Evidence(
                    id=stmt.evidence_id,
                    kind=stmt.kind,
                    observation=stmt.observation,
                    confidence=stmt.confidence,
                    supports=supports,
                    provenance={"source": self.filename, "compiler": COMPILER_VERSION},
                ))
                self.evidence_ids[stmt.evidence_id] = stmt.evidence_id

            elif isinstance(stmt, ReopenStmt):
                if self.branch_state.get(stmt.branch) not in {"PRUNED", "SUSPENDED"}:
                    raise CompileError("PL-STATE-003", f"branch {stmt.branch!r} cannot be reopened")
                if stmt.evidence_id not in self.evidence_ids:
                    raise CompileError("PL-NAME-006", f"unknown Evidence {stmt.evidence_id!r}")
                rt.reopen(self.resolve_branch(stmt.branch), stmt.trigger, [stmt.evidence_id])
                self.branch_state[stmt.branch] = "ACTIVE"

            elif isinstance(stmt, AllocateStmt):
                rt.allocate(
                    self.resolve_branch(stmt.branch),
                    {k: float(v) for k, v in stmt.resources.items()},
                    stmt.reason or "",
                )

            elif isinstance(stmt, ExperimentStmt):
                if stmt.evidence_id in self.evidence_ids:
                    raise CompileError("PL-NAME-007", f"duplicate Evidence {stmt.evidence_id!r}")
                observation = "; ".join(
                    f"{k}={json.dumps(v, sort_keys=True)}"
                    for k, v in stmt.observations.items()
                )
                rt.execute_experiment(
                    self.resolve_branch(stmt.branch),
                    ExperimentArgs(
                        hypothesis=stmt.hypothesis,
                        intervention=stmt.intervention,
                        observation=observation,
                        evidence_id=stmt.evidence_id,
                        confidence=stmt.confidence,
                        kind=stmt.evidence_kind,
                    ),
                )
                self.evidence_ids[stmt.evidence_id] = stmt.evidence_id

            elif isinstance(stmt, TerminateStmt):
                for b in stmt.branches:
                    self.resolve_branch(b)
                rt.terminate(stmt.reason, [self.branch_ids[b] for b in stmt.branches])
                for b in stmt.branches:
                    self.branch_state[b] = "TERMINAL"

            else:
                raise CompileError("PL-SEMANTIC-099", f"unsupported AST node {type(stmt).__name__}")

        errors = rt.validate_runtime()
        if errors:
            raise CompileError("PL-IR-CONFORMANCE-001", " | ".join(errors))

        try:
            proof = validate_conformance(rt.export_package())
        except Exception as exc:
            raise CompileError("PL-IR-CONFORMANCE-002", str(exc)) from exc

        metadata = {
            "compiler_version": COMPILER_VERSION,
            "language_version": LANGUAGE_VERSION,
            "target": COMPILER_TARGET,
            "invention": program.invention_name,
            "branch_map": dict(self.branch_ids),
            "candidate_map": dict(self.candidate_ids),
            "evidence_map": dict(self.evidence_ids),
            "conformance": proof,
        }
        return rt, metadata

    def field_map(self, fields: List[Tuple[str, Any]]) -> Dict[str, Any]:
        out = {}
        for k, v in fields:
            if k in out:
                raise CompileError("PL-SEMANTIC-010", f"duplicate transformation field {k!r}")
            out[k] = v
        return out

    def compile_transform(self, rt: InventionRuntime, stmt: TransformStmt) -> None:
        for source in stmt.sources:
            if source not in self.branch_ids:
                raise CompileError("PL-NAME-008", f"unknown source branch {source!r}")
            if self.branch_state.get(source) not in {"ACTIVE", "SELECTED"}:
                raise CompileError("PL-STATE-004", f"cannot transform inactive branch {source!r}")

        bid, cid = self.alloc_branch(stmt.result)
        f = self.field_map(stmt.fields)
        preserved = []
        changed = [f"source:{stmt.operator}"]

        def require_list(name):
            value = f[name]
            if not isinstance(value, list):
                raise CompileError("PL-TYPE-010", f"{stmt.operator} field {name!r} must be a list")
            return value

        try:
            if stmt.operator == "decompose":
                args = DecomposeArgs(f["target"], require_list("into"))
            elif stmt.operator == "compose":
                args = ComposeArgs(require_list("elements"), f["as"])
            elif stmt.operator == "substitute":
                role = f.get("preserve")
                if role is None:
                    raise CompileError("PL-SEMANTIC-014", "substitute requires explicit preserve")
                preserved = [str(role)]
                args = SubstituteArgs(f["old"], f["new"], str(role))
            elif stmt.operator == "modify":
                args = ModifyArgs(f["target"], f["property"], f["from"], f["to"])
            elif stmt.operator == "reconfigure":
                args = ReconfigureArgs(f["target"], require_list("prior"), require_list("new"))
            elif stmt.operator == "abstract":
                args = AbstractArgs(f["source"], f["generalize"])
            elif stmt.operator == "instantiate":
                args = InstantiateArgs(f["abstract"], f["as"])
            elif stmt.operator == "transfer":
                args = TransferArgs(f["source_domain"], f["target_domain"], f["structure"])
            elif stmt.operator == "reframe":
                need = f.get("preserve_need")
                if need is None:
                    raise CompileError("PL-SEMANTIC-015", "reframe requires 'preserve need <id>'")
                declared_needs = {
                    n["id"] for n in rt.branches["B0"].candidate.properties["problem"]["needs"]
                }
                if need not in declared_needs:
                    raise CompileError("PL-NAME-009", f"unknown Need {need!r}")
                preserved = [need]
                args = ReframeArgs(f["target"], f["from"], f["to"], need)
            else:
                raise CompileError("PL-SEMANTIC-016", f"unsupported transformation {stmt.operator}")
        except KeyError as exc:
            raise CompileError("PL-SEMANTIC-017", f"{stmt.operator} missing required field {exc.args[0]!r}") from exc

        spec = TransformSpec(
            operator=DSCOperator(stmt.operator),
            child_branch_id=bid,
            child_candidate_id=cid,
            description=f"{stmt.operator} -> {stmt.result}",
            arguments=args,
            preserved=preserved,
            changed=changed,
        )

        try:
            rt.expand(
                [self.branch_ids[s] for s in stmt.sources],
                [spec],
                reason=f"compiled:{stmt.operator}:{stmt.result}",
            )
        except Exception as exc:
            raise CompileError("PL-IR-CONFORMANCE-003", str(exc)) from exc

        self.branch_state[stmt.result] = "ACTIVE"


def compile_text(text: str, filename: str = "<memory>"):
    try:
        program = parse_source(text, filename=filename)
        return Compiler(filename).compile(program)
    except CompileError as exc:
        exc.filename = filename
        exc.source_text = text
        raise exc


def compile_file(path: str | Path):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    return compile_text(text, str(p))
