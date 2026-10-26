"""Typed domain models for parsed Python source code.

This is the parser's entire output contract — see ARCHITECTURE.md
"Tree-sitter parsing flow" and AGENTS.md rule 9. Nothing here imports from
app.graph, app.persistence, app.core.database, or any HTTP-facing schema;
a future graph-construction stage consumes these models, but they carry no
Neo4j- or database-specific concepts (no driver types, no ORM columns).

All models are immutable (frozen dataclasses): a ParsedFile is a snapshot
produced once by a single parse call, not a mutable working structure.

Design notes on a few genuinely ambiguous field semantics (documented here
rather than guessed silently):

- ``SourceLocation`` line numbers are 1-based (required). Columns are
  0-based byte offsets within their line, matching Tree-sitter's native
  ``Point`` — the task only mandated 1-based *lines*.
- ``ParsedParameter.position`` is a 0-based index into the parameter list
  as written (including ``self``/``cls`` — they are not special-cased).
- ``ParsedImport`` groups one record per *statement clause*: a plain
  ``import a, b`` yields two records (one per module); a
  ``from X import a, b, c`` yields one record with ``imported_names``
  holding the locally-bound names (post-alias). ``alias`` is populated for
  the single-target case (``import x as y`` / ``from m import x as y``)
  and left ``None`` when a single ``from`` clause imports multiple names
  with per-name aliases — that per-name alias mapping isn't modeled in
  this phase, since cross-file/alias resolution is an explicit non-goal
  here (see the parsing task's "Non-goals").
- Nested functions (a ``def`` inside another ``def``, at any depth,
  including inside a method) are flattened into ``ParsedFile.functions``
  alongside top-level functions, distinguished only by their dotted
  ``qualified_name`` (e.g. ``app.auth.service.login.validate_password``) —
  there is no ``nested_functions`` field on ``ParsedFunction``, only a
  ``complexity_signals.nested_function_count``. Methods (a ``def`` directly
  inside a ``class`` body) are the one exception: they live only in
  ``ParsedClass.methods``, never in ``ParsedFile.functions``.
- Calls and complexity signals are only tracked for expressions that occur
  inside some function/method body. Module-level and class-body-level
  (outside any method) statements have nowhere to record calls in this
  schema and are not tracked — this mirrors ``ParsedFile`` having no
  top-level ``calls`` field.
"""

from dataclasses import dataclass, field

from app.domain.code_symbols.enums import CallType, ParameterKind, ParseErrorType


@dataclass(frozen=True)
class SourceLocation:
    file_path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class ParsedParameter:
    id: str
    name: str
    annotation: str | None
    default_value: str | None
    kind: ParameterKind
    position: int
    location: SourceLocation


@dataclass(frozen=True)
class ParsedImport:
    id: str
    module: str | None
    imported_names: list[str]
    alias: str | None
    is_from_import: bool
    relative_level: int
    location: SourceLocation


@dataclass(frozen=True)
class ParsedCall:
    id: str
    caller_qualified_name: str
    called_expression: str
    probable_target_name: str | None
    call_type: CallType
    argument_count: int
    location: SourceLocation


@dataclass(frozen=True)
class ComplexitySignals:
    """Deterministic raw counts — no derived risk score (see task Non-goals)."""

    branch_count: int = 0
    loop_count: int = 0
    exception_handler_count: int = 0
    return_count: int = 0
    await_count: int = 0
    nested_function_count: int = 0


@dataclass(frozen=True)
class ParsedRouteInfo:
    """Best-effort literal route metadata extracted from a decorator call.

    Populated only when the decorator's shape matches a recognized
    "web-framework-ish" pattern (``@x.get(...)``, ``@x.post(...)``, ...,
    or ``@x.route(...)``) — see the python parser's ``queries.py``. This is
    not coupled to any specific framework's import; it's a syntactic
    pattern match, and never used to create graph nodes at this stage.
    """

    http_method: str | None
    path: str | None


@dataclass(frozen=True)
class ParsedDecorator:
    raw_expression: str
    route_info: ParsedRouteInfo | None


@dataclass(frozen=True)
class ParsedAssignment:
    """A simple module- or class-level assignment target.

    Only plain-identifier targets are captured (``x = 1``, ``x: int = 1``,
    ``x: int``) — tuple/list-unpacking or attribute/subscript targets are
    not simple assignment targets and are skipped, per the task's
    "Class attributes should capture simple assignment targets" rule,
    applied consistently to module-level attributes too.
    """

    name: str
    annotation: str | None
    value: str | None
    location: SourceLocation


@dataclass(frozen=True)
class ParsedFunction:
    id: str
    name: str
    qualified_name: str
    signature: str
    async_function: bool
    decorators: list[ParsedDecorator]
    parameters: list[ParsedParameter]
    return_annotation: str | None
    docstring: str | None
    source_code: str
    location: SourceLocation
    calls: list[ParsedCall]
    parent_class: str | None
    complexity_signals: ComplexitySignals


@dataclass(frozen=True)
class ParsedClass:
    id: str
    name: str
    qualified_name: str
    base_classes: list[str]
    decorators: list[ParsedDecorator]
    docstring: str | None
    source_code: str
    location: SourceLocation
    methods: list[ParsedFunction] = field(default_factory=list)
    nested_classes: list["ParsedClass"] = field(default_factory=list)
    class_attributes: list[ParsedAssignment] = field(default_factory=list)


@dataclass(frozen=True)
class ParseError:
    error_type: ParseErrorType
    message: str
    file_path: str
    location: SourceLocation | None
    recoverable: bool


@dataclass(frozen=True)
class ParsedFile:
    id: str
    repository_id: str
    file_path: str
    module_name: str
    language: str
    content_hash: str
    imports: list[ParsedImport] = field(default_factory=list)
    functions: list[ParsedFunction] = field(default_factory=list)
    classes: list[ParsedClass] = field(default_factory=list)
    module_docstring: str | None = None
    module_attributes: list[ParsedAssignment] = field(default_factory=list)
    parse_errors: list[ParseError] = field(default_factory=list)
    parser_version: str = "0"
