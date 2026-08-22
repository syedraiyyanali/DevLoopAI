from fastapi.testclient import TestClient

from app.api.v1.endpoints import task_execution as task_endpoint
from app.main import app
from app.models.execution_verification import ExecutionVerificationResult
from app.services.execution_handoff import ExecutionHandoffService
from app.services.execution_mutation import ExecutionMutationService
from app.services.execution_preflight import ExecutionPreflightService
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionStore
from app.services.execution_verification import ExecutionVerificationRunner
from app.services.git_commit import GitCommitStore
from app.services.planning_approval import PlanningApprovalStore
from app.services.task_execution import ControlledTaskExecutionService
from app.services.task_execution_store import TaskExecutionStore
from app.services.task_recovery import TaskRecoveryService
from app.services.workspace import WorkspaceService
from tests.test_task_execution_api import (
    FakeDiffAgent,
    FakeDryRunAgent,
    create_workflow,
    create_workspace,
)


client = TestClient(app, raise_server_exceptions=False)


def configure_services(tmp_path, monkeypatch, *, proposed_content="value = 2\n"):
    database = tmp_path / "runtime" / "devloopai.sqlite3"
    services = make_services(database, proposed_content=proposed_content)
    monkeypatch.setattr(task_endpoint, "get_task_execution_service", lambda: services["task"])
    monkeypatch.setattr(task_endpoint, "get_task_recovery_service", lambda: services["recovery"])
    return services


def make_services(database, *, proposed_content="value = 2\n"):
    approval_store = PlanningApprovalStore(database)
    execution_store = ExecutionStore(database)
    workspace_service = WorkspaceService()
    preflight_service = ExecutionPreflightService(
        approval_store=approval_store,
        workspace_service=workspace_service,
    )
    handoff_service = ExecutionHandoffService(
        approval_store=approval_store,
        workspace_service=workspace_service,
        preflight_service=preflight_service,
    )
    quality_gate = ExecutionQualityGate(
        execution_store=execution_store,
        workspace_service=workspace_service,
    )
    task_service = ControlledTaskExecutionService(
        task_store=TaskExecutionStore(database),
        approval_store=approval_store,
        preflight_service=preflight_service,
        handoff_service=handoff_service,
        dry_run_agent=FakeDryRunAgent(),
        diff_preview_agent=FakeDiffAgent(execution_store, proposed_content=proposed_content),
        mutation_service=ExecutionMutationService(
            handoff_service=handoff_service,
            workspace_service=workspace_service,
            execution_store=execution_store,
        ),
        verification_runner=ExecutionVerificationRunner(
            execution_store=execution_store,
            approval_store=approval_store,
            workspace_service=workspace_service,
        ),
        quality_gate=quality_gate,
    )
    return {
        "approval_store": approval_store,
        "execution_store": execution_store,
        "task_store": TaskExecutionStore(database),
        "task": task_service,
        "recovery": TaskRecoveryService(
            task_store=TaskExecutionStore(database),
            approval_store=approval_store,
            execution_store=execution_store,
            quality_gate=quality_gate,
            git_commit_store=GitCommitStore(database),
        ),
    }


def restart_services(tmp_path, monkeypatch, database, *, proposed_content="value = 2\n"):
    services = make_services(database, proposed_content=proposed_content)
    monkeypatch.setattr(task_endpoint, "get_task_execution_service", lambda: services["task"])
    monkeypatch.setattr(task_endpoint, "get_task_recovery_service", lambda: services["recovery"])
    return services


def prepare_task(workflow_id):
    return client.post("/api/v1/workflows/execution/task", json={"workflow_id": workflow_id}).json()


def apply_task(task_id):
    return client.post(f"/api/v1/workflows/execution/task/{task_id}/apply", json={}).json()


def verify_task(task_id):
    return client.post(f"/api/v1/workflows/execution/task/{task_id}/verify", json={}).json()


def recover_task(task_id):
    return client.get(f"/api/v1/workflows/execution/task/{task_id}/recovery").json()


def resume_task(task_id):
    return client.post(f"/api/v1/workflows/execution/task/{task_id}/resume").json()


def test_prepared_task_survives_restart_awaiting_execution_approval(tmp_path, monkeypatch):
    services = configure_services(tmp_path, monkeypatch)
    workspace = create_workspace(tmp_path)
    gate = create_workflow(services, workspace)
    task = prepare_task(gate.workflow_id)

    restart_services(tmp_path, monkeypatch, services["approval_store"].database_path)
    recovered = recover_task(task["task_execution_id"])

    assert recovered["current_task_state"] == "AWAITING_EXECUTION_APPROVAL"
    assert recovered["approval_required"] is True
    assert recovered["mutation_already_performed"] is False
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 1\n"


def test_applied_task_survives_restart_and_duplicate_apply_does_not_rewrite(tmp_path, monkeypatch):
    services = configure_services(tmp_path, monkeypatch)
    workspace = create_workspace(tmp_path)
    gate = create_workflow(services, workspace)
    task = prepare_task(gate.workflow_id)
    applied = apply_task(task["task_execution_id"])

    restarted = restart_services(tmp_path, monkeypatch, services["approval_store"].database_path)
    duplicate = apply_task(task["task_execution_id"])
    recovered = recover_task(task["task_execution_id"])

    assert duplicate["mutation_execution_id"] == applied["mutation_execution_id"]
    assert len(restarted["execution_store"].list_execution_history()) == 1
    assert recovered["mutation_already_performed"] is True
    assert workspace.joinpath("sample.py").read_text(encoding="utf-8") == "value = 2\n"


def test_interrupted_verification_is_not_reported_passed_and_can_resume(tmp_path, monkeypatch):
    services = configure_services(tmp_path, monkeypatch)
    workspace = create_workspace(tmp_path)
    gate = create_workflow(services, workspace)
    task = prepare_task(gate.workflow_id)
    applied = apply_task(task["task_execution_id"])
    session = services["task_store"].get(task["task_execution_id"])
    session.state = "VERIFYING"
    services["task_store"].update(session)

    restart_services(tmp_path, monkeypatch, services["approval_store"].database_path)
    recovered = recover_task(task["task_execution_id"])
    resumed = resume_task(task["task_execution_id"])

    assert "Verification" in recovered["interrupted_or_unknown_stages"]
    assert recovered["completed_verification_types"] == []
    assert recovered["mutation_already_performed"] is True
    assert resumed["state"] == "APPLIED"
    assert resumed["mutation_execution_id"] == applied["mutation_execution_id"]


def test_quality_can_be_recovered_after_restart_from_persisted_verification(tmp_path, monkeypatch):
    services = configure_services(tmp_path, monkeypatch)
    workspace = create_workspace(tmp_path)
    gate = create_workflow(services, workspace)
    task = prepare_task(gate.workflow_id)
    applied_task = apply_task(task["task_execution_id"])
    execution_id = applied_task["mutation_execution_id"]
    services["execution_store"].record_verification(
        ExecutionVerificationResult(
            verification_id="verify-recovered",
            execution_id=execution_id,
            workflow_id=gate.workflow_id,
            verification_type="python_compile",
            command_identity="python_compile:v1",
            working_directory=str(workspace),
            status="PASSED",
            exit_code=0,
            duration_seconds=0.01,
            timestamp="2026-08-22T00:00:00Z",
            changed_files=["sample.py"],
        )
    )

    restart_services(tmp_path, monkeypatch, services["approval_store"].database_path)
    recovered = recover_task(task["task_execution_id"])

    assert recovered["quality_status"] == "QUALITY_PASSED"
    assert recovered["completed_verification_types"] == ["python_compile"]


def test_retry_attempt_two_is_restored_without_creating_attempt_three(tmp_path, monkeypatch):
    services = configure_services(tmp_path, monkeypatch, proposed_content="def broken(:\n")
    workspace = create_workspace(tmp_path)
    gate = create_workflow(services, workspace)
    task = prepare_task(gate.workflow_id)
    apply_task(task["task_execution_id"])
    verify_task(task["task_execution_id"])
    services["task"].diff_preview_agent = FakeDiffAgent(
        services["execution_store"],
        proposed_content="value = 3\n",
    )
    retried = client.post(f"/api/v1/workflows/execution/task/{task['task_execution_id']}/retry", json={}).json()

    restart_services(tmp_path, monkeypatch, services["approval_store"].database_path)
    recovered = recover_task(task["task_execution_id"])

    assert retried["current_attempt"] == 2
    assert recovered["current_task_state"] == "AWAITING_EXECUTION_APPROVAL"
    assert "Diff Review" in recovered["completed_stages"]
    assert len(client.get(f"/api/v1/workflows/execution/task/{task['task_execution_id']}").json()["attempts"]) == 2


def test_stale_file_during_downtime_blocks_recovery(tmp_path, monkeypatch):
    services = configure_services(tmp_path, monkeypatch)
    workspace = create_workspace(tmp_path)
    gate = create_workflow(services, workspace)
    task = prepare_task(gate.workflow_id)
    apply_task(task["task_execution_id"])
    workspace.joinpath("sample.py").write_text("value = 99\n", encoding="utf-8", newline="\n")

    restart_services(tmp_path, monkeypatch, services["approval_store"].database_path)
    recovered = recover_task(task["task_execution_id"])

    assert recovered["recovery_status"] == "BLOCKED"
    assert recovered["stale_or_corrupt_state_detected"] is True
    assert any("no longer matches" in blocker for blocker in recovered["blockers"])


def test_corrupt_missing_execution_link_blocks_recovery(tmp_path, monkeypatch):
    services = configure_services(tmp_path, monkeypatch)
    workspace = create_workspace(tmp_path)
    gate = create_workflow(services, workspace)
    task = prepare_task(gate.workflow_id)
    session = services["task_store"].get(task["task_execution_id"])
    session.mutation_execution_id = "missing-execution"
    session.state = "APPLIED"
    services["task_store"].update(session)

    recovered = recover_task(task["task_execution_id"])

    assert recovered["recovery_status"] == "BLOCKED"
    assert "Linked mutation execution record is missing or incomplete." in recovered["blockers"]
