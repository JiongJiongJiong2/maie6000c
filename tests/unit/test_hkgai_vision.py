import base64
from io import BytesIO
import json

import pytest
from PIL import Image

from services.search_agent import meme_providers as providers
from services.search_agent.meme_types import Ledger, MemeSettings, PipelineError


def hkgai_settings(**values):
    return MemeSettings(
        _env_file=None, provider_policy="hkgai-deepseek-v1", vision_provider="hkgai", **values
    )


def visual_reply():
    return {
        "observations": ["visible orange circle"],
        "ocr_text": "ORANGE",
        "queries": [
            {"text": "orange circle icon", "angle": "visual_description"},
            {"text": "orange dot with caption", "angle": "caption"},
        ],
    }


@pytest.mark.parametrize("fenced", [False, True])
def test_hkgai_uses_only_its_bearer_key_and_returns_traced_analysis(monkeypatch, fenced):
    def request(method, url, ledger, *, headers, json):
        assert method == "POST"
        assert url == "https://api1.hkgai.net/v1/chat/completions"
        assert headers == {"Authorization": "Bearer controlled-hkgai-key"}
        assert json["model"] == "t2_hkgai-v3_fp8_1m_e10"
        assert json["stream"] is False
        assert json["chat_template_kwargs"] == {"enable_thinking": False}
        assert "response_format" not in json
        parts = json["messages"][0]["content"]
        assert len(parts) == 5
        for part in parts[1:]:
            scheme, encoded = part["image_url"]["url"].split(",", 1)
            assert scheme == "data:image/png;base64"
            with Image.open(BytesIO(base64.b64decode(encoded))) as image:
                assert image.getpixel((0, 0)) == (255, 165, 0)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": content, "reasoning_content": "ignored reasoning"},
                }
            ]
        }

    content = json.dumps(visual_reply())
    if fenced:
        content = f"```json\n{content}\n```"
    monkeypatch.setattr(providers, "bounded_json", request)
    settings = hkgai_settings(
        hkgai_api_key="controlled-hkgai-key", hkust_api_key="unrelated-school-key"
    )
    ledger = Ledger(settings)
    analysis = providers.vision_client(settings, ledger).analyze(
        [Image.new("RGB", (10, 10), "orange")] * 6, "actual preference"
    )
    assert analysis.user_text == "actual preference"
    assert analysis.ocr_text == "ORANGE"
    assert analysis.ocr_provider == "hkgai-visible-text"
    assert analysis.analysis_version.startswith(f"hkgai/{settings.effective_vision_model}/")
    assert ledger.counts["model_calls"] == 1
    assert ledger.trace[0]["details"] == {
        "provider": "hkgai",
        "model": "t2_hkgai-v3_fp8_1m_e10",
        "provider_policy": "hkgai-deepseek-v1",
    }
    assert "controlled-hkgai-key" not in repr(settings)
    assert "hkgai_api_key" not in settings.model_dump()


def test_hkgai_key_is_read_from_its_designated_environment(monkeypatch):
    monkeypatch.setenv("HKGAI_API_KEY", "alias-key")
    assert hkgai_settings().hkgai_api_key.get_secret_value() == "alias-key"
    monkeypatch.setenv("MEME50_HKGAI_API_KEY", "meme-only-key")
    assert hkgai_settings().hkgai_api_key.get_secret_value() == "meme-only-key"
    settings = hkgai_settings(hkgai_api_key="explicit-key")
    assert settings.hkgai_api_key.get_secret_value() == "explicit-key"


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"hkust_api_key": "unrelated-school-key"}, "visual_provider_unconfigured"),
        ({"hkgai_api_key": "own-key", "hkgai_model": "../unexpected"}, "visual_model_config"),
    ],
)
def test_hkgai_invalid_configuration_is_rejected_before_using_the_budget(values, error):
    settings = hkgai_settings(**values)
    ledger = Ledger(settings)
    with pytest.raises(PipelineError, match=error):
        providers.vision_client(settings, ledger).analyze([], "")
    assert ledger.counts["model_calls"] == 0
    assert not ledger.trace


@pytest.mark.parametrize(
    ("provider_policy", "vision_provider"),
    [("hkust-deepseek-v1", "hkgai"), ("hkgai-deepseek-v1", "hkust")],
)
def test_mismatched_vision_policy_is_rejected(provider_policy, vision_provider):
    settings = MemeSettings(provider_policy=provider_policy, vision_provider=vision_provider)
    with pytest.raises(PipelineError, match="provider_policy_violation"):
        providers.vision_client(settings, Ledger(settings))


@pytest.mark.parametrize(
    "response",
    [{"finish_reason": "length", "message": {"content": "{}"}}, {"message": {"content": None}}],
)
def test_hkgai_rejects_nonfinal_or_malformed_output(monkeypatch, response):
    monkeypatch.setattr(providers, "bounded_json", lambda *a, **k: {"choices": [response]})
    settings = hkgai_settings(hkgai_api_key="own-key")
    with pytest.raises(PipelineError, match="visual_response_invalid"):
        providers.vision_client(settings, Ledger(settings)).analyze([], "")
