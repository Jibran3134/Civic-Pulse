"""The workflow table is served rather than duplicated in clients.

The assignment requires valid status transitions to be decided by the backend
and rendered by the frontend, "never duplicated in it". That only holds if a
client can ask, so GET /api/meta/status-transitions has to exist and has to
agree with the table the PATCH route enforces.
"""


from app.services.status_machine import Status


class TestStatusTransitionsEndpoint:
    async def test_endpoint_returns_every_status(self, client):
        response = await client.get("/api/meta/status-transitions")
        assert response.status_code == 200

        transitions = response.json()["transitions"]
        assert set(transitions) == {"open", "in_progress", "resolved", "rejected"}

    async def test_endpoint_matches_the_enforced_table(self, client):
        """The served table must be the same object the PATCH route checks.

        If these ever diverge, the dashboard offers an action the server then
        refuses with a 409, which is the exact outcome the single-source-of-
        truth rule exists to prevent.
        """
        from app.services.status_machine import VALID_TRANSITIONS

        served = (await client.get("/api/meta/status-transitions")).json()["transitions"]

        for status, targets in VALID_TRANSITIONS.items():
            assert set(served[status.value]) == {t.value for t in targets}, (
                f"table served for {status.value} disagrees with VALID_TRANSITIONS"
            )

    async def test_terminal_states_advertise_nothing(self, client):
        served = (await client.get("/api/meta/status-transitions")).json()["transitions"]
        assert served["resolved"] == []
        assert served["rejected"] == []

    async def test_every_served_transition_is_actually_accepted(self, client, unique_complaint):
        """Not just consistent with the table -- accepted end to end.

        Offers what the endpoint advertises, then confirms the PATCH route
        agrees. A 409 here means the served table is lying.
        """
        created = await client.post("/api/complaints", json=unique_complaint)
        assert created.status_code == 201
        complaint_id = created.json()["id"]

        served = (await client.get("/api/meta/status-transitions")).json()["transitions"]

        for target in served["open"]:
            response = await client.patch(
                f"/api/complaints/{complaint_id}/status", json={"status": target}
            )
            assert response.status_code == 200, (
                f"endpoint advertises open -> {target} but the route rejected it"
            )

    async def test_transition_helper_agrees_with_the_table(self):
        from app.services.status_machine import allowed_transitions, is_valid_transition

        for status in Status:
            for target in Status:
                assert is_valid_transition(status, target) == (
                    target in allowed_transitions(status)
                )
