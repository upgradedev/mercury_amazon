"""Unit tests for Amazon SageMaker Real-Time Inference Adapter."""
import pytest
from src.infrastructure.sagemaker_inference_adapter import (
    SageMakerEndpointAdapter,
    SageMakerInferenceResponse,
)


def test_sagemaker_endpoint_invocation():
    adapter = SageMakerEndpointAdapter(endpoint_name="ambient-vad-classifier-v1")
    payload = {
        "audio_frames_b64": "AAAA////",
        "intent": "doorbell_arrival",
        "entities": {"source": "ring_doorbell"},
    }
    res = adapter.invoke_endpoint(payload)

    assert isinstance(res, SageMakerInferenceResponse)
    assert res.endpoint_name == "ambient-vad-classifier-v1"
    assert res.prediction["intent"] == "doorbell_arrival"
    assert res.confidence >= 0.95
    assert res.latency_ms < 25.0
    assert res.is_fallback is True


def test_sagemaker_empty_payload_rejected():
    adapter = SageMakerEndpointAdapter(endpoint_name="test-endpoint")
    with pytest.raises(ValueError, match="cannot be empty"):
        adapter.invoke_endpoint({})
