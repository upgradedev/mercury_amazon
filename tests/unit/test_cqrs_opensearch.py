"""Unit tests for Bedrock Knowledge Base & OpenSearch Serverless CQRS adapter."""
import pytest
from src.infrastructure.cqrs_opensearch_adapter import BedrockKnowledgeBaseCQRSAdapter


def test_vector_indexing():
    adapter = BedrockKnowledgeBaseCQRSAdapter("test-collection")
    vdoc = adapter.index_document("doc_01", "Architecture decision: Open port 443 with 300s lease", {"author": "marcus"})
    assert vdoc.doc_id == "doc_01"
    assert vdoc.embedding_dimension == 1536
    assert len(vdoc.vector_sample) == 8


def test_semantic_similarity_query():
    adapter = BedrockKnowledgeBaseCQRSAdapter()
    adapter.index_document("doc_01", "Decision regarding TLS port 443 configuration", {"system": "auth"})
    adapter.index_document("doc_02", "Grocery shopping list: milk and bread", {"system": "kitchen"})

    results = adapter.semantic_similarity_query("port 443 TLS")
    assert len(results) >= 1
    assert results[0]["doc_id"] == "doc_01"
    assert results[0]["score"] > 0.90
