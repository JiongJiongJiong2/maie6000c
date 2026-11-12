import json

import pytest
from PIL import Image

from services.search_agent import meme_providers as providers
from services.search_agent.meme_types import Ledger, MemeSettings, PipelineError


def visual_reply():
    return {
        "observations": ["visible orange animal"],
        "entity_hypotheses": [{"name": "unknown", "confidence": 0.2, "status": "uncertain"}],
        "queries": [
            {"text": "orange animal reaction", "angle": "appearance"},
            {"text": "suspicious reaction", "angle": "emotion"},
        ],
        "evidence_relations": [{"id": "e1", "relation": "conflicts", "reason": "different animal"}],
        "user_text": "provider cannot replace actual user input",
        "evidence": [{"id": "e1", "url": "https://invented.example.org"}],
    }


def test_school_protocol_sends_image_bytes_and_only_school_header(monkeypatch):
    calls = []

    def request(method, url, ledger, **kwargs):
        calls.append(kwargs)
        assert method == "POST"
        assert url == "https://hkust.azure-api.net/hkust-genai/v1/chat/completions"
        assert kwargs["headers"] == {"api-key": "controlled-school-key"}
        body = kwargs["json"]
        assert body["model"] == "gemini-2.5-flash-lite"
        assert body["response_format"] == {"type": "json_object"}
        parts = body["messages"][0]["content"]
        assert len(parts) == 5  # at most four actual image frames
        assert all(p["image_url"]["url"].startswith("data:image/png;base64,") for p in parts[1:])
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": json.dumps(visual_reply())}}
            ]
        }

    monkeypatch.setattr(providers, "bounded_json", request)
    settings = MemeSettings(
        vision_provider="hkust",
        hkust_api_key="controlled-school-key",
        gemini_api_key="different-google-key",
    )
    ledger = Ledger(settings)
    evidence = [{"id": "e1", "url": "https://example.org/actual"}]
    client = providers.vision_client(settings, ledger)
    analysis = client.analyze([Image.new("RGB", (10, 10))] * 6, "actual optional text", evidence)
    assert analysis.user_text == "actual optional text"
    assert analysis.evidence[0]["url"] == evidence[0]["url"]
    assert analysis.evidence[0]["relation"] == "conflicts"
    assert analysis.analysis_version.startswith("hkust/gemini-2.5-flash-lite/")
    assert ledger.counts["model_calls"] == 1 and len(calls) == 1
    assert "controlled-school-key" not in repr(settings)
    assert "hkust_api_key" not in settings.model_dump()


def test_missing_school_key_never_falls_back_to_google(monkeypatch):
    monkeypatch.delenv("MEME50_HKUST_API_KEY", raising=False)
    monkeypatch.delenv("HKUST_API_KEY", raising=False)
    settings = MemeSettings(
        _env_file=None,
        vision_provider="hkust",
        hkust_api_key="",
        gemini_api_key="controlled-google-key",
    )
    ledger = Ledger(settings)
    with pytest.raises(PipelineError, match="visual_provider_unconfigured"):
        providers.vision_client(settings, ledger).analyze([Image.new("RGB", (10, 10))], "")
    assert ledger.counts["model_calls"] == 0


@pytest.mark.parametrize(
    "response",
    [
        {"choices": []},
        {"choices": [{"message": {"content": "invalid json"}}]},
        {
            "choices": [
                {"finish_reason": "length", "message": {"content": json.dumps(visual_reply())}}
            ]
        },
        {"choices": [{"message": {"content": "{}"}}]},
    ],
)
def test_bad_or_truncated_school_response_is_failure(monkeypatch, response):
    monkeypatch.setattr(providers, "bounded_json", lambda *a, **k: response)
    settings = MemeSettings(vision_provider="hkust", hkust_api_key="controlled-test")
    with pytest.raises(PipelineError, match="visual_response_invalid"):
        providers.vision_client(settings, Ledger(settings)).analyze(
            [Image.new("RGB", (10, 10))], ""
        )


def test_school_http200_error_does_not_pass_or_leak_vendor_message(monkeypatch):
    monkeypatch.setattr(
        providers,
        "bounded_json",
        lambda *a, **k: {"error": {"code": "credit_exhausted", "message": "secret echoed here"}},
    )
    settings = MemeSettings(vision_provider="hkust", hkust_api_key="controlled-test")
    ledger = Ledger(settings)
    with pytest.raises(PipelineError, match="visual_service_error") as caught:
        providers.vision_client(settings, ledger).analyze([Image.new("RGB", (10, 10))], "")
    assert "secret" not in json.dumps(caught.value.diagnostic)
    assert "secret" not in json.dumps(ledger.trace)


def test_visual_identity_without_web_evidence_cannot_mark_itself_supported(monkeypatch):
    response = visual_reply()
    response["entity_hypotheses"][0].update(status="supported", confidence=0.99)
    monkeypatch.setattr(
        providers,
        "bounded_json",
        lambda *a, **k: {
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response)}}]
        },
    )
    settings = MemeSettings(vision_provider="hkust", hkust_api_key="controlled-test")
    result = providers.vision_client(settings, Ledger(settings)).analyze(
        [Image.new("RGB", (10, 10))], ""
    )
    assert result.entity_hypotheses[0].status == "uncertain"
