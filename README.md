# 🎮 XServer Game 無料サーバー自动续期

## 🌟 亮点

🌐 **浏览器自动过 Cloudflare 盾** · 无需人工干预（自动等待 JS 挑战 / 点击 Turnstile）

⚡ **HTTP 快速模式** · 期限读取 / 续期提交直接走 curl_cffi（真实 TLS 指纹 + 浏览器 Cookie），秒级完成；被 CF 拦截或解析失败自动回退浏览器（面板跳转由浏览器执行，保证会话完整）

🕐 剩余低于 **4 小时** 自动续期

🔁 已过期也能自动恢复

☁️ **可选**：动态更新 Cloudflare Worker Cron，实现准点续期

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
- **CF_SCRIPT_NAME**：`Workers & Pages` 列表中你的 Worker 名称。

> 未配置这三项时脚本会自动跳过 Cron 更新，不影响续期主流程。

---

## ⏰ 触发时间

工作流默认每 12 小时触发一次：

```yaml
schedule:
  - cron: "0 0,12 * * *"  # UTC 时间，对应北京时间 08:00 / 20:00
```

配置 CF 三项后，脚本会根据剩余时间动态改写 Worker Cron，
让下次运行更贴近到期时间。也可在 Actions 页面手动触发。

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
