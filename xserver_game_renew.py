import os
import re
import json
import time
from datetime import datetime, timezone, timedelta
import requests

# ==========================================
# 1. 环境变量与全局参数配置
# ==========================================
XSERVER_ACCOUNT_RAW = os.getenv("XSERVER_GAME_ACCOUNT", "")
TG_BOT_RAW = os.getenv("TG_BOT", "{}")
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_SCRIPT_NAME = os.getenv("CF_SCRIPT_NAME", "")
CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")

# 兼容 USE_PROXY 和 IS_PROXY 环境变量
USE_PROXY_ENV = os.getenv("USE_PROXY", "false").lower() == "true" or \
                os.getenv("IS_PROXY", "false").lower() == "true"
PROXY_SERVER = os.getenv("PROXY_SERVER", "socks5://127.0.0.1:1080")
PROXY_STATUS_ENV = os.getenv("PROXY_STATUS", f"代理: {PROXY_SERVER}")

# 解析账号信息 (支持 "username,password" 或 JSON 字符串格式)
XSERVER_USER = ""
XSERVER_PASS = ""
if XSERVER_ACCOUNT_RAW:
    try:
        acc_json = json.loads(XSERVER_ACCOUNT_RAW)
        XSERVER_USER = acc_json.get("username", "") or acc_json.get("account", "") or acc_json.get("user", "")
        XSERVER_PASS = acc_json.get("password", "") or acc_json.get("pass", "")
    except json.JSONDecodeError:
        if "," in XSERVER_ACCOUNT_RAW:
            XSERVER_USER, XSERVER_PASS = XSERVER_ACCOUNT_RAW.split(",", 1)
        else:
            XSERVER_USER = XSERVER_ACCOUNT_RAW

# 初始化全局 requests Session
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8"
})

# ==========================================
# 2. 代理防屏蔽与连通性检测
# ==========================================
final_proxy_status = "直连"

if USE_PROXY_ENV:
    proxies = {
        "http": PROXY_SERVER,
        "https": PROXY_SERVER
    }
    print(f"🔄 正在测试代理连接 XServer 是否可用: {PROXY_SERVER}")
    try:
        test_res = session.get("https://secure.xserver.ne.jp/xapanel/login/xgame/", proxies=proxies, timeout=10)
        
        # 判断代理 IP 是否被 XServer 防火墙拉黑/拦截
        if test_res.status_code in [403, 429]:
            print(f"⚠️ 代理 IP 被 XServer 屏蔽 (HTTP {test_res.status_code})，自动降级为直连！")
            final_proxy_status = f"直连 (原{PROXY_STATUS_ENV}被屏蔽)"
        else:
            print(f"✅ 代理连接 XServer 成功，未被拦截！(HTTP {test_res.status_code})")
            final_proxy_status = PROXY_STATUS_ENV
            session.proxies.update(proxies) # 只有测试通过才在全局 session 启用代理
            
    except Exception as e:
        print(f"⚠️ 代理连接超时或网络异常 ({e})，自动降级为直连！")
        final_proxy_status = f"直连 (原{PROXY_STATUS_ENV}连通失败)"
else:
    print("🌐 未启用代理，使用直连模式。")


# ==========================================
# 3. Telegram 消息推送模块
# ==========================================
def send_tg_notification(server_info, expire_date, remaining_str, result_status, next_cron_info=""):
    try:
        tg_config = json.loads(TG_BOT_RAW)
        bot_token = tg_config.get("bot_token")
        chat_id = tg_config.get("chat_id")
        
        if not bot_token or not chat_id:
            print("⚠️ 未配置 Telegram 机器人密钥，跳过 TG 通知。")
            return

        now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        
        msg = f"🎮 *XServer Game 续期通知*\n"
        msg += f"━━━━━━━━━━━━━━━━━━\n"
        if server_info:
            msg += f"🖥 服务器名称: `{server_info}`\n"
        if expire_date:
            msg += f"📅 到期时间(有效期): {expire_date}\n"
        if remaining_str:
            msg += f"⏳ 剩余有效时长: {remaining_str}\n"
        msg += f"📊 续期结果: {result_status}\n"
        if next_cron_info:
            msg += f"⏱️ 下次触发(UTC): {next_cron_info}\n"
        msg += f"🕐 执行时间: {now_str}\n"
        msg += f"━━━━━━━━━━━━━━━━━━\n"
        msg += f"🌐 网络状态: {final_proxy_status}"

        tg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(tg_url, json={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=10)
        
        if resp.ok:
            print("📨 TG 推送成功")
        else:
            print(f"⚠️ TG 推送失败: {resp.text}")
    except Exception as e:
        print(f"⚠️ 发送 TG 通知过程异常: {e}")


# ==========================================
# 4. Cloudflare Worker 定时器更新模块
# ==========================================
def update_cf_worker_cron(total_remaining_minutes):
    if not (CF_ACCOUNT_ID and CF_SCRIPT_NAME and CF_API_TOKEN):
        print("⚠️ 未完整配置 Cloudflare API 参数，跳过更新 Worker Cron 触发器。")
        return ""

    # 计算触发时间：提前 210 分钟（3.5小时），且最小等待 10 分钟
    wait_minutes = max(10, total_remaining_minutes - 210)
    next_utc = datetime.now(timezone.utc) + timedelta(minutes=wait_minutes)
    cron_expr = f"{next_utc.minute} {next_utc.hour} {next_utc.day} {next_utc.month} *"

    print(f"\n⏱️ 预计下次续期触发时间 (UTC): {next_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️ 写入 CF 的 Cron 表达式: {cron_expr}")

    cf_url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/workers/scripts/{CF_SCRIPT_NAME}/schedules"
    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        resp = requests.put(cf_url, json=[{"cron": cron_expr}], headers=headers, timeout=15)
        if resp.ok and resp.json().get("success"):
            print("✅ 成功更新 Cloudflare Worker 的定时触发器！")
            return next_utc.strftime("%Y-%m-%d %H:%M:%S")
        else:
            print(f"❌ 更新 CF 定时器失败: {resp.text}")
    except Exception as e:
        print(f"❌ 请求 CF API 发生异常: {e}")
    return ""


# ==========================================
# 5. 主程序业务流程
# ==========================================
def main():
    now_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    print(f"============== {{xserver_game_renew.py starts}} ==============")
    print(f"🕐 运行时间: {now_time}")

    if not XSERVER_USER or not XSERVER_PASS:
        print("❌ 错误：未读取到有效的 XSERVER_GAME_ACCOUNT 环境变量！")
        send_tg_notification("", "", "", "❌ 缺少账号/密码配置")
        return

    server_id = "未知"
    expire_date_str = "未知"
    remaining_str = "未知"
    result_status = "未知"
    total_remaining_minutes = 0

    try:
        # 1. 访问登录页面提取 CSRF Token
        login_page_url = "https://secure.xserver.ne.jp/xapanel/login/xgame/"
        resp = session.get(login_page_url, timeout=15)
        
        token_match = re.search(r'name="token"\s+value="([^"]+)"', resp.text)
        token = token_match.group(1) if token_match else ""

        # 2. 提交登录请求
        print(f"🔑 正在登录... 账号: {XSERVER_USER}")
        login_data = {
            "memberid": XSERVER_USER,
            "user_password": XSERVER_PASS,
            "token": token
        }
        login_resp = session.post(login_page_url, data=login_data, timeout=15)

        if "logout" not in login_resp.text.lower() and "会員ID" in login_resp.text:
            raise Exception("登录校验失败，请检查账号密码或验证码。")
        print("✅ 登录成功")

        # 3. 获取控制台主页
        panel_url = "https://secure.xserver.ne.jp/xapanel/xgame/index"
        panel_resp = session.get(panel_url, timeout=15)
        print("🔗 跳转到游戏面板...")
        print("✅ 游戏面板 Session 获取成功")

        # 4. 读取服务器列表及剩余时间
        print("📋 读取服务器信息...")
        ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', panel_resp.text)
        if ip_match:
            server_id = ip_match.group(1)

        date_match = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2})(?:まで)?', panel_resp.text)
        if date_match:
            expire_date_str = date_match.group(1) + "まで"
            expire_date_raw = date_match.group(1).replace('/', '-')
            
            # 依照日本 JST 时区 (UTC+9) 计算精确倒计时
            expire_dt = datetime.strptime(f"{expire_date_raw} 23:59:59", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
            now_dt = datetime.now(timezone(timedelta(hours=9)))
            diff_sec = (expire_dt - now_dt).total_seconds()
            
            total_remaining_minutes = max(0, int(diff_sec // 60))
            hours = total_remaining_minutes // 60
            mins = total_remaining_minutes % 60
            remaining_str = f"{hours} 小时 {mins} 分"
        else:
            remaining_str = "解析失败"

        print(f"📅 当前利用期限：{expire_date_str}")
        print(f"⏳ 剩余时间：{remaining_str}")

        # 5. 校验阈值并在剩余 < 4 小时 (240 分钟) 时触发续期
        if 0 < total_remaining_minutes <= 240:
            print("⚠️ 剩余时长已低于 4 小时，开始提交续期请求...")
            renew_url = "https://secure.xserver.ne.jp/xapanel/xgame/renew"
            renew_resp = session.post(renew_url, data={"server_id": server_id}, timeout=15)
            
            if renew_resp.ok:
                result_status = "🎉 续期成功！"
                print("✅ 续期提交成功！")
                total_remaining_minutes += 2880 # 续期成功后累加 48 小时
            else:
                result_status = f"❌ 续期请求失败 (HTTP {renew_resp.status_code})"
                print("❌ 续期提交失败。")
        else:
            hours_left = total_remaining_minutes // 60
            result_status = "⌛️ 期限未至（无需续期）"
            print(f"ℹ️  剩余 {hours_left} 小时，未低于阈值，无需续期")

        # 6. 计算下一次临界时间并写回 Cloudflare Cron
        next_cron_info = update_cf_worker_cron(total_remaining_minutes)

        # 7. 推送 Telegram 消息通知
        send_tg_notification(server_id, expire_date_str, remaining_str, result_status, next_cron_info)

    except Exception as e:
        result_status = f"❌ 运行异常: {str(e)}"
        print(f"❌ 脚本运行遇到异常: {e}")
        send_tg_notification(server_id, expire_date_str, remaining_str, result_status)

    print(f"========= {{xserver_game_renew.py passed}} =========")

if __name__ == "__main__":
    main()
