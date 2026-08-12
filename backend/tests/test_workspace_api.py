from pathlib import Path

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
