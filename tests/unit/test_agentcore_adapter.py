"""Unit tests for AWS AgentCore Session Adapter."""
import pytest
from src.infrastructure.agentcore_adapter import (
    AWSAgentCoreSessionManager,
    AgentCoreExecutionResult,
)


def test_agentcore_registration_and_invocation():
    mgr = AWSAgentCoreSessionManager(agent_id="agent-ambient-hero")
    
    executed_events = []
    def sample_executor(data):
        executed_events.append(data)

    mgr.register_action_group(
        name="BatchArrivalApproval",
        description="Executes batch payments and calendar bookings",
        api_schema={"type": "object"},
        executor=sample_executor,
    )

    res = mgr.invoke_agent(
        session_id="session-user-123",
        input_text="Please trigger BatchArrivalApproval for Maria",
        session_attributes={"user_tier": "SANDWICH_PRO"},
    )

    assert res.status == "SUCCESS"
    assert "BatchArrivalApproval" in res.action_groups_called
    assert len(executed_events) == 1
    assert res.guardrail_interventions == 0


def test_agentcore_guardrail_intervention():
    mgr = AWSAgentCoreSessionManager(agent_id="agent-governance")
    res = mgr.invoke_agent(
        session_id="session-456",
        input_text="My credit_card is 4111-2222-3333-4444 and password is secret",
    )
    assert res.status == "GUARDRAIL_INTERVENED"
    assert res.guardrail_interventions >= 1


def test_agentcore_empty_input_rejected():
    mgr = AWSAgentCoreSessionManager(agent_id="agent-test")
    with pytest.raises(ValueError, match="cannot be empty"):
        mgr.invoke_agent(session_id="s1", input_text="   ")
