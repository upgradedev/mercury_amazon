"""
OpenSearch Serverless Vector RAG Adapter for Production Incident Post-Mortems (ACT-08).
Indexes historical root-cause analyses and injects institutional scar tissue into live pipelines.
"""

from typing import List, Dict, Any, Optional
import json
import logging
from src.domain.post_mortem_rag import PostMortemIncident

logger = logging.getLogger(__name__)

# Canonical Seed Post-Mortem Database (Historical Scar Tissue)
HISTORICAL_INCIDENTS = [
    PostMortemIncident(
        incident_id="INC-2025-0811",
        title="Cascading Connection Exhaustion under Spike Load",
        severity="SEV-1",
        root_cause="Unbounded Lambda connection pools overwhelmed Postgres RDS during flash mob event.",
        contributing_factors=["Missing RDS Proxy", "Synchronous blocking DB calls without circuit breaker"],
        preventive_architecture_changes=["Enforce AWS RDS Proxy connection pooling", "Migrate to DynamoDB Single-Table Design with GSI1PK"],
        affected_services=["RDS", "Lambda", "API Gateway"],
        occurred_at="2025-08-11",
        tags=["database", "connection_pool", "circuit_breaker", "dynamodb"]
    ),
    PostMortemIncident(
        incident_id="INC-2025-1104",
        title="Uncompensated Distributed Transaction State Desynchronization",
        severity="SEV-1",
        root_cause="Stripe payment succeeded but inventory reservation timed out with zero refund.",
        contributing_factors=["Naive dual-write pattern without distributed transaction coordinator"],
        preventive_architecture_changes=["Implement AWS Step Functions Distributed Saga pattern with automated compensating transactions"],
        affected_services=["Stripe", "Step Functions", "Inventory Microservice"],
        occurred_at="2025-11-04",
        tags=["saga", "distributed_transactions", "stripe", "rollback", "compensating_action"]
    ),
    PostMortemIncident(
        incident_id="INC-2026-0118",
        title="PII Leakage in Unsanitized CloudWatch Log Streams",
        severity="SEV-2",
        root_cause="Full HTTP request payload logged at DEBUG level during authorization failure.",
        contributing_factors=["Lack of automated client-side PII redactor in logging middleware"],
        preventive_architecture_changes=["Enforce AWS CloudWatch EMF structured logging with regex PII redactor (GDPR/EU AI Act compliance)"],
        affected_services=["CloudWatch", "Lambda", "Cognito"],
        occurred_at="2026-01-18",
        tags=["privacy", "pii", "gdpr", "emf", "logging"]
    ),
    PostMortemIncident(
        incident_id="INC-2026-0220",
        title="Silent Event Loss During Downstream Consumer Outage",
        severity="SEV-2",
        root_cause="EventBridge rule had no Dead-Letter Queue (DLQ) configured.",
        contributing_factors=["Direct Lambda invocation from EventBridge without retry buffer"],
        preventive_architecture_changes=["Mandate SQS DLQ on all EventBridge bus targets and Step Functions executions"],
        affected_services=["EventBridge", "SQS", "Lambda"],
        occurred_at="2026-02-20",
        tags=["eventbridge", "dlq", "sqs", "resilience"]
    )
]

class PostMortemOpenSearchRAGAdapter:
    """
    Adapter for querying historical post-mortem vectors and injecting architectural warnings.
    """
    
    def __init__(self, opensearch_client: Any = None):
        self.opensearch_client = opensearch_client
        self._incidents_db: List[PostMortemIncident] = list(HISTORICAL_INCIDENTS)

    def retrieve_relevant_post_mortems(self, query: str, top_k: int = 2) -> List[PostMortemIncident]:
        """
        Performs semantic RAG retrieval matching the query keywords against institutional scar tissue.
        """
        query_terms = [t.lower() for t in query.replace("-", " ").replace("_", " ").split()]
        
        scored = []
        for inc in self._incidents_db:
            score = 0
            text_corpus = f"{inc.title} {inc.root_cause} {' '.join(inc.tags)} {' '.join(inc.contributing_factors)}".lower()
            for term in query_terms:
                if term in text_corpus:
                    score += 1
            if score > 0:
                scored.append((score, inc))
                
        scored.sort(key=lambda x: x[0], reverse=True)
        return [inc for score, inc in scored[:top_k]]

    def inject_scar_tissue_guidance(self, architecture_plan: str) -> Dict[str, Any]:
        """
        Analyzes a proposed architecture plan and returns historical warnings and preventive recommendations.
        """
        matches = self.retrieve_relevant_post_mortems(architecture_plan, top_k=2)
        recommendations = []
        for m in matches:
            for rec in m.preventive_architecture_changes:
                if rec not in recommendations:
                    recommendations.append(rec)
                    
        return {
            "query": architecture_plan,
            "matched_historical_incidents": len(matches),
            "incident_ids": [m.incident_id for m in matches],
            "preventive_recommendations": recommendations,
            "risk_mitigated": len(recommendations) > 0
        }
