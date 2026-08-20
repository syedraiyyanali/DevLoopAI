from app.models.context_selection import ContextSelectionRequest
from app.models.workspace import WorkspaceContextSummary, WorkspaceGitSummary, WorkspaceMetadata
from app.services.context_selection import ContextSelectionService
from app.services.workspace import WorkspaceService


def make_workspace(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "tests").mkdir()
    (workspace / "node_modules").mkdir()
    (workspace / "package.json").write_text('{"scripts":{"lint":"next lint"}}', encoding="utf-8")
    (workspace / "src" / "feature.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (workspace / "tests" / "test_feature.py").write_text("from src.feature import value\n", encoding="utf-8")
    (workspace / ".env").write_text("SECRET=value\n", encoding="utf-8")
    (workspace / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")
    return workspace


def context_summary(workspace):
    return WorkspaceContextSummary(
        workspace=WorkspaceMetadata(
            name=workspace.name,
            root_path=str(workspace),
            total_visible_entries=3,
        ),
        project_types=["Python"],
        frameworks=[],
        important_config_files=["package.json"],
        important_source_directories=["src", "tests"],
        likely_entry_points=[],
        detected_languages={"Python": 2},
        file_count=3,
        directory_count=2,
        dependency_metadata=[],
        git=WorkspaceGitSummary(present=False),
        readme_excerpt=None,
        ignored_directories=[".git", "node_modules"],
        warnings=[],
    )


def test_selects_planned_config_and_related_test_files(tmp_path):
    workspace = make_workspace(tmp_path)
    selector = ContextSelectionService(WorkspaceService())

    result = selector.select(
        ContextSelectionRequest(
            workspace_path=str(workspace),
            task="Update feature behavior.",
            planned_paths=["src/feature.py"],
            project_context=context_summary(workspace),
        )
    )

    selected = {item.relative_path: item.reason for item in result.selected_files}
    assert selected["src/feature.py"] == "Planned file from approved handoff."
    assert selected["tests/test_feature.py"] == "Related test file for a planned source path."
    assert selected["package.json"] == "Important project configuration."
    assert ".env" not in selected
    assert "node_modules/ignored.js" not in selected
    assert result.total_bytes > 0


def test_context_limits_skip_extra_files(tmp_path):
    workspace = make_workspace(tmp_path)
    selector = ContextSelectionService(WorkspaceService())

    result = selector.select(
        ContextSelectionRequest(
            workspace_path=str(workspace),
            task="feature package test",
            planned_paths=["src/feature.py"],
            project_context=context_summary(workspace),
            max_files=1,
        )
    )

    assert len(result.selected_files) == 1
    assert result.skipped_files
    assert result.warnings


def test_large_file_is_truncated_by_budget(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / "src" / "feature.py").write_text("x" * 4096, encoding="utf-8")
    selector = ContextSelectionService(WorkspaceService())

    result = selector.select(
        ContextSelectionRequest(
            workspace_path=str(workspace),
            planned_paths=["src/feature.py"],
            max_file_bytes=1024,
        )
    )

    selected = result.selected_files[0]
    assert selected.relative_path == "src/feature.py"
    assert selected.truncated is True
    assert len(selected.content or "") <= 1024
