"""Unit tests for the status state machine.

Pure functions with no I/O, so these need neither Postgres nor Redis and run
in milliseconds. The transition table is the piece of business logic most
worth pinning down precisely, because every illegal transition silently
becoming legal is a data-integrity bug that only shows up in production.
"""

import pytest

from app.services.status_machine import VALID_TRANSITIONS, Status, is_valid_transition


class TestTransitionTable:
    def test_table_covers_every_status(self):
        # A status missing from the table would be treated as having no valid
        # transitions, silently rejecting every transition out of it.
        assert set(VALID_TRANSITIONS.keys()) == set(Status)

    def test_required_edges_are_present(self):
        # Exactly the edges the assignment specifies.
        assert VALID_TRANSITIONS[Status.OPEN] == {Status.IN_PROGRESS, Status.REJECTED}
        assert VALID_TRANSITIONS[Status.IN_PROGRESS] == {Status.RESOLVED, Status.REJECTED}

    @pytest.mark.parametrize("terminal", [Status.RESOLVED, Status.REJECTED])
    def test_terminal_states_have_no_exits(self, terminal):
        assert VALID_TRANSITIONS[terminal] == set()
        for target in Status:
            assert not is_valid_transition(terminal, target)

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (Status.OPEN, Status.IN_PROGRESS),
            (Status.OPEN, Status.REJECTED),
            (Status.IN_PROGRESS, Status.RESOLVED),
            (Status.IN_PROGRESS, Status.REJECTED),
        ],
    )
    def test_valid_transitions(self, source, target):
        assert is_valid_transition(source, target)

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            # Skipping in_progress.
            (Status.OPEN, Status.RESOLVED),
            # Self-transitions are not offered by the table.
            (Status.OPEN, Status.OPEN),
            (Status.IN_PROGRESS, Status.IN_PROGRESS),
            # Backwards.
            (Status.IN_PROGRESS, Status.OPEN),
            # Terminal states.
            (Status.RESOLVED, Status.OPEN),
            (Status.RESOLVED, Status.IN_PROGRESS),
            (Status.REJECTED, Status.OPEN),
            (Status.REJECTED, Status.IN_PROGRESS),
            (Status.REJECTED, Status.RESOLVED),
        ],
    )
    def test_invalid_transitions(self, source, target):
        assert not is_valid_transition(source, target)

    def test_unknown_source_has_no_transitions(self):
        # Defensive: a status read from the database that the enum does not
        # know about must fail closed (no transitions) rather than open.
        assert VALID_TRANSITIONS.get("not_a_status", set()) == set()


class TestStatusEnum:
    def test_values_match_the_database_enum(self):
        # These strings are persisted in a Postgres enum type. If a value here
        # drifts from the migration, inserts start failing at runtime.
        assert Status.OPEN == "open"
        assert Status.IN_PROGRESS == "in_progress"
        assert Status.RESOLVED == "resolved"
        assert Status.REJECTED == "rejected"

    def test_str_enum_serialises_as_plain_string(self):
        # StrEnum so a Status can be bound straight into a SQL parameter and
        # JSON-encoded without an explicit .value everywhere.
        assert isinstance(Status.OPEN, str)
        assert Status("open") is Status.OPEN

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            Status("archived")
