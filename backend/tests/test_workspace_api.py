import os
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


def create_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "sample-project"
    workspace.mkdir()
    (workspace / "README.md").write_bytes(b"# Sample Project\n")
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_bytes(b"print('hello')\n")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_bytes(b"[core]\n")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "package").write_bytes(b"heavy\n")
    (workspace / ".env").write_bytes(b"TOKEN=secret\n")

    return workspace


def test_open_workspace_returns_metadata_for_valid_directory(tmp_path):
    workspace = create_workspace(tmp_path)

    response = client.post("/api/v1/workspace/open", json={"path": str(workspace)})

    assert response.status_code == 200
    assert response.json() == {
        "name": "sample-project",
        "root_path": str(workspace.resolve()),
        "total_visible_entries": 2,
    }


def test_open_workspace_rejects_invalid_path(tmp_path):
    missing_workspace = tmp_path / "missing"

    response = client.post(
        "/api/v1/workspace/open",
        json={"path": str(missing_workspace)},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == (
        "Workspace path must be an existing directory"
    )


def test_list_workspace_returns_visible_entries_and_ignores_heavy_directories(tmp_path):
    workspace = create_workspace(tmp_path)

    response = client.post(
        "/api/v1/workspace/list",
        json={"workspace_path": str(workspace), "relative_path": ""},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["relative_path"] == ""
    assert body["entries"] == [
        {
            "name": "src",
            "relative_path": "src",
            "kind": "directory",
            "size_bytes": None,
        },
        {
            "name": "README.md",
            "relative_path": "README.md",
            "kind": "file",
            "size_bytes": 17,
        },
    ]


def test_list_workspace_blocks_path_traversal(tmp_path):
    workspace = create_workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    response = client.post(
        "/api/v1/workspace/list",
        json={"workspace_path": str(workspace), "relative_path": "../outside"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == (
        "Path escapes the selected workspace"
    )


def test_read_workspace_text_file(tmp_path):
    workspace = create_workspace(tmp_path)

    response = client.post(
        "/api/v1/workspace/read",
        json={"workspace_path": str(workspace), "relative_path": "src/app.py"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "workspace": {
            "name": "sample-project",
            "root_path": str(workspace.resolve()),
            "total_visible_entries": 2,
        },
        "relative_path": "src/app.py",
        "content": "print('hello')\n",
        "size_bytes": 15,
        "truncated": False,
    }


def test_read_workspace_blocks_path_traversal(tmp_path):
    workspace = create_workspace(tmp_path)
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("outside\n", encoding="utf-8")

    response = client.post(
        "/api/v1/workspace/read",
        json={"workspace_path": str(workspace), "relative_path": "../outside.txt"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == (
        "Path escapes the selected workspace"
    )


def test_read_workspace_blocks_secret_files(tmp_path):
    workspace = create_workspace(tmp_path)

    response = client.post(
        "/api/v1/workspace/read",
        json={"workspace_path": str(workspace), "relative_path": ".env"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == (
        "Path is blocked by workspace safety rules"
    )


def test_read_workspace_rejects_binary_file(tmp_path):
    workspace = create_workspace(tmp_path)
    binary_file = workspace / "image.bin"
    binary_file.write_bytes(b"\x89PNG\x00\x00")

    response = client.post(
        "/api/v1/workspace/read",
        json={"workspace_path": str(workspace), "relative_path": "image.bin"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["message"] == "Binary files cannot be read"


def test_read_workspace_rejects_files_over_size_limit(tmp_path, monkeypatch):
    workspace = create_workspace(tmp_path)
    large_file = workspace / "large.txt"
    large_file.write_text("0123456789", encoding="utf-8")
    monkeypatch.setattr(WorkspaceService, "max_read_bytes", 5)

    response = client.post(
        "/api/v1/workspace/read",
        json={"workspace_path": str(workspace), "relative_path": "large.txt"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["message"] == "File is too large to read safely"


def test_context_detects_python_fastapi_project(tmp_path):
    workspace = tmp_path / "fastapi-project"
    workspace.mkdir()
    (workspace / "README.md").write_bytes(b"# FastAPI Project\nAPI service summary.\n")
    (workspace / "requirements.txt").write_bytes(b"fastapi==0.125.0\npytest\n")
    (workspace / "app").mkdir()
    (workspace / "app" / "main.py").write_bytes(b"from fastapi import FastAPI\n")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    (workspace / ".git" / "config").write_bytes(
        b'[remote \"origin\"]\n\turl = https://example.test/repo.git\n'
    )

    response = client.post(
        "/api/v1/workspace/context",
        json={"workspace_path": str(workspace)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workspace"]["name"] == "fastapi-project"
    assert body["project_types"] == ["Python"]
    assert body["frameworks"] == ["FastAPI"]
    assert body["important_config_files"] == ["requirements.txt"]
    assert body["important_source_directories"] == ["app"]
    assert body["likely_entry_points"] == ["app/main.py"]
    assert body["detected_languages"]["Python"] == 1
    assert body["dependency_metadata"] == [
        {
            "manifest": "requirements.txt",
            "package_name": None,
            "dependencies": ["fastapi", "pytest"],
            "dev_dependencies": [],
        }
    ]
    assert body["git"] == {
        "present": True,
        "current_branch": "main",
        "remotes": ["origin"],
    }
    assert body["readme_excerpt"].startswith("# FastAPI Project")


def test_context_detects_node_next_project(tmp_path):
    workspace = tmp_path / "next-project"
    workspace.mkdir()
    (workspace / "package.json").write_bytes(
        b'{'
        b'\"name\":\"next-project\",'
        b'\"dependencies\":{\"next\":\"16.2.10\",\"react\":\"19.2.4\"},'
        b'\"devDependencies\":{\"typescript\":\"5.0.0\"}'
        b'}'
    )
    (workspace / "next.config.ts").write_bytes(b"export default {};\n")
    (workspace / "app").mkdir()
    (workspace / "app" / "page.tsx").write_bytes(b"export default function Page() {}\n")

    response = client.post(
        "/api/v1/workspace/context",
        json={"workspace_path": str(workspace)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project_types"] == ["Node.js"]
    assert body["frameworks"] == ["Next.js"]
    assert body["important_config_files"] == ["next.config.ts", "package.json"]
    assert body["important_source_directories"] == ["app"]
    assert body["likely_entry_points"] == ["app/page.tsx"]
    assert body["detected_languages"]["TypeScript"] == 2
    assert body["dependency_metadata"] == [
        {
            "manifest": "package.json",
            "package_name": "next-project",
            "dependencies": ["next", "react"],
            "dev_dependencies": ["typescript"],
        }
    ]
    assert body["git"] == {
        "present": False,
        "current_branch": None,
        "remotes": [],
    }


def test_context_detects_nested_node_next_project(tmp_path):
    workspace = tmp_path / "monorepo-project"
    workspace.mkdir()
    (workspace / "frontend").mkdir()
    (workspace / "frontend" / "package.json").write_bytes(
        b'{\"dependencies\":{\"next\":\"16.2.10\"}}'
    )
    (workspace / "frontend" / "app").mkdir()
    (workspace / "frontend" / "app" / "page.tsx").write_bytes(
        b"export default function Page() {}\n"
    )

    response = client.post(
        "/api/v1/workspace/context",
        json={"workspace_path": str(workspace)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project_types"] == ["Node.js"]
    assert body["frameworks"] == ["Next.js"]
    assert body["dependency_metadata"] == [
        {
            "manifest": "frontend/package.json",
            "package_name": None,
            "dependencies": ["next"],
            "dev_dependencies": [],
        }
    ]


def test_context_returns_generic_project_without_known_metadata(tmp_path):
    workspace = tmp_path / "generic-project"
    workspace.mkdir()
    (workspace / "notes.txt").write_bytes(b"plain notes\n")

    response = client.post(
        "/api/v1/workspace/context",
        json={"workspace_path": str(workspace)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project_types"] == ["Generic"]
    assert body["frameworks"] == []
    assert body["dependency_metadata"] == []
    assert body["file_count"] == 1
    assert body["directory_count"] == 0


def test_context_handles_invalid_package_json_without_failing(tmp_path):
    workspace = tmp_path / "broken-metadata"
    workspace.mkdir()
    (workspace / "package.json").write_bytes(b"{not-json")
    (workspace / "src").mkdir()
    (workspace / "src" / "index.js").write_bytes(b"console.log('ok');\n")

    response = client.post(
        "/api/v1/workspace/context",
        json={"workspace_path": str(workspace)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project_types"] == ["Node.js"]
    assert body["dependency_metadata"] == []
    assert body["likely_entry_points"] == ["src/index.js"]


def test_context_ignores_generated_and_secret_files(tmp_path):
    workspace = create_workspace(tmp_path)
    (workspace / "src" / "main.py").write_bytes(b"print('visible')\n")
    (workspace / "node_modules" / "index.js").write_bytes(b"console.log('hidden')\n")
    (workspace / ".env.local").write_bytes(b"SECRET=hidden\n")

    response = client.post(
        "/api/v1/workspace/context",
        json={"workspace_path": str(workspace)},
    )

    assert response.status_code == 200
    body = response.json()
    serialized_body = str(body)
    assert "node_modules" not in body["important_source_directories"]
    assert ".env" not in serialized_body
    assert ".env.local" not in serialized_body
    assert body["detected_languages"]["Python"] == 2


def test_list_workspace_hides_symlink_that_escapes_root(tmp_path):
    workspace = create_workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside secret\n", encoding="utf-8")
    link = workspace / "outside-link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation is unavailable in this environment: {exc}")

    body = client.post(
        "/api/v1/workspace/list",
        json={"workspace_path": str(workspace), "relative_path": ""},
    ).json()

    assert "outside-link" not in {entry["name"] for entry in body["entries"]}


def test_context_hides_symlink_that_escapes_root(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "external.py").write_text("SECRET = 'outside'\n", encoding="utf-8")
    try:
        os.symlink(outside / "external.py", workspace / "external.py")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation is unavailable in this environment: {exc}")

    body = client.post(
        "/api/v1/workspace/context",
        json={"workspace_path": str(workspace)},
    ).json()

    assert body["file_count"] == 0
    assert "Python" not in body["detected_languages"]
    assert "external.py" not in str(body)


def test_context_rejects_invalid_workspace_path(tmp_path):
    response = client.post(
        "/api/v1/workspace/context",
        json={"workspace_path": str(tmp_path / "missing")},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == (
        "Workspace path must be an existing directory"
    )
