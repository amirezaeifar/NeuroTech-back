from io import BytesIO

from tests.api.test_content_management import _admin


def test_product_details_and_uploaded_gallery_are_public(client, app):
    from app.services.seed import seed_catalog_and_events

    seed_catalog_and_events(app.extensions["container"])
    headers = _admin(client, app)
    product = client.get("/api/v1/admin/products").json["data"][0]
    for tr in product["translations"]:
        tr["details"] = {
            "specs": [{"label": "Channels", "value": "64"}],
            "certs": [],
            "keyFeatures": ["Custom feature"],
        }
    result = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        headers=headers,
        json={"translations": product["translations"]},
    )
    assert result.status_code == 200
    public = client.get(f"/api/v1/products/{product['slug']}").json["data"]
    assert public["details"]["specs"][0]["value"] == "64"
    assert public["details"]["certs"] == []


def test_course_summary_images_and_curriculum_round_trip(client, app):
    from app.services.seed import seed_academy

    seed_academy(app.extensions["container"])
    headers = _admin(client, app)
    course = client.get("/api/v1/admin/courses").json["data"][0]
    url = f"/api/v1/admin/courses/{course['id']}"
    for translation in course["translations"]:
        translation["summary"] = "Custom summary"
    assert (
        client.patch(
            url, headers=headers, json={"translations": course["translations"]}
        ).status_code
        == 200
    )
    upload = client.post(
        "/api/v1/admin/files",
        headers=headers,
        data={"file": (BytesIO(b"\x89PNG\r\n\x1a\nimage"), "cover.png"), "is_public": "true"},
    )
    assert upload.status_code == 201
    assert client.post(url + "/unpublish", headers=headers).status_code == 200
    content = course["content"]
    for section in content["sections"]:
        section.pop("id", None)
        for lesson in section["lessons"]:
            lesson.pop("id", None)
    content["media"] = [
        {"kind": "cover_light", "position": 1, "storage_path": upload.json["data"]["url"]}
    ]
    assert client.put(url + "/content", headers=headers, json=content).status_code == 200
    assert client.post(url + "/publish", headers=headers).status_code == 200
    public = client.get(f"/api/v1/courses/{course['slug']}").json["data"]
    assert public["summary"] == "Custom summary"
    assert public["images"][0]["url"] == upload.json["data"]["url"]
    assert public["sections"][0]["lessons"]
