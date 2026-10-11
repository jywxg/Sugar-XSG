export default {
  // 1. 处理 HTTP 请求 (返回 UI 界面 或 处理触发接口)
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 🌐 路由 1: 访问根目录 "/" 时，返回可视化的 UI 界面
    if (url.pathname === "/" && request.method === "GET") {
      return new Response(getUIHtml(), {
        headers: { "Content-Type": "text/html; charset=utf-8" }
      });
    }

    // 🚀 路由 2: 处理唤醒请求 "/trigger"
    if (url.pathname === "/trigger") {
      // ⚠️ 只允许 GET / POST，其余 (HEAD/OPTIONS/PUT 等) 一律 405，避免意外触发任务
      if (request.method !== "GET" && request.method !== "POST") {
        return new Response("方法不允许：仅支持 GET / POST", { status: 405 });
      }

      // 🛡️ 仅支持 POST body 传 token；GET 的 query token 已下线（token 会进 Worker 日志/访问记录，有泄露风险）
      let providedToken = "";
      // 提取前端发来的 POST 请求体里的密码
      if (request.method === "POST") {
        try {
          const body = await request.json();
          if (body && body.token) providedToken = body.token;
        } catch (e) {
          // 忽略解析失败
        }
      }

      // 🛡️ 安全校验
      if (env.AUTH_TOKEN) {
        if (providedToken !== env.AUTH_TOKEN) {
          return new Response("❌ 触发失败：密码 (Token) 错误或未提供，禁止访问。", { 
            status: 401, 
            headers: { "Content-Type": "text/plain; charset=utf-8" }
          });
        }
      } else {
        console.warn("⚠️ 未配置 AUTH_TOKEN：/trigger 接口对所有人开放，建议立即在 Secrets 中添加！");
      }

      // 执行核心任务，按真实结果返回提示
      // ⏱️ 60 秒去重：同一分钟内重复触发直接 429 忽略，避免 cron 与手动撞车双发
      if (rejectDuplicateTrigger()) {
        return new Response("⏳ 60 秒内已触发过，本次重复请求已忽略。", {
          status: 429,
          headers: { "Content-Type": "text/plain; charset=utf-8" }
        });
      }

      const ok = await runTask(env, "🖥️ Web 控制台手动触发");
      if (ok) {
        return new Response("✅ 手动唤醒已执行成功！GitHub Actions 已收到通知。", {
          headers: { "Content-Type": "text/plain; charset=utf-8" }
        });
      }
      return new Response("❌ 唤醒失败：重试后仍无法通知 GitHub Actions，请查看 Telegram / Worker 日志。", {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8" }
      });
    }

    // 其他路径返回 404
    return new Response("页面不存在", { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  },

  // 2. 处理定时 Cron 触发任务 (无需修改，继续生效)
  async scheduled(event, env, ctx) {
    await runTask(env, "⏰ Cron 定时触发");
  }
};


// ==========================================
// 🎨 前端 UI 界面 HTML 生成器
// ==========================================
function getUIHtml() {
  return `
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>触发器控制台</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; background: #f3f4f6; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
    .card { background: white; padding: 2.5rem 2rem; border-radius: 16px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); width: 100%; max-width: 360px; text-align: center; box-sizing: border-box;}
    .icon { font-size: 3rem; margin-bottom: 0.5rem; }
    h1 { margin: 0 0 1.5rem 0; color: #1f2937; font-size: 1.5rem; font-weight: 600; }
    input { width: 100%; padding: 0.875rem; margin-bottom: 1rem; border: 1px solid #d1d5db; border-radius: 8px; box-sizing: border-box; font-size: 1rem; outline: none; transition: border-color 0.2s; }
    input:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1); }
    button { width: 100%; padding: 0.875rem; background: #3b82f6; color: white; border: none; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; transition: background 0.2s, transform 0.1s; }
    button:hover { background: #2563eb; }
    button:active { transform: scale(0.98); }
    button:disabled { background: #9ca3af; cursor: not-allowed; transform: none; }
    #msg { margin-top: 1.25rem; font-size: 0.9rem; min-height: 1.5rem; line-height: 1.5; color: #4b5563; word-break: break-all; }
    .success { color: #059669 !important; font-weight: 500; }
    .error { color: #dc2626 !important; font-weight: 500; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🚀</div>
    <h1>Actions 触发器</h1>
    <input type="password" id="token" placeholder="请输入 AUTH_TOKEN 密码" autocomplete="off" />
    <button id="btn" onclick="triggerTask()">立即唤醒</button>
    <div id="msg"></div>
  </div>

  <script>
    document.getElementById("token").addEventListener("keypress", function(event) {
      if (event.key === "Enter") {
        event.preventDefault();
        triggerTask();
      }
    });

    async function triggerTask() {
      const btn = document.getElementById('btn');
      const msg = document.getElementById('msg');
      const token = document.getElementById('token').value;
      
      if (!token) {
        msg.className = "error";
        msg.innerText = "⚠️ 请先输入密码！";
        return;
      }

      btn.disabled = true;
      btn.innerText = "⏳ 正在唤醒后台...";
      msg.className = "";
      msg.innerText = "";
      
      try {
        const res = await fetch('/trigger', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: token })
        });
        const text = await res.text();
        
        if (res.ok) {
          msg.className = "success";
          msg.innerText = text; 
          document.getElementById('token').value = ""; 
        } else {
          msg.className = "error";
          msg.innerText = text;
        }
      } catch(e) {
        msg.className = "error";
        msg.innerText = "❌ 网络错误：" + e.message;
      } finally {
        btn.disabled = false;
        btn.innerText = "立即唤醒";
      }
    }
  </script>
</body>
</html>
  `;
}


// ==========================================
// ⏱️ 60 秒内存去重：/trigger 短时间重复触发时（cron 与手动撞车、远端请求重试），
// 避免重复 dispatch 消耗 GitHub Actions 配额。scheduled 定时触发不经过此逻辑，不受影响。
// ==========================================
let lastTriggerAt = 0;
function rejectDuplicateTrigger() {
  const now = Date.now();
  if (now - lastTriggerAt < 60000) return true; // 60 秒内已触发过 → 本次应拒绝
  lastTriggerAt = now;
  return false;
}

// ==========================================
// ⏱️ 带超时的 fetch（防上游 hang 住拖死 Worker，重试逻辑才能正常推进）
// ==========================================
async function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}


// ==========================================
// ⚙️ 核心任务逻辑
// ==========================================
async function runTask(env, triggerSource) {
  console.log(`${triggerSource}: 正在唤醒 GitHub Actions...`);

  if (!env.GH_OWNER || !env.GH_REPO || !env.GH_PAT) {
    const errorMsg = "缺少必要的 GitHub 环境变量 (GH_OWNER, GH_REPO, GH_PAT)";
    console.error(`⚠️ ${errorMsg}`);
    await sendTgNotification(env, false, 0, errorMsg, triggerSource);
    return false;
  }

  // 重试次数可配置（默认 3），避免硬编码
  const maxRetries = Math.max(1, parseInt(env.MAX_RETRIES, 10) || 3);
  let attempt = 0;
  let success = false;
  let lastError = "";

  const url = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/dispatches`;

  while (attempt < maxRetries && !success) {
    attempt++;
    try {
      const response = await fetchWithTimeout(url, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.GH_PAT}`,
          "User-Agent": "CF-Worker-Scheduler",
          "Content-Type": "application/json",
          "Accept": "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28"
        },
        body: JSON.stringify({ event_type: "renew-trigger" })
      }, 20000);

      if (response.ok) {
        success = true;
        console.log(`✅ 第 ${attempt} 次尝试成功唤醒 GitHub Actions！`);
      } else {
        const errText = await response.text();
        lastError = `HTTP ${response.status}: ${errText}`;
      }
    } catch (err) {
      lastError = err.message || String(err);
    }
    if (!success && attempt < maxRetries) await new Promise((res) => setTimeout(res, 3000));
  }
  await sendTgNotification(env, success, attempt, lastError, triggerSource);
  return success;
}


// ==========================================
// 📨 Telegram 推送逻辑
// ==========================================
async function sendTgNotification(env, success, attempt, lastError, triggerSource) {
  if (!env.TG_BOT_TOKEN || !env.TG_CHAT_ID) return;

  const statusIcon = success ? "✅" : "❌";
  const statusText = success ? "唤醒 GitHub Actions 成功" : "唤醒 GitHub Actions 失败";

  let msg = `${statusIcon} <b>Cloudflare 触发器通知</b>\n━━━━━━━━━━━━━━━━━━\n`;
  msg += `📍 触发来源: <b>${triggerSource}</b>\n`;
  msg += `⏰ 触发时间: <code>${new Date().toISOString().replace('T', ' ').substring(0, 19)} UTC</code>\n`;
  msg += `📊 执行结果: <b>${statusText}</b> (尝试 ${attempt} 次)\n`;

  if (!success) {
    // 🐛 修复：必须先转义 & 再转义 < >，否则 &lt; 里的 & 会被二次转义成 &amp;lt;
    const safeError = String(lastError)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    msg += `❌ 错误详情: <code>${safeError}</code>\n`;
  } else {
    msg += `🚀 目标仓库: <code>${env.GH_OWNER}/${env.GH_REPO}</code>\n`;
  }

  try {
    const tgRes = await fetchWithTimeout(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: String(env.TG_CHAT_ID),
        text: msg,
        parse_mode: "HTML",
        disable_web_page_preview: true
      })
    }, 15000);
    if (!tgRes.ok) {
      console.error(`❌ TG 推送失败: HTTP ${tgRes.status}`);
    }
  } catch (err) {
    console.error("❌ CF 请求 TG 接口异常:", err);
  }
}