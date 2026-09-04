"""
Unit tests for DynamicRecommendationEngine.
"""
from src.domain.recommendation_invalidator import DynamicRecommendationEngine, EvidenceContract

def test_dynamic_recommendation_auto_withdrawal():
    engine = DynamicRecommendationEngine()
    contract = EvidenceContract(metric_name="LambdaErrorRate", safe_threshold=2.0, comparison="less_than")
    
    engine.register_recommendation("rec-roll-1", "Initiate Step Functions Rollback", contract)
    
    # 1. Error rate high (5.2%) -> Active
    res1 = engine.evaluate_liveness("rec-roll-1", 5.2)
    assert res1["status"] == "ACTIVE"
    
    # 2. Error rate self-heals to 0.8% -> Auto-withdrawn
    res2 = engine.evaluate_liveness("rec-roll-1", 0.8)
    assert res2["status"] == "WITHDRAWN"
    assert "Telemetry self-resolved" in res2["reason"]
