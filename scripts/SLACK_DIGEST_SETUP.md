# Slack Daily Unread Digest — 设置指南

自动每天 07:00(北京时间)汇总你在 Slack 里所有已加入频道的新消息，用 GitHub
Models 生成中文摘要，并通过 Slack 私信(DM)发给你。

**设计要点**：读取消息用的是你**自己的用户身份**（User Token），只读取你本来
就已经加入的频道，不需要任何机器人加入你的任何频道，其他成员完全看不到变化。
只有"把摘要发给你"这一步用一个极简的机器人（只有 `chat:write` 权限），它不需要
加入任何频道。

## 1. 创建 Slack App

1. 打开 https://api.slack.com/apps → **Create New App** → **From scratch**
2. App Name 填 `Daily Digest`（随意），选择你的工作区 → **Create App**

## 2. 配置 User Token Scopes（用于读取你自己的消息）

左侧菜单 **OAuth & Permissions** → 往下找到 **User Token Scopes**（不是 Bot Token
Scopes），添加：
- `channels:history`
- `channels:read`
- `groups:history`
- `groups:read`
- `users:read`
（如果也想汇总私聊/多人私聊，再加 `im:history`、`im:read`、`mpim:history`、`mpim:read`）

## 3. 配置 Bot Token Scopes（仅用于发 DM 给你）

同一页面 **Bot Token Scopes** 添加：
- `chat:write`
- `im:write`

## 4. 安装到工作区

页面顶部 **Install to Workspace** → 会跳转到一个授权页面，注意会分别对
**你的用户身份**和**这个 App 的机器人身份**分别授权。同意后：
- 复制 **User OAuth Token**（形如 `xoxp-...`）
- 复制 **Bot User OAuth Token**（形如 `xoxb-...`）

⚠️ User Token 等价于你自己的 Slack 账号权限，请务必只放进 GitHub Secrets，
不要泄露给任何人或提交进代码仓库。

## 5. 获取你自己的 Slack 用户 ID

Slack 客户端 → 点击你的头像 → **Profile** → 右上角 `···` → **Copy member ID**
（形如 `U0123ABC456`）

## 6. 在 GitHub 仓库添加 Secrets

`kev1ngusonos/agent-cron-tasks` 仓库 → **Settings → Secrets and variables →
Actions** → 添加：

| Secret name                 | 值                              |
|-------------------------------|----------------------------------|
| `SLACK_DIGEST_USER_TOKEN`     | 第 4 步复制的 `xoxp-...` token     |
| `SLACK_DIGEST_BOT_TOKEN`      | 第 4 步复制的 `xoxb-...` token     |
| `SLACK_DIGEST_USER_ID`        | 第 5 步复制的 `U...` 用户 ID       |

`GITHUB_TOKEN` 由 Actions 自动提供，workflow 已声明 `permissions: models: read`
用于调用 GitHub Models，无需手动配置。

## 7. 首次运行验证

仓库 **Actions** 页 → `Slack Daily Unread Digest` → **Run workflow**（手动触发）
- 首次运行没有历史状态文件，默认回溯最近 24 小时的消息
- 运行结束后会把每个频道读取到的最新消息时间戳写入
  `scripts/slack_digest_state.json` 并自动提交，下次运行只处理「上次运行之后」
  的新消息，从而实现「未读消息」效果
- 检查 Slack 私信是否收到摘要；同时可以到 Actions 运行日志里看有没有报错

## 8. 之后

- 默认每天 UTC 23:00（北京时间 07:00）自动运行，可在
  `.github/workflows/slack-daily-digest.yml` 里改 cron 表达式调整时间
- 你加入新频道后，下次运行会自动纳入摘要范围，无需任何额外操作
- 某天没有新消息时脚本会跳过发送 DM，不会打扰你
