#!/usr/bin/env python3
"""
Fetch open HWSTAGE Jira issues, flag ones with no reply/comment in > 3 days,
and write a Slack Block Kit payload to digest.json.

Requires env vars: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JQL
(Uses Jira Cloud REST API v3 with basic auth: email + API token.
 Create a token at https://id.atlassian.com/manage-profile/security/api-tokens)
"""
import base64
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ["JIRA_BASE_URL"].rstrip("/")
EMAIL = os.environ["JIRA_EMAIL"]
TOKEN = os.environ["JIRA_API_TOKEN"]
JQL = os.environ.get("JQL", "project = HWSTAGE AND statusCategory != Done ORDER BY created DESC")

STALE_DAYS = 3


def jira_get(path, params):
    query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{BASE_URL}{path}?{query}"
    auth = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main():
    import urllib.parse  # noqa: E401

    # Atlassian retired GET /rest/api/3/search (returns 410 Gone);
    # use the newer /rest/api/3/search/jql endpoint instead.
    data = jira_get(
        "/rest/api/3/search/jql",
        {
            "jql": JQL,
            "fields": "summary,status,assignee,created,comment",
            "maxResults": 50,
        },
    )

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=STALE_DAYS)

    rows, stale_rows = [], []
    for issue in data.get("issues", []):
        f = issue["fields"]
        comments = (f.get("comment") or {}).get("comments", [])
        last_dt = None
        if comments:
            last_dt = datetime.strptime(
                comments[-1]["created"][:19], "%Y-%m-%dT%H:%M:%S"
            ).replace(tzinfo=timezone.utc)
        else:
            last_dt = datetime.strptime(
                f["created"][:19], "%Y-%m-%dT%H:%M:%S"
            ).replace(tzinfo=timezone.utc)

        row = {
            "key": issue["key"],
            "summary": f["summary"],
            "status": f["status"]["name"],
            "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
            "last_activity": last_dt.date().isoformat(),
        }
        rows.append(row)
        if last_dt < cutoff:
            stale_rows.append(row)

    lines = [f"*HWSTAGE 每日检查 — {now.date().isoformat()}*", f"Open issues: {len(rows)}"]
    if stale_rows:
        lines.append(f"\n:warning: *超过 {STALE_DAYS} 天无人回复 ({len(stale_rows)}):*")
        for r in stale_rows:
            url = f"{BASE_URL}/browse/{r['key']}"
            lines.append(f"• <{url}|{r['key']}> {r['summary']} — {r['assignee']} (最后活动 {r['last_activity']})")
    else:
        lines.append("\n:white_check_mark: 没有超过3天无人回复的 issue")

    payload = {"text": "\n".join(lines)}
    with open("digest.json", "w") as fh:
        json.dump(payload, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
