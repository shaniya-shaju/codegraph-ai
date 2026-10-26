"""Conservative call/inheritance/import resolution — see the graph task's
"Relationship resolution rules". All pure logic, no Neo4j involved."""

from app.domain.code_symbols.enums import CallType
from app.domain.code_symbols.models import (
    ParsedCall,
    ParsedFile,
    ParsedImport,
    SourceLocation,
)
from app.domain.graph.enums import CallResolutionConfidence, CallResolutionStrategy, NodeLabel
from app.graph.relationship_resolver import (
    build_repository_index,
    resolve_base_class,
    resolve_call,
    resolve_import_target,
)
from app.parsing.python.parser import PythonParser


def _parse(source: str, file_path: str, repository_id: str = "repo-1") -> ParsedFile:
    from pathlib import Path

    return PythonParser().parse(source, Path(file_path), repository_id)


def _location() -> SourceLocation:
    return SourceLocation(file_path="m.py", start_line=1, start_column=0, end_line=1, end_column=1)


def _call(expression: str, call_type: CallType, target_name: str | None) -> ParsedCall:
    return ParsedCall(
        id="call-1",
        caller_qualified_name="m.caller",
        called_expression=expression,
        probable_target_name=target_name,
        call_type=call_type,
        argument_count=0,
        location=_location(),
    )


class TestSameModuleResolution:
    def test_resolves_unique_same_module_function(self) -> None:
        source = "def login():\n    pass\n\ndef caller():\n    login()\n"
        parsed = _parse(source, "m.py")
        index = build_repository_index([parsed])
        call = next(c for f in parsed.functions if f.name == "caller" for c in f.calls)

        resolution = resolve_call(
            call, caller_module="m", caller_class_qualified_name=None, imports=[], index=index
        )

        assert resolution.confidence is CallResolutionConfidence.PROBABLE
        assert resolution.strategy is CallResolutionStrategy.SAME_MODULE
        assert resolution.target is not None
        assert resolution.target.qualified_name == "m.login"

    def test_ambiguous_same_name_in_different_modules_is_not_same_module_resolved(self) -> None:
        # Two functions named `login` in two different modules: calling
        # `login()` from module `a` must resolve to `a.login`, not `b.login`.
        file_a = _parse("def login():\n    pass\n\ndef caller():\n    login()\n", "a.py")
        file_b = _parse("def login():\n    pass\n", "b.py")
        index = build_repository_index([file_a, file_b])
        call = next(c for f in file_a.functions if f.name == "caller" for c in f.calls)

        resolution = resolve_call(
            call, caller_module="a", caller_class_qualified_name=None, imports=[], index=index
        )

        assert resolution.target is not None
        assert resolution.target.qualified_name == "a.login"


class TestSelfAndClsResolution:
    def test_self_method_resolves_within_the_same_class(self) -> None:
        source = "class C:\n    def a(self):\n        self.b()\n\n    def b(self):\n        pass\n"
        parsed = _parse(source, "m.py")
        index = build_repository_index([parsed])
        method_a = next(m for m in parsed.classes[0].methods if m.name == "a")
        call = method_a.calls[0]

        resolution = resolve_call(
            call,
            caller_module="m",
            caller_class_qualified_name="m.C",
            imports=[],
            index=index,
        )

        assert resolution.confidence is CallResolutionConfidence.EXACT
        assert resolution.strategy is CallResolutionStrategy.SELF_METHOD
        assert resolution.target is not None
        assert resolution.target.qualified_name == "m.C.b"

    def test_cls_method_resolves_within_the_same_class(self) -> None:
        source = (
            "class C:\n"
            "    @classmethod\n"
            "    def make(cls):\n"
            "        cls.helper()\n\n"
            "    @classmethod\n"
            "    def helper(cls):\n"
            "        pass\n"
        )
        parsed = _parse(source, "m.py")
        index = build_repository_index([parsed])
        make = next(m for m in parsed.classes[0].methods if m.name == "make")
        call = make.calls[0]

        resolution = resolve_call(
            call, caller_module="m", caller_class_qualified_name="m.C", imports=[], index=index
        )

        assert resolution.strategy is CallResolutionStrategy.CLS_METHOD
        assert resolution.target is not None
        assert resolution.target.qualified_name == "m.C.helper"


class TestAmbiguousAndUnresolvedCalls:
    def test_ambiguous_short_name_across_repository_is_unresolved(self) -> None:
        file_a = _parse("def helper():\n    pass\n", "a.py")
        file_b = _parse("def helper():\n    pass\n", "b.py")
        file_c = _parse("def caller():\n    helper()\n", "c.py")
        index = build_repository_index([file_a, file_b, file_c])
        call = file_c.functions[0].calls[0]

        resolution = resolve_call(
            call, caller_module="c", caller_class_qualified_name=None, imports=[], index=index
        )

        assert resolution.confidence is CallResolutionConfidence.UNRESOLVED
        assert resolution.target is None

    def test_unique_repository_wide_short_name_resolves(self) -> None:
        file_a = _parse("def only_one_named_this():\n    pass\n", "a.py")
        file_b = _parse("def caller():\n    only_one_named_this()\n", "b.py")
        index = build_repository_index([file_a, file_b])
        call = file_b.functions[0].calls[0]

        resolution = resolve_call(
            call, caller_module="b", caller_class_qualified_name=None, imports=[], index=index
        )

        assert resolution.strategy is CallResolutionStrategy.UNIQUE_REPOSITORY_SYMBOL
        assert resolution.target is not None
        assert resolution.target.qualified_name == "a.only_one_named_this"

    def test_call_on_call_result_is_unresolved(self) -> None:
        source = "def factory():\n    pass\n\ndef caller():\n    factory()()\n"
        parsed = _parse(source, "m.py")
        index = build_repository_index([parsed])
        caller = next(f for f in parsed.functions if f.name == "caller")
        outer_call = next(c for c in caller.calls if c.called_expression == "factory()")

        resolution = resolve_call(
            outer_call, caller_module="m", caller_class_qualified_name=None, imports=[], index=index
        )

        assert resolution.confidence is CallResolutionConfidence.UNRESOLVED

    def test_never_resolves_by_short_name_alone_when_ambiguous_even_with_direct_call(self) -> None:
        # rule: "Do not resolve solely by a common short name when several
        # candidates exist" — covered above, restated explicitly here.
        call = _call("build", CallType.DIRECT, "build")
        file_a = _parse("def build():\n    pass\n", "a.py")
        file_b = _parse("def build():\n    pass\n", "b.py")
        index = build_repository_index([file_a, file_b])

        resolution = resolve_call(
            call,
            caller_module="somewhere_else",
            caller_class_qualified_name=None,
            imports=[],
            index=index,
        )

        assert resolution.confidence is CallResolutionConfidence.UNRESOLVED


class TestImportedSymbolResolution:
    def test_resolves_call_through_an_aliased_module_import(self) -> None:
        # An alias is used deliberately so `called_expression` ("auth_mod.login")
        # can't already match a real qualified_name outright (rule 1) —
        # this exercises the imported-symbol rule (3) specifically.
        auth_module = _parse("def login():\n    pass\n", "app/auth.py")
        caller_module = _parse(
            "import app.auth as auth_mod\n\ndef f():\n    auth_mod.login()\n", "app/main.py"
        )
        index = build_repository_index([auth_module, caller_module])
        call = caller_module.functions[0].calls[0]
        imports = caller_module.imports

        resolution = resolve_call(
            call,
            caller_module="app.main",
            caller_class_qualified_name=None,
            imports=imports,
            index=index,
        )

        assert resolution.strategy is CallResolutionStrategy.IMPORTED_SYMBOL
        assert resolution.target is not None
        assert resolution.target.qualified_name == "app.auth.login"

    def test_resolves_call_through_an_unaliased_from_import(self) -> None:
        services_module = _parse("def helper():\n    pass\n", "app/services.py")
        caller_module = _parse(
            "from app.services import helper\n\ndef f():\n    helper()\n",
            "app/main.py",
        )
        index = build_repository_index([services_module, caller_module])
        imports = caller_module.imports
        call = caller_module.functions[0].calls[0]

        resolution = resolve_call(
            call,
            caller_module="app.main",
            caller_class_qualified_name=None,
            imports=imports,
            index=index,
        )

        assert resolution.strategy is CallResolutionStrategy.IMPORTED_SYMBOL
        assert resolution.target is not None
        assert resolution.target.qualified_name == "app.services.helper"

    def test_aliased_from_import_single_name_is_a_known_unresolved_gap(self) -> None:
        # ParsedImport.imported_names stores the *bound* (post-alias) name
        # only — the original exported name ("helper") isn't retained once
        # aliased (see app.domain.code_symbols.models's documented import
        # grouping rule). So `from X import helper as h` followed by `h()`
        # can't be mapped back to `X.helper` from a ParsedImport alone.
        # Documenting this as an accepted gap rather than silently guessing.
        services_module = _parse("def helper():\n    pass\n", "app/services.py")
        caller_module = _parse(
            "from app.services import helper as h\n\ndef f():\n    h()\n",
            "app/main.py",
        )
        index = build_repository_index([services_module, caller_module])
        call = caller_module.functions[0].calls[0]

        resolution = resolve_call(
            call,
            caller_module="app.main",
            caller_class_qualified_name=None,
            imports=caller_module.imports,
            index=index,
        )

        assert resolution.confidence is CallResolutionConfidence.UNRESOLVED


class TestBaseClassResolution:
    def test_resolves_same_module_base_class(self) -> None:
        parsed = _parse("class Base:\n    pass\n\nclass Child(Base):\n    pass\n", "m.py")
        index = build_repository_index([parsed])

        resolved = resolve_base_class("Base", caller_module="m", imports=[], index=index)

        assert resolved is not None
        assert resolved.label is NodeLabel.CLASS
        assert resolved.qualified_name == "m.Base"

    def test_unresolvable_expression_returns_none(self) -> None:
        parsed = _parse("class Child:\n    pass\n", "m.py")
        index = build_repository_index([parsed])

        resolved = resolve_base_class("Generic[T]", caller_module="m", imports=[], index=index)

        assert resolved is None


class TestImportTargetResolution:
    def test_absolute_import_resolves_when_module_is_known(self) -> None:
        imp = ParsedImport(
            id="i1",
            module="app.services",
            imported_names=["UserService"],
            alias=None,
            is_from_import=True,
            relative_level=0,
            location=_location(),
        )

        resolved = resolve_import_target(
            imp, file_path="app/main.py", module_name="app.main", known_modules={"app.services"}
        )

        assert resolved == "app.services"

    def test_relative_import_resolves_against_the_current_package(self) -> None:
        imp = ParsedImport(
            id="i1",
            module="models",
            imported_names=["User"],
            alias=None,
            is_from_import=True,
            relative_level=1,
            location=_location(),
        )

        resolved = resolve_import_target(
            imp,
            file_path="app/auth/service.py",
            module_name="app.auth.service",
            known_modules={"app.auth.models"},
        )

        assert resolved == "app.auth.models"

    def test_unknown_module_is_treated_as_external(self) -> None:
        imp = ParsedImport(
            id="i1",
            module="numpy",
            imported_names=[],
            alias=None,
            is_from_import=False,
            relative_level=0,
            location=_location(),
        )

        resolved = resolve_import_target(
            imp, file_path="m.py", module_name="m", known_modules={"m"}
        )

        assert resolved is None
