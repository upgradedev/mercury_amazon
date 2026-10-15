"""Shared-handoff routes the TV's D-pad path calls, and the revision reads.

The labelled record-only demo publishes one fixed handoff. It takes no secret and it
does change state: each publish bumps a revision. It is refused whenever a
dispatcher that can reach a pipeline is selected, and it contacts nothing.

A shared handoff is written against the revision the writer last saw, and the store
refuses a stale one. A screen that loaded before somebody else published used to
send revision 0 and be refused with HTTP 409, which is what happened to every second
viewer of a shared deployment. A writer reads a revision route first. Both answer 200
when nothing has been published yet, with revision 0: that is a state, not an error,
and a 404 there would log an error in the browser console on a clean first run.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.domain.incident_handoff import HandoffConflict, IncidentHandoffStore

DEMO_INCIDENT_ID = "checkout-api-active"
DEMO_ACTION_ID = "tv-demo-handoff"
DEMO_STAMP = {"authorization_mode": "DPAD_RECORD_ONLY_DEMO", "external_effect": "NONE"}


class DemoHandoffRequest(BaseModel):
    expected_revision: int | None = Field(default=None, ge=0)
    service_name: str = Field(default="checkout-api", min_length=1, max_length=64)


def register_handoff_routes(
    app: FastAPI,
    store: IncidentHandoffStore,
    require_operator: Callable[..., str],
    validate_record_only_demo: Callable[[str], None],
    demo_payload: Callable[..., dict | None],
) -> None:
    """Register the demo handoff and revision routes on the server's own app.

    Registered on the app itself rather than through an included router, so every
    route stays a plain route with a path for anything that lists the app's routes.
    """

    def revision_of(incident_id: str) -> dict[str, Any]:
        item = store.get(incident_id)
        return {"incident_id": incident_id, "revision": item.revision if item else 0}

    @app.get("/mcp/handoffs/{incident_id}/revision", dependencies=[Depends(require_operator)])
    async def get_handoff_revision(incident_id: str) -> dict[str, Any]:
        """The revision an operator's next write must carry; needs the shared secret."""
        return revision_of(incident_id)

    @app.post("/mcp/tools/demo_update_handoff")
    async def demo_update_handoff(req: DemoHandoffRequest) -> dict[str, Any]:
        """Publish fixed fixture content; accept no responder-authored text."""
        validate_record_only_demo(DEMO_ACTION_ID)
        payload = demo_payload(req.service_name)
        if payload is None:
            raise HTTPException(status_code=409, detail="The labelled demo handoff is unavailable.")
        try:
            item = store.update(**payload, expected_revision=req.expected_revision)
        except HandoffConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {**item.to_dict(), **DEMO_STAMP}

    @app.get("/mcp/demo-handoff")
    async def get_demo_handoff() -> dict[str, Any]:
        """Read the single fixed demo handoff without exposing operator state."""
        validate_record_only_demo(DEMO_ACTION_ID)
        item = store.get(DEMO_INCIDENT_ID)
        if item is None:
            raise HTTPException(status_code=404, detail="No recorded demo handoff exists yet.")
        return {**item.to_dict(), **DEMO_STAMP}

    @app.get("/mcp/demo-handoff/revision")
    async def get_demo_handoff_revision() -> dict[str, Any]:
        """The same read for the one fixed demo handoff, refused outside record-only mode."""
        validate_record_only_demo(DEMO_ACTION_ID)
        return revision_of(DEMO_INCIDENT_ID)
