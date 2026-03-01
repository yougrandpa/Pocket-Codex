#!/usr/bin/env python3
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.main import app


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing env var {name} for regression test")
    return value


def main() -> None:
    username = required_env("APP_USERNAME")
    password = required_env("APP_PASSWORD")

    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 55000)) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
            headers={"X-Real-IP": "127.0.0.1"},
        )
        assert_true(login.status_code == 200, f"login failed: {login.status_code} {login.text}")
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        created_ids: list[str] = []
        options = client.get("/api/v1/tasks/executor/options", headers=headers)
        assert_true(options.status_code == 200, f"executor options failed: {options.text}")
        for index in range(3):
            created = client.post(
                "/api/v1/tasks",
                headers=headers,
                json={
                    "prompt": f"regression pagination task {index}",
                    "priority": 5,
                    "timeout_seconds": 20,
                    "model": "gpt-5-codex",
                    "reasoning_effort": "medium",
                    "enable_parallel_agents": index % 2 == 0,
                },
            )
            assert_true(created.status_code == 201, f"create task failed: {created.status_code} {created.text}")
            created_ids.append(created.json()["id"])

        first_page = client.get("/api/v1/tasks?limit=2&offset=0", headers=headers)
        assert_true(first_page.status_code == 200, f"task list page1 failed: {first_page.text}")
        first_payload = first_page.json()
        assert_true(first_payload.get("limit") == 2, f"unexpected task page limit: {first_payload}")
        assert_true(first_payload.get("offset") == 0, f"unexpected task page offset: {first_payload}")
        assert_true(first_payload.get("total", 0) >= 3, f"unexpected task total: {first_payload}")
        assert_true(len(first_payload.get("items", [])) == 2, f"expected 2 items on page1: {first_payload}")

        second_page = client.get("/api/v1/tasks?limit=2&offset=2", headers=headers)
        assert_true(second_page.status_code == 200, f"task list page2 failed: {second_page.text}")
        second_payload = second_page.json()
        assert_true(second_payload.get("offset") == 2, f"unexpected task page2 offset: {second_payload}")
        assert_true(len(second_payload.get("items", [])) >= 1, f"expected at least 1 item on page2: {second_payload}")

        target_task_id = created_ids[0]
        appended = client.post(
            f"/api/v1/tasks/{target_task_id}/message",
            headers=headers,
            json={"message": "regression follow-up"},
        )
        assert_true(appended.status_code == 200, f"append message failed: {appended.status_code} {appended.text}")

        actor_filtered = client.get(
            "/api/v1/tasks/audit/logs?limit=20&offset=0&actor=" + username,
            headers=headers,
        )
        assert_true(actor_filtered.status_code == 200, f"actor filter failed: {actor_filtered.text}")
        actor_payload = actor_filtered.json()
        assert_true(actor_payload.get("total", 0) > 0, f"actor filter empty: {actor_payload}")
        assert_true(
            all(username in (item.get("actor") or "") for item in actor_payload.get("items", [])),
            f"actor filter mismatch: {actor_payload}",
        )

        action_filtered = client.get(
            "/api/v1/tasks/audit/logs?limit=20&offset=0&action=task.message.append",
            headers=headers,
        )
        assert_true(action_filtered.status_code == 200, f"action filter failed: {action_filtered.text}")
        action_payload = action_filtered.json()
        assert_true(action_payload.get("total", 0) >= 1, f"action filter empty: {action_payload}")
        assert_true(
            all("task.message.append" in (item.get("action") or "") for item in action_payload.get("items", [])),
            f"action filter mismatch: {action_payload}",
        )

        task_filtered = client.get(
            f"/api/v1/tasks/audit/logs?limit=20&offset=0&task_id={target_task_id[:10]}",
            headers=headers,
        )
        assert_true(task_filtered.status_code == 200, f"task_id filter failed: {task_filtered.text}")
        task_payload = task_filtered.json()
        assert_true(task_payload.get("total", 0) >= 1, f"task_id filter empty: {task_payload}")
        assert_true(
            all(target_task_id[:10] in (item.get("task_id") or "") for item in task_payload.get("items", [])),
            f"task_id filter mismatch: {task_payload}",
        )

    print("task api regression test passed")


if __name__ == "__main__":
    main()
