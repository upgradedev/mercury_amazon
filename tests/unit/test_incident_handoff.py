import pytest

from src.domain.incident_handoff import HandoffConflict, IncidentHandoffStore


def test_second_responder_reads_the_complete_compact_state():
    store = IncidentHandoffStore()
    first = store.update(
        incident_id="inc-17", responder="Maya", current_action="Checking deployment markers",
        confirmed_facts=["5xx rose at 08:42", "release-19 is deployed"],
        next_step="Compare release-19 with the last healthy marker", expected_revision=0,
    )
    resumed = store.get("inc-17")
    assert resumed == first
    assert resumed.to_dict() == {
        "incident_id": "inc-17",
        "responder": "Maya",
        "current_action": "Checking deployment markers",
        "confirmed_facts": ["5xx rose at 08:42", "release-19 is deployed"],
        "next_step": "Compare release-19 with the last healthy marker",
        "revision": 1,
        "updated_at": resumed.updated_at.isoformat(),
    }


def test_stale_responder_cannot_overwrite_newer_handoff_state():
    store = IncidentHandoffStore()
    store.update(
        incident_id="inc-17", responder="Maya", current_action="Investigating",
        confirmed_facts=["alarm verified"], next_step="Check deploy", expected_revision=0,
    )
    with pytest.raises(HandoffConflict, match="stale handoff revision"):
        store.update(
            incident_id="inc-17", responder="Noah", current_action="Rolling back",
            confirmed_facts=["target verified"], next_step="Confirm", expected_revision=0,
        )
