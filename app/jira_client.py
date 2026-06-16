"""Minimal Jira Cloud client — pull FAIR document attachments from a ticket.

Configured entirely via environment variables (no secrets in code):
    JIRA_BASE_URL    e.g. https://skyryse.atlassian.net
    JIRA_EMAIL       the Atlassian account email the API token belongs to
    JIRA_API_TOKEN   created at https://id.atlassian.com/manage-profile/security/api-tokens

Uses HTTP Basic auth (email:api_token) over HTTPS, the standard for Jira Cloud REST.
Dependency-free (urllib only).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class JiraError(Exception):
    pass


def is_configured() -> bool:
    return all(os.environ.get(k) for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"))


def _cfg() -> tuple[str, str]:
    base = (os.environ.get("JIRA_BASE_URL") or "").rstrip("/")
    email = os.environ.get("JIRA_EMAIL") or ""
    token = os.environ.get("JIRA_API_TOKEN") or ""
    if not (base and email and token):
        raise JiraError("Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN.")
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    return base, auth


def base_url() -> str:
    return (os.environ.get("JIRA_BASE_URL") or "").rstrip("/")


def _open(url: str, auth: str, accept: str = "application/json"):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "Accept": accept})
    return urllib.request.urlopen(req, timeout=90)


def get_issue(key: str) -> dict:
    """Return the issue with its attachment list and summary."""
    base, auth = _cfg()
    url = f"{base}/rest/api/3/issue/{key}?fields=attachment,summary,status"
    try:
        with _open(url, auth) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise JiraError(f"Issue '{key}' not found, or this account cannot see it.")
        if e.code in (401, 403):
            raise JiraError("Jira authentication/permission failed — check the email, API token, and that the account can view this ticket.")
        raise JiraError(f"Jira returned error {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise JiraError(f"Could not reach Jira ({base}): {e.reason}")


def list_attachments(key: str) -> tuple[str, list[dict]]:
    """Return (issue summary, [attachment dicts])."""
    data = get_issue(key)
    fields = data.get("fields", {}) or {}
    return fields.get("summary", "") or "", (fields.get("attachment") or [])


def download_attachments(key: str, dest_dir: Path, allowed_exts: set[str] | None = None) -> dict:
    """Download every (allowed) attachment on the issue into dest_dir.

    Returns {summary, saved:[names], skipped:[names]}.
    """
    base, auth = _cfg()
    summary, atts = list_attachments(key)
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved, skipped = [], []
    for a in atts:
        name = Path(a.get("filename", "")).name
        if not name:
            continue
        if allowed_exts is not None and Path(name).suffix.lower() not in allowed_exts:
            skipped.append(name)
            continue
        content_url = a.get("content")
        if not content_url:
            skipped.append(name)
            continue
        try:
            with _open(content_url, auth, accept="*/*") as r:
                (dest_dir / name).write_bytes(r.read())
            saved.append(name)
        except urllib.error.HTTPError as e:
            raise JiraError(f"Failed downloading '{name}' from {key}: {e.code} {e.reason}")
    return {"summary": summary, "saved": saved, "skipped": skipped}
