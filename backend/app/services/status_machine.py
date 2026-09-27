from enum import StrEnum


class Status(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    REJECTED = "rejected"


VALID_TRANSITIONS: dict[Status, set[Status]] = {
    Status.OPEN: {Status.IN_PROGRESS, Status.REJECTED},
    Status.IN_PROGRESS: {Status.RESOLVED, Status.REJECTED},
    Status.RESOLVED: set(),
    Status.REJECTED: set(),
}


def is_valid_transition(from_status: Status, to_status: Status) -> bool:
    return to_status in VALID_TRANSITIONS.get(from_status, set())


def allowed_transitions(from_status: Status) -> set[Status]:
    """The statuses reachable from `from_status`.

    Exposed over the API so the dashboard renders the operator's available
    actions from this table instead of hard-coding them. The assignment is
    explicit that valid status transitions are decided by the backend and
    rendered by the frontend, "never duplicated in it" -- a React component
    that branches on `status === 'open'` to decide which button to draw is a
    second source of truth, and it rots the moment an edge is added here.
    """
    return VALID_TRANSITIONS.get(from_status, set())


def transition_table() -> dict[str, list[str]]:
    """The whole table as plain strings, for GET /api/meta/status-transitions."""
    return {
        status.value: sorted(s.value for s in targets)
        for status, targets in VALID_TRANSITIONS.items()
    }
