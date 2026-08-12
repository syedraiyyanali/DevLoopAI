from fastapi.testclient import TestClient

from app.agents.planner import PlannerAgent, PlannerAgentError
from app.agents.reviewer import ReviewerAgent, ReviewerAgentError
from app.agents.validator import ValidatorAgent, ValidatorAgentError
from app.main import app
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse
from app.services.planning_approval import planning_approval_store


client = TestClient(app, raise_server_exceptions=False)


def planner_response() -> PlannerResponse:
    return PlannerResponse(
        task_summary="Add a safe status label.",
        assumptions=["Workspace panel exists."],
        detected_project_context=PlannerProjectContext(
            workspace_name="sample",
            project_types=["Node.js"],
            frameworks=["Next.js"],
            languages={"TypeScript": 3},
        ),
        implementation_steps=["Inspect the panel.", "Add the label."],
        files_likely_to_change=["frontend/components/workspace-panel.tsx"],
        tests_verification_required=["Run frontend lint."],
        risks=["UI may become noisy."],
        dependencies_or_user_input_needed=[],
        model="qwen2.5-coder:7b",
    )


def reviewer_response(recommendation: str = "APPROVE_WITH_CHANGES") -> ReviewerResponse:
    return ReviewerResponse(
        overall_assessment="The plan is reasonable with minor changes.",
        missing_steps=["Add exact verification command."],
        incorrect_assumptions=[],
        architecture_concerns=["Keep the label inside the existing panel."],
        security_concerns=[],
        performance_concerns=[],
        testing_gaps=["Run frontend build."],
        unnecessary_changes=[],
        recommended_improvements=["Keep the change read-only."],
        approval_recommendation=recommendation,
        model="qwen2.5-coder:7b",
    )


def validator_response(status: str = "READY_WITH_WARNINGS") -> ValidatorResponse:
    return ValidatorResponse(
        overall_validation_status=status,
        plan_completeness=["Planner output includes implementation steps."],
        file_path_validity=["frontend/components/workspace-panel.tsx: path exists."],
        dependency_concerns=[],
        environment_tool_requirements=["Expected verification/tooling mentioned: ESLint."],
        security_concerns=[],
        destructive_operation_warnings=[],
        missing_user_information=(
            ["Confirm the exact status label copy."]
            if status == "READY_WITH_WARNINGS"
            else []
        ),
        test_verification_readiness=["Run frontend build."],
        blockers=(["Validator blocked execution."] if status == "BLOCKED" else []),
        final_execution_readiness=(
            "Reviewed plan is ready for future execution after normal user approval."
            if status == "READY"
            else "Reviewed plan needs warnings addressed before future execution."
            if status == "READY_WITH_WARNINGS"
            else "Reviewed plan is blocked and must not be executed."
        ),
        model="qwen2.5-coder:7b",
    )


async def mock_create_plan(
    self: PlannerAgent,
    request,
) -> PlannerResponse:
    return planner_response()


async def mock_review_plan(
    self: ReviewerAgent,
    request,
) -> ReviewerResponse:
    return reviewer_response()


async def mock_validate_plan(
    self: ValidatorAgent,
    request,
) -> ValidatorResponse:
    return validator_response()


def project_context_payload() -> dict:
    return {
        "workspace": {
            "name": "sample",
            "root_path": "D:\\sample",
            "total_visible_entries": 2,
        },
        "project_types": ["Node.js"],
        "frameworks": ["Next.js"],
        "important_config_files": ["frontend/package.json"],
        "important_source_directories": ["frontend/components"],
        "likely_entry_points": ["frontend/app/page.tsx"],
        "detected_languages": {"TypeScript": 3},
        "file_count": 4,
        "directory_count": 2,
        "dependency_metadata": [],
        "git": {
            "present": True,
            "current_branch": "main",
            "remotes": ["origin"],
        },
        "readme_excerpt": "# Sample",
        "ignored_directories": [".git", "node_modules"],
        "warnings": [],
    }


def test_planning_workflow_returns_planner_reviewer_and_final_summary(monkeypatch):
    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_validate_plan)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["planner_output"]["task_summary"] == "Add a safe status label."
    assert body["reviewer_output"]["overall_assessment"] == (
        "The plan is reasonable with minor changes."
    )
    assert body["validator_output"]["overall_validation_status"] == (
        "READY_WITH_WARNINGS"
    )
    assert body["final_reviewed_summary"] == {
        "final_recommendation": "READY_WITH_WARNINGS",
        "final_execution_readiness": (
            "Reviewed plan needs warnings addressed before future execution."
        ),
        "execution_ready": False,
        "required_changes_before_execution": [
            "Add exact verification command.",
            "Keep the change read-only.",
            "Confirm the exact status label copy.",
        ],
        "blockers": [],
        "warnings": [
            "Keep the label inside the existing panel.",
            "Run frontend build.",
            "Expected verification/tooling mentioned: ESLint.",
            "Confirm the exact status label copy.",
        ],
        "risks": [
            "UI may become noisy.",
            "Keep the label inside the existing panel.",
        ],
        "tests_expected": [
            "Run frontend lint.",
            "Run frontend build.",
        ],
        "user_approval_required": True,
        "summary": (
            "Planner, reviewer, and validator completed. "
            "Final execution readiness: READY_WITH_WARNINGS."
        ),
    }
    assert body["approval"]["status"] == "PENDING_APPROVAL"
    assert body["approval"]["approval_allowed"] is True
    assert len(body["approval"]["approval_id"]) > 10
    assert len(body["approval"]["approval_token"]) > 20
    assert len(body["approval"]["plan_fingerprint"]) == 64


def test_planning_workflow_supports_approve_and_ready(monkeypatch):
    async def mock_approve(self: ReviewerAgent, request) -> ReviewerResponse:
        return reviewer_response("APPROVE")

    async def mock_ready(self: ValidatorAgent, request) -> ValidatorResponse:
        return validator_response("READY")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_approve)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_ready)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 200
    assert response.json()["final_reviewed_summary"]["final_recommendation"] == "READY"
    assert response.json()["final_reviewed_summary"]["execution_ready"] is False
    assert response.json()["final_reviewed_summary"]["user_approval_required"] is True
    assert response.json()["approval"]["status"] == "PENDING_APPROVAL"
    assert response.json()["approval"]["approval_allowed"] is True


def test_planning_workflow_supports_approve_with_changes_and_warnings(monkeypatch):
    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_validate_plan)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 200
    assert response.json()["final_reviewed_summary"]["final_recommendation"] == (
        "READY_WITH_WARNINGS"
    )
    assert response.json()["final_reviewed_summary"]["execution_ready"] is False
    assert response.json()["final_reviewed_summary"]["user_approval_required"] is True


def test_planning_workflow_reviewer_reject_forces_blocked(monkeypatch):
    async def mock_reject(self: ReviewerAgent, request) -> ReviewerResponse:
        return reviewer_response("REJECT")

    async def mock_validator_ready(self: ValidatorAgent, request) -> ValidatorResponse:
        return validator_response("READY")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_reject)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_validator_ready)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 200
    assert response.json()["final_reviewed_summary"]["final_recommendation"] == "BLOCKED"
    assert response.json()["final_reviewed_summary"]["execution_ready"] is False
    assert "Reviewer rejected the planner output." in response.json()[
        "final_reviewed_summary"
    ]["blockers"]
    assert response.json()["final_reviewed_summary"]["user_approval_required"] is False
    assert response.json()["approval"]["status"] == "BLOCKED"
    assert response.json()["approval"]["approval_allowed"] is False


def test_planning_workflow_supports_blocked_validation(monkeypatch):
    async def mock_blocked(self: ValidatorAgent, request) -> ValidatorResponse:
        return validator_response("BLOCKED")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_blocked)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 200
    assert response.json()["final_reviewed_summary"]["final_recommendation"] == "BLOCKED"
    assert response.json()["final_reviewed_summary"]["execution_ready"] is False
    assert response.json()["final_reviewed_summary"]["final_execution_readiness"] == (
        "Execution is blocked; do not execute until blockers are resolved."
    )
    assert response.json()["approval"]["status"] == "BLOCKED"
    assert response.json()["approval"]["approval_allowed"] is False


def test_planning_workflow_accepts_project_context(monkeypatch):
    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_validate_plan)

    response = client.post(
        "/api/v1/workflows/planning",
        json={
            "task": "Add a status label.",
            "project_context": project_context_payload(),
        },
    )

    assert response.status_code == 200
    assert response.json()["planner_output"]["detected_project_context"]["frameworks"] == [
        "Next.js"
    ]


def test_planning_workflow_can_use_workspace_context(tmp_path, monkeypatch):
    workspace = tmp_path / "workflow-project"
    workspace.mkdir()
    (workspace / "package.json").write_bytes(
        b'{\"dependencies\":{\"next\":\"16.2.10\"}}'
    )

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_validate_plan)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label.", "workspace_path": str(workspace)},
    )

    assert response.status_code == 200
    assert response.json()["final_reviewed_summary"]["final_recommendation"] == (
        "READY_WITH_WARNINGS"
    )


def test_planning_workflow_maps_planner_failure(monkeypatch):
    async def mock_planner_failure(self: PlannerAgent, request) -> PlannerResponse:
        raise PlannerAgentError("Planner model did not return valid JSON")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_planner_failure)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Planner failed: Planner model did not return valid JSON"
    )


def test_planning_workflow_maps_reviewer_failure(monkeypatch):
    async def mock_reviewer_failure(self: ReviewerAgent, request) -> ReviewerResponse:
        raise ReviewerAgentError("Reviewer model did not return valid JSON")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_reviewer_failure)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Reviewer failed: Reviewer model did not return valid JSON"
    )


def test_planning_workflow_maps_validator_failure(monkeypatch):
    async def mock_validator_failure(self: ValidatorAgent, request) -> ValidatorResponse:
        raise ValidatorAgentError("Validator model did not return valid JSON")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_validator_failure)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Validator failed: Validator model did not return valid JSON"
    )


def test_planning_workflow_rejects_invalid_workspace():
    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label.", "workspace_path": "D:\\missing"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == (
        "Workspace path must be an existing directory"
    )


def test_planning_workflow_allows_valid_explicit_approval(monkeypatch):
    async def mock_approve(self: ReviewerAgent, request) -> ReviewerResponse:
        return reviewer_response("APPROVE")

    async def mock_ready(self: ValidatorAgent, request) -> ValidatorResponse:
        return validator_response("READY")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_approve)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_ready)

    workflow_response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )
    approval = workflow_response.json()["approval"]

    response = client.post(
        "/api/v1/workflows/planning/approve",
        json={
            "approval_id": approval["approval_id"],
            "approval_token": approval["approval_token"],
            "plan_fingerprint": approval["plan_fingerprint"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert response.json()["message"] == "Plan approved. No code was executed."


def test_planning_workflow_allows_explicit_rejection(monkeypatch):
    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_validate_plan)

    workflow_response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )
    approval = workflow_response.json()["approval"]

    response = client.post(
        "/api/v1/workflows/planning/reject",
        json={
            "approval_id": approval["approval_id"],
            "approval_token": approval["approval_token"],
            "plan_fingerprint": approval["plan_fingerprint"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    assert response.json()["message"] == "Plan rejected. No code was executed."


def test_planning_workflow_blocks_approval_when_validator_blocks(monkeypatch):
    async def mock_blocked(self: ValidatorAgent, request) -> ValidatorResponse:
        return validator_response("BLOCKED")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_blocked)

    workflow_response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )
    approval = workflow_response.json()["approval"]

    response = client.post(
        "/api/v1/workflows/planning/approve",
        json={
            "approval_id": approval["approval_id"],
            "approval_token": approval["approval_token"],
            "plan_fingerprint": approval["plan_fingerprint"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Validator blocked the reviewed plan."


def test_planning_workflow_blocks_approval_when_reviewer_rejects(monkeypatch):
    async def mock_reject(self: ReviewerAgent, request) -> ReviewerResponse:
        return reviewer_response("REJECT")

    async def mock_ready(self: ValidatorAgent, request) -> ValidatorResponse:
        return validator_response("READY")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_reject)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_ready)

    workflow_response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )
    approval = workflow_response.json()["approval"]

    response = client.post(
        "/api/v1/workflows/planning/approve",
        json={
            "approval_id": approval["approval_id"],
            "approval_token": approval["approval_token"],
            "plan_fingerprint": approval["plan_fingerprint"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Reviewer rejected the planner output."


def test_planning_workflow_rejects_stale_changed_plan_approval(monkeypatch):
    async def mock_approve(self: ReviewerAgent, request) -> ReviewerResponse:
        return reviewer_response("APPROVE")

    async def mock_ready(self: ValidatorAgent, request) -> ValidatorResponse:
        return validator_response("READY")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_approve)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_ready)

    workflow_response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )
    approval = workflow_response.json()["approval"]

    response = client.post(
        "/api/v1/workflows/planning/approve",
        json={
            "approval_id": approval["approval_id"],
            "approval_token": approval["approval_token"],
            "plan_fingerprint": "0" * 64,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "Approval does not match the current reviewed plan."
    )


def test_planning_workflow_rejects_invalid_approval_id_or_token():
    response = client.post(
        "/api/v1/workflows/planning/approve",
        json={
            "approval_id": "missing",
            "approval_token": "bad-token",
            "plan_fingerprint": "0" * 64,
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Approval id or token is invalid."


def test_planning_workflow_repeated_approval_is_idempotent(monkeypatch):
    async def mock_approve(self: ReviewerAgent, request) -> ReviewerResponse:
        return reviewer_response("APPROVE")

    async def mock_ready(self: ValidatorAgent, request) -> ValidatorResponse:
        return validator_response("READY")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_approve)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_ready)

    workflow_response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )
    approval = workflow_response.json()["approval"]
    payload = {
        "approval_id": approval["approval_id"],
        "approval_token": approval["approval_token"],
        "plan_fingerprint": approval["plan_fingerprint"],
    }

    first_response = client.post("/api/v1/workflows/planning/approve", json=payload)
    second_response = client.post("/api/v1/workflows/planning/approve", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["status"] == "APPROVED"
    assert second_response.json()["message"] == "Plan is already approved."


def test_planning_workflow_repeated_rejection_is_idempotent(monkeypatch):
    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_validate_plan)

    workflow_response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )
    approval = workflow_response.json()["approval"]
    payload = {
        "approval_id": approval["approval_id"],
        "approval_token": approval["approval_token"],
        "plan_fingerprint": approval["plan_fingerprint"],
    }

    first_response = client.post("/api/v1/workflows/planning/reject", json=payload)
    second_response = client.post("/api/v1/workflows/planning/reject", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["status"] == "REJECTED"
    assert second_response.json()["message"] == "Plan is already rejected."


def test_planning_workflow_cannot_reject_after_approval(monkeypatch):
    async def mock_approve(self: ReviewerAgent, request) -> ReviewerResponse:
        return reviewer_response("APPROVE")

    async def mock_ready(self: ValidatorAgent, request) -> ValidatorResponse:
        return validator_response("READY")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_approve)
    monkeypatch.setattr(ValidatorAgent, "validate_plan", mock_ready)

    workflow_response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )
    approval = workflow_response.json()["approval"]
    payload = {
        "approval_id": approval["approval_id"],
        "approval_token": approval["approval_token"],
        "plan_fingerprint": approval["plan_fingerprint"],
    }

    approve_response = client.post("/api/v1/workflows/planning/approve", json=payload)
    reject_response = client.post("/api/v1/workflows/planning/reject", json=payload)

    assert approve_response.status_code == 200
    assert reject_response.status_code == 409
    assert reject_response.json()["error"]["message"] == (
        "Approved plans cannot be rejected here."
    )


def test_planning_approval_fingerprint_changes_when_plan_changes():
    first_fingerprint = planning_approval_store.plan_fingerprint(
        planner_output=planner_response(),
        reviewer_output=reviewer_response("APPROVE"),
        validator_output=validator_response("READY"),
    )
    changed_planner = planner_response()
    changed_planner.implementation_steps.append("Add a second label.")
    changed_fingerprint = planning_approval_store.plan_fingerprint(
        planner_output=changed_planner,
        reviewer_output=reviewer_response("APPROVE"),
        validator_output=validator_response("READY"),
    )

    assert first_fingerprint != changed_fingerprint
