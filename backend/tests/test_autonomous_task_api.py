from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import autonomous_task as autonomous_endpoint
from app.main import app
from app.models.autonomous_task import AutonomousTaskStartRequest
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.planning_workflow import FinalReviewedPlanSummary, PlanningWorkflowResponse
from app.models.reviewer import ReviewerResponse
from app.models.task_execution import TaskExecutionSession
from app.models.validator import ValidatorResponse
from app.services.autonomous_task import BoundedAutonomousTaskService
from app.services.autonomous_task_store import AutonomousTaskStore
from app.services.planning_approval import PlanningApprovalStore
from app.services.task_execution_store import TaskExecutionStore


client = TestClient(app, raise_server_exceptions=False)


class FakePlanningWorkflow:
    def __init__(self, approval_store: PlanningApprovalStore, workspace_path: str | None = None):
        self.approval_store = approval_store
        self.workspace_path = workspace_path

    async def run(self, request: AutonomousTaskStartRequest) -> PlanningWorkflowResponse:
        planner = planner_response()
        reviewer = reviewer_response()
        validator = validator_response()
        summary = FinalReviewedPlanSummary(
            final_recommendation="READY",
            final_execution_readiness="Ready after explicit approval.",
            execution_ready=False,
            required_changes_before_execution=[],
            blockers=[],
            warnings=[],
            risks=[],
            tests_expected=["python_compile"],
            user_approval_required=True,
            summary="Ready.",
        )
        approval = self.approval_store.create_gate(
            task=request.task,
            workspace_path=request.workspace_path or self.workspace_path,
            planner_output=planner,
            reviewer_output=reviewer,
            validator_output=validator,
            final_reviewed_summary=summary,
            blockers=[],
        )
        return PlanningWorkflowResponse(
            planner_output=planner,
            reviewer_output=reviewer,
            validator_output=validator,
            final_reviewed_summary=summary,
            approval=approval,
        )


class FakeTaskExecutionService:
    def __init__(self):
        self.prepared = 0
        self.verified = 0
        self.retried = 0
        self.tasks: dict[str, TaskExecutionSession] = {}

    async def prepare(self, request):
        self.prepared += 1
        task = task_session(
            workflow_id=request.workflow_id,
            state="AWAITING_EXECUTION_APPROVAL",
            task_execution_id="task-1",
            message="Prepared diff.",
        )
        self.tasks[task.task_execution_id] = task
        return task

    def get(self, task_execution_id: str):
        return self.tasks[task_execution_id]

    def verify(self, task_execution_id: str):
        self.verified += 1
        task = self.tasks[task_execution_id]
        task.state = "QUALITY_PASSED"
        task.message = "Quality passed."
        self.tasks[task_execution_id] = task
        return task

    async def retry(self, task_execution_id: str):
        self.retried += 1
        task = self.tasks[task_execution_id]
        task.state = "AWAITING_EXECUTION_APPROVAL"
        task.current_attempt += 1
        task.message = "Retry prepared."
        self.tasks[task_execution_id] = task
        return task


@pytest.fixture
def autonomous_context(tmp_path, monkeypatch):
    database = tmp_path / "runtime" / "devloopai.sqlite3"
    approval_store = PlanningApprovalStore(database)
    task_service = FakeTaskExecutionService()
    service = BoundedAutonomousTaskService(
        store=AutonomousTaskStore(database),
        approval_store=approval_store,
        planning_workflow=FakePlanningWorkflow(approval_store),
        task_execution_service=task_service,
    )
    monkeypatch.setattr(
        autonomous_endpoint,
        "get_autonomous_task_service",
        lambda: service,
    )
    return {
        "approval_store": approval_store,
        "database": database,
        "service": service,
        "task_service": task_service,
    }


def planner_response() -> PlannerResponse:
    return PlannerResponse(
        task_summary="Update sample.py.",
        assumptions=[],
        detected_project_context=PlannerProjectContext(
            workspace_name="sample",
            project_types=["Python"],
            frameworks=[],
            languages={"Python": 1},
        ),
        implementation_steps=["Update sample.py."],
        files_likely_to_change=["sample.py"],
        tests_verification_required=["python_compile"],
        risks=[],
        dependencies_or_user_input_needed=[],
        model="fake",
    )


def reviewer_response() -> ReviewerResponse:
    return ReviewerResponse(
        overall_assessment="Safe plan.",
        missing_steps=[],
        incorrect_assumptions=[],
        architecture_concerns=[],
        security_concerns=[],
        performance_concerns=[],
        testing_gaps=[],
        unnecessary_changes=[],
        recommended_improvements=[],
        approval_recommendation="APPROVE",
        model="fake",
    )


def validator_response() -> ValidatorResponse:
    return ValidatorResponse(
        overall_validation_status="READY",
        plan_completeness=["Complete."],
        file_path_validity=["sample.py: path exists."],
        dependency_concerns=[],
        environment_tool_requirements=[],
        security_concerns=[],
        destructive_operation_warnings=[],
        missing_user_information=[],
        test_verification_readiness=["python_compile"],
        blockers=[],
        final_execution_readiness="Ready.",
        model="fake",
    )


def task_session(
    *,
    workflow_id: str,
    state: str,
    task_execution_id: str = "task-1",
    current_attempt: int = 1,
    max_attempts: int = 3,
    message: str = "",
) -> TaskExecutionSession:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return TaskExecutionSession(
        task_execution_id=task_execution_id,
        workflow_id=workflow_id,
        plan_fingerprint="a" * 64,
        workspace_path="D:\\sample",
        state=state,
        created_at=now,
        updated_at=now,
        current_attempt=current_attempt,
        max_attempts=max_attempts,
        message=message,
    )


def start_session():
    return client.post(
        "/api/v1/workflows/autonomous-task",
        json={"task": "Update sample.py."},
    )


def approve_session_plan(context, session):
    approval = session["planning_result"]["approval"]
    return context["approval_store"].approve(
        approval_id=approval["approval_id"],
        approval_token=approval["approval_token"],
        plan_fingerprint=approval["plan_fingerprint"],
    )


def test_start_stops_at_plan_approval_boundary(autonomous_context):
    response = start_session()

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "AWAITING_PLAN_APPROVAL"
    assert body["waiting_for"] == "Explicit plan approval is required."
    assert body["mutation_performed_by_autonomous_mode"] is False
    assert body["workflow_id"]


def test_continue_before_plan_approval_does_not_prepare_execution(autonomous_context):
    session = start_session().json()

    continued = client.post(
        f"/api/v1/workflows/autonomous-task/{session['autonomous_session_id']}/continue",
        json={"expected_state": "AWAITING_PLAN_APPROVAL"},
    ).json()

    assert continued["state"] == "AWAITING_PLAN_APPROVAL"
    assert autonomous_context["task_service"].prepared == 0


def test_continue_after_plan_approval_prepares_diff_and_stops_before_mutation(
    autonomous_context,
):
    session = start_session().json()
    approve_session_plan(autonomous_context, session)

    continued = client.post(
        f"/api/v1/workflows/autonomous-task/{session['autonomous_session_id']}/continue",
        json={"expected_state": "AWAITING_PLAN_APPROVAL"},
    ).json()

    assert continued["state"] == "AWAITING_EXECUTION_APPROVAL"
    assert continued["waiting_for"] == "Explicit mutation approval is required for the reviewed diff."
    assert continued["task_execution_id"] == "task-1"
    assert continued["current_attempt"] == 1
    assert autonomous_context["task_service"].prepared == 1


def test_continue_is_idempotent_while_waiting_for_execution_approval(
    autonomous_context,
):
    session = start_session().json()
    approve_session_plan(autonomous_context, session)
    prepared = client.post(
        f"/api/v1/workflows/autonomous-task/{session['autonomous_session_id']}/continue",
        json={},
    ).json()

    repeated = client.post(
        f"/api/v1/workflows/autonomous-task/{prepared['autonomous_session_id']}/continue",
        json={"expected_state": "AWAITING_EXECUTION_APPROVAL"},
    ).json()

    assert repeated["state"] == "AWAITING_EXECUTION_APPROVAL"
    assert autonomous_context["task_service"].prepared == 1


def test_after_explicit_apply_continue_runs_verification_to_quality_passed(
    autonomous_context,
):
    session = start_session().json()
    approve_session_plan(autonomous_context, session)
    prepared = client.post(
        f"/api/v1/workflows/autonomous-task/{session['autonomous_session_id']}/continue",
        json={},
    ).json()
    task = autonomous_context["task_service"].tasks[prepared["task_execution_id"]]
    task.state = "APPLIED"
    autonomous_context["task_service"].tasks[task.task_execution_id] = task

    continued = client.post(
        f"/api/v1/workflows/autonomous-task/{prepared['autonomous_session_id']}/continue",
        json={"expected_state": "AWAITING_EXECUTION_APPROVAL"},
    ).json()

    assert continued["state"] == "QUALITY_PASSED"
    assert autonomous_context["task_service"].verified == 1


def test_quality_failed_continue_prepares_retry_without_hidden_mutation(
    autonomous_context,
):
    session = start_session().json()
    approve_session_plan(autonomous_context, session)
    prepared = client.post(
        f"/api/v1/workflows/autonomous-task/{session['autonomous_session_id']}/continue",
        json={},
    ).json()
    task = autonomous_context["task_service"].tasks[prepared["task_execution_id"]]
    task.state = "QUALITY_FAILED"
    task.current_attempt = 1
    autonomous_context["task_service"].tasks[task.task_execution_id] = task

    continued = client.post(
        f"/api/v1/workflows/autonomous-task/{prepared['autonomous_session_id']}/continue",
        json={"expected_state": "AWAITING_EXECUTION_APPROVAL"},
    ).json()

    assert continued["state"] == "AWAITING_EXECUTION_APPROVAL"
    assert continued["current_attempt"] == 2
    assert autonomous_context["task_service"].retried == 1
    assert continued["mutation_performed_by_autonomous_mode"] is False


def test_retry_limit_is_terminal(autonomous_context):
    session = start_session().json()
    approve_session_plan(autonomous_context, session)
    prepared = client.post(
        f"/api/v1/workflows/autonomous-task/{session['autonomous_session_id']}/continue",
        json={},
    ).json()
    task = autonomous_context["task_service"].tasks[prepared["task_execution_id"]]
    task.state = "RETRY_LIMIT_REACHED"
    task.current_attempt = 3
    autonomous_context["task_service"].tasks[task.task_execution_id] = task

    continued = client.post(
        f"/api/v1/workflows/autonomous-task/{prepared['autonomous_session_id']}/continue",
        json={"expected_state": "AWAITING_EXECUTION_APPROVAL"},
    ).json()

    assert continued["state"] == "RETRY_LIMIT_REACHED"
    assert autonomous_context["task_service"].retried == 0


def test_session_reloads_after_store_restart(autonomous_context):
    session = start_session().json()

    restarted = AutonomousTaskStore(autonomous_context["database"])
    reloaded = restarted.get(session["autonomous_session_id"])

    assert reloaded.state == "AWAITING_PLAN_APPROVAL"
    assert reloaded.workflow_id == session["workflow_id"]


def test_wrong_state_guard_blocks_duplicate_or_stale_action(autonomous_context):
    session = start_session().json()

    response = client.post(
        f"/api/v1/workflows/autonomous-task/{session['autonomous_session_id']}/continue",
        json={"expected_state": "QUALITY_PASSED"},
    )

    assert response.status_code == 409
