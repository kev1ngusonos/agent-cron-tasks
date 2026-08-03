# Slack Daily Unread Digest — 设置指南

自动每天 07:00(北京时间)汇总你所在的几十个 Slack 频道里的新消息，用 GitHub Models
生成中文摘要，并通过 Slack 机器人私信(DM)发给你。

## 1. 创建专用 Slack App

1. 打开 https://api.slack.com/apps → **Create New App** → **From scratch**
2. App Name 填 `Daily Digest Bot`（随意），选择你的工作区
3. 左侧菜单 **OAuth & Permissions** → **Scopes** → **Bot Token Scopes**，添加：
   - `channels:history`
   - `channels:read`
   - `groups:history`
   - `groups:read`
   - `im:write`
   - `chat:write`
   - `users:read`
   （如果你有私聊/多人私聊也想纳入摘要，再加 `im:history`、`mpim:history`、`mpim:read`）
4. 页面顶部 **Install to Workspace**，授权后复制 **Bot User OAuth Token**
   （形如 `xoxb-...`）
5. 把机器人加入你想汇总的频道：在每个频道里发送 `/invite @Daily Digest Bot`
   （公开频道机器人也可以后续用 API 自动加入，但手动 invite 最省事最可控）

## 2. 获取你自己的 Slack 用户 ID

Slack 客户端 → 点击你的头像 → **Profile** → 右上角 `···` → **Copy member ID**
（形如 `U0123ABC456`）

## 3. 在 GitHub 仓库添加 Secrets

在 `kev1ngusonos/agent-cron-tasks` 仓库 → **Settings → Secrets and variables →
Actions** 添加：

| Secret name              | 值                          |
|---------------------------|-----------------------------|
| `SLACK_DIGEST_BOT_TOKEN`  | 第 1 步复制的 `xoxb-...` token |
| `SLACK_DIGEST_USER_ID`    | 第 2 步复制的 `U...` 用户 ID   |

`GITHUB_TOKEN` 由 Actions 自动提供，无需手动配置；workflow 已声明
`permissions: models: read` 用于调用 GitHub Models。

## 4. 首次运行

- 手动触发一次验证：仓库 **Actions** 页 → `Slack Daily Unread Digest` →
  **Run workflow**
- 首次运行没有历史状态文件，默认回溯最近 24 小时的消息
- 运行结束后，脚本会把每个频道读取到的最新消息时间戳写入
  `scripts/slack_digest_state.json` 并由 workflow 自动提交，下次运行只处理
  「上次运行之后」的新消息，从而实现「未读消息」的效果

## 5. 之后

- 默认每天 UTC 23:00（北京时间 07:00）自动运行，可在
  `.github/workflows/slack-daily-digest.yml` 里改 cron 表达式调整时间
- 想新增频道纳入摘要：把机器人 `/invite` 进去即可，无需改代码
- 如果某天没有新消息，脚本会跳过发送 DM（不会打扰你）
