"""Conservative, deterministic resolution of calls, inheritance, and
imports to internal graph symbols.

Pure logic over already-parsed data (app.domain.code_symbols) — never
touches Neo4j (that's graph_builder.py's job) and never claims a
certainty it doesn't have (see CallResolutionConfidence). Resolution
order follows the task's suggested rules exactly:

  1. Exact qualified-name match
  2. Same-module symbol match
  3. Imported-symbol match
  4. `self.method()` within the same class
  5. `cls.method()` within the same class
  6. Unique repository-wide symbol match
  7. Otherwise unresolved

Only EXACT and the documented PROBABLE cases ever produce an internal
CALLS/EXTENDS edge (see graph_builder.py) — a short-name match that is
ambiguous (multiple candidates) is left unresolved rather than guessed.

Known Python limitations this resolver does not attempt to see through:
monkey-patching, runtime (lazy/conditional) imports resolved differently
than statically written, decorator replacement of the underlying function,
dependency injection, reflection/``getattr``-based dispatch, import
aliasing beyond one hop, wildcard (``import *``) name resolution, and
polymorphic dispatch (a call through a base-class-typed reference that
resolves to a subclass override at runtime). All of these fall through to
``CallResolutionConfidence.UNRESOLVED`` — see AGENTS.md rule 12 ("Dynamic
Python behavior must be represented as uncertain when it cannot be
resolved deterministically").
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from app.domain.code_symbols.enums import CallType
from app.domain.code_symbols.models import (
    ParsedCall,
    ParsedClass,
    ParsedFile,
    ParsedFunction,
    ParsedImport,
)
from app.domain.graph.enums import CallResolutionConfidence, CallResolutionStrategy, NodeLabel


@dataclass(frozen=True)
class SymbolRef:
    """A minimal pointer into the graph, enough to target a relationship."""

    node_id: str
    label: NodeLabel
    qualified_name: str
    module_name: str
    file_path: str


@dataclass(frozen=True)
class CallResolution:
    call: ParsedCall
    target: SymbolRef | None
    confidence: CallResolutionConfidence
    strategy: CallResolutionStrategy


@dataclass
class RepositoryIndex:
    """In-memory index over every symbol in a repository's parsed files,
    built once per analysis run and reused for every call/inheritance
    resolution (see build_repository_index)."""

    by_qualified_name: dict[str, SymbolRef] = field(default_factory=dict)
    by_module_short_name: dict[tuple[str, str], list[SymbolRef]] = field(default_factory=dict)
    by_short_name: dict[str, list[SymbolRef]] = field(default_factory=dict)
    by_class_method_name: dict[tuple[str, str], SymbolRef] = field(default_factory=dict)
    known_modules: set[str] = field(default_factory=set)


def build_repository_index(parsed_files: list[ParsedFile]) -> RepositoryIndex:
    index = RepositoryIndex()
    for parsed_file in parsed_files:
        index.known_modules.add(parsed_file.module_name)
        for function in parsed_file.functions:
            _index_function(index, function, parsed_file)
        for cls in parsed_file.classes:
            _index_class(index, cls, parsed_file)
    return index


def _short_name(qualified_name: str) -> str:
    return qualified_name.rsplit(".", 1)[-1]


def _add_ref(index: RepositoryIndex, ref: SymbolRef) -> None:
    index.by_qualified_name[ref.qualified_name] = ref
    short_name = _short_name(ref.qualified_name)
    index.by_module_short_name.setdefault((ref.module_name, short_name), []).append(ref)
    index.by_short_name.setdefault(short_name, []).append(ref)


def _index_function(
    index: RepositoryIndex, function: ParsedFunction, parsed_file: ParsedFile
) -> None:
    _add_ref(
        index,
        SymbolRef(
            node_id=function.id,
            label=NodeLabel.FUNCTION,
            qualified_name=function.qualified_name,
            module_name=parsed_file.module_name,
            file_path=parsed_file.file_path,
        ),
    )


def _index_class(index: RepositoryIndex, cls: ParsedClass, parsed_file: ParsedFile) -> None:
    _add_ref(
        index,
        SymbolRef(
            node_id=cls.id,
            label=NodeLabel.CLASS,
            qualified_name=cls.qualified_name,
            module_name=parsed_file.module_name,
            file_path=parsed_file.file_path,
        ),
    )
    for method in cls.methods:
        method_ref = SymbolRef(
            node_id=method.id,
            label=NodeLabel.METHOD,
            qualified_name=method.qualified_name,
            module_name=parsed_file.module_name,
            file_path=parsed_file.file_path,
        )
        _add_ref(index, method_ref)
        index.by_class_method_name[(cls.qualified_name, _short_name(method.qualified_name))] = (
            method_ref
        )
    for nested in cls.nested_classes:
        _index_class(index, nested, parsed_file)


def _bound_import_names(imp: ParsedImport) -> list[tuple[str, str]]:
    """(local_bound_name, resolvable_qualified_prefix) pairs this import introduces.

    Known gap: ``ParsedImport.imported_names`` stores only the *bound*
    (post-alias) name for a ``from X import name as alias`` — the
    original exported name isn't retained (see
    app.domain.code_symbols.models's documented import-grouping rule).
    So an aliased ``from`` import resolves here only when the bound name
    happens to equal the real attribute name (i.e. unaliased, or aliased
    to the same string) — a genuinely aliased single name falls through
    to UNRESOLVED rather than guessing. Plain ``import module as alias``
    doesn't have this gap: the full dotted module path survives regardless
    of the local binding name.
    """
    if not imp.is_from_import:
        if imp.module is None:
            return []
        bound = imp.alias or imp.module.split(".", 1)[0]
        return [(bound, imp.module)]

    prefix = imp.module or ""
    results: list[tuple[str, str]] = []
    for name in imp.imported_names:
        if name == "*":
            continue
        qualified_prefix = f"{prefix}.{name}" if prefix else name
        results.append((name, qualified_prefix))
    return results


def _resolve_via_imports(
    call: ParsedCall, imports: list[ParsedImport], index: RepositoryIndex
) -> SymbolRef | None:
    base: str | None
    method_name: str | None
    if call.call_type is CallType.ATTRIBUTE:
        if "." not in call.called_expression:
            return None
        base = call.called_expression.split(".", 1)[0]
        method_name = call.probable_target_name
    elif call.call_type in (CallType.DIRECT, CallType.CONSTRUCTOR_CANDIDATE):
        base = call.probable_target_name
        method_name = None
    else:
        return None

    if base is None:
        return None

    for imp in imports:
        for bound_name, qualified_prefix in _bound_import_names(imp):
            if bound_name != base:
                continue
            candidate = f"{qualified_prefix}.{method_name}" if method_name else qualified_prefix
            target = index.by_qualified_name.get(candidate)
            if target is not None:
                return target
    return None


def resolve_call(
    call: ParsedCall,
    *,
    caller_module: str,
    caller_class_qualified_name: str | None,
    imports: list[ParsedImport],
    index: RepositoryIndex,
) -> CallResolution:
    """Apply the 6 resolution rules in order; UNRESOLVED if none match."""

    # 1. Exact qualified-name match.
    exact = index.by_qualified_name.get(call.called_expression)
    if exact is not None:
        return CallResolution(
            call, exact, CallResolutionConfidence.EXACT, CallResolutionStrategy.QUALIFIED_NAME_EXACT
        )

    # 2. Same-module match for a bare DIRECT/CONSTRUCTOR_CANDIDATE call.
    if (
        call.call_type in (CallType.DIRECT, CallType.CONSTRUCTOR_CANDIDATE)
        and call.probable_target_name
    ):
        same_module = index.by_module_short_name.get((caller_module, call.probable_target_name), [])
        if len(same_module) == 1:
            return CallResolution(
                call,
                same_module[0],
                CallResolutionConfidence.PROBABLE,
                CallResolutionStrategy.SAME_MODULE,
            )

    # 3. Imported-symbol match.
    imported = _resolve_via_imports(call, imports, index)
    if imported is not None:
        return CallResolution(
            call,
            imported,
            CallResolutionConfidence.PROBABLE,
            CallResolutionStrategy.IMPORTED_SYMBOL,
        )

    # 4/5. self.method() / cls.method() within the current class.
    if (
        call.call_type is CallType.ATTRIBUTE
        and caller_class_qualified_name is not None
        and "." in call.called_expression
    ):
        base = call.called_expression.split(".", 1)[0]
        if base in ("self", "cls") and call.probable_target_name:
            method_ref = index.by_class_method_name.get(
                (caller_class_qualified_name, call.probable_target_name)
            )
            if method_ref is not None:
                strategy = (
                    CallResolutionStrategy.SELF_METHOD
                    if base == "self"
                    else CallResolutionStrategy.CLS_METHOD
                )
                return CallResolution(call, method_ref, CallResolutionConfidence.EXACT, strategy)

    # 6. Unique repository-wide short-name match.
    if call.probable_target_name:
        candidates = index.by_short_name.get(call.probable_target_name, [])
        if len(candidates) == 1:
            return CallResolution(
                call,
                candidates[0],
                CallResolutionConfidence.PROBABLE,
                CallResolutionStrategy.UNIQUE_REPOSITORY_SYMBOL,
            )

    # 7. Unresolved (includes factory()() and any other dynamic/ambiguous shape).
    return CallResolution(
        call, None, CallResolutionConfidence.UNRESOLVED, CallResolutionStrategy.UNRESOLVED
    )


def resolve_base_class(
    base_class_expression: str,
    *,
    caller_module: str,
    imports: list[ParsedImport],
    index: RepositoryIndex,
) -> SymbolRef | None:
    """Resolve a class's raw base-class expression to an internal Class,
    or None (treated as an external dependency by graph_builder.py)."""
    exact = index.by_qualified_name.get(base_class_expression)
    if exact is not None and exact.label is NodeLabel.CLASS:
        return exact

    same_module = index.by_module_short_name.get((caller_module, base_class_expression), [])
    same_module_classes = [ref for ref in same_module if ref.label is NodeLabel.CLASS]
    if len(same_module_classes) == 1:
        return same_module_classes[0]

    for imp in imports:
        for bound_name, qualified_prefix in _bound_import_names(imp):
            if bound_name != base_class_expression:
                continue
            candidate = index.by_qualified_name.get(qualified_prefix)
            if candidate is not None and candidate.label is NodeLabel.CLASS:
                return candidate

    candidates = [
        ref
        for ref in index.by_short_name.get(base_class_expression, [])
        if ref.label is NodeLabel.CLASS
    ]
    if len(candidates) == 1:
        return candidates[0]

    return None


def _package_for_module(file_path: str, module_name: str) -> str:
    if PurePosixPath(file_path).name == "__init__.py":
        return module_name
    return module_name.rsplit(".", 1)[0] if "." in module_name else ""


def resolve_import_target(
    imp: ParsedImport,
    *,
    file_path: str,
    module_name: str,
    known_modules: set[str],
) -> str | None:
    """Resolve `imp` to a known internal dotted module path, or None if it
    should be treated as external (see graph_builder.py)."""
    if imp.relative_level == 0:
        candidate = imp.module
    else:
        package = _package_for_module(file_path, module_name)
        for _ in range(imp.relative_level - 1):
            package = package.rsplit(".", 1)[0] if "." in package else ""
        candidate = f"{package}.{imp.module}" if imp.module else package

    if candidate and candidate in known_modules:
        return candidate
    return None
