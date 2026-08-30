#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
import os
import re
import sys
import time
import requests

XSERVER_GAME_ACCOUNT = os.environ.get("XSERVER_GAME_ACCOUNT", "")
if not XSERVER_GAME_ACCOUNT:
    print(
        "❌ 请设置 GitHub Secret: XSERVER_GAME_ACCOUNT（格式:"
        " 自定义名称,email,password）"
    )
    sys.exit(1)

ACCOUNTS = []
for item in re.split(r"[\n;]+", XSERVER_GAME_ACCOUNT.strip()):
    item = item.strip()
    if not item:
        continue
    parts = item.split(",", 2)
    if len(parts) < 3:
        print(
            "❌ XSERVER_GAME_ACCOUNT 格式错误，应为: 自定义名称,email,password"
        )
        sys.exit(1)
    ACCOUNTS.append({
        "name": parts[0].strip(),
        "email": parts[1].strip(),
        "password": parts[2].strip(),
    })

if not ACCOUNTS:
    print("❌ 没有有效账号")
    sys.exit(1)

BASE_URL = "https://secure.xserver.ne.jp"
LOGIN_PAGE = f"{BASE_URL}/xapanel/login/xserver/?request_page=xserver%2Findex"
LOGIN_URL = f"{BASE_URL}/xapanel/myaccount/login"
XMGAME_INDEX_URL = f"{BASE_URL}/xapanel/xmgame/index"
ONETIMELOGIN_URL = f"{BASE_URL}/xmgame/onetimelogin"
INFO_URL = f"{BASE_URL}/xmgame/game/index"
EXTEND_URL = f"{BASE_URL}/xmgame/game/freeplan/extend/index"
RENEW_URL = f"{BASE_URL}/xmgame/game/freeplan/extend/input"
CONF_URL = f"{BASE_URL}/xmgame/game/freeplan/extend/conf"
DO_URL = f"{BASE_URL}/xmgame/game/freeplan/extend/do"
IP_CHECK_URL = "https://ipinfo.io/json"

RENEW_THRESHOLD_HOURS = 4

# 代理配置判断
is_proxy_enabled = os.getenv("USE_PROXY", "").lower() in ["true", "1", "yes"] or os.getenv("IS_PROXY", "").lower() in ["true", "1", "yes"]
USE_PROXY = is_proxy_enabled

def get_proxy_config():
    return {"http": "http://127.0.0.1:1081", "https": "http://127.0.0.1:1081"} if USE_PROXY else {}

TG_BOT = os.environ.get("TG_BOT", "")

BASE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not;A=Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}

DEFAULT_TIMEOUT = 30
SLOW_TIMEOUT = 60
SCRIPT_NAME = os.path.basename(__file__)

NEXT_RUN_MINUTES = []

def log(msg):
    print(msg, flush=True)

def divider(label):
    width = 60
    inner = f" {{{label}}} "
    pad_total = width - len(inner)
    pad_l = pad_total // 2
    pad_r = pad_total - pad_l
    log("=" * pad_l + inner + "=" * pad_r)

def get_cst_time():
    """获取东八区(北京)时间"""
    return datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=8)))

def now_str():
    return get_cst_time().strftime("%Y-%m-%d %H:%M:%S")

def get_exact_cst_time(h: int, m: int) -> str:
    """计算精确的具体到期CST(UTC+8)时间点"""
    if h < 0:
        return "未知"
    exact_dt = get_cst_time() + datetime.timedelta(hours=h, minutes=m)
    return exact_dt.strftime('%Y-%m-%d %H:%M:%S')

def parse_remaining(page_html: str) -> tuple:
    deadline = re.search(r'<span class="dateLimit">\(([^)]+)\)</span>', page_html)
    dl_str = deadline.group(1) if deadline else "未知"

    if "limitOverTxt" in page_html and "期限切れ" in page_html:
        return -1, -1, dl_str, True

    numbers = re.findall(r'<span class="numberTxt">(\d+)</span>', page_html)
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1]), dl_str, False

    return -2, -2, dl_str, False

def can_renew(page_html: str) -> bool:
    return "残り契約時間が4時間を切るまで" not in page_html

def extract_form_data(html: str) -> dict:
    """动态解析网页表单元素，实现最大容错率"""
    data = {}
    inputs = re.findall(r'<input[^>]+>', html, re.IGNORECASE)
    
    for inp in inputs:
        if 'type="hidden"' in inp.lower() or "type='hidden'" in inp.lower():
            n_match = re.search(r'name=["\']([^"\']+)["\']', inp, re.IGNORECASE)
            v_match = re.search(r'value=["\']([^"\']*)["\']', inp, re.IGNORECASE)
            if n_match:
                data[n_match.group(1)] = v_match.group(1) if v_match else ""
                
    for inp in inputs:
        if 'type="submit"' in inp.lower() or 'type="image"' in inp.lower() or 'class="btn' in inp.lower():
            n_match = re.search(r'name=["\'](action_[^"\']+)["\']', inp, re.IGNORECASE)
            if n_match:
                v_match = re.search(r'value=["\']([^"\']*)["\']', inp, re.IGNORECASE)
                data[n_match.group(1)] = v_match.group(1) if v_match else "1"
                
    buttons = re.findall(r'<button[^>]+>.*?</button>', html, re.IGNORECASE | re.DOTALL)
    for btn in buttons:
        n_match = re.search(r'name=["\'](action_[^"\']+)["\']', btn, re.IGNORECASE)
        if n_match:
            v_match = re.search(r'value=["\']([^"\']*)["\']', btn, re.IGNORECASE)
            data[n_match.group(1)] = v_match.group(1) if v_match else "1"
            
    periods = re.findall(r'name=["\']period["\'][^>]*value=["\'](\d+)["\']', html, re.IGNORECASE)
    if not periods:
        sel_match = re.search(r'<select[^>]*name=["\']period["\'][^>]*>(.*?)</select>', html, re.IGNORECASE | re.DOTALL)
        if sel_match:
            periods = re.findall(r'value=["\'](\d+)["\']', sel_match.group(1), re.IGNORECASE)
    if periods:
        data["period"] = str(max(int(p) for p in periods))
        
    return data

def update_cf_cron(remaining_hours: int, remaining_minutes: int) -> tuple:
    """计算并在 CF 中更新下一次执行的 CRON，返回状态元组"""
    cf_account_id = os.environ.get("CF_ACCOUNT_ID", "")
    cf_script_name = os.environ.get("CF_SCRIPT_NAME", "")
    cf_api_token = os.environ.get("CF_API_TOKEN", "")
    
    cron_str = "未知"
    cst_next_run_str = "未知"

    if not all([cf_account_id, cf_script_name, cf_api_token]):
        log("\n⚠️ 未配置完整的 Cloudflare 变量，跳过 Cron 更新")
        return False, "⚠️ 未配置 CF 环境变量", cron_str, cst_next_run_str

    if remaining_hours < 0:
        cron_str = "0 */2 * * *"
        cst_next_run_str = "兜底每2小时"
        log("\n⚠️ 账号状态异常或未取得剩余时间，Cron 兜底设为每 2 小时运行: 0 */2 * * *")
    else:
        total_remaining_minutes = remaining_hours * 60 + remaining_minutes
        wait_minutes = max(10, total_remaining_minutes - 235)

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        next_run_utc = now_utc + datetime.timedelta(minutes=wait_minutes)
        cron_str = f"{next_run_utc.minute} {next_run_utc.hour} {next_run_utc.day} {next_run_utc.month} *"
        
        cst_next_run = next_run_utc.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        cst_next_run_str = cst_next_run.strftime('%Y-%m-%d %H:%M:%S')
        log(f"\n⏱️ 预计下次触发 [UTC+8]: {cst_next_run_str}")
        log(f"⏱️ 写入 CF Worker 的 Cron 表达式 (UTC): {cron_str}")

    url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/workers/scripts/{cf_script_name}/schedules"
    headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.put(url, json=[{"cron": cron_str}], headers=headers, timeout=15)
        if resp.ok:
            log("✅ 成功更新 Cloudflare Worker 的定时触发器 (Cron)！")
            return True, "✅ 更新成功", cron_str, cst_next_run_str
        else:
            log(f"❌ 更新 Cloudflare Cron 失败: HTTP {resp.status_code} - {resp.text}")
            return False, f"❌ 更新失败 (HTTP {resp.status_code})", cron_str, cst_next_run_str
    except Exception as e:
        log(f"❌ 调用 Cloudflare API 异常: {e}")
        return False, "❌ 调用 API 异常", cron_str, cst_next_run_str

def notify_tg(ctx: dict, result: str, raw_dl: str, cst_dl: str, remaining_str: str, cf_info: dict = None):
    if not TG_BOT:
        return
    parts = TG_BOT.split(",", 1)
    if len(parts) != 2:
        return
    chat_id, bot_token = parts[0].strip(), parts[1].strip()

    proxy_ip = ctx.get("PROXY_IP", "未知")
    direct_ip = ctx.get("DIRECT_IP", "未知")
    actual_ip = ctx.get("ACTUAL_IP", "未知")

    network_info = []
    if USE_PROXY:
        proxy_status = "✅ 可用" if ctx.get("PROXY_AVAILABLE") else "❌ 不可用/被屏蔽"
        network_info.append(f"🔀 代理: {proxy_status}")
        if ctx.get("PROXY_AVAILABLE"):
            network_info.append(f"   IP: {proxy_ip} ({ctx.get('PROXY_COUNTRY', '未知')})")
        network_info.append(f"🌐 直连: IP {direct_ip} ({ctx.get('DIRECT_COUNTRY', '未知')})")
        network_info.append(f"✅ 实际使用: {ctx.get('ACTUAL_MODE', '直连')}")
        if ctx.get("ACTUAL_MODE") == "代理":
            network_info.append(f"   IP: {actual_ip} ({ctx.get('ACTUAL_COUNTRY', '未知')})")
    else:
        network_info.append(f"🌐 直连: IP {direct_ip} ({ctx.get('DIRECT_COUNTRY', '未知')})")
        network_info.append(f"✅ 实际使用: {ctx.get('ACTUAL_MODE', '直连')}")

    network_str = "\n".join(network_info)
    cst_str = f"\n⏱️ 对应CST时间: {cst_dl}" if cst_dl and cst_dl != "未知" else ""

    # 新增构建 CF 信息文本块
    cf_str = ""
    if cf_info:
        cf_status = cf_info.get("status", "未知")
        cf_cron = cf_info.get("cron", "未知")
        cf_cst = cf_info.get("cst", "未知")
        cf_str = (
            f"☁️ CF 定时器: {cf_status}\n"
            f"⏱️ 下次触发(CST): {cf_cst}\n"
            f"⚙️ CRON (UTC): {cf_cron}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
        )

    message = (
        f"🎮 XServer Game 续期通知\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🖥 服务器名称: {ctx.get('SERVER_NAME')}\n"
        f"📅 到期时间(有效期): {raw_dl}{cst_str}\n"
        f"⏳ 剩余有效时长: {remaining_str}\n"
        f"📊 续期结果: {result}\n"
        f"🕐 执行时间: {now_str()}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{cf_str}"
        f"{network_str}"
    )
    
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
            proxies=ctx.get("PROXIES", {})
        )
        log("📨 TG 推送成功")
    except Exception as e:
        log(f"⚠️ TG 推送失败: {e}")

def finish_account(ctx: dict, success: bool, result: str, raw_dl: str, cst_dl: str, remaining_str: str) -> tuple:
    """运行结束，仅打包结果，延迟给外部调用推送"""
    tag = "passed" if success else "failed"
    elapsed_time = f"{time.time() - ctx['START_TIME']:.2f}s"
    divider(f"{SCRIPT_NAME} {tag} in {elapsed_time}")
    
    tg_args = {
        "ctx": ctx,
        "result": result,
        "raw_dl": raw_dl,
        "cst_dl": cst_dl,
        "remaining_str": remaining_str
    }
    return success, tg_args

def check_ip_info(proxies=None):
    try:
        resp = requests.get(IP_CHECK_URL, timeout=DEFAULT_TIMEOUT, proxies=proxies)
        ip_data = resp.json()
        return ip_data.get("ip", "未知"), ip_data.get("country", "未知")
    except Exception:
        return "未知", "未知"

def run_account(account) -> tuple:
    ctx = {
        "SERVER_NAME": account["name"],
        "START_TIME": time.time(),
        "PROXIES": get_proxy_config(),
        "PROXY_AVAILABLE": False,
        "ACTUAL_MODE": "直连",
        "ACTUAL_IP": "未知",
        "ACTUAL_COUNTRY": "未知",
        "DIRECT_IP": "未知",
        "DIRECT_COUNTRY": "未知"
    }

    divider(f"{SCRIPT_NAME} starts")
    log(f"🕐 运行时间: {now_str()}")
    log(f"🖥 服务器: {ctx['SERVER_NAME']}")

    ctx["DIRECT_IP"], ctx["DIRECT_COUNTRY"] = check_ip_info()

    if USE_PROXY:
        log("🌐 检测代理是否可用及目标网站联通性...")
        proxy_ip, proxy_country = check_ip_info(ctx["PROXIES"])
        if proxy_ip != "未知":
            try:
                test_resp = requests.get(LOGIN_PAGE, headers=BASE_HEADERS, timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"])
                if test_resp.status_code == 200 and 'name="uniqid"' in test_resp.text:
                    ctx["PROXY_AVAILABLE"] = True
                    ctx["PROXY_IP"], ctx["PROXY_COUNTRY"] = proxy_ip, proxy_country
                    ctx["ACTUAL_MODE"] = "代理"
                    ctx["ACTUAL_IP"], ctx["ACTUAL_COUNTRY"] = proxy_ip, proxy_country
                    log("✅ 代理测试通过，未被目标网站屏蔽")
            except Exception:
                pass
        if not ctx["PROXY_AVAILABLE"]:
            log("🔄 放弃代理，自动退回 [直连] 模式运行...")
            ctx["ACTUAL_MODE"] = "直连"
            ctx["ACTUAL_IP"], ctx["ACTUAL_COUNTRY"] = ctx["DIRECT_IP"], ctx["DIRECT_COUNTRY"]
            ctx["PROXIES"] = {}
    else:
        ctx["ACTUAL_MODE"] = "直连"
        ctx["ACTUAL_IP"], ctx["ACTUAL_COUNTRY"] = ctx["DIRECT_IP"], ctx["DIRECT_COUNTRY"]

    with requests.Session() as session:
        session.headers.update(BASE_HEADERS)
        email_masked = re.sub(r"(.{2}).*(@.*)", r"\1***\2", account["email"])
        log(f"🔑 正在登录... 账号: {email_masked}")
        
        try:
            resp = session.get(LOGIN_PAGE, headers=BASE_HEADERS, timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"])
            uniqid_match = re.search(r'name=["\']uniqid["\']\s+value=["\']([^"\']+)["\']', resp.text)
            if not uniqid_match:
                uniqid_match = re.search(r'value=["\']([^"\']+)["\']\s+name=["\']uniqid["\']', resp.text)
                
            if not uniqid_match:
                NEXT_RUN_MINUTES.append(-1)
                return finish_account(ctx, False, "❌ 未找到登录 uniqid", "未知", "未知", "0小时0分")

            session.post(
                LOGIN_URL,
                headers={**BASE_HEADERS, "content-type": "application/x-www-form-urlencoded", "origin": BASE_URL, "referer": LOGIN_PAGE},
                data={"request_page": "xserver/index", "site": "", "uniqid": uniqid_match.group(1), "memberid": account["email"], "user_password": account["password"], "service_login": "xserver", "action_user_login": "ログインする"},
                allow_redirects=True, timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"]
            )
            
            if not session.cookies.get("X2SESSID"):
                NEXT_RUN_MINUTES.append(-1)
                return finish_account(ctx, False, "❌ 登录失败", "未知", "未知", "0小时0分")
            log("✅ 登录成功")

            log("🔗 跳转到游戏面板...")
            resp = session.get(XMGAME_INDEX_URL, headers={**BASE_HEADERS, "referer": f"{BASE_URL}/xapanel/"}, timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"])
            jumpvps_match = re.search(r"/xapanel/xmgame/jumpvps/\?id=(\d+)", resp.text)
            if not jumpvps_match:
                NEXT_RUN_MINUTES.append(-1)
                return finish_account(ctx, False, "❌ 未找到 jumpvps 链接", "未知", "未知", "0小时0分")

            server_id = jumpvps_match.group(1)
            resp2 = session.get(f"{BASE_URL}/xapanel/xmgame/jumpvps/?id={server_id}", headers={**BASE_HEADERS, "referer": XMGAME_INDEX_URL}, timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"])

            uname = re.search(r'name="username"\s+value="([^"]+)"', resp2.text)
            s_iden = re.search(r'name="server_identify"\s+value="([^"]+)"', resp2.text)
            pwd = re.search(r'name="password"\s+value="([^"]+)"', resp2.text)
            srv = re.search(r'name="service"\s+value="([^"]+)"', resp2.text)

            if not all([uname, s_iden, pwd, srv]):
                NEXT_RUN_MINUTES.append(-1)
                return finish_account(ctx, False, "❌ 解析一次性登录表单参数失败", "未知", "未知", "0小时0分")

            session.post(
                ONETIMELOGIN_URL,
                headers={**BASE_HEADERS, "content-type": "application/x-www-form-urlencoded", "origin": BASE_URL, "referer": f"{BASE_URL}/xapanel/xmgame/jumpvps/?id={server_id}"},
                data={"username": uname.group(1), "server_identify": s_iden.group(1), "password": pwd.group(1), "service": srv.group(1), "master_panel_username": "", "back": ""},
                allow_redirects=True, timeout=SLOW_TIMEOUT, proxies=ctx["PROXIES"]
            )
            log("✅ 游戏面板 Session 获取成功")
        except Exception as e:
            NEXT_RUN_MINUTES.append(-1)
            return finish_account(ctx, False, f"❌ 登录网络异常: {e}", "未知", "未知", "0小时0分")

        log("📋 读取服务器信息...")
        resp_info = session.get(INFO_URL, headers={**BASE_HEADERS, "referer": BASE_URL}, timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"])
        resp_info.encoding = "EUC-JP"
        h_before, m_before, dl_before, is_expired = parse_remaining(resp_info.text)
        
        cst_before = get_exact_cst_time(h_before, m_before)
        remaining_str_before = f"{h_before} 小时 {m_before} 分"

        if is_expired:
            log(f"⚠️ 服务器已过期（{dl_before}），直接尝试续期...")
        else:
            log(f"📅 当前利用期限：{dl_before} (CST: {cst_before})")
            log(f"⏳ 剩余时间：{remaining_str_before}")
            if h_before >= RENEW_THRESHOLD_HOURS:
                NEXT_RUN_MINUTES.append(h_before * 60 + m_before)
                return finish_account(ctx, True, "⌛️ 期限未至（无需续期）", dl_before, cst_before, remaining_str_before)

            resp_extend = session.get(EXTEND_URL, headers={**BASE_HEADERS, "referer": INFO_URL}, timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"])
            resp_extend.encoding = "EUC-JP"
            if not can_renew(resp_extend.text):
                NEXT_RUN_MINUTES.append(h_before * 60 + m_before)
                return finish_account(ctx, True, "⌛️ 期限未至（暂不可续期）", dl_before, cst_before, remaining_str_before)

        log("🔄 开始续期...")
        try:
            resp_renew = session.get(RENEW_URL, headers={**BASE_HEADERS, "referer": EXTEND_URL}, timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"])
            
            form_data_conf = extract_form_data(resp_renew.text)
            if "login_token" not in form_data_conf:
                lt_match = re.search(r'name=["\']login_token["\']\s+value=["\']([^"\']+)["\']', resp_renew.text)
                if not lt_match:
                    NEXT_RUN_MINUTES.append(-1)
                    return finish_account(ctx, False, "❌ 未能在续期页找到 login_token", dl_before, cst_before, remaining_str_before)
                form_data_conf["login_token"] = lt_match.group(1)
            
            if "period" not in form_data_conf:
                form_data_conf["period"] = "48"
                
            if not any(k.startswith("action_") for k in form_data_conf.keys()):
                form_data_conf["action_game_freeplan_extend_conf"] = "確認画面へ進む"
            
            time.sleep(1)
            resp_conf = session.post(
                CONF_URL, 
                headers={**BASE_HEADERS, "content-type": "application/x-www-form-urlencoded", "origin": BASE_URL, "referer": RENEW_URL}, 
                data=form_data_conf, 
                timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"]
            )
            
            form_data_do = extract_form_data(resp_conf.text)
            if "login_token" not in form_data_do:
                form_data_do["login_token"] = form_data_conf.get("login_token", "")
            if "period" not in form_data_do:
                form_data_do["period"] = form_data_conf.get("period", "48")
            if not any(k.startswith("action_") for k in form_data_do.keys()):
                form_data_do["action_game_freeplan_extend_do"] = "延長する"

            time.sleep(1)
            session.post(
                DO_URL, 
                headers={**BASE_HEADERS, "content-type": "application/x-www-form-urlencoded", "origin": BASE_URL, "referer": CONF_URL}, 
                data=form_data_do, 
                timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"]
            )
        except Exception as e:
            NEXT_RUN_MINUTES.append(-1)
            return finish_account(ctx, False, f"❌ 续期请求抛出异常: {e}", dl_before, cst_before, remaining_str_before)

        log("⏳ 等待系统更新...")
        time.sleep(3)

        resp_after = session.get(INFO_URL, headers={**BASE_HEADERS, "referer": BASE_URL}, timeout=DEFAULT_TIMEOUT, proxies=ctx["PROXIES"])
        resp_after.encoding = "EUC-JP"
        h_after, m_after, dl_after, expired_after = parse_remaining(resp_after.text)
        
        cst_after = get_exact_cst_time(h_after, m_after)
        log(f"📅 续期后利用期限：{dl_after} (CST: {cst_after})")
        remaining_str_after = f"{h_after} 小时 {m_after} 分"

        success = False
        if is_expired and not expired_after: 
            success = True
        elif dl_after != dl_before or h_after > h_before: 
            success = True

        if success:
            log("✅ 续期成功！")
            NEXT_RUN_MINUTES.append(h_after * 60 + m_after)
            return finish_account(ctx, True, "✅ 续期成功！", dl_after, cst_after, remaining_str_after)
        else:
            log("❌ 续期失败，时间未变化")
            NEXT_RUN_MINUTES.append(-1)
            return finish_account(ctx, False, "❌ 续期后期限未延伸", dl_after or dl_before, cst_after or cst_before, remaining_str_after)

def main():
    failed = 0
    tg_tasks = []
    
    # 1. 遍历所有账号运行并收集 TG 推送材料
    for account in ACCOUNTS:
        start_len = len(NEXT_RUN_MINUTES)
        try:
            ok, tg_args = run_account(account)
            tg_tasks.append(tg_args)
            if not ok: failed += 1
        except Exception as e:
            failed += 1
            log(f"❌ 账号 {account['name']} 运行遇到致命错误: {e}")

        if len(NEXT_RUN_MINUTES) == start_len:
            NEXT_RUN_MINUTES.append(-1)

    # 2. 集中处理 CF Cron 定时器更新
    if not NEXT_RUN_MINUTES or -1 in NEXT_RUN_MINUTES:
        _, cf_msg, cf_cron, cf_cst = update_cf_cron(-1, -1)
    else:
        min_minutes = min(NEXT_RUN_MINUTES)
        _, cf_msg, cf_cron, cf_cst = update_cf_cron(min_minutes // 60, min_minutes % 60)

    cf_info = {
        "status": cf_msg,
        "cron": cf_cron,
        "cst": cf_cst
    }

    # 3. 将包含 CF 结果的信息统一发送给 TG
    for args in tg_tasks:
        notify_tg(
            ctx=args["ctx"],
            result=args["result"],
            raw_dl=args["raw_dl"],
            cst_dl=args["cst_dl"],
            remaining_str=args["remaining_str"],
            cf_info=cf_info
        )

    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
