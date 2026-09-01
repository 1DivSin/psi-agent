"""Compile and execute checked FusionFlow workflows."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field
from os import PathLike
from os.path import isabs
from typing import Literal, TypeGuard, cast

from .checker import check_workflow, collect_core_ir_diagnostics
from .contracts import Diagnostic
from .core_ir import Assertion, CompoundTerm, Concept, Constant, Operator
from .execution.model import AgentConfig
from .graph_compiler import WorkflowGraphCompilation, WorkflowGraphCompiler
from .parser import ParseContext, parse_workflow, parse_workflow_comments
from .step_timing import StepTiming, StepTimingMetadata
from .workflow_execution import (
    CheckpointObserver,
    DispatchContext,
    ExecutionCheckpoint,
    ResourceAllocator,
    ResourceCapacity,
    StepDispatcher,
    execute_plan,
    generate_plan,
)
from .workflow_graph import ConsumesEdge, ForeachEdge, ProducesEdge, StepNode, WorkflowGraph

type PathResolver = Callable[[str], Awaitable[str]]
type InstructionResolver = Callable[[str], Awaitable[str]]
type ExecutorKind = Literal["Agent", "Human", "Program"]
type JsonArtifactType = Literal["null", "boolean", "integer", "number", "string", "object", "array"]


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    """Machine-enforced JSON Schema subset plus human-readable semantics."""

    description: str
    json_type: JsonArtifactType | None = None
    schema: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        supported_types = {"null", "boolean", "integer", "number", "string", "object", "array"}
        if self.json_type is not None and self.json_type not in supported_types:
            raise ValueError(f"unsupported Artifact JSON type: {self.json_type!r}")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("Artifact contract description must be non-empty")
        if not isinstance(self.schema, Mapping) or not all(isinstance(key, str) for key in self.schema):
            raise ValueError("Artifact contract schema must be a JSON object")
        schema = dict(self.schema)
        schema_description = schema.get("description")
        if schema_description is not None and (
            not isinstance(schema_description, str) or schema_description.strip() != self.description.strip()
        ):
            raise ValueError("Artifact contract schema description conflicts with its description")
        schema_type = schema.get("type")
        if schema_type is not None and schema_type not in supported_types:
            raise ValueError(f"unsupported Artifact JSON type: {schema_type!r}")
        if self.json_type is not None and schema_type is not None and self.json_type != schema_type:
            raise ValueError("Artifact contract json_type conflicts with schema type")
        normalized_type = self.json_type if self.json_type is not None else cast(JsonArtifactType | None, schema_type)
        if normalized_type is not None:
            schema["type"] = normalized_type
        schema["description"] = self.description.strip()
        _validate_artifact_schema(schema)
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "json_type", normalized_type)
        object.__setattr__(self, "schema", schema)

    def to_dict(self) -> dict[str, object]:
        """Return a detached JSON Schema fragment in stable JSON-ready form."""

        return cast(dict[str, object], json.loads(json.dumps(self.schema, ensure_ascii=False, allow_nan=False)))

    def to_tool_schema(self, *, foreach_iteration: bool = False) -> dict[str, object]:
        """Return the JSON Schema fragment used by ``submit_step_result``."""

        if not foreach_iteration:
            return self.to_dict()
        items = self.schema.get("items")
        if self.json_type == "array" and isinstance(items, Mapping):
            item_schema = cast(dict[str, object], json.loads(json.dumps(items, ensure_ascii=False, allow_nan=False)))
            item_description = item_schema.get("description")
            prefix = "One element contributed by this foreach iteration."
            item_schema["description"] = (
                prefix if not isinstance(item_description, str) else f"{prefix} {item_description.strip()}"
            )
            return item_schema
        return {
            "description": (
                "One element contributed by this foreach iteration. "
                f"Aggregate Artifact contract: {self.description.strip()}"
            )
        }


_LEGACY_ARTIFACT_CONTRACT_DIRECTIVE = re.compile(
    r"^\s*@artifact\s+(?P<artifact>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"(?:\s+\[(?P<json_type>null|boolean|integer|number|string|object|array)\])?"
    r"\s*:\s*(?P<description>\S.*)\s*$",
    re.IGNORECASE,
)
_SCHEMA_ARTIFACT_CONTRACT_DIRECTIVE = re.compile(
    r"^\s*@artifact\s+(?P<artifact>[A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*(?P<schema>\{.*\})\s*$",
    re.IGNORECASE,
)
_SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "const",
        "description",
        "enum",
        "items",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "pattern",
        "properties",
        "required",
        "type",
    }
)
_PROGRAM_ERROR_KEY = "$fusion_flow/program_error"


def _is_json_value(value: object) -> bool:
    if value is None or type(value) in {bool, int, str}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    return isinstance(value, Mapping) and all(
        isinstance(key, str) and _is_json_value(item) for key, item in value.items()
    )


def _non_negative_integer(value: object) -> TypeGuard[int]:
    return type(value) is int and value >= 0


def _finite_number(value: object) -> TypeGuard[int | float]:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _validate_artifact_schema(schema: Mapping[str, object], *, path: str = "$") -> None:
    """Validate the supported JSON Schema subset before workflow dispatch."""

    unsupported = sorted(schema.keys() - _SUPPORTED_SCHEMA_KEYWORDS)
    if unsupported:
        raise ValueError(f"unsupported Artifact schema keywords at {path}: {unsupported}")
    description = schema.get("description")
    if description is not None and (not isinstance(description, str) or not description.strip()):
        raise ValueError(f"Artifact schema description at {path} must be non-empty text")
    json_type = schema.get("type")
    supported_types = {"null", "boolean", "integer", "number", "string", "object", "array"}
    if json_type is not None and json_type not in supported_types:
        raise ValueError(f"unsupported Artifact schema type at {path}: {json_type!r}")

    properties = schema.get("properties")
    if properties is not None:
        if json_type not in (None, "object") or not isinstance(properties, Mapping):
            raise ValueError(f"Artifact schema properties at {path} require an object schema")
        for key, child in properties.items():
            if not isinstance(key, str) or not isinstance(child, Mapping):
                raise ValueError(f"Artifact schema property definitions at {path} must be JSON objects")
            _validate_artifact_schema(cast(Mapping[str, object], child), path=f"{path}.{key}")

    required = schema.get("required")
    if required is not None:
        if json_type not in (None, "object") or not isinstance(required, list):
            raise ValueError(f"Artifact schema required at {path} requires an object schema")
        if not all(isinstance(key, str) for key in required) or len(set(required)) != len(required):
            raise ValueError(f"Artifact schema required at {path} must contain unique property names")
        if isinstance(properties, Mapping) and not set(required).issubset(properties):
            unknown = sorted(set(required) - set(properties))
            raise ValueError(f"Artifact schema required at {path} names undefined properties: {unknown}")

    additional = schema.get("additionalProperties")
    if additional is not None:
        if json_type not in (None, "object") or not isinstance(additional, (bool, Mapping)):
            raise ValueError(f"Artifact schema additionalProperties at {path} must be boolean or a schema")
        if isinstance(additional, Mapping):
            _validate_artifact_schema(cast(Mapping[str, object], additional), path=f"{path}.*")

    items = schema.get("items")
    if items is not None:
        if json_type not in (None, "array") or not isinstance(items, Mapping):
            raise ValueError(f"Artifact schema items at {path} requires an array schema")
        _validate_artifact_schema(cast(Mapping[str, object], items), path=f"{path}[]")

    for minimum_name, maximum_name, allowed_type in (
        ("minItems", "maxItems", "array"),
        ("minLength", "maxLength", "string"),
        ("minProperties", "maxProperties", "object"),
    ):
        minimum = schema.get(minimum_name)
        maximum = schema.get(maximum_name)
        if minimum is not None and (json_type not in (None, allowed_type) or not _non_negative_integer(minimum)):
            raise ValueError(f"Artifact schema {minimum_name} at {path} is invalid")
        if maximum is not None and (json_type not in (None, allowed_type) or not _non_negative_integer(maximum)):
            raise ValueError(f"Artifact schema {maximum_name} at {path} is invalid")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"Artifact schema {minimum_name} exceeds {maximum_name} at {path}")

    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if minimum is not None and (json_type not in (None, "integer", "number") or not _finite_number(minimum)):
        raise ValueError(f"Artifact schema minimum at {path} is invalid")
    if maximum is not None and (json_type not in (None, "integer", "number") or not _finite_number(maximum)):
        raise ValueError(f"Artifact schema maximum at {path} is invalid")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"Artifact schema minimum exceeds maximum at {path}")

    pattern = schema.get("pattern")
    if pattern is not None:
        if json_type not in (None, "string") or not isinstance(pattern, str):
            raise ValueError(f"Artifact schema pattern at {path} requires a string schema")
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"Artifact schema pattern at {path} is invalid: {error}") from error

    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum or not all(_is_json_value(item) for item in enum)):
        raise ValueError(f"Artifact schema enum at {path} must be a non-empty JSON array")
    if "const" in schema and not _is_json_value(schema["const"]):
        raise ValueError(f"Artifact schema const at {path} must be a finite JSON value")


def _combine_artifact_contracts(
    existing: ArtifactContract,
    addition: ArtifactContract,
    *,
    artifact_id: str,
    context: str,
) -> ArtifactContract:
    """Combine identical machine constraints while preserving semantic guidance."""

    existing_schema = existing.to_dict()
    addition_schema = addition.to_dict()
    existing_schema.pop("description", None)
    addition_schema.pop("description", None)
    if existing_schema != addition_schema:
        raise ValueError(f"conflicting Artifact contracts for {artifact_id!r} in {context}")
    existing_description = existing.description.strip()
    addition_description = addition.description.strip()
    description = (
        existing_description
        if existing_description == addition_description
        else f"{existing_description}\n{addition_description}"
    )
    return ArtifactContract(
        description=description,
        schema=existing_schema,
    )


def _artifact_contract_directives(text: str, *, context: str) -> dict[str, ArtifactContract]:
    """Parse exact one-line ``@artifact`` directives from comments or instructions."""

    contracts: dict[str, ArtifactContract] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        cleaned = re.sub(r"^\s*\*\s?", "", line)
        schema_match = _SCHEMA_ARTIFACT_CONTRACT_DIRECTIVE.fullmatch(cleaned)
        legacy_match = _LEGACY_ARTIFACT_CONTRACT_DIRECTIVE.fullmatch(cleaned)
        if schema_match is None and legacy_match is None:
            if cleaned.lstrip().casefold().startswith("@artifact"):
                raise ValueError(f"malformed Artifact contract in {context} at line {line_number}: {cleaned.strip()}")
            continue
        if schema_match is not None:
            try:
                schema = json.loads(schema_match.group("schema"))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"malformed Artifact schema in {context} at line {line_number}: {error.msg}"
                ) from error
            if not isinstance(schema, dict):
                raise ValueError(f"Artifact schema in {context} at line {line_number} must be a JSON object")
            description = schema.get("description")
            if not isinstance(description, str) or not description.strip():
                raise ValueError(
                    f"Artifact schema in {context} at line {line_number} requires a non-empty description"
                )
            if "type" not in schema:
                raise ValueError(f"Artifact schema in {context} at line {line_number} requires a top-level type")
            contract = ArtifactContract(description=description, schema=schema)
            artifact_id = schema_match.group("artifact")
        else:
            assert legacy_match is not None
            json_type_text = legacy_match.group("json_type")
            contract = ArtifactContract(
                description=legacy_match.group("description"),
                json_type=(None if json_type_text is None else cast(JsonArtifactType, json_type_text.casefold())),
            )
            artifact_id = legacy_match.group("artifact")
        existing = contracts.get(artifact_id)
        if existing is not None:
            contract = _combine_artifact_contracts(
                existing,
                contract,
                artifact_id=artifact_id,
                context=f"{context} at line {line_number}",
            )
        contracts[artifact_id] = contract
    return contracts


def _source_artifact_contracts(source: str) -> dict[str, ArtifactContract]:
    """Read Artifact directives from comment tokens emitted by the G4 lexer."""

    contracts: dict[str, ArtifactContract] = {}
    for comment_index, comment in enumerate(parse_workflow_comments(source), start=1):
        additions = _artifact_contract_directives(comment, context=f"workflow comment {comment_index}")
        _merge_artifact_contracts(contracts, additions, context="workflow comments")
    return contracts


def _merge_artifact_contracts(
    target: dict[str, ArtifactContract],
    additions: Mapping[str, ArtifactContract],
    *,
    context: str,
) -> None:
    """Merge compatible guidance and fail when declared JSON types disagree."""

    for artifact_id, contract in additions.items():
        existing = target.get(artifact_id)
        if existing is not None:
            contract = _combine_artifact_contracts(
                existing,
                contract,
                artifact_id=artifact_id,
                context=context,
            )
        target[artifact_id] = contract


def _artifact_type_matches(value: object, json_type: JsonArtifactType) -> bool:
    """Apply JSON type semantics without Python's bool/int coercion."""

    match json_type:
        case "null":
            return value is None
        case "boolean":
            return type(value) is bool
        case "integer":
            return type(value) is int
        case "number":
            return type(value) is int or (type(value) is float and math.isfinite(value))
        case "string":
            return isinstance(value, str)
        case "object":
            return isinstance(value, Mapping) and all(isinstance(key, str) for key in value)
        case "array":
            return isinstance(value, list)
    raise AssertionError(f"unhandled Artifact JSON type: {json_type}")


def _json_values_equal(left: object, right: object) -> bool:
    """Compare JSON values without treating booleans as the numbers 0 and 1."""

    if type(left) in {int, float} and type(right) in {int, float}:
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        right_list = cast(list[object], right)
        return len(left) == len(right_list) and all(
            _json_values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right_list, strict=True)
        )
    if isinstance(left, Mapping):
        left_mapping = cast(Mapping[object, object], left)
        right_mapping = cast(Mapping[object, object], right)
        return set(left_mapping) == set(right_mapping) and all(
            _json_values_equal(left_mapping[key], right_mapping[key]) for key in left_mapping
        )
    return left == right


def _validate_artifact_value(
    value: object,
    schema: Mapping[str, object],
    *,
    context: str,
) -> None:
    if not _is_json_value(value):
        raise ValueError(f"{context} must be a finite JSON value")
    json_type = schema.get("type")
    if json_type is not None and not _artifact_type_matches(value, cast(JsonArtifactType, json_type)):
        raise ValueError(f"{context} must be JSON {json_type}, got {type(value).__name__}")

    enum = schema.get("enum")
    if isinstance(enum, list) and not any(_json_values_equal(value, candidate) for candidate in enum):
        raise ValueError(f"{context} must equal one of the declared enum values")
    if "const" in schema and not _json_values_equal(value, schema["const"]):
        raise ValueError(f"{context} must equal the declared const value")

    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        object_value = cast(Mapping[str, object], value)
        minimum = schema.get("minProperties")
        maximum = schema.get("maxProperties")
        if isinstance(minimum, int) and len(object_value) < minimum:
            raise ValueError(f"{context} must contain at least {minimum} properties")
        if isinstance(maximum, int) and len(object_value) > maximum:
            raise ValueError(f"{context} must contain at most {maximum} properties")
        required = schema.get("required")
        if isinstance(required, list):
            missing = [key for key in required if key not in object_value]
            if missing:
                raise ValueError(f"{context} is missing required properties: {missing}")
        properties = schema.get("properties")
        property_schemas = cast(Mapping[str, object], properties) if isinstance(properties, Mapping) else {}
        for key, child_schema in property_schemas.items():
            if key in object_value:
                _validate_artifact_value(
                    object_value[key],
                    cast(Mapping[str, object], child_schema),
                    context=f"{context}.{key}",
                )
        additional = schema.get("additionalProperties", True)
        extras = sorted(set(object_value) - set(property_schemas))
        if additional is False and extras:
            raise ValueError(f"{context} contains undeclared properties: {extras}")
        if isinstance(additional, Mapping):
            for key in extras:
                _validate_artifact_value(
                    object_value[key],
                    cast(Mapping[str, object], additional),
                    context=f"{context}.{key}",
                )

    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ValueError(f"{context} must contain at least {minimum} items")
        if isinstance(maximum, int) and len(value) > maximum:
            raise ValueError(f"{context} must contain at most {maximum} items")
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                _validate_artifact_value(
                    item,
                    cast(Mapping[str, object], items),
                    context=f"{context}[{index}]",
                )

    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ValueError(f"{context} must contain at least {minimum} characters")
        if isinstance(maximum, int) and len(value) > maximum:
            raise ValueError(f"{context} must contain at most {maximum} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise ValueError(f"{context} must match pattern {pattern!r}")

    if _finite_number(value) and type(value) is not bool:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if _finite_number(minimum) and value < minimum:
            raise ValueError(f"{context} must be at least {minimum}")
        if _finite_number(maximum) and value > maximum:
            raise ValueError(f"{context} must be at most {maximum}")


def validate_artifact_values(
    values: Mapping[str, object],
    contracts: Mapping[str, ArtifactContract],
    *,
    context: str,
    program_error_artifact_ids: Collection[str] = (),
) -> None:
    """Validate every present value with its machine-enforced schema."""

    for artifact_id, value in values.items():
        contract = contracts.get(artifact_id)
        if contract is None:
            continue
        if (
            artifact_id in program_error_artifact_ids
            and isinstance(value, dict)
            and set(value) == {_PROGRAM_ERROR_KEY}
            and isinstance(value.get(_PROGRAM_ERROR_KEY), Mapping)
        ):
            continue
        _validate_artifact_value(
            value,
            contract.schema,
            context=f"{context} Artifact {artifact_id!r}",
        )


def _validate_foreach_iteration_values(
    values: Mapping[str, object],
    contracts: Mapping[str, ArtifactContract],
    *,
    context: str,
    program_error_artifact_ids: Collection[str] = (),
) -> None:
    """Validate one foreach contribution against each aggregate's item schema."""

    for artifact_id, value in values.items():
        contract = contracts.get(artifact_id)
        if contract is None:
            continue
        if (
            artifact_id in program_error_artifact_ids
            and isinstance(value, dict)
            and set(value) == {_PROGRAM_ERROR_KEY}
            and isinstance(value.get(_PROGRAM_ERROR_KEY), Mapping)
        ):
            continue
        items = contract.schema.get("items")
        if isinstance(items, Mapping):
            _validate_artifact_value(
                value,
                cast(Mapping[str, object], items),
                context=f"{context} Artifact {artifact_id!r}",
            )


@dataclass(frozen=True, slots=True)
class CompiledAgentConfig:
    """G4 Agent settings before the workspace adds its fixed safety prompt.

    ``system_prompt`` is an optional specialization overlay, never the complete
    system prompt.  This keeps workspace policy out of the language compiler
    while still making every declarative setting available to the runtime.
    """

    name: str
    system_prompt: str | None = None
    model: str | None = None
    engine: str | None = None
    api_base: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None
    tools: tuple[str, ...] = ()
    max_turns: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", tuple(self.tools))

    def to_agent_config(self, base_system_prompt: str) -> AgentConfig:
        """Finalize this overlay against a caller-owned fixed system prompt."""

        if not isinstance(base_system_prompt, str) or not base_system_prompt.strip():
            raise ValueError("base_system_prompt must be a non-empty string")
        system_prompt = base_system_prompt.rstrip()
        if self.system_prompt is not None:
            system_prompt = f"{system_prompt}\n\n# Workflow agent specialization\n{self.system_prompt.strip()}"
        return AgentConfig(
            name=self.name,
            system_prompt=system_prompt,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            engine=self.engine,
            tools=self.tools,
            max_turns=self.max_turns,
            api_base=self.api_base,
            reasoning_effort=self.reasoning_effort,
        )


@dataclass(frozen=True, slots=True)
class CompiledWorkflow:
    """One executable graph plus classifications and non-fatal diagnostics."""

    graph: WorkflowGraph
    executor_kinds: Mapping[str, ExecutorKind]
    program_paths: Mapping[str, str] = field(default_factory=dict)
    agent_configs: Mapping[str, CompiledAgentConfig] = field(default_factory=dict)
    artifact_contracts: Mapping[str, ArtifactContract] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class CompletionContext:
    """Structured runtime contract for an Agent or Human callback."""

    step_id: str
    executor_id: str
    executor_kind: ExecutorKind
    inputs: Mapping[str, object]
    output_ids: tuple[str, ...]
    dispatch: DispatchContext
    agent_config: CompiledAgentConfig | None = None
    input_contracts: Mapping[str, ArtifactContract] = field(default_factory=dict)
    output_contracts: Mapping[str, ArtifactContract] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProgramInvocation:
    """Exact script and artifact contract passed to an injected Program runner."""

    name: str
    argv: tuple[str, ...]
    stdin: str
    cwd: str | PathLike[str] | None
    binding_name: str
    dispatch: DispatchContext
    instruction: str = ""
    inputs: Mapping[str, object] = field(default_factory=dict)
    output_ids: tuple[str, ...] = ()
    input_contracts: Mapping[str, ArtifactContract] = field(default_factory=dict)
    output_contracts: Mapping[str, ArtifactContract] = field(default_factory=dict)


type Completion = Callable[
    [str, CompletionContext],
    Awaitable[object],
]
type HumanInstructionPreparer = Callable[
    [str, CompletionContext],
    Awaitable[str],
]
type HumanRequester = Callable[
    [str, CompletionContext],
    Awaitable[object],
]
type ProgramRunner = Callable[[ProgramInvocation], Awaitable[object]]


_CONCEPT_NAMES = (
    "Agent",
    "ApiBase",
    "Artifact",
    "Bool",
    "ComplexNumber",
    "Engine",
    "Executor",
    "Human",
    "Instruction",
    "Integer",
    "List",
    "Model",
    "Path",
    "Program",
    "ReasoningEffort",
    "Resource",
    "Step",
    "StepName",
    "Tool",
    "Workflow",
)
# This is an explicit catalog, not a source-code name discovery mechanism.
# ``step_executor`` deliberately has no output concept because the minimal
# parser does not model Agent/Human/Program as sub-concepts of Executor.
_OPERATOR_SIGNATURES: Mapping[
    str,
    tuple[tuple[str, ...], str | None],
] = {
    "agent_config": (("Agent", "Model", "Engine", "ApiBase"), "Bool"),
    "agent_system_prompt": (("Agent",), "Instruction"),
    "allowed_tool": (("Agent", "Tool"), "Bool"),
    "comparison_gt_op": ((), None),
    "comparison_gte_op": ((), None),
    "comparison_lt_op": ((), None),
    "comparison_lte_op": ((), None),
    "consumes": (("Step",), "List"),
    "depends_on": (("Step", "Step"), "Bool"),
    "foreach_item": (("Step", "Artifact"), "Artifact"),
    "independent": (("Step",), "Bool"),
    "input_workflow": (("Workflow",), "List"),
    "max_attempts": (("Step",), "Integer"),
    "max_concurrency": (("Workflow",), "Integer"),
    "max_output_tokens": (("Agent",), "Integer"),
    "max_turns": (("Agent",), "Integer"),
    "output_workflow": (("Workflow",), "List"),
    "program_path": (("Program",), "Path"),
    "produces": (("Step",), "List"),
    "reasoning_effort": (("Agent",), "ReasoningEffort"),
    "resource_requirement": (("Step", "Resource"), "Integer"),
    "step_executor": (("Step",), None),
    "step_instruction": (("Step",), "Instruction"),
    "step_name": (("Step",), "StepName"),
    "step_timeout": (("Step",), "Integer"),
    "temperature": (("Agent",), "ComplexNumber"),
    "workflow_timeout": (("Workflow",), "Integer"),
}

_AGENT_OPERATOR_NAMES = frozenset(
    {
        "agent_config",
        "agent_system_prompt",
        "allowed_tool",
        "max_output_tokens",
        "max_turns",
        "reasoning_effort",
        "temperature",
    }
)


def _default_parse_context() -> ParseContext:
    """Build the runner's closed, typed operator catalog."""

    concepts = {name: Concept(name) for name in _CONCEPT_NAMES}
    operators = {
        name: Operator(
            name=name,
            input_concepts=tuple(concepts[concept_name] for concept_name in inputs),
            output_concept=None if output is None else concepts[output],
        )
        for name, (inputs, output) in _OPERATOR_SIGNATURES.items()
    }
    return ParseContext(concepts=concepts, operators=operators)


def _residual_operator_counts(
    assertions: tuple[Assertion, ...],
) -> Counter[str]:
    """Name every unconsumed assertion without dropping ordinary equalities."""

    counts: Counter[str] = Counter()
    for assertion in assertions:
        calls = [term.operator.name for term in (assertion.lhs, assertion.rhs) if isinstance(term, CompoundTerm)]
        counts.update(calls or ("<equality>",))
    return counts


def _typed_constant(
    value: object,
    concept_name: str,
    context: str,
) -> Constant:
    if not isinstance(value, Constant) or not value.symbol:
        raise ValueError(f"{context} must be a non-empty constant")
    concepts = {concept.name for concept in value.belong_concepts}
    if concept_name not in concepts:
        raise ValueError(f"{context} must belong to {concept_name}")
    return value


def _extract_program_paths(
    assertions: tuple[Assertion, ...],
) -> tuple[dict[str, str], tuple[Assertion, ...]]:
    """Consume catalog-owned Program path declarations from graph residuals."""

    program_paths: dict[str, str] = {}
    residual: list[Assertion] = []
    for assertion in assertions:
        candidates = tuple(
            (term, value)
            for term, value in (
                (assertion.lhs, assertion.rhs),
                (assertion.rhs, assertion.lhs),
            )
            if isinstance(term, CompoundTerm) and term.operator.name == "program_path"
        )
        if not candidates:
            residual.append(assertion)
            continue
        if len(candidates) != 1:
            raise ValueError("one equality cannot configure multiple Program paths")

        call, value = candidates[0]
        if len(call.arguments) != 1:
            raise ValueError(f"program_path expects 1 argument, got {len(call.arguments)}")
        executor = _typed_constant(
            call.arguments[0],
            "Program",
            "program_path argument",
        )
        path = _typed_constant(value, "Path", "program_path value")
        if executor.symbol in program_paths:
            raise ValueError(f"duplicate program_path for {executor.symbol!r}")
        program_paths[executor.symbol] = path.symbol

    return program_paths, tuple(residual)


@dataclass(slots=True)
class _AgentConfigDraft:
    """Mutable accumulator used while consuming order-independent assertions."""

    system_prompt: str | None = None
    model: str | None = None
    engine: str | None = None
    api_base: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None
    tools: list[str] = field(default_factory=list)
    max_turns: int | None = None
    declarations: set[str] = field(default_factory=set)


def _agent_owner(call: CompoundTerm, *, arity: int) -> Constant:
    operator_name = call.operator.name
    if len(call.arguments) != arity:
        raise ValueError(f"{operator_name} expects {arity} arguments, got {len(call.arguments)}")
    agent = _typed_constant(
        call.arguments[0],
        "Agent",
        f"{operator_name} owner",
    )
    executor_concepts = {
        concept.name for concept in agent.belong_concepts if concept.name in {"Agent", "Human", "Program"}
    }
    if executor_concepts != {"Agent"}:
        raise ValueError(f"{operator_name} owner must belong to Agent only")
    return agent


def _assert_true(value: object, operator_name: str) -> None:
    predicate = _typed_constant(value, "Bool", f"{operator_name} value")
    if predicate.symbol != "True":
        raise ValueError(f"{operator_name} must be asserted true")


def _positive_integer(value: object, operator_name: str) -> int:
    constant = value if isinstance(value, Constant) else None
    symbol = None if constant is None else constant.symbol
    if symbol is None or not symbol.isascii() or not symbol.isdecimal():
        raise ValueError(f"{operator_name} value must be a positive integer constant")
    try:
        parsed = int(symbol)
    except ValueError as error:
        raise ValueError(f"{operator_name} value must be a positive integer constant") from error
    if parsed < 1:
        raise ValueError(f"{operator_name} value must be a positive integer constant")
    return parsed


def _finite_temperature(value: object) -> float:
    constant = value if isinstance(value, Constant) else None
    if constant is None or "ComplexNumber" not in {concept.name for concept in constant.belong_concepts}:
        raise ValueError("temperature value must be a finite numeric constant")
    try:
        parsed = float(constant.symbol)
    except ValueError as error:
        raise ValueError("temperature value must be a finite numeric constant") from error
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("temperature value must be a finite non-negative numeric constant")
    return parsed


def _extract_agent_configs(
    assertions: tuple[Assertion, ...],
) -> tuple[dict[str, CompiledAgentConfig], tuple[Assertion, ...]]:
    """Consume every operator in the closed G4 Agent configuration vocabulary."""

    drafts: dict[str, _AgentConfigDraft] = {}
    residual: list[Assertion] = []
    for assertion in assertions:
        candidates = tuple(
            (term, value)
            for term, value in (
                (assertion.lhs, assertion.rhs),
                (assertion.rhs, assertion.lhs),
            )
            if isinstance(term, CompoundTerm) and term.operator.name in _AGENT_OPERATOR_NAMES
        )
        if not candidates:
            residual.append(assertion)
            continue
        if len(candidates) != 1:
            raise ValueError("one equality cannot configure multiple Agent settings")

        call, value = candidates[0]
        operator_name = call.operator.name
        expected_arity = 4 if operator_name == "agent_config" else 2 if operator_name == "allowed_tool" else 1
        agent = _agent_owner(call, arity=expected_arity)
        draft = drafts.setdefault(agent.symbol, _AgentConfigDraft())

        if operator_name == "allowed_tool":
            _assert_true(value, operator_name)
            tool = _typed_constant(
                call.arguments[1],
                "Tool",
                "allowed_tool tool",
            )
            if tool.symbol in draft.tools:
                raise ValueError(f"duplicate allowed_tool {tool.symbol!r} for {agent.symbol!r}")
            draft.tools.append(tool.symbol)
            continue

        if operator_name in draft.declarations:
            raise ValueError(f"duplicate {operator_name} for {agent.symbol!r}")
        draft.declarations.add(operator_name)

        if operator_name == "agent_config":
            _assert_true(value, operator_name)
            draft.model = _typed_constant(
                call.arguments[1],
                "Model",
                "agent_config model",
            ).symbol
            draft.engine = _typed_constant(
                call.arguments[2],
                "Engine",
                "agent_config engine",
            ).symbol
            draft.api_base = _typed_constant(
                call.arguments[3],
                "ApiBase",
                "agent_config API base",
            ).symbol
        elif operator_name == "agent_system_prompt":
            prompt = _typed_constant(
                value,
                "Instruction",
                "agent_system_prompt value",
            ).symbol
            if not prompt.strip():
                raise ValueError("agent_system_prompt value must not be blank")
            draft.system_prompt = prompt
        elif operator_name == "max_output_tokens":
            draft.max_tokens = _positive_integer(value, operator_name)
        elif operator_name == "temperature":
            draft.temperature = _finite_temperature(value)
        elif operator_name == "reasoning_effort":
            draft.reasoning_effort = _typed_constant(
                value,
                "ReasoningEffort",
                "reasoning_effort value",
            ).symbol
        elif operator_name == "max_turns":
            draft.max_turns = _positive_integer(value, operator_name)
        else:
            raise AssertionError(f"unhandled Agent operator {operator_name!r}")

    configs = {
        name: CompiledAgentConfig(
            name=name,
            system_prompt=draft.system_prompt,
            model=draft.model,
            engine=draft.engine,
            api_base=draft.api_base,
            max_tokens=draft.max_tokens,
            temperature=draft.temperature,
            reasoning_effort=draft.reasoning_effort,
            tools=tuple(draft.tools),
            max_turns=draft.max_turns,
        )
        for name, draft in drafts.items()
    }
    return configs, tuple(residual)


def compile_workflow(
    source: str,
    *,
    context: ParseContext | None = None,
    diagnostic_callback: Callable[[Diagnostic], None] | None = None,
) -> CompiledWorkflow:
    """Parse and compile one strictly typed workflow through a closed catalog.

    ``diagnostic_callback`` receives non-fatal warning diagnostics before this
    function returns or raises. Fatal diagnostics are reported through
    ``ValueError``. Successful results also retain their warnings.
    """

    parsed = parse_workflow(
        source,
        context=context if context is not None else _default_parse_context(),
    )
    if parsed.core_ir is None:
        details = "; ".join(
            (
                diagnostic.message
                if diagnostic.span is None
                else (f"{diagnostic.span.start.line}:{diagnostic.span.start.column}: {diagnostic.message}")
            )
            for diagnostic in parsed.diagnostics
        )
        raise ValueError(f"workflow parse failed: {details}")

    try:
        compiled = WorkflowGraphCompiler().compile(parsed.core_ir)
    except (TypeError, ValueError) as error:
        core_ir_diagnostics = collect_core_ir_diagnostics(parsed.core_ir)
        if diagnostic_callback is not None:
            for diagnostic in core_ir_diagnostics:
                if diagnostic.severity == "warning":
                    diagnostic_callback(diagnostic)
        error_messages = [diagnostic.message for diagnostic in core_ir_diagnostics if diagnostic.severity == "error"]
        error_messages.append(str(error))
        unique_error_messages = tuple(dict.fromkeys(error_messages))
        raise ValueError(f"workflow check failed: {'; '.join(unique_error_messages)}") from error
    if not isinstance(compiled, tuple):
        raise TypeError("workflow graph compiler returned an unexpected result")
    compilations = cast(tuple[WorkflowGraphCompilation, ...], compiled)

    checked = check_workflow(
        parsed.core_ir,
        graph_compilations=compilations,
        consumed_residual_operators=_AGENT_OPERATOR_NAMES,
    )
    check_errors = [diagnostic.message for diagnostic in checked.diagnostics if diagnostic.severity == "error"]
    check_warnings = tuple(diagnostic for diagnostic in checked.diagnostics if diagnostic.severity == "warning")
    # Warnings must escape before any fatal checker or strict-runner error:
    # a failed compilation has no CompiledWorkflow result to carry them.
    if diagnostic_callback is not None:
        for diagnostic in check_warnings:
            diagnostic_callback(diagnostic)
    if check_errors:
        raise ValueError(f"workflow check failed: {'; '.join(check_errors)}")

    if len(compilations) != 1:
        raise ValueError("workflow runner expects exactly one workflow")
    compilation = compilations[0]
    program_paths, residual_assertions = _extract_program_paths(compilation.residual_assertions)
    configured_agents, residual_assertions = _extract_agent_configs(residual_assertions)
    if residual_assertions:
        counts = _residual_operator_counts(residual_assertions)
        details = ", ".join(f"{operator_name}={count}" for operator_name, count in sorted(counts.items()))
        raise ValueError(f"workflow contains unconsumed assertions: {details}")

    constants_by_symbol = {constant.symbol: constant for constant in parsed.core_ir.constants}
    executor_kinds: dict[str, ExecutorKind] = {}
    for step in compilation.graph.steps:
        executor = constants_by_symbol.get(step.executor_id)
        matches = (
            set()
            if executor is None
            else {concept.name for concept in executor.belong_concepts if concept.name in {"Agent", "Human", "Program"}}
        )
        if len(matches) != 1:
            raise ValueError(
                f"executor {step.executor_id!r} for step {step.step_id!r} "
                "must be declared as exactly one of Agent, Human, or Program"
            )
        executor_kinds[step.executor_id] = cast(ExecutorKind, matches.pop())
        if executor_kinds[step.executor_id] == "Program" and step.executor_id not in program_paths:
            raise ValueError(f"Program executor {step.executor_id!r} has no program_path")

    used_agent_executors = {
        executor_id for executor_id, executor_kind in executor_kinds.items() if executor_kind == "Agent"
    }
    unused_configured_agents = sorted(configured_agents.keys() - used_agent_executors)
    if unused_configured_agents:
        raise ValueError(
            "every configured Agent must execute at least one Step; "
            f"unused configured Agents: {unused_configured_agents}"
        )

    agent_configs = dict(configured_agents)
    for executor_id, executor_kind in executor_kinds.items():
        if executor_kind == "Agent":
            agent_configs.setdefault(
                executor_id,
                CompiledAgentConfig(name=executor_id),
            )

    artifact_contracts = _source_artifact_contracts(source)
    declared_artifact_ids = {artifact.artifact_id for artifact in compilation.graph.artifacts}
    unknown_contracts = sorted(artifact_contracts.keys() - declared_artifact_ids)
    if unknown_contracts:
        raise ValueError(f"workflow comments declare contracts for unknown Artifacts: {unknown_contracts}")

    return CompiledWorkflow(
        graph=compilation.graph,
        executor_kinds=executor_kinds,
        program_paths=program_paths,
        agent_configs=agent_configs,
        artifact_contracts=artifact_contracts,
        diagnostics=check_warnings,
    )


def _normalize_outputs(
    step_id: str,
    output_ids: tuple[str, ...],
    result: object,
    *,
    named_mapping_required: bool,
) -> dict[str, object]:
    """Normalize scalar single outputs while keeping N-output calls explicit."""

    if not output_ids:
        if result is None or (isinstance(result, Mapping) and not result):
            return {}
        raise ValueError(f"step {step_id!r} produces no artifacts")

    if len(output_ids) == 1 and not named_mapping_required:
        return {output_ids[0]: result}

    if not isinstance(result, Mapping) or not all(isinstance(artifact_id, str) for artifact_id in result):
        raise ValueError(f"step {step_id!r} must return a mapping keyed by artifact ID")
    outputs = dict(result)
    expected_outputs = set(output_ids)
    actual_outputs = set(outputs)
    if actual_outputs != expected_outputs:
        raise ValueError(
            f"outputs for {step_id!r} must match exactly: "
            f"expected {sorted(expected_outputs)}, got {sorted(actual_outputs)}"
        )
    return outputs


def _contract_subset(
    artifact_ids: Collection[str],
    contracts: Mapping[str, ArtifactContract],
) -> dict[str, ArtifactContract]:
    """Select declared contracts in stable Artifact-ID order."""

    return {artifact_id: contracts[artifact_id] for artifact_id in sorted(artifact_ids) if artifact_id in contracts}


def _program_output_ids(compiled: CompiledWorkflow) -> set[str]:
    steps_by_id = {step.step_id: step for step in compiled.graph.steps}
    return {
        edge.artifact_id
        for edge in compiled.graph.edges
        if (
            isinstance(edge, ProducesEdge)
            and compiled.executor_kinds[steps_by_id[edge.step_id].executor_id] == "Program"
        )
    }


def _contracts_text(label: str, contracts: Mapping[str, ArtifactContract]) -> str:
    if not contracts:
        return f"{label}: none declared."
    payload = {artifact_id: contract.to_dict() for artifact_id, contract in contracts.items()}
    return f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"


def _output_contract(
    output_ids: tuple[str, ...],
    contracts: Mapping[str, ArtifactContract] | None = None,
    *,
    foreach_iteration: bool = False,
) -> str:
    if not output_ids:
        return "Return no artifact value for this step."
    declared_contracts = {} if contracts is None else contracts
    parts: list[str] = []
    if len(output_ids) == 1:
        parts.append(f"Return the value for output artifact {output_ids[0]!r}.")
    else:
        parts.append(
            "Return a mapping keyed exactly by these output artifact IDs: "
            f"{json.dumps(output_ids, ensure_ascii=False)}."
        )
    parts.append(_contracts_text("Output Artifact contracts", declared_contracts))
    if foreach_iteration:
        parts.append(
            "This is one foreach iteration. Return one element for each output Artifact; "
            "the runtime collects those elements into the aggregate Artifact described above."
        )
    return "\n".join(parts)


async def _build_program_paths(
    compiled: CompiledWorkflow,
    resolve_path: PathResolver | None,
) -> dict[str, str]:
    """Resolve only catalog identities; explicit absolute and ``./`` paths pass through."""

    paths: dict[str, str] = {}
    program_ids = {
        step.executor_id for step in compiled.graph.steps if compiled.executor_kinds[step.executor_id] == "Program"
    }
    for program_id in sorted(program_ids):
        path_reference = compiled.program_paths[program_id]
        if isabs(path_reference) or path_reference.startswith("./"):
            executable_path = path_reference
        else:
            if resolve_path is None:
                raise ValueError(f"Program executor {program_id!r} has a path identity but no path resolver")
            executable_path = await resolve_path(path_reference)
            if not isinstance(executable_path, str) or not executable_path.strip():
                raise ValueError(f"program_path for {program_id!r} resolved to no path")
        paths[program_id] = executable_path
    return paths


async def _materialize_instructions(
    compiled: CompiledWorkflow,
    resolve_instruction: InstructionResolver | None,
) -> tuple[dict[str, str], dict[str, ArtifactContract]]:
    """Resolve every instruction path before the execution plan can dispatch."""

    resolved_references: dict[str, str] = {}
    instructions: dict[str, str] = {}
    contracts = dict(compiled.artifact_contracts)
    inputs_by_step: dict[str, set[str]] = {step.step_id: set() for step in compiled.graph.steps}
    outputs_by_step: dict[str, set[str]] = {step.step_id: set() for step in compiled.graph.steps}
    for edge in compiled.graph.edges:
        if isinstance(edge, ConsumesEdge):
            inputs_by_step[edge.step_id].add(edge.artifact_id)
        elif isinstance(edge, ForeachEdge):
            inputs_by_step[edge.step_id].update((edge.artifact_id, edge.item_binding_id))
        elif isinstance(edge, ProducesEdge):
            outputs_by_step[edge.step_id].add(edge.artifact_id)
    for step in sorted(compiled.graph.steps, key=lambda item: item.step_id):
        reference = step.instruction_id
        if reference is None:
            raise ValueError(f"step {step.step_id!r} has no step_instruction")
        if reference.startswith("./"):
            if resolve_instruction is None:
                raise ValueError(f"step {step.step_id!r} has an instruction path but no instruction resolver")
            if reference not in resolved_references:
                resolved_references[reference] = await resolve_instruction(reference)
            instruction = resolved_references[reference]
        else:
            instruction = reference
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError(f"step {step.step_id!r} instruction resolved to no text")
        instructions[step.step_id] = instruction
        instruction_contracts = _artifact_contract_directives(
            instruction,
            context=f"step_instruction for {step.step_id!r}",
        )
        related_artifact_ids = inputs_by_step[step.step_id] | outputs_by_step[step.step_id]
        unrelated_contracts = sorted(instruction_contracts.keys() - related_artifact_ids)
        if unrelated_contracts:
            raise ValueError(
                f"step_instruction for {step.step_id!r} declares contracts for unrelated "
                f"Artifacts: {unrelated_contracts}"
            )
        _merge_artifact_contracts(
            contracts,
            instruction_contracts,
            context=f"step_instruction for {step.step_id!r}",
        )
    return instructions, contracts


def _normalize_program_stdout(
    step_id: str,
    output_ids: tuple[str, ...],
    stdout: str,
    output_contracts: Mapping[str, ArtifactContract] | None = None,
) -> dict[str, object]:
    """Normalize Program stdout, parsing JSON when its contract requires it."""

    def reject_non_finite_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON constant {value!r}")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key {key!r}")
            result[key] = value
        return result

    def strict_json_value() -> object:
        result = json.loads(
            stdout,
            parse_constant=reject_non_finite_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
        # ``json.loads("1e400")`` produces infinity without invoking
        # ``parse_constant``. Re-encoding validates every nested number.
        json.dumps(result, allow_nan=False)
        return result

    if len(output_ids) <= 1:
        result: object = stdout if output_ids or stdout else None
        if output_ids:
            contracts = {} if output_contracts is None else output_contracts
            contract = contracts.get(output_ids[0])
            if contract is not None and contract.json_type not in (None, "string"):
                try:
                    result = strict_json_value()
                except (json.JSONDecodeError, OverflowError, ValueError) as error:
                    raise ValueError(
                        f"Program step {step_id!r} must write one strict JSON {contract.json_type} value"
                    ) from error
        return _normalize_outputs(
            step_id,
            output_ids,
            result,
            named_mapping_required=False,
        )

    try:
        result = strict_json_value()
    except (json.JSONDecodeError, OverflowError, ValueError) as error:
        raise ValueError(f"Program step {step_id!r} must write a strict JSON object keyed by artifact ID") from error
    return _normalize_outputs(
        step_id,
        output_ids,
        result,
        named_mapping_required=True,
    )


def _build_dispatch(
    compiled: CompiledWorkflow,
    *,
    instructions: Mapping[str, str],
    program_paths: Mapping[str, str],
    work_dir: str | PathLike[str] | None,
    complete: Completion | None,
    run_program: ProgramRunner | None,
    prepare_human_instruction: HumanInstructionPreparer | None,
    request_human: HumanRequester | None,
) -> StepDispatcher:
    graph = compiled.graph
    foreach_step_ids = {edge.step_id for edge in graph.edges if isinstance(edge, ForeachEdge)}
    program_output_ids = _program_output_ids(compiled)
    outputs_by_step: dict[str, list[str]] = {step.step_id: [] for step in graph.steps}
    for edge in graph.edges:
        if isinstance(edge, ProducesEdge):
            outputs_by_step[edge.step_id].append(edge.artifact_id)

    async def dispatch(
        step: StepNode,
        inputs: Mapping[str, object],
        dispatch_context: DispatchContext,
    ) -> Mapping[str, object]:
        output_ids = tuple(sorted(outputs_by_step[step.step_id]))
        foreach_iteration = step.step_id in foreach_step_ids
        input_contracts = _contract_subset(inputs, compiled.artifact_contracts)
        output_contracts = _contract_subset(output_ids, compiled.artifact_contracts)
        validate_artifact_values(
            inputs,
            input_contracts,
            context=f"inputs for step {step.step_id!r}",
            program_error_artifact_ids=program_output_ids,
        )
        output_contract = _output_contract(
            output_ids,
            output_contracts,
            foreach_iteration=foreach_iteration,
        )
        instruction = instructions[step.step_id]
        executor_kind = compiled.executor_kinds[step.executor_id]
        completion_context = CompletionContext(
            step_id=step.step_id,
            executor_id=step.executor_id,
            executor_kind=executor_kind,
            inputs=dict(inputs),
            output_ids=output_ids,
            dispatch=dispatch_context,
            agent_config=(compiled.agent_configs[step.executor_id] if executor_kind == "Agent" else None),
            input_contracts=input_contracts,
            output_contracts=output_contracts,
        )

        def normalize_and_validate(
            result: object,
            *,
            named_mapping_required: bool,
            allow_program_errors: bool = False,
        ) -> dict[str, object]:
            outputs = _normalize_outputs(
                step.step_id,
                output_ids,
                result,
                named_mapping_required=named_mapping_required,
            )
            if foreach_iteration:
                _validate_foreach_iteration_values(
                    outputs,
                    output_contracts,
                    context=f"outputs for foreach step {step.step_id!r}",
                    program_error_artifact_ids=(output_ids if allow_program_errors else ()),
                )
            else:
                validate_artifact_values(
                    outputs,
                    output_contracts,
                    context=f"outputs for step {step.step_id!r}",
                    program_error_artifact_ids=(output_ids if allow_program_errors else ()),
                )
            return outputs

        if executor_kind == "Human":
            if prepare_human_instruction is None or request_human is None:
                raise ValueError(
                    f"step {step.step_id!r} requires prepare_human_instruction and request_human callbacks"
                )
            preparation_prompt = (
                "Prepare this workflow step for a human.\n"
                f"Step: {step.step_id}\n"
                f"Instruction:\n{instruction}\n\n"
                f"Inputs: "
                f"{json.dumps(dict(inputs), ensure_ascii=False, sort_keys=True, default=str)}\n"
                f"{_contracts_text('Input Artifact contracts', input_contracts)}\n"
                f"Output contract:\n{output_contract}\n"
                "Produce concise, readable guidance. Use available tools only when "
                "needed to inspect supporting resources named by the inputs. Do not ask the human "
                "directly, change resources, or invent inaccessible contents."
            )
            prepared_instruction = await prepare_human_instruction(
                preparation_prompt,
                completion_context,
            )
            if not prepared_instruction.strip():
                raise ValueError(f"step {step.step_id!r} human instruction preparation returned no text")
            human_result = await request_human(
                prepared_instruction,
                completion_context,
            )
            return normalize_and_validate(
                human_result,
                named_mapping_required=False,
            )

        if executor_kind == "Program":
            try:
                payload = json.dumps(
                    {
                        "instruction": instruction,
                        "inputs": dict(inputs),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
            except (TypeError, ValueError) as error:
                raise ValueError(f"Program step {step.step_id!r} inputs must be finite JSON values") from error
            if run_program is None:
                raise AssertionError("Program runner preflight did not select a runner")
            program_result = await run_program(
                ProgramInvocation(
                    name=step.executor_id,
                    argv=(program_paths[step.executor_id],),
                    stdin=f"{payload}\n",
                    cwd=work_dir,
                    binding_name=step.step_id,
                    dispatch=dispatch_context,
                    instruction=instruction,
                    inputs=dict(inputs),
                    output_ids=output_ids,
                    input_contracts=input_contracts,
                    output_contracts=output_contracts,
                )
            )
            if isinstance(program_result, str):
                outputs = _normalize_program_stdout(
                    step.step_id,
                    output_ids,
                    program_result,
                    output_contracts,
                )
                if foreach_iteration:
                    _validate_foreach_iteration_values(
                        outputs,
                        output_contracts,
                        context=f"outputs for foreach step {step.step_id!r}",
                        program_error_artifact_ids=output_ids,
                    )
                else:
                    validate_artifact_values(
                        outputs,
                        output_contracts,
                        context=f"outputs for step {step.step_id!r}",
                        program_error_artifact_ids=output_ids,
                    )
                return outputs
            return normalize_and_validate(
                program_result,
                named_mapping_required=True,
                allow_program_errors=True,
            )

        prompt = (
            f"Instruction:\n{instruction}\n\n"
            f"Inputs: "
            f"{json.dumps(dict(inputs), ensure_ascii=False, sort_keys=True, default=str)}\n"
            f"{_contracts_text('Input Artifact contracts', input_contracts)}\n"
            f"{output_contract}"
        )
        if complete is None:
            raise AssertionError("completion preflight did not select a completion")
        result = await complete(
            prompt,
            completion_context,
        )
        return normalize_and_validate(
            result,
            named_mapping_required=True,
        )

    return dispatch


async def execute_workflow(
    source: str,
    *,
    inputs: Mapping[str, object],
    complete: Completion | None = None,
    resource_capacities: Mapping[str, ResourceCapacity] | None = None,
    allocator: ResourceAllocator | None = None,
    parse_context: ParseContext | None = None,
    supported_executor_kinds: Collection[ExecutorKind] | None = None,
    resolve_path: PathResolver | None = None,
    resolve_instruction: InstructionResolver | None = None,
    work_dir: str | PathLike[str] | None = None,
    run_program: ProgramRunner | None = None,
    prepare_human_instruction: HumanInstructionPreparer | None = None,
    request_human: HumanRequester | None = None,
    checkpoint: ExecutionCheckpoint | None = None,
    checkpoint_observer: CheckpointObserver | None = None,
    timing_recorder: Callable[[StepTiming], None] | None = None,
) -> dict[str, object]:
    """Execute one checked workflow with explicit dispatcher/runtime injection."""

    if (prepare_human_instruction is None) != (request_human is None):
        raise ValueError("provide prepare_human_instruction and request_human together")
    workflow_inputs: Mapping[str, object] = dict(inputs)

    compiled = compile_workflow(
        source,
        context=parse_context,
    )
    if supported_executor_kinds is not None:
        supported = frozenset(supported_executor_kinds)
        unsupported = sorted(
            (
                step.step_id,
                compiled.executor_kinds[step.executor_id],
            )
            for step in compiled.graph.steps
            if compiled.executor_kinds[step.executor_id] not in supported
        )
        if unsupported:
            details = ", ".join(f"{step_id}={kind}" for step_id, kind in unsupported)
            raise ValueError(f"workflow contains unsupported executors: {details}")

    graph = compiled.graph
    foreach_step_ids = {edge.step_id for edge in graph.edges if isinstance(edge, ForeachEdge)}
    human_foreach_steps = sorted(
        step.step_id
        for step in graph.steps
        if (step.step_id in foreach_step_ids and compiled.executor_kinds[step.executor_id] == "Human")
    )
    if human_foreach_steps:
        raise ValueError(
            "Human executors are not supported for foreach steps because "
            "resumable requests have no iteration identity: "
            f"{human_foreach_steps}"
        )
    if any(compiled.executor_kinds[step.executor_id] == "Agent" for step in graph.steps) and complete is None:
        raise ValueError("Agent workflow requires a complete callback")
    instructions, artifact_contracts = await _materialize_instructions(compiled, resolve_instruction)
    compiled = CompiledWorkflow(
        graph=compiled.graph,
        executor_kinds=compiled.executor_kinds,
        program_paths=compiled.program_paths,
        agent_configs=compiled.agent_configs,
        artifact_contracts=artifact_contracts,
        diagnostics=compiled.diagnostics,
    )
    validate_artifact_values(
        workflow_inputs,
        artifact_contracts,
        context="workflow inputs",
    )
    program_paths = await _build_program_paths(compiled, resolve_path)
    if work_dir is None and any(not isabs(path) for path in program_paths.values()):
        raise ValueError("relative program_path requires an explicit work_dir")
    if program_paths and run_program is None:
        raise ValueError("Program workflow requires an injected run_program callback")
    plan = generate_plan(graph)
    dispatch = _build_dispatch(
        compiled,
        instructions=instructions,
        program_paths=program_paths,
        work_dir=work_dir,
        complete=complete,
        run_program=run_program,
        prepare_human_instruction=prepare_human_instruction,
        request_human=request_human,
    )
    timing_metadata = (
        None
        if timing_recorder is None
        else {
            step.step_id: StepTimingMetadata(
                step_name=step.name_id,
                executor_id=step.executor_id,
                executor_kind=cast(Literal["Agent", "Program"], compiled.executor_kinds[step.executor_id]),
            )
            for step in graph.steps
            if compiled.executor_kinds[step.executor_id] != "Human"
        }
    )

    outputs = await execute_plan(
        plan,
        graph,
        inputs=workflow_inputs,
        dispatch=dispatch,
        resource_capacities=resource_capacities,
        allocator=allocator,
        checkpoint=checkpoint,
        checkpoint_observer=checkpoint_observer,
        timing_recorder=timing_recorder,
        timing_metadata=timing_metadata,
    )
    validate_artifact_values(
        outputs,
        artifact_contracts,
        context="workflow outputs",
        program_error_artifact_ids=_program_output_ids(compiled),
    )
    return outputs
