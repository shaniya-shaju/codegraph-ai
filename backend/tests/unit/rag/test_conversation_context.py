"""Lightweight conversation persistence and follow-up resolution."""

from app.rag.conversation_context import (
    ConversationRole,
    append_turn,
    get_conversation_repository_id,
    get_recent_turns,
    resolve_follow_up_question,
)


def _session():
    from app.core.database import get_session_factory

    return get_session_factory()()


class TestAppendAndRetrieveTurns:
    def test_turns_come_back_in_chronological_order(self, isolated_database) -> None:
        session = _session()
        append_turn(
            session,
            conversation_id="c1",
            repository_id="repo-1",
            role=ConversationRole.USER,
            message="Explain login.",
        )
        append_turn(
            session,
            conversation_id="c1",
            repository_id="repo-1",
            role=ConversationRole.ASSISTANT,
            message="It authenticates users.",
            referenced_qualified_name="app.auth.login",
        )

        turns = get_recent_turns(session, conversation_id="c1", repository_id="repo-1", limit=10)

        assert [t.role for t in turns] == ["user", "assistant"]
        assert turns[1].referenced_qualified_name == "app.auth.login"
        session.close()

    def test_limit_returns_only_the_most_recent_turns(self, isolated_database) -> None:
        session = _session()
        for i in range(5):
            append_turn(
                session,
                conversation_id="c1",
                repository_id="repo-1",
                role=ConversationRole.USER,
                message=f"q{i}",
            )

        turns = get_recent_turns(session, conversation_id="c1", repository_id="repo-1", limit=2)

        assert len(turns) == 2
        assert turns[-1].message == "q4"
        session.close()


class TestConversationRepositoryId:
    def test_none_for_a_brand_new_conversation(self, isolated_database) -> None:
        session = _session()
        assert get_conversation_repository_id(session, "never-seen") is None
        session.close()

    def test_returns_the_repository_after_a_turn_is_recorded(self, isolated_database) -> None:
        session = _session()
        append_turn(
            session,
            conversation_id="c1",
            repository_id="repo-1",
            role=ConversationRole.USER,
            message="hi",
        )
        assert get_conversation_repository_id(session, "c1") == "repo-1"
        session.close()


class TestRepositoryScoping:
    def test_turns_from_a_different_repository_never_leak_in(self, isolated_database) -> None:
        session = _session()
        append_turn(
            session,
            conversation_id="c1",
            repository_id="repo-a",
            role=ConversationRole.USER,
            message="a",
        )
        append_turn(
            session,
            conversation_id="c1",
            repository_id="repo-b",
            role=ConversationRole.USER,
            message="b",
        )

        turns_a = get_recent_turns(session, conversation_id="c1", repository_id="repo-a", limit=10)
        turns_b = get_recent_turns(session, conversation_id="c1", repository_id="repo-b", limit=10)

        assert [t.message for t in turns_a] == ["a"]
        assert [t.message for t in turns_b] == ["b"]
        session.close()


class TestResolveFollowUpQuestion:
    def test_pronoun_question_is_augmented_with_prior_reference(self, isolated_database) -> None:
        session = _session()
        append_turn(
            session,
            conversation_id="c1",
            repository_id="repo-1",
            role=ConversationRole.ASSISTANT,
            message="...",
            referenced_qualified_name="app.auth.login",
        )
        turns = get_recent_turns(session, conversation_id="c1", repository_id="repo-1", limit=10)

        resolved = resolve_follow_up_question("What calls it?", turns)

        assert "app.auth.login" in resolved
        session.close()

    def test_question_without_a_pronoun_is_unchanged(self) -> None:
        turns: list = []
        resolved = resolve_follow_up_question("Explain AuthService.login.", turns)
        assert resolved == "Explain AuthService.login."

    def test_pronoun_with_no_prior_reference_is_unchanged(self) -> None:
        resolved = resolve_follow_up_question("What calls it?", [])
        assert resolved == "What calls it?"
