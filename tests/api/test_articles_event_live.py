"""Article sections and reservation-gated live activity."""

from tests.api.test_catalog_events_files import _event_payload
from tests.api.test_content_management import _admin
from tests.api.test_governance import _blog, _staff


def test_article_categories_and_seo_metadata(client, app):
    headers = _admin(client, app)
    scientific = _blog("new-study", "New study")
    scientific["category"] = "scientific"
    scientific["cover_alt"] = "MRI image"
    scientific["translations"][0]["seo_title"] = "Brain research update"
    created = client.post("/api/v1/admin/blog", headers=headers, json=scientific)
    assert created.status_code == 201
    post_id = created.json["data"]["id"]
    assert client.post(f"/api/v1/admin/blog/{post_id}/publish", headers=headers).status_code == 200
    listing = client.get("/api/v1/blog?category=scientific&locale=en")
    assert [post["slug"] for post in listing.json["data"]] == ["new-study"]
    assert client.get("/api/v1/blog?category=blog&locale=en").json["data"] == []
    detail = client.get("/api/v1/blog/new-study?locale=en").json["data"]
    assert detail["seo_title"] == "Brain research update"
    assert detail["cover_alt"] == "MRI image"


def test_live_room_requires_reservation_and_persists_activity(client, app):
    headers = _admin(client, app)
    payload = _event_payload()
    payload["status"] = "live"
    payload["agenda_steps"] = ["Introduction", "Discussion"]
    created = client.post("/api/v1/admin/events", headers=headers, json=payload)
    assert created.status_code == 201
    event_id = created.json["data"]["id"]
    assert (
        client.post(f"/api/v1/admin/events/{event_id}/publish", headers=headers).status_code == 200
    )
    assert client.get("/api/v1/events/brain-health-day").json["data"]["online_url"] is None

    viewer = app.test_client()
    viewer_headers = _staff(viewer, app, "user")
    path = "/api/v1/events/brain-health-day/live"
    assert viewer.get(path).status_code == 403
    assert (
        viewer.post(
            "/api/v1/events/brain-health-day/reservations", headers=viewer_headers
        ).status_code
        == 202
    )
    from tests.api.test_event_management import confirm_latest
    assert confirm_latest(viewer, app).status_code == 200
    assert viewer.get(path).json["data"]["viewer_count"] == 1
    question = viewer.post(
        f"{path}/questions", headers=viewer_headers, json={"body": "What is next?"}
    )
    assert question.status_code == 201
    question_id = question.json["data"]["id"]
    assert (
        viewer.post(f"{path}/questions/{question_id}/vote", headers=viewer_headers).json["data"][
            "voted"
        ]
        is True
    )
    assert (
        viewer.post(f"{path}/messages", headers=viewer_headers, json={"body": "Hello"}).status_code
        == 201
    )
    assert viewer.post(f"{path}/step", headers=viewer_headers, json={"step": 1}).status_code == 403
    assert client.post(f"{path}/step", headers=headers, json={"step": 1}).status_code == 200
    assert client.post(f"{path}/questions/{question_id}/answer", headers=headers).status_code == 200
    state = viewer.get(path).json["data"]
    assert state["event"]["current_step"] == 1
    assert state["questions"][0]["votes"] == 1
    assert state["questions"][0]["answered"] is True
    assert state["messages"][0]["body"] == "Hello"
