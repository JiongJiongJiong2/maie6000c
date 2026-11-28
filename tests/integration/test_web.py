import pytest

from services.common.config import get_settings


def test_client_and_assets_are_served_without_shadowing_api(client):
    page = client.get("/web/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "MemeRetrieve" in page.text
    assert 'src="./app.js"' in page.text
    for asset in ("app.js", "api.js", "store.js", "meme50.js", "share.js", "styles.css"):
        response = client.get(f"/web/{asset}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        expected_type = "text/css" if asset.endswith(".css") else "text/javascript"
        assert response.headers["content-type"].split(";")[0] == expected_type
    for name in ("cmunrm.woff", "cmunbx.woff"):
        font = client.get(f"/web/fonts/{name}")
        assert font.status_code == 200
        assert font.content.startswith(b"wOFF")
    assert client.get("/web/fonts/private.txt").status_code == 404
    assert client.get("/").json()["service"] == "api"
    assert client.get("/health/live").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_web_publishes_only_beta_controls_and_feedback_link(client, monkeypatch):
    monkeypatch.setenv("ACCOUNT_LOGIN_ENABLED", "false")
    monkeypatch.setenv("PUBLIC_BETA_ENABLED", "true")
    monkeypatch.setenv("ONLINE_SEARCH_ENABLED", "false")
    monkeypatch.setenv("BETA_INVITE_CODE", "private-invite-fixture")
    monkeypatch.setenv("BETA_FEEDBACK_URL", "https://feedback.example/form?a=1&b=2")
    get_settings.cache_clear()
    page = client.get("/web/").text
    login = client.get("/web/sign-in").text
    assert "data-local-first" in page and "data-online-disabled" in page
    assert "data-invite-required" in login
    for content in (page, login):
        assert "private-invite-fixture" not in content
        assert 'href="https://feedback.example/form?a=1&amp;b=2"' in content
        assert "data-beta-feedback hidden" not in content
        assert 'rel="noopener noreferrer"' in content


@pytest.mark.parametrize(
    "feedback_url", ["", "not a URL", "http://example.org", "https://user:pw@example.org/"]
)
def test_unconfigured_or_invalid_feedback_stays_hidden(client, monkeypatch, feedback_url):
    monkeypatch.setenv("PUBLIC_BETA_ENABLED", "false")
    monkeypatch.setenv("ONLINE_SEARCH_ENABLED", "true")
    monkeypatch.setenv("BETA_INVITE_CODE", "")
    monkeypatch.setenv("BETA_FEEDBACK_URL", feedback_url)
    get_settings.cache_clear()
    page = client.get("/web/").text
    login = client.get("/web/sign-in").text
    assert "data-local-first" not in page and "data-online-disabled" not in page
    assert "data-invite-required" not in login
    for content in (page, login):
        assert "data-beta-feedback hidden" in content and "data-feedback-link" in content
        if feedback_url:
            assert feedback_url not in content


def test_web_does_not_expose_sources_or_test_files(client):
    assert client.get("/web/README.md").status_code == 404
    assert client.get("/web/package.json").status_code == 404
    assert client.get("/web/../.env").status_code == 404
    assert client.get("/web/tests/example.js").status_code == 404


def test_module_types_do_not_depend_on_windows_registry(client, monkeypatch):
    import mimetypes

    mimetypes.init()
    monkeypatch.setitem(mimetypes.types_map, ".js", "text/plain")
    for asset in ("app.js", "api.js", "store.js", "meme50.js", "share.js"):
        response = client.get(f"/web/{asset}")
        assert response.status_code == 200
        assert response.headers["content-type"].split(";")[0] == "text/javascript"


def test_whatsapp_experiment_assets_have_explicit_types(client, monkeypatch, tmp_path):
    from services.api.app import web

    for asset, content_type in (
        ("whatsapp-import.html", "text/html"),
        ("whatsapp-import.js", "text/javascript"),
    ):
        response = client.get(f"/web/{asset}")
        assert response.status_code == 200
        assert response.headers["content-type"].split(";")[0] == content_type
    # A fresh checkout has no generated pack: it must fail cleanly, not with 500.
    monkeypatch.setattr(web, "WEB_ROOT", tmp_path)
    assert client.get("/web/whatsapp-demo-pack.json").status_code == 404
    (tmp_path / "whatsapp-demo-pack.json").write_text("{}", encoding="utf-8")
    response = client.get("/web/whatsapp-demo-pack.json")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == "application/json"
