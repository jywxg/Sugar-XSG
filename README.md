# 🎮 XServer Game 无料サーバー自动续期

## 🌟 亮点

⚡️ 纯 HTTP 请求，无浏览器 · 秒级完成

🕐 剩余低于 16 小时自动续期

🔁 已过期也能自动恢复

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
| `XSERVER_GAME_ACCOUNT` | ✅ | `自定义名称,邮箱,密码` | `我的服务器,foo@bar.com,mypassword` |
| `TG_BOT` | ❌ | `chat_id,bot_token` | `123456789,7712345:AAFxxx` |
| `GOST_PROXY` | ❌ | GOST 代理地址 | `socks5://user:pass@1.2.3.4:1080` |

---

## ⏰ 触发时间

默认不设定自动触发时间，请在 `.github/workflows/xserver_game_renew.yml` 中自行修改 cron：

```yaml
schedule:
  - cron: "0 0,12 * * *"  # UTC 时间，对应北京时间 08:00 / 20:00
```

也可在 Actions 页面手动触发。

---

## 📊 通知示例

```
🎮 XServer Game 续期通知
🕐 运行时间: 2026-06-12 08:00:00
🖥 服务器: 我的服务器
📅 利用期限: 2026-06-14まで
📊 续期结果: ✅ 续期成功！
```

| 结果 | 说明 |
|---|---|
| ✅ 续期成功！ | 已成功续期 |
| ⌛️ 期限未至！ | 剩余时间充足，无需续期 |
| ❌ 续期失败！ | 请检查账号密码或查看 Actions 日志 |
