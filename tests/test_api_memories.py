"""Integration tests for memory API behavior."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_add_search_round_trip_returns_score_breakdown(app_client: AsyncClient) -> None:
    add_response = await app_client.post(
        "/v1/memories",
        json={"text": "PhaseEightAlpha likes jasmine tea.", "user_id": "phase8-user"},
    )
    assert add_response.status_code == 200
    memory_id = add_response.json()["memory"]["id"]

    search_response = await app_client.get(
        "/v1/memories/search",
        params={"q": "What does PhaseEightAlpha like?", "user_id": "phase8-user"},
    )

    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["items"][0]["id"] == memory_id
    assert payload["items"][0]["content"] == "PhaseEightAlpha likes jasmine tea."
    assert payload["items"][0]["signals"].keys() == {"vector", "keyword", "graph"}
    assert 0.0 <= payload["items"][0]["score"] <= 1.0


async def test_soft_delete_returns_audit_trail_and_hides_memory(
    app_client: AsyncClient,
) -> None:
    added = (
        await app_client.post(
            "/v1/memories",
            json={"text": "PhaseEightBeta uses blue notebooks.", "user_id": "phase8-user"},
        )
    ).json()
    memory_id = added["memory"]["id"]

    delete_response = await app_client.delete(f"/v1/memories/{memory_id}")
    assert delete_response.status_code == 200
    deleted = delete_response.json()

    assert deleted["deleted"] is True
    assert deleted["memory"]["is_active"] is False
    assert deleted["events"][0]["event_type"] == "DELETE"
    assert deleted["events"][0]["old_content"] == "PhaseEightBeta uses blue notebooks."

    search_response = await app_client.get(
        "/v1/memories/search",
        params={"q": "What does PhaseEightBeta use?", "user_id": "phase8-user"},
    )
    assert search_response.json()["items"] == []


async def test_contradiction_add_creates_update_event(app_client: AsyncClient) -> None:
    first = (
        await app_client.post(
            "/v1/memories",
            json={"text": "PhaseEightGamma likes tea.", "user_id": "phase8-user"},
        )
    ).json()

    second_response = await app_client.post(
        "/v1/memories",
        json={"text": "PhaseEightGamma likes coffee.", "user_id": "phase8-user"},
    )
    assert second_response.status_code == 200
    second = second_response.json()

    assert second["events"][0]["event_type"] == "UPDATE"
    assert second["events"][0]["old_content"] == "PhaseEightGamma likes tea."
    assert second["memory"]["id"] != first["memory"]["id"]

    list_response = await app_client.get("/v1/memories", params={"user_id": "phase8-user"})
    assert [item["content"] for item in list_response.json()["items"]] == [
        "PhaseEightGamma likes coffee."
    ]
