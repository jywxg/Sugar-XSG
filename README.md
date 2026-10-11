# 🎮 XServer Game 無料サーバー自动续期

## 🌟 亮点

🌐 **浏览器自动过 Cloudflare 盾** · 无需人工干预（自动等待 JS 挑战 / 点击 Turnstile）

⚡ **HTTP 快速模式** · 期限读取 / 续期提交直接走 curl_cffi（真实 TLS 指纹 + 浏览器 Cookie），秒级完成；被 CF 拦截或解析失败自动回退浏览器（面板跳转由浏览器执行，保证会话完整）

🕐 剩余低于 **4 小时** 自动续期

🔁 已过期也能自动恢复

☁️ **可选**：动态更新 Cloudflare Worker Cron，实现准点续期

🧩 **可选**：Cloudflare Worker 触发控制台——网页按钮 / 定时任务 / API 三种方式随时唤醒 GitHub Actions

---

## 🚀 快速开始

1. **Fork** 本仓库
2. 进入 **Settings → Secrets and variables → Actions**
3. 添加下方环境变量
4. 手动触发一次 `XServer-Game-Renew` 确认运行正常

---

## 🔑 环境变量配置

| 变量名 | 必填 | 格式 | 示例 |
|---|:---:|---|---|
| `XSERVER_GAME_ACCOUNT` | ✅ | `自定义名称,邮箱,密码`（多个账号用换行/分号分隔） | `我的服务器,foo@bar.com,mypassword` |
| `TG_BOT` | ❌ | `chat_id,bot_token` | `123456789,7712345:AAFxxx` |
| `NODE_LINK` | ❌ | 代理链接（如 vless:// vmess:// trojan:// hysteria2:// tuic:// anytls:// socks5:// ) | `vmess://...` |
| `CF_ACCOUNT_ID` | ❌ | Cloudflare 账户 ID | `a1b2c3d4e5f6...` |
| `CF_API_TOKEN` | ❌ | Cloudflare API Token（需 **Workers Scripts Edit** 权限） | `xxxxx` |
| `CF_SCRIPT_NAME` | ❌ | Cloudflare Worker 脚本名称 | `xserver-renew-worker` |

### ☁️ Cloudflare 变量说明（可选）

配置后，脚本会在每次续期完成后通过 Cloudflare Workers API
动态更新 Worker 的 cron 调度，把下次运行时间精确设置到"剩余时间-235 分钟"，
从而无需频繁触发 GitHub Actions 也能准点续期。

获取方式：

- **CF_ACCOUNT_ID**：登录 Cloudflare Dashboard，地址栏 URL 中的
  `/account/` 后面那串 ID（或页面右上角 → 账户 ID）。
- **CF_API_TOKEN**：`My Profile → API Tokens → Create Token`，
  模板选 **Edit Cloudflare Workers**（权限：Account → Workers Scripts → Edit），
  Resources 选对应账户。
- **CF_SCRIPT_NAME**：`Workers & Pages` 列表中你的 Worker 名称（即下节部署的 Worker）。

> 未配置这三项时脚本会自动跳过 Cron 更新，不影响续期主流程。

---

## ⏰ 触发时间

工作流默认每 12 小时触发一次：

```yaml
schedule:
  - cron: "0 0,12 * * *"  # UTC 时间，对应北京时间 08:00 / 20:00
```

配置 CF 三项后，脚本会根据剩余时间动态改写 Worker Cron，让下次运行更贴近到期时间。

工作流同时监听外部唤醒事件（`renew-trigger`），可用下方 Worker 触发器随时手动唤醒：

```yaml
on:
  workflow_dispatch:          # Actions 页面手动触发
  repository_dispatch:        # Cloudflare Worker / API 外部触发
    types: [renew-trigger]
  schedule:
    - cron: "0 0,12 * * *"
```

也可在 Actions 页面直接手动触发。

---

## 🧩 Cloudflare Worker 外部触发（可选）

配套的 `worker.js` 是一个部署在 Cloudflare 上的触发控制台，提供三种方式
向本仓库发送 `renew-trigger` 事件，立即运行续期工作流：

- 🌐 **网页按钮**：打开 Worker 域名，输入密码点「立即唤醒」
- ⏰ **定时任务**：Worker 自带 Cron Trigger，到点自动唤醒
- 🔗 **API 调用**：`curl` 直接请求 `/trigger` 接口

配合脚本的 CF 三项变量，还能实现**全自动闭环**：
脚本每次跑完 → 自动把该 Worker 的 Cron 改为"到期前 235 分钟" →
到点 Worker 定时触发 → 唤醒 GitHub Actions 续期。

### 部署步骤

1. Cloudflare Dashboard → **Workers & Pages → Create → Worker**，
   命名（如 `xserver-renew-trigger`），点击 **Edit Code**。
2. 将 `worker.js` 全部内容粘贴进编辑器，**Deploy** 保存。
3. 进入 Worker **Settings → Variables and Secrets**，添加以下变量：

| 变量名 | 必填 | 说明 | 示例 |
|---|:---:|---|---|
| `AUTH_TOKEN` | 建议 | 网页/API 访问密码；未配置时接口不做校验（任何人都能触发） | `my-secret-token` |
| `GH_OWNER` | ✅ | 仓库所属用户名/组织 | `yourname` |
| `GH_REPO` | ✅ | 仓库名（Fork 后的仓库） | `xserver-game-renew` |
| `GH_PAT` | ✅ | GitHub Personal Access Token，需仓库 **Actions** 写权限 | `ghp_xxxxx` |
| `TG_BOT_TOKEN` | ❌ | 唤醒结果推送；与 TG_CHAT_ID 同时配置才生效 | `7712345:AAFxxx` |
| `TG_CHAT_ID` | ❌ | Telegram 接收者 ID | `123456789` |

> `GH_PAT` 获取：GitHub → Settings → Developer settings → Personal access tokens →
> Generate new token，勾选仓库 **Actions**（或直接 `repo` 范围）权限。
> 也可复用仓库里已有的 PAT，但推荐单独创建。

### 三种触发方式

- **🌐 网页控制台**：浏览器打开 `https://<你的worker域名>/`，
  输入 `AUTH_TOKEN` → 点击「立即唤醒」。支持回车提交。
- **⏰ Cron 定时**：Worker → Settings → **Triggers → Cron Triggers → Add**，
  例如 `0 */12 * * *`（每 12 小时）作为兜底。
  注意：脚本每次续期完会**自动覆盖**这个 Cron Trigger 为"到期前 235 分钟"，
  所以手动添加的兜底仅在脚本未配置 CF 变量时长期生效。
- **🔗 API 调用**（仅 POST，token 走 JSON body；GET 传 token 已下线）：
  ```bash
  curl -X POST "https://<你的worker域名>/trigger" \
    -H "Content-Type: application/json" \
    -d '{"token": "my-secret-token"}'
  ```
  返回 `200 OK` 即触发成功；60 秒内重复触发会返回 `429`（已自动去重）。

### 触发结果通知

每次唤醒都会向 Telegram 推送一条结果（配置了 TG 变量时）：

```
✅ <b>Cloudflare 触发器通知</b>
━━━━━━━━━━━━━━━━━━
📍 触发来源: <b>🖥️ Web 控制台手动触发</b>（或 ⏰ Cron 定时触发）
⏰ 触发时间: 2026-10-11 01:30:00 UTC
📊 执行结果: <b>唤醒 GitHub Actions 成功</b> (尝试 1 次)
🚀 目标仓库: yourname/xserver-game-renew
```

之后 Actions 工作流运行续期脚本，脚本本身还会再推送一条续期结果通知。

### 安全提示

- **务必配置 `AUTH_TOKEN`**：未配置时 `/trigger` 接口对所有请求开放，
  任何人知道 Worker 地址都能触发你的工作流（可能消耗 Actions 配额）。
- `AUTH_TOKEN` 只用于手动触发 / 网页控制台；Cron 定时触发由 Cloudflare
  服务端发起，不经过该校验。
- `GH_PAT` 是敏感凭据，建议单独创建并限制为 `repo` 范围，
  不要提交到代码/README，只放在 Worker 的 Secrets 里。

---

## 📊 通知示例

```
🎮 XServer Game 续期通知
━━━━━━━━━━━━━━━━━━
🖥 服务器名称: 我的服务器
📅 到期时间: 2026-06-14まで
⏱️ CST: 2026-06-12 08:00:00
⏳ 剩余: 15 小时 45 分
📊 结果: ✅ 续期成功！
🌐 IP: 1.2.3.4 (JP)
☁️ CF Cron: ✅ 更新成功
⚙️ CRON: 55 7 12 6 *
🕐 执行时间: 2026-06-12 08:00:00
━━━━━━━━━━━━━━━━━━
```

| 结果 | 说明 |
|---|---|
| ✅ 续期成功！ | 已成功续期，期限已刷新 |
| ⌛️ 期限未至（无需续期） | 剩余 ≥ 4 小时，本次跳过 |
| ⌛️ 期限未至（暂不可续期） | 剩余 < 4 小时但页面尚未开放续期 |
| ❌ 续期失败 | 请检查账号密码、代理或查看 Actions 日志 |
