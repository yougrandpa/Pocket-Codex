#!/usr/bin/env python3
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as local_client:
        login_response = local_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert_true(login_response.status_code == 200, f"local login failed: {login_response.text}")
        token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(
        app,
        base_url="http://172.20.10.11:8000",
        client=("172.20.10.1", 50001),
    ) as remote_client:
        direct_login = remote_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert_true(
            direct_login.status_code == 403,
            f"remote direct login should be forbidden: {direct_login.status_code} {direct_login.text}",
        )

        preflight = remote_client.options(
            "/api/v1/auth/mobile/request",
            headers={
                "Origin": "http://172.20.10.11:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert_true(preflight.status_code == 200, f"preflight failed: {preflight.text}")
        assert_true(
            preflight.headers.get("access-control-allow-origin") == "http://172.20.10.11:3000",
            f"unexpected CORS allow-origin: {preflight.headers.get('access-control-allow-origin')}",
        )

        mobile_request = remote_client.post(
            "/api/v1/auth/mobile/request",
            json={
                "username": "admin",
                "password": "admin123",
                "device_name": "iphone-regression",
            },
            headers={"Origin": "http://172.20.10.11:3000"},
        )
        assert_true(
            mobile_request.status_code == 200,
            f"mobile request failed: {mobile_request.status_code} {mobile_request.text}",
        )
        request_id = mobile_request.json()["request_id"]

    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50002)) as local_client:
        pending = local_client.get("/api/v1/auth/mobile/pending", headers=headers)
        assert_true(pending.status_code == 200, f"pending list failed: {pending.text}")
        pending_ids = [item["request_id"] for item in pending.json().get("items", [])]
        assert_true(request_id in pending_ids, "pending request not listed")

        approve = local_client.post(f"/api/v1/auth/mobile/requests/{request_id}/approve", headers=headers)
        assert_true(approve.status_code == 200, f"approve failed: {approve.text}")

    with TestClient(
        app,
        base_url="http://172.20.10.11:8000",
        client=("172.20.10.1", 50003),
    ) as remote_client:
        payload = {}
        for _ in range(6):
            poll = remote_client.get(f"/api/v1/auth/mobile/requests/{request_id}")
            assert_true(poll.status_code == 200, f"poll failed: {poll.text}")
            payload = poll.json()
            if payload.get("status") == "COMPLETED":
                break
            time.sleep(0.1)
        assert_true(payload.get("status") == "COMPLETED", f"unexpected status: {payload}")
        assert_true(bool(payload.get("access_token")), "missing access_token")
        assert_true(bool(payload.get("refresh_token")), "missing refresh_token")

    print("mobile auth flow regression test passed")


if __name__ == "__main__":
    main()
