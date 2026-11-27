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
