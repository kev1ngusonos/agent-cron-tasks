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

STALE_DAYS = 2
STALE_STATUSES = {"打开", "重新打开", "正在进行", "Open", "Reopened", "In Progress"}


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
        if last_dt < cutoff and row["status"] in STALE_STATUSES:
            stale_rows.append(row)

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📋 HWSTAGE 每日检查 — {now.date().isoformat()}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"Open issues: *{len(rows)}*"},
        },
        {"type": "divider"},
    ]

    if stale_rows:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *超过 {STALE_DAYS} 天无人回复 ({len(stale_rows)}):*",
                },
            }
        )
        # Slack section "fields" max is 10 per block, so chunk every 5 issues
        # (2 fields per issue: title/link and assignee/last-activity).
        for i in range(0, len(stale_rows), 5):
            chunk = stale_rows[i : i + 5]
            fields = []
            for r in chunk:
                issue_url = f"{BASE_URL}/browse/{r['key']}"
                fields.append(
                    {
                        "type": "mrkdwn",
                        "text": f"*<{issue_url}|{r['key']}>*\n{r['summary']}",
                    }
                )
                fields.append(
                    {
                        "type": "mrkdwn",
                        "text": f"👤 {r['assignee']}\n🕐 最后活动 {r['last_activity']}",
                    }
                )
            blocks.append({"type": "section", "fields": fields})
            blocks.append({"type": "divider"})
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":white_check_mark: 没有超过{STALE_DAYS}天无人回复的 issue",
                },
            }
        )
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "查看全部 Jira", "emoji": True},
                    "url": f"{BASE_URL}/issues/?jql={urllib.parse.quote(JQL)}",
                }
            ],
        }
    )

    # Slack requires a top-level "text" fallback for notifications/screen readers.
    payload = {
        "text": f"HWSTAGE 每日检查 — {now.date().isoformat()}: {len(stale_rows)} 个超期未回复",
        "blocks": blocks,
    }
    with open("digest.json", "w") as fh:
        json.dump(payload, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
