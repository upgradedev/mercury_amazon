"""Durable single-table state for the Lambda deployment.

The domain objects depend only on the small method surface implemented here.
When ``MERCURY_STATE_TABLE`` is absent the composition root passes ``None`` and
the local quickstart remains memory-only.  The public Lambda configures the table,
so deployment evidence, handoffs, staged actions and spent nonces survive cold
starts and concurrent Lambda instances.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any


class StateConflict(RuntimeError):
    """A conditional durable-state write lost to another writer."""


class DynamoStateStore:
    """DynamoDB adapter using ``pk`` and ``sk`` string keys."""

    def __init__(self, table_name: str, table: Any | None = None) -> None:
        if not table_name.strip():
            raise ValueError("table_name must not be empty")
        self.table_name = table_name.strip()
        if table is None:
            import boto3

            table = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "eu-west-1")).Table(
                self.table_name
            )
        self._table = table

    @classmethod
    def from_env(cls) -> "DynamoStateStore | None":
        name = os.getenv("MERCURY_STATE_TABLE", "").strip()
        return cls(name) if name else None

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _decode(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        try:
            value = json.loads(str(item["payload_json"]))
        except (KeyError, TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def put_deployment_marker(self, payload: dict[str, Any]) -> None:
        service = payload["service"]
        environment = payload["environment"]
        marker_id = payload["marker_id"]
        self._table.put_item(Item={
            "pk": f"deployment#{service}#{environment}",
            "sk": f"{payload['deployed_at']}#{marker_id}",
            "marker_id": marker_id,
            "payload_json": self._json(payload),
        })

    def list_deployment_markers(self, service: str, environment: str) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        response = self._table.query(
            KeyConditionExpression=Key("pk").eq(f"deployment#{service}#{environment}"),
            ScanIndexForward=True,
        )
        return [value for item in response.get("Items", []) if (value := self._decode(item))]

    def get_handoff(self, incident_id: str) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={"pk": f"handoff#{incident_id}", "sk": "state"}, ConsistentRead=True
        )
        return self._decode(response.get("Item"))

    def put_handoff(self, payload: dict[str, Any], expected_revision: int) -> None:
        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        if expected_revision == 0:
            condition = "attribute_not_exists(pk)"
        else:
            condition = "#revision = :expected"
            names["#revision"] = "revision"
            values[":expected"] = expected_revision
        kwargs: dict[str, Any] = {
            "Item": {
                "pk": f"handoff#{payload['incident_id']}",
                "sk": "state",
                "revision": int(payload["revision"]),
                "payload_json": self._json(payload),
            },
            "ConditionExpression": condition,
        }
        if names:
            kwargs["ExpressionAttributeNames"] = names
        if values:
            kwargs["ExpressionAttributeValues"] = values
        try:
            self._table.put_item(**kwargs)
        except Exception as exc:
            if self._is_conditional_failure(exc):
                raise StateConflict("handoff revision changed before the durable write") from exc
            raise

    def put_rollback(self, action_id: str, payload: dict[str, Any]) -> None:
        self._table.put_item(Item={
            "pk": f"rollback#{action_id}", "sk": "state", "payload_json": self._json(payload),
            "expires_at": int(payload.get("created_at_epoch", time.time()) + payload.get("lease_sec", 300) + 86400),
        })

    def get_rollback(self, action_id: str) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={"pk": f"rollback#{action_id}", "sk": "state"}, ConsistentRead=True
        )
        return self._decode(response.get("Item"))

    def claim_nonce(self, nonce: str, expires_at: int) -> bool:
        try:
            self._table.put_item(
                Item={"pk": f"nonce#{nonce}", "sk": "spent", "expires_at": int(expires_at)},
                ConditionExpression="attribute_not_exists(pk)",
            )
        except Exception as exc:
            if self._is_conditional_failure(exc):
                return False
            raise
        return True

    @staticmethod
    def _is_conditional_failure(exc: Exception) -> bool:
        response = getattr(exc, "response", {})
        return response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
