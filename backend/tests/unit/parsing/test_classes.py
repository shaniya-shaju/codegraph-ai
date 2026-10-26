"""Class extraction: inheritance, methods, nested classes, class attributes."""

from pathlib import Path

from app.parsing.python.parser import PythonParser


def test_class_extraction_basic_fields(python_parser: PythonParser) -> None:
    source = (
        'class Animal:\n    """A basic animal."""\n\n    def speak(self):\n        return "..."\n'
    )

    parsed = python_parser.parse(source, Path("zoo.py"), "repo-1")

    assert len(parsed.classes) == 1
    cls = parsed.classes[0]
    assert cls.name == "Animal"
    assert cls.qualified_name == "zoo.Animal"
    assert cls.docstring == "A basic animal."
    assert cls.base_classes == []


def test_single_inheritance_base_classes(python_parser: PythonParser) -> None:
    source = "class Animal:\n    pass\n\nclass Dog(Animal):\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    dog = next(c for c in parsed.classes if c.name == "Dog")

    assert dog.base_classes == ["Animal"]


def test_multiple_inheritance_excludes_keyword_arguments(python_parser: PythonParser) -> None:
    source = "class Foo(Base, Mixin, metaclass=Meta):\n    pass\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.classes[0].base_classes == ["Base", "Mixin"]


def test_methods_are_attached_to_class_not_flattened_to_file(python_parser: PythonParser) -> None:
    source = "class Dog:\n    def speak(self):\n        return 'Woof'\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.functions == []
    assert len(parsed.classes[0].methods) == 1
    method = parsed.classes[0].methods[0]
    assert method.name == "speak"
    assert method.qualified_name == "m.Dog.speak"
    assert method.parent_class == "m.Dog"


def test_nested_class_is_contained_not_flattened(python_parser: PythonParser) -> None:
    source = "class Outer:\n    class Config:\n        debug = True\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert len(parsed.classes) == 1
    outer = parsed.classes[0]
    assert len(outer.nested_classes) == 1
    inner = outer.nested_classes[0]
    assert inner.name == "Config"
    assert inner.qualified_name == "m.Outer.Config"


def test_class_attributes_capture_simple_targets_only(python_parser: PythonParser) -> None:
    source = "class Config:\n    debug = False\n    max_connections: int = 10\n    a, b = 1, 2\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")
    attrs = {a.name: a for a in parsed.classes[0].class_attributes}

    assert set(attrs) == {"debug", "max_connections"}
    assert attrs["debug"].value == "False"
    assert attrs["max_connections"].annotation == "int"
    assert attrs["max_connections"].value == "10"


def test_class_source_code_is_preserved_exactly(python_parser: PythonParser) -> None:
    source = "class Dog:\n    def speak(self):\n        return 'Woof'\n"

    parsed = python_parser.parse(source, Path("m.py"), "repo-1")

    assert parsed.classes[0].source_code == source.strip()
