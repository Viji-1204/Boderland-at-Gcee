"""Round 1 login system, token separation, throttling, WebSocket auth."""
from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.helpers import key, seed

API = "/api/v1"


def test_team_login_round1_style(client):
    demo = seed(client)
    ok = client.post(f"{API}/auth/team/login", json={"team_code": "b@gcee-1001#", "password": "9840"})  # code is case-insensitive
    assert ok.status_code == 200 and ok.json()["team_name"] == "Dragon Warriors"
    bad = client.post(f"{API}/auth/team/login", json={"team_code": "B@GCEE-1001#", "password": "0000"})
    assert bad.status_code == 401 and bad.json()["detail"] == "Invalid team code or password"
    assert demo.event_id == ok.json()["event_id"]


def test_login_is_throttled_after_repeated_failures(client):
    seed(client)
    for _ in range(8):
        client.post(f"{API}/auth/team/login", json={"team_code": "B@GCEE-1002#", "password": "0000"})
    blocked = client.post(f"{API}/auth/team/login", json={"team_code": "B@GCEE-1002#", "password": "9841"})
    assert blocked.status_code == 429


def test_tokens_cannot_cross_roles(client):
    demo = seed(client)
    team_headers = demo.teams["Dragon Warriors"]["headers"]
    assert client.get(f"{API}/admin/event", headers=team_headers).status_code == 401
    assert client.get(f"{API}/me/state", headers=demo.admin).status_code == 401
    assert client.get(f"{API}/me/state").status_code == 401


def test_coordinator_role_limits(client):
    demo = seed(client)
    res = client.post(f"{API}/admin/admins", json={"username": "coord1", "password": "secret1", "role": "COORDINATOR"}, headers=demo.admin)
    assert res.status_code == 201
    login = client.post(f"{API}/auth/admin/login", json={"username": "coord1", "password": "secret1"}).json()
    coord = {"Authorization": f"Bearer {login['access_token']}"}
    assert client.get(f"{API}/admin/events/{demo.event_id}/dashboard", headers=coord).status_code == 200
    assert client.get(f"{API}/admin/admins", headers=coord).status_code == 403
    assert client.get(f"{API}/admin/event", headers=coord).status_code == 200  # the one game is theirs to run
    # deactivation takes effect immediately, even for an issued token
    admin_id = res.json()["admin_id"]
    assert client.delete(f"{API}/admin/admins/{admin_id}", headers=demo.admin).status_code == 204
    assert client.get(f"{API}/admin/event", headers=coord).status_code == 401


def test_websocket_rejects_bad_tokens(client):
    with client.websocket_connect("/ws/team?token=not-a-token") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4001


def test_websocket_pushes_attack_to_target_only(client):
    demo = seed(client, start=True)
    attacker, target = demo.teams["Dragon Warriors"], demo.teams["Border Runners"]
    target_token = target["headers"]["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/team?token={target_token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post(f"{API}/powers/attack", json={"target_team_id": target["id"], "idempotency_key": key()}, headers=attacker["headers"])
        seen = []
        for _ in range(6):
            message = ws.receive_json()
            seen.append(message["type"])
            if message["type"] == "attack_incoming":
                assert message["usage_id"] and message["expires_at"]
                assert "Dragon" not in str(message)
                break
        assert "attack_incoming" in seen


def test_admin_websocket_needs_admin_token(client):
    demo = seed(client)
    team_token = demo.teams["Dragon Warriors"]["headers"]["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/admin?token={team_token}&event_id={demo.event_id}") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4001
    admin_token = demo.admin["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/admin?token={admin_token}&event_id={demo.event_id}") as ws:
        assert ws.receive_json()["type"] == "hello"
