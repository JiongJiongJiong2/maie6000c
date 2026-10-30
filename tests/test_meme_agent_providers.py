import httpx
import pytest
from types import SimpleNamespace
from services.meme_agent import providers, media
import io
import unittest
from unittest.mock import patch
from PIL import Image
from services.meme_agent.media import inspect_image, validate_url, MediaError


class MediaTests(unittest.TestCase):
    def test_real_decode(self):
        output = io.BytesIO()
        Image.new("RGB", (8, 9)).save(output, format="PNG")
        self.assertEqual(inspect_image(output.getvalue())["width"], 8)
        with self.assertRaises(MediaError):
            inspect_image(b"<html>not an image</html>")

    def test_private_and_untrusted_hosts_rejected(self):
        for url in [
            "https://127.0.0.1/a.png",
            "http://i.imgflip.com/a.png",
            "https://user:password@i.imgflip.com/a.png",
            "https://evil.example/a.png",
        ]:
            with self.assertRaises(MediaError):
                validate_url(url)
        with patch(
            "services.meme_agent.media.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
        ):
            with self.assertRaises(MediaError):
                validate_url("https://i.imgflip.com/a.png")


def settings(key=""):
    return SimpleNamespace(
        deepseek_api_key=key,
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-flash",
        brave_api_key="test",
    )


def test_local_alias_and_no_fabricated_matches(monkeypatch):
    monkeypatch.setattr(providers, "get_agent_settings", settings)
    assert "Two Buttons" in providers.plan_query("两个按钮")["queries"]
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://api.imgflip.com"),
        json={
            "data": {
                "memes": [{"name": "Two Buttons", "id": "1", "url": "https://i.imgflip.com/a.png"}]
            }
        },
    )
    monkeypatch.setattr(providers.httpx, "get", lambda *a, **kw: response)
    assert providers.search_templates(providers.plan_query("fabricatedxyz")) == []
    assert providers.search_templates(providers.plan_query("两个按钮"))[0]["editable"]


@pytest.mark.parametrize(
    "payload",
    [None, {"queries": "bad"}, {"queries": [123]}, {"queries": ["valid"], "keywords": False}],
)
def test_invalid_planner_json_falls_back(monkeypatch, payload):
    monkeypatch.setattr(providers, "get_agent_settings", lambda: settings("secret"))
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://api.deepseek.com"),
        json={"choices": [{"message": {"content": __import__("json").dumps(payload)}}]},
    )
    monkeypatch.setattr(providers.httpx, "post", lambda *a, **kw: response)
    result = providers.plan_query("两个按钮")
    assert result["warnings"]
    assert "secret" not in str(result)


def test_auth_error_is_safe(monkeypatch):
    monkeypatch.setattr(providers, "get_agent_settings", lambda: settings("secret"))
    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://api.deepseek.com"),
        text="secret credential error",
    )
    monkeypatch.setattr(providers.httpx, "post", lambda *a, **kw: response)
    result = providers.plan_query("drake")
    assert result["planner"] == "local aliases"
    assert "secret" not in str(result)


def test_brave_uses_original_image(monkeypatch):
    monkeypatch.setattr(providers, "get_agent_settings", settings)
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://api.search.brave.com"),
        json={
            "results": [
                {
                    "title": "x",
                    "url": "https://example.com/page",
                    "thumbnail": {"src": "https://example.com/thumb"},
                    "properties": {"url": "https://i.imgur.com/original.png"},
                }
            ]
        },
    )
    monkeypatch.setattr(providers.httpx, "get", lambda *a, **kw: response)
    assert (
        providers.search_web({"queries": ["x"]})[0]["image_url"]
        == "https://i.imgur.com/original.png"
    )


def test_pixel_and_byte_limits(monkeypatch):
    output = io.BytesIO()
    Image.new("RGB", (8, 9)).save(output, format="PNG")
    monkeypatch.setattr(media, "MAX_PIXELS", 10)
    with pytest.raises(MediaError):
        inspect_image(output.getvalue())
    monkeypatch.setattr(media, "MAX_BYTES", 1)
    with pytest.raises(MediaError):
        inspect_image(output.getvalue())


def test_no_substring_noise_and_strong_family(monkeypatch):
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://api.imgflip.com"),
        json={
            "data": {
                "memes": [
                    dict(name=name, id="1", url="https://i.imgflip.com/a.png")
                    for name in ["UNO Draw 25", "Drake Hotline Bling", "Drake"]
                ]
            }
        },
    )
    monkeypatch.setattr(providers.httpx, "get", lambda *a, **kw: response)
    result = providers.search_templates(
        {"queries": ["Drake Hotline Bling"], "keywords": ["no", "drake"]}
    )
    assert [item["title"] for item in result] == ["Drake Hotline Bling"]


def test_partial_invalid_plan_does_not_mutate_fallback(monkeypatch):
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://api.deepseek.com"),
        json={"choices": [{"message": {"content": '{"queries":["injected"],"keywords":false}'}}]},
    )
    monkeypatch.setattr(providers.httpx, "post", lambda *a, **kw: response)
    result = providers.plan_query("drake", settings=settings("secret"))
    assert "injected" not in result["queries"]
    assert result["planner"] == "local aliases"


def test_redirect_target_is_revalidated(monkeypatch):
    real_client = httpx.Client
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://127.0.0.1/private"})

    monkeypatch.setattr(
        media.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr(
        media.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )
    with pytest.raises(MediaError):
        media.download_image("https://i.imgflip.com/a.png")
    assert len(visited) == 1


def test_download_rejects_html_and_oversized_image(monkeypatch):
    real_client = httpx.Client
    monkeypatch.setattr(
        media.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )
    for content_type, body in [("text/html", b"<html>"), ("image/png", b"x" * 20)]:

        def handler(request):
            return httpx.Response(200, headers={"content-type": content_type}, content=body)

        monkeypatch.setattr(
            media.httpx,
            "Client",
            lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
        )
        monkeypatch.setattr(media, "MAX_BYTES", 10)
        with pytest.raises(MediaError):
            media.download_image("https://i.imgflip.com/a.png")


def test_malformed_provider_entries_are_skipped(monkeypatch):
    payloads = [
        {"data": {"memes": [None, {"name": None}, {"name": "Drake", "url": None}]}},
        {"results": [None, {"properties": None}, {"properties": {"url": {}}}]},
    ]
    for provider, payload in zip(
        [providers.search_templates, providers.search_web], payloads, strict=True
    ):
        response = httpx.Response(
            200, request=httpx.Request("GET", "https://example.com"), json=payload
        )
        monkeypatch.setattr(providers.httpx, "get", lambda *a, **kw: response)
        monkeypatch.setattr(providers, "get_agent_settings", settings)
        assert provider({"queries": ["drake"]}) == []


def test_model_queries_survive_full_fallback_plan(monkeypatch):
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://api.deepseek.com"),
        json={
            "choices": [
                {
                    "message": {
                        "content": '{"queries":["Distracted Boyfriend"],"keywords":["distracted"]}'
                    }
                }
            ]
        },
    )
    monkeypatch.setattr(providers.httpx, "post", lambda *a, **kw: response)
    plan = providers.plan_query("drake 两个按钮 这很好 男友", settings=settings("secret"))
    assert plan["queries"][0] == "Distracted Boyfriend"
    assert len(plan["queries"]) <= 4
