"""Integration tests for the frontend-integration task's (Prompt 11)
backend compatibility additions: GET /repositories (list), GET
/repositories/{id} (detail), and GET /repositories/{id}/files/source
(safe source-snippet viewing) — see app/api/routes/repositories.py and
app/ingestion/source_reader.py.
"""

import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _upload(name: str, files: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/repositories/upload",
        data={"name": name},
        files={"file": ("demo.zip", _zip_bytes(files), "application/zip")},
    )
    assert response.status_code == 201, response.text
    return response.json()["repository_id"]


class TestListRepositories:
    def test_lists_every_imported_repository(self, isolated_database: None) -> None:
        first = _upload("list-a", {"a.py": "x = 1\n"})
        second = _upload("list-b", {"b.py": "y = 2\n"})

        response = client.get("/api/v1/repositories")

        assert response.status_code == 200
        ids = {item["repository_id"] for item in response.json()}
        assert {first, second}.issubset(ids)

    def test_list_items_include_created_at(self, isolated_database: None) -> None:
        _upload("list-c", {"a.py": "x = 1\n"})
        response = client.get("/api/v1/repositories")
        assert response.status_code == 200
        assert all(item["created_at"] is not None for item in response.json())

    def test_empty_database_returns_empty_list(self, isolated_database: None) -> None:
        response = client.get("/api/v1/repositories")
        assert response.status_code == 200
        assert response.json() == []


class TestGetRepositoryDetail:
    def test_returns_the_repository(self, isolated_database: None) -> None:
        repository_id = _upload("detail-a", {"a.py": "x = 1\n"})
        response = client.get(f"/api/v1/repositories/{repository_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["repository_id"] == repository_id
        assert body["name"] == "detail-a"
        assert body["status"] == "ready"

    def test_missing_repository_returns_404(self, isolated_database: None) -> None:
        response = client.get("/api/v1/repositories/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


class TestGetSourceSnippet:
    def test_returns_a_context_padded_snippet(self, isolated_database: None) -> None:
        lines = [f"# line {i}" for i in range(1, 31)]
        content = "\n".join(lines) + "\ndef foo():\n    return 1\n"
        repository_id = _upload("source-a", {"pkg/mod.py": content})

        response = client.get(
            f"/api/v1/repositories/{repository_id}/files/source",
            params={"path": "pkg/mod.py", "start_line": 31, "end_line": 32},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["start_line"] < 31
        assert body["end_line"] >= 32
        assert "def foo" in body["content"]

    def test_without_a_range_returns_a_bounded_prefix(self, isolated_database: None) -> None:
        content = "\n".join(f"x{i} = {i}" for i in range(1, 20)) + "\n"
        repository_id = _upload("source-b", {"a.py": content})

        response = client.get(
            f"/api/v1/repositories/{repository_id}/files/source",
            params={"path": "a.py"},
        )

        assert response.status_code == 200
        assert response.json()["start_line"] == 1

    def test_rejects_path_traversal(self, isolated_database: None) -> None:
        repository_id = _upload("source-c", {"a.py": "x = 1\n"})
        response = client.get(
            f"/api/v1/repositories/{repository_id}/files/source",
            params={"path": "../../etc/passwd"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_rejects_absolute_path(self, isolated_database: None) -> None:
        repository_id = _upload("source-d", {"a.py": "x = 1\n"})
        response = client.get(
            f"/api/v1/repositories/{repository_id}/files/source",
            params={"path": "/etc/passwd"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_missing_file_returns_404(self, isolated_database: None) -> None:
        repository_id = _upload("source-e", {"a.py": "x = 1\n"})
        response = client.get(
            f"/api/v1/repositories/{repository_id}/files/source",
            params={"path": "does_not_exist.py"},
        )
        assert response.status_code == 404

    def test_missing_repository_returns_404(self, isolated_database: None) -> None:
        response = client.get(
            "/api/v1/repositories/does-not-exist/files/source", params={"path": "a.py"}
        )
        assert response.status_code == 404
