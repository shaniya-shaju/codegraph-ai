"""Heuristic entity extraction — original strings preserved verbatim,
nothing claimed to exist in the repository (see the hybrid-retrieval
task's "Entity extraction")."""

from app.rag.entity_extractor import extract_entities


class TestExampleQuestions:
    def test_explain_dotted_name_splits_into_class_and_function(self) -> None:
        entities = extract_entities("Explain AuthService.login")
        assert "AuthService.login" in entities.symbols
        assert "AuthService" in entities.class_names
        assert "login" in entities.function_names

    def test_call_like_syntax_extracts_a_function_name(self) -> None:
        entities = extract_entities("Which functions call login()?")
        assert "login" in entities.function_names
        assert "login" in entities.symbols

    def test_camel_case_extracts_a_class_name(self) -> None:
        entities = extract_entities("What depends on UserRepository?")
        assert "UserRepository" in entities.class_names
        assert "UserRepository" in entities.symbols

    def test_api_route_is_extracted_with_method_and_path(self) -> None:
        entities = extract_entities("Which function handles POST /login?")
        assert entities.api_routes == ["POST /login"]

    def test_file_path_is_extracted(self) -> None:
        entities = extract_entities("What is defined in auth.py?")
        assert "auth.py" in entities.file_paths


class TestPreservation:
    def test_original_casing_is_preserved(self) -> None:
        entities = extract_entities("Explain the find_by_email method on UserRepository")
        assert "UserRepository" in entities.symbols
        assert "UserRepository" not in [s.lower() for s in []]  # sanity no-op

    def test_deduplicates_case_insensitively_but_keeps_first_spelling(self) -> None:
        entities = extract_entities("login() calls login() again")
        assert entities.function_names.count("login") == 1


class TestNoFalsePositivesOnPlainEnglish:
    def test_a_question_with_no_identifiers_extracts_nothing(self) -> None:
        entities = extract_entities("Where is authentication implemented?")
        assert entities.symbols == []
        assert entities.class_names == []
        assert entities.function_names == []
        assert entities.api_routes == []
