"""Git provider abstraction: GitHub, GitLab, Azure DevOps, generic git-over-HTTPS."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestError, UpstreamError
from app.core.logging import get_logger

log = get_logger("ofme.git")


@dataclass(slots=True)
class PullRequest:
    number: int
    title: str
    url: str
    state: str
    source_branch: str
    target_branch: str


@dataclass(slots=True)
class FileChange:
    path: str
    content: str
    operation: str = "update"  # create | update | delete


class GitProvider(ABC):
    def __init__(self, base_url: str, token: str, verify_tls: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.AsyncClient(
            timeout=30.0,
            verify=verify_tls,
            headers={"User-Agent": "OFME/1.0", "Accept": "application/json"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def aclose(self) -> None:
        await self.close()

    @abstractmethod
    async def repo_info(self, repo: str) -> dict[str, Any]: ...

    @abstractmethod
    async def list_branches(self, repo: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def list_commits(self, repo: str, ref: str, limit: int = 50) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def read_file(self, repo: str, path: str, ref: str) -> str | None: ...

    @abstractmethod
    async def commit_files(
        self,
        repo: str,
        branch: str,
        message: str,
        changes: list[FileChange],
        *,
        base_branch: str | None = None,
    ) -> str: ...

    @abstractmethod
    async def create_pull_request(
        self, repo: str, title: str, body: str, source: str, target: str
    ) -> PullRequest: ...

    @abstractmethod
    async def merge_pull_request(self, repo: str, number: int) -> bool: ...

    # ------------------------------------------------------------------ helpers
    async def _json(self, method: str, url: str, **kwargs: Any) -> Any:
        response = await self._client.request(method, url, **kwargs)
        if response.status_code == 401:
            raise BadRequestError("Git provider rejected credentials")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise UpstreamError(
                f"Git provider error {response.status_code} for {method} {url}",
                details=response.text[:1000],
            )
        return response.json() if response.content else {}

    @staticmethod
    def verify_webhook(secret: str, body: bytes, signature: str | None) -> bool:
        if not secret:
            return False
        if not signature:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        provided = signature.removeprefix("sha256=")
        return hmac.compare_digest(expected, provided)

    def auth_headers(self, scheme: str = "Bearer") -> dict[str, str]:
        return {"Authorization": f"{scheme} {self.token}"}


class GitHubProvider(GitProvider):
    API = "https://api.github.com"

    def __init__(self, token: str, api_url: str | None = None) -> None:
        super().__init__(api_url or self.API, token)
        self._client.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _repo_url(self, repo: str) -> str:
        return f"{self.base_url}/repos/{repo}"

    async def repo_info(self, repo: str) -> dict[str, Any]:
        return await self._json("GET", self._repo_url(repo)) or {}

    async def list_branches(self, repo: str) -> list[dict[str, Any]]:
        data = await self._json("GET", f"{self._repo_url(repo)}/branches", params={"per_page": 100})
        return [
            {"name": b["name"], "sha": b["commit"]["sha"], "protected": b.get("protected", False)}
            for b in (data or [])
        ]

    async def list_commits(self, repo: str, ref: str, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._json(
            "GET", f"{self._repo_url(repo)}/commits", params={"sha": ref, "per_page": limit}
        )
        return [
            {
                "sha": c["sha"],
                "message": c["commit"]["message"],
                "author": c["commit"]["author"]["name"],
                "date": c["commit"]["author"]["date"],
            }
            for c in (data or [])
        ]

    async def read_file(self, repo: str, path: str, ref: str) -> str | None:
        data = await self._json("GET", f"{self._repo_url(repo)}/contents/{quote(path)}", params={"ref": ref})
        if not data:
            return None
        if isinstance(data, list):
            raise BadRequestError(f"{path} is a directory")
        import base64

        return base64.b64decode(data["content"]).decode("utf-8")

    async def _branch_sha(self, repo: str, branch: str) -> str:
        data = await self._json("GET", f"{self._repo_url(repo)}/git/ref/heads/{quote(branch)}")
        if not data:
            raise UpstreamError(f"Branch {branch} not found in {repo}")
        return data["object"]["sha"]

    async def _create_branch_if_missing(self, repo: str, branch: str, base: str) -> None:
        existing = await self._json("GET", f"{self._repo_url(repo)}/git/ref/heads/{quote(branch)}")
        if existing:
            return
        base_sha = await self._branch_sha(repo, base)
        await self._json(
            "POST", f"{self._repo_url(repo)}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha}
        )

    async def commit_files(
        self,
        repo: str,
        branch: str,
        message: str,
        changes: list[FileChange],
        *,
        base_branch: str | None = None,
    ) -> str:
        if base_branch:
            await self._create_branch_if_missing(repo, branch, base_branch)

        base_sha = await self._branch_sha(repo, branch)
        base_commit = await self._json("GET", f"{self._repo_url(repo)}/git/commits/{base_sha}")
        base_tree = base_commit["tree"]["sha"]

        tree_entries: list[dict[str, Any]] = []
        for change in changes:
            if change.operation == "delete":
                tree_entries.append({"path": change.path, "mode": "100644", "type": "blob", "sha": None})
                continue
            blob = await self._json(
                "POST",
                f"{self._repo_url(repo)}/git/blobs",
                json={"content": change.content, "encoding": "utf-8"},
            )
            tree_entries.append({"path": change.path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

        tree = await self._json(
            "POST", f"{self._repo_url(repo)}/git/trees", json={"base_tree": base_tree, "tree": tree_entries}
        )
        commit = await self._json(
            "POST",
            f"{self._repo_url(repo)}/git/commits",
            json={"message": message, "tree": tree["sha"], "parents": [base_sha]},
        )
        await self._json(
            "PATCH", f"{self._repo_url(repo)}/git/refs/heads/{quote(branch)}", json={"sha": commit["sha"]}
        )
        return commit["sha"]

    async def create_pull_request(
        self, repo: str, title: str, body: str, source: str, target: str
    ) -> PullRequest:
        data = await self._json(
            "POST",
            f"{self._repo_url(repo)}/pulls",
            json={"title": title, "body": body, "head": source, "base": target},
        )
        return PullRequest(
            number=data["number"],
            title=data["title"],
            url=data["html_url"],
            state=data["state"],
            source_branch=source,
            target_branch=target,
        )

    async def merge_pull_request(self, repo: str, number: int) -> bool:
        result = await self._json(
            "PUT", f"{self._repo_url(repo)}/pulls/{number}/merge", json={"merge_method": "squash"}
        )
        return bool(result and result.get("merged"))

    def verify_webhook(self, secret: str, body: bytes, signature: str | None) -> bool:  # type: ignore[override]
        return GitProvider.verify_webhook(secret, body, signature)


class GitLabProvider(GitProvider):
    def __init__(self, base_url: str, token: str) -> None:
        super().__init__(base_url, token)
        self._client.headers.update({"PRIVATE-TOKEN": token})

    def _project(self, repo: str) -> str:
        return f"{self.base_url}/api/v4/projects/{quote(repo, safe='')}"

    async def repo_info(self, repo: str) -> dict[str, Any]:
        return await self._json("GET", self._project(repo)) or {}

    async def list_branches(self, repo: str) -> list[dict[str, Any]]:
        data = await self._json("GET", f"{self._project(repo)}/repository/branches")
        return [
            {"name": b["name"], "sha": b["commit"]["id"], "protected": b.get("protected", False)}
            for b in (data or [])
        ]

    async def list_commits(self, repo: str, ref: str, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._json(
            "GET", f"{self._project(repo)}/repository/commits", params={"ref_name": ref, "per_page": limit}
        )
        return [
            {"sha": c["id"], "message": c["message"], "author": c["author_name"], "date": c["created_at"]}
            for c in (data or [])
        ]

    async def read_file(self, repo: str, path: str, ref: str) -> str | None:
        data = await self._json(
            "GET",
            f"{self._project(repo)}/repository/files/{quote(path, safe='')}",
            params={"ref": ref},
        )
        if not data:
            return None
        import base64

        return base64.b64decode(data["content"]).decode("utf-8")

    async def commit_files(
        self,
        repo: str,
        branch: str,
        message: str,
        changes: list[FileChange],
        *,
        base_branch: str | None = None,
    ) -> str:
        if base_branch:
            branches = {b["name"] for b in await self.list_branches(repo)}
            if branch not in branches:
                await self._json(
                    "POST",
                    f"{self._project(repo)}/repository/branches",
                    params={"branch": branch, "ref": base_branch},
                )
        actions = [{"action": c.operation, "file_path": c.path, "content": c.content} for c in changes]
        data = await self._json(
            "POST",
            f"{self._project(repo)}/repository/commits",
            json={"branch": branch, "commit_message": message, "actions": actions},
        )
        return data["id"]

    async def create_pull_request(
        self, repo: str, title: str, body: str, source: str, target: str
    ) -> PullRequest:
        data = await self._json(
            "POST",
            f"{self._project(repo)}/merge_requests",
            json={
                "title": title,
                "description": body,
                "source_branch": source,
                "target_branch": target,
                "remove_source_branch": False,
            },
        )
        return PullRequest(
            number=data["iid"],
            title=data["title"],
            url=data["web_url"],
            state=data["state"],
            source_branch=source,
            target_branch=target,
        )

    async def merge_pull_request(self, repo: str, number: int) -> bool:
        result = await self._json("PUT", f"{self._project(repo)}/merge_requests/{number}/merge")
        return bool(result and result.get("state") == "merged")


class AzureDevOpsProvider(GitProvider):
    def __init__(self, organization: str, project: str, token: str) -> None:
        super().__init__(f"https://dev.azure.com/{organization}/{quote(project)}", token)
        self._client.headers.update({"Authorization": f"Basic {self._basic(token)}"})

    @staticmethod
    def _basic(token: str) -> str:
        import base64

        return base64.b64encode(f":{token}".encode()).decode()

    async def repo_info(self, repo: str) -> dict[str, Any]:
        return await self._json("GET", f"{self.base_url}/_apis/git/repositories/{repo}") or {}

    async def list_branches(self, repo: str) -> list[dict[str, Any]]:
        data = await self._json("GET", f"{self.base_url}/_apis/git/repositories/{repo}/refs")
        branches = [
            {"name": r["name"].replace("refs/heads/", ""), "sha": r["objectId"], "protected": False}
            for r in (data or {}).get("value", [])
            if r["name"].startswith("refs/heads/")
        ]
        return sorted(branches, key=lambda b: b["name"])

    async def list_commits(self, repo: str, ref: str, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._json(
            "GET",
            f"{self.base_url}/_apis/git/repositories/{repo}/commits",
            params={"searchCriteria.itemVersion.version": ref, "$top": limit},
        )
        return [
            {
                "sha": c["commitId"],
                "message": c["comment"],
                "author": c["author"]["name"],
                "date": c["author"]["date"],
            }
            for c in (data or {}).get("value", [])
        ]

    async def read_file(self, repo: str, path: str, ref: str) -> str | None:
        response = await self._client.get(
            f"{self.base_url}/_apis/git/repositories/{repo}/items",
            params={"path": path, "versionDescriptor.version": ref, "includeContent": "true"},
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise UpstreamError(f"Azure DevOps read failed: {response.status_code}")
        return response.text

    async def commit_files(
        self,
        repo: str,
        branch: str,
        message: str,
        changes: list[FileChange],
        *,
        base_branch: str | None = None,
    ) -> str:
        changes_payload = [
            {
                "changeType": {"create": "add", "update": "edit", "delete": "delete"}[c.operation],
                "item": {"path": f"/{c.path}"},
                **(
                    {"newContent": {"content": c.content, "contentType": "rawtext"}}
                    if c.operation != "delete"
                    else {}
                ),
            }
            for c in changes
        ]
        payload = {
            "refUpdates": [{"name": f"refs/heads/{branch}", "oldObjectId": await self._tip(repo, branch)}],
            "commits": [{"comment": message, "changes": changes_payload}],
        }
        data = await self._json("POST", f"{self.base_url}/_apis/git/repositories/{repo}/pushes", json=payload)
        return data["commits"][0]["commitId"]

    async def _tip(self, repo: str, branch: str) -> str:
        data = await self._json(
            "GET",
            f"{self.base_url}/_apis/git/repositories/{repo}/refs",
            params={"filter": f"heads/{branch}"},
        )
        return data["value"][0]["objectId"]

    async def create_pull_request(
        self, repo: str, title: str, body: str, source: str, target: str
    ) -> PullRequest:
        data = await self._json(
            "POST",
            f"{self.base_url}/_apis/git/repositories/{repo}/pullrequests",
            json={
                "sourceRefName": f"refs/heads/{source}",
                "targetRefName": f"refs/heads/{target}",
                "title": title,
                "description": body,
            },
        )
        return PullRequest(
            number=data["pullRequestId"],
            title=data["title"],
            url=data.get("url", ""),
            state=data["status"],
            source_branch=source,
            target_branch=target,
        )

    async def merge_pull_request(self, repo: str, number: int) -> bool:
        data = await self._json(
            "PATCH",
            f"{self.base_url}/_apis/git/repositories/{repo}/pullrequests/{number}",
            json={"status": "completed", "completionOptions": {"squashMerge": True}},
        )
        return bool(data)


def provider_for(
    provider: str,
    *,
    url: str = "",
    token: str = "",
    organization: str = "",
    project: str = "",
) -> GitProvider:
    match provider:
        case "github":
            return GitHubProvider(token=token or settings.GITHUB_TOKEN)
        case "gitlab":
            return GitLabProvider(base_url=url or settings.GITLAB_URL, token=token or settings.GITLAB_TOKEN)
        case "azure_devops":
            return AzureDevOpsProvider(
                organization=organization or settings.AZURE_DEVOPS_ORG,
                project=project,
                token=token or settings.AZURE_DEVOPS_PAT,
            )
        case _:
            raise BadRequestError(f"Unsupported git provider: {provider}")


# --------------------------------------------------------------------------- local workspace
class LocalGitWorkspace:
    """Ephemeral clone used for diffing and policy linting without provider APIs."""

    def __init__(self, url: str, token: str | None = None, branch: str = "main") -> None:
        self.url = url
        self.token = token
        self.branch = branch
        self.path: Path | None = None

    def __enter__(self) -> LocalGitWorkspace:
        self.path = Path(tempfile.mkdtemp(prefix="ofme-git-"))
        asyncio.get_event_loop().run_until_complete(self._clone(self.path))
        return self

    def __exit__(self, *_: object) -> None:
        if self.path and self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)

    def _auth_url(self) -> str:
        parsed = urlparse(self.url)
        if not self.token or parsed.scheme not in {"http", "https"}:
            return self.url
        return parsed._replace(netloc=f"x-access-token:{self.token}@{parsed.netloc}").geturl()

    async def _clone(self, target: Path) -> None:
        process = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            self.branch,
            self._auth_url(),
            str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise UpstreamError(f"git clone failed: {stderr.decode(errors='replace')[:500]}")

    def files(self, pattern: str = "**/*.yaml") -> list[Path]:
        assert self.path is not None
        return sorted(p for p in self.path.glob(pattern) if p.is_file())
