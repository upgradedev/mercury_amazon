"""
Unit tests for AWSAgentCoreSessionManager & Multi-Model Circuit Breaker.
"""

import pytest
from src.infrastructure.agentcore_adapter import AWSAgentCoreSessionManager

def test_session_lifecycle():
    manager = AWSAgentCoreSessionManager()
    session = manager.create_session("sess-100", "user-alex")
    
    assert session.session_id == "sess-100"
    assert session.user_id == "user-alex"
    assert len(session.conversation_history) == 0
    
    manager.append_message("sess-100", "user", "Synthesize AST diff")
    retrieved = manager.get_session("sess-100")
    assert len(retrieved.conversation_history) == 1
    assert retrieved.conversation_history[0]["content"] == "Synthesize AST diff"

def test_circuit_breaker_automatic_failover():
    manager = AWSAgentCoreSessionManager()
    
    # Simulate primary Bedrock throttling (HTTP 429)
    res = manager.invoke_with_circuit_breaker(
        session_id="sess-cb-1",
        user_prompt="Critical assistive wellness action",
        simulate_primary_throttling=True
    )
    
    assert res["status"] == "FAILOVER_SUCCESS"
    assert res["circuit_breaker_active"] is True
    assert res["model_used"] == "amazon.nova-pro-v1:0"
    assert "CIRCUIT-BREAKER FAILOVER" in res["response"]
    
    session = manager.get_session("sess-cb-1")
    assert session.circuit_breaker_triggered is True
    assert len(session.conversation_history) == 2  # user prompt + assistant failover response
