from fastapi.testclient import TestClient

from app.agents.planner import PlannerAgent, PlannerAgentError
from app.agents.reviewer import ReviewerAgent, ReviewerAgentError
from app.main import app
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.reviewer import ReviewerResponse


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
    assert body["final_reviewed_summary"] == {
        "final_recommendation": "APPROVE_WITH_CHANGES",
        "required_changes_before_execution": [
            "Add exact verification command.",
            "Keep the change read-only.",
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
            "Planner output was reviewed. "
            "Recommendation: APPROVE_WITH_CHANGES."
        ),
    }


def test_planning_workflow_supports_approve(monkeypatch):
    async def mock_approve(self: ReviewerAgent, request) -> ReviewerResponse:
        return reviewer_response("APPROVE")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_approve)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 200
    assert response.json()["final_reviewed_summary"]["final_recommendation"] == "APPROVE"
    assert response.json()["final_reviewed_summary"]["user_approval_required"] is False


def test_planning_workflow_supports_reject(monkeypatch):
    async def mock_reject(self: ReviewerAgent, request) -> ReviewerResponse:
        return reviewer_response("REJECT")

    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_reject)

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label."},
    )

    assert response.status_code == 200
    assert response.json()["final_reviewed_summary"]["final_recommendation"] == "REJECT"
    assert response.json()["final_reviewed_summary"]["user_approval_required"] is True


def test_planning_workflow_accepts_project_context(monkeypatch):
    monkeypatch.setattr(PlannerAgent, "create_plan", mock_create_plan)
    monkeypatch.setattr(ReviewerAgent, "review_plan", mock_review_plan)

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

    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label.", "workspace_path": str(workspace)},
    )

    assert response.status_code == 200
    assert response.json()["final_reviewed_summary"]["final_recommendation"] == (
        "APPROVE_WITH_CHANGES"
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


def test_planning_workflow_rejects_invalid_workspace():
    response = client.post(
        "/api/v1/workflows/planning",
        json={"task": "Add a status label.", "workspace_path": "D:\\missing"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == (
        "Workspace path must be an existing directory"
    )
