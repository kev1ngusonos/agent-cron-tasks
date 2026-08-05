#!/usr/bin/env python3
"""
Daily Slack unread-messages digest.

1. Lists every channel the digest bot is a member of.
2. Fetches messages posted since the last run (tracked per-channel in
   scripts/slack_digest_state.json, committed back to the repo by the
   workflow).
3. Summarizes the batch with GitHub Models (gpt-4o-mini) into a concise,
   Chinese digest grouped by channel.
4. DMs the digest to SLACK_USER_ID via the bot's chat.postMessage.

Reading is done with YOUR OWN Slack user token (xoxp) so no bot ever has to
join any of your channels - it simply reads whatever you, the token owner,
already have access to (mirroring "my own unread messages"). A separate,
minimal bot token (chat:write only) is used purely to DM the digest to you.

Env vars required:
  SLACK_USER_TOKEN  - xoxp-... user token (User Token Scopes: channels:history,
                       channels:read, groups:history, groups:read, im:history,
                       mpim:history, users:read)
  SLACK_BOT_TOKEN   - xoxb-... bot token (Bot Token Scopes: chat:write, im:write)
                       used only to open/send the digest DM
  SLACK_USER_ID     - your Slack member ID (e.g. U0123ABC456), DM recipient
  GITHUB_TOKEN      - provided automatically by Actions; needs `models: read`
                       permission for the GitHub Models inference call
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SLACK_API = "https://slack.com/api"
STATE_FILE = Path(__file__).parent / "slack_digest_state.json"
MODELS_API = "https://models.github.ai/inference/chat/completions"
MODEL_NAME = "openai/gpt-4o-mini"
LOOKBACK_SECONDS_DEFAULT = 24 * 3600  # first-run fallback: last 24h
MAX_MESSAGES_PER_CHANNEL = 200
SKIP_SUBTYPES = {
    "channel_join", "channel_leave", "channel_topic", "channel_purpose",
    "channel_name", "bot_add", "bot_remove", "pinned_item", "unpinned_item",
}

USER_TOKEN = os.environ["SLACK_USER_TOKEN"]
BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
USER_ID = os.environ["SLACK_USER_ID"]
GH_TOKEN = os.environ["GITHUB_TOKEN"]


def slack_call(method, params=None, post=False, token=None):
    headers = {"Authorization": f"Bearer {token or USER_TOKEN}"}
    if post:
        data = json.dumps(params or {}).encode()
        req = urllib.request.Request(
            f"{SLACK_API}/{method}", data=data, headers={**headers, "Content-Type": "application/json"}
        )
    else:
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in (params or {}).items())
        url = f"{SLACK_API}/{method}"
        if query:
            url += f"?{query}"
        req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        result = json.load(resp)
    if not result.get("ok"):
        raise RuntimeError(f"Slack API {method} failed: {result.get('error')} {result}")
    return result


def list_member_channels():
    """Channels the token owner (you) already belongs to. Uses users.conversations
    with the user token, so no bot needs to join anything - it's just your own
    channel membership."""
    channels = []
    cursor = None
    while True:
        params = {
            "types": "public_channel,private_channel",
            "limit": 200,
            "exclude_archived": "true",
        }
        if cursor:
            params["cursor"] = cursor
        result = slack_call("users.conversations", params)
        channels.extend(result.get("channels", []))
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return channels


def get_last_read(channel_id):
    """Slack's own per-channel 'last read' cursor for the token owner - this is
    exactly what Slack's UI uses to compute the unread badge. Used as the
    fallback starting point on a channel's first digest run so the very first
    run captures the *entire* unread backlog, not just a rolling 24h window."""
    try:
        result = slack_call("conversations.info", {"channel": channel_id})
        last_read = result.get("channel", {}).get("last_read")
        if last_read:
            return last_read
    except Exception as e:
        print(f"warn: could not fetch last_read for {channel_id}: {e}")
    return None


def fetch_history(channel_id, oldest_ts):
    messages = []
    cursor = None
    while True:
        params = {"channel": channel_id, "oldest": oldest_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        result = slack_call("conversations.history", params)
        for m in result.get("messages", []):
            if m.get("subtype") in SKIP_SUBTYPES:
                continue
            messages.append(m)
        if len(messages) >= MAX_MESSAGES_PER_CHANNEL or not result.get("has_more"):
            break
        cursor = result.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return messages[:MAX_MESSAGES_PER_CHANNEL]


_user_name_cache = {}


def resolve_user(user_id):
    if not user_id:
        return "unknown"
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]
    try:
        result = slack_call("users.info", {"user": user_id})
        name = result["user"].get("real_name") or result["user"].get("name") or user_id
    except Exception:
        name = user_id
    _user_name_cache[user_id] = name
    return name


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def summarize_with_github_models(channel_digests):
    """channel_digests: list of {"name": str, "lines": [str, ...]}"""
    if not channel_digests:
        return None

    transcript_parts = []
    for cd in channel_digests:
        transcript_parts.append(f"### #{cd['name']}\n" + "\n".join(cd["lines"]))
    transcript = "\n\n".join(transcript_parts)

    system_prompt = (
        "你是一个 Slack 消息摘要助手。你会收到多个频道自上次查看以来的新消息列表。"
        "请为每个频道生成简洁的中文摘要：突出重要讨论、需要用户回复的问题/@提及、"
        "以及行动项；忽略闲聊寒暄。用 Markdown 格式，按频道分组，每个频道 1-4 条要点。"
        "如果某频道消息很少或不重要，可以直接一句话带过或省略。最后给出总体是否有紧急事项需要立即处理的提示。"
    )
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcript[:100000]},  # guard against oversized payloads
        ],
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        MODELS_API,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.load(resp)
    return result["choices"][0]["message"]["content"]


def send_dm(text):
    opened = slack_call("conversations.open", {"users": USER_ID}, post=True, token=BOT_TOKEN)
    dm_channel = opened["channel"]["id"]
    slack_call(
        "chat.postMessage",
        {"channel": dm_channel, "text": text, "unfurl_links": False, "unfurl_media": False},
        post=True,
        token=BOT_TOKEN,
    )


def main():
    state = load_state()
    now_ts = time.time()
    channels = list_member_channels()

    channel_digests = []
    new_state = dict(state)
    total_new_messages = 0

    for ch in channels:
        cid = ch["id"]
        name = ch.get("name", cid)
        if cid in state:
            oldest = state[cid]
        else:
            # First run for this channel: prefer Slack's own unread cursor so we
            # capture the full backlog, falling back to a rolling 24h window if
            # last_read isn't available (e.g. never-visited channel).
            oldest = get_last_read(cid) or str(now_ts - LOOKBACK_SECONDS_DEFAULT)
        try:
            messages = fetch_history(cid, oldest)
        except Exception as e:
            print(f"warn: failed to fetch history for #{name}: {e}")
            continue
        if not messages:
            continue
        messages.sort(key=lambda m: float(m["ts"]))
        lines = []
        for m in messages:
            text = (m.get("text") or "").replace("\n", " ").strip()
            if not text:
                continue
            author = resolve_user(m.get("user") or m.get("bot_id"))
            lines.append(f"- {author}: {text}")
        if lines:
            channel_digests.append({"name": name, "lines": lines})
            total_new_messages += len(lines)
        new_state[cid] = str(messages[-1]["ts"])

    save_state(new_state)

    if not channel_digests:
        print("No new messages across any channel; skipping DM.")
        return

    summary = summarize_with_github_models(channel_digests)
    header = f"🗞️ *Slack 每日摘要* — 共 {len(channel_digests)} 个频道有新消息，{total_new_messages} 条未读\n\n"
    send_dm(header + (summary or "(摘要生成失败，请查看原始频道)"))
    print(f"Digest sent: {len(channel_digests)} channels, {total_new_messages} messages")


if __name__ == "__main__":
    main()
