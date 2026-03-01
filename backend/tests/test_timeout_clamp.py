from app.services import task_service as task_service_module


TaskService = task_service_module.TaskService


def test_simulator_timeout_clamped_to_minimum(monkeypatch):
    monkeypatch.setattr(task_service_module.settings, "task_executor", "simulator", raising=False)
    assert TaskService._normalize_timeout_for_executor(2) == 5
    assert TaskService._normalize_timeout_for_executor(60) == 60


def test_codex_timeout_clamped_to_codex_floor(monkeypatch):
    monkeypatch.setattr(task_service_module.settings, "task_executor", "codex", raising=False)
    monkeypatch.setattr(task_service_module.settings, "codex_min_timeout_seconds", 180, raising=False)
    assert TaskService._normalize_timeout_for_executor(20) == 180
    assert TaskService._normalize_timeout_for_executor(240) == 240


def test_codex_cli_timeout_clamped_to_floor(monkeypatch):
    monkeypatch.setattr(task_service_module.settings, "task_executor", "codex-cli", raising=False)
    monkeypatch.setattr(task_service_module.settings, "codex_min_timeout_seconds", 300, raising=False)
    assert TaskService._normalize_timeout_for_executor(60) == 300
