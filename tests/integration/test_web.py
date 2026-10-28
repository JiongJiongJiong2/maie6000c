def test_client_and_assets_are_served_without_shadowing_api(client):
    page = client.get("/web/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "MemeRetrieve" in page.text
    assert 'src="./app.js"' in page.text
    for asset in ("app.js", "api.js", "store.js", "styles.css"):
        response = client.get(f"/web/{asset}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
    assert client.get("/").json()["service"] == "api"
    assert client.get("/health/live").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_web_does_not_expose_sources_or_test_files(client):
    assert client.get("/web/README.md").status_code == 404
    assert client.get("/web/package.json").status_code == 404
    assert client.get("/web/../.env").status_code == 404
    assert client.get("/web/tests/example.js").status_code == 404
