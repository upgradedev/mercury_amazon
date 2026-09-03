"""
Unit tests for Institutional Memory & Post-Mortem RAG (ACT-08).
"""

from src.domain.post_mortem_rag import PostMortemIncident
from src.infrastructure.post_mortem_opensearch_adapter import PostMortemOpenSearchRAGAdapter

def test_post_mortem_rag_retrieval():
    adapter = PostMortemOpenSearchRAGAdapter()
    
    # Query for database spike / connection exhaustion
    results = adapter.retrieve_relevant_post_mortems("database connection pool exhaustion under load", top_k=1)
    assert len(results) == 1
    assert results[0].incident_id == "INC-2025-0811"
    assert "Enforce AWS RDS Proxy" in results[0].preventive_architecture_changes[0]

def test_post_mortem_saga_scar_tissue_injection():
    adapter = PostMortemOpenSearchRAGAdapter()
    
    guidance = adapter.inject_scar_tissue_guidance("Implementing Stripe checkout with distributed microservices")
    assert guidance["matched_historical_incidents"] >= 1
    assert "INC-2025-1104" in guidance["incident_ids"]
    assert any("Step Functions Distributed Saga" in r for r in guidance["preventive_recommendations"])
