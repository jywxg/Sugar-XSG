#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import requests
from datetime import datetime

XSERVER_GAME_ACCOUNT = os.environ.get("XSERVER_GAME_ACCOUNT", "")
if not XSERVER_GAME_ACCOUNT:
    print("❌ 请设置 GitHub Secret: XSERVER_GAME_ACCOUNT（格式: 自定义名称,email,password）")
    sys.exit(1)

ACCOUNTS = []
for item in re.split(r"[\n;]+", XSERVER_GAME_ACCOUNT.strip()):
    item = item.strip()
    if not item:
        continue
    parts = item.split(",", 2)
    if len(parts) < 3:
        print("❌ XSERVER_GAME_ACCOUNT 格式错误，应为: 自定义名称,email,password")
        sys.exit(1)
    ACCOUNTS.append({"name": parts[0].strip(), "email": parts[1].strip(), "password": parts[2].strip()})

if not ACCOUNTS:
    print("❌ 没有有效账号")
    sys.exit(1)

BASE_URL         = "https://secure.xserver.ne.jp"
LOGIN_PAGE       = f"{BASE_URL}/xapanel/login/xserver/?request_page=xserver%2Findex"
LOGIN_URL        = f"{BASE_URL}/xapanel/myaccount/login"
XMGAME_INDEX_URL = f"{BASE_URL}/xapanel/xmgame/index"
ONETIMELOGIN_URL = f"{BASE_URL}/xmgame/onetimelogin"
INFO_URL         = f"{BASE_URL}/xmgame/game/index"
EXTEND_URL       = f"{BASE_URL}/xmgame/game/freeplan/extend/index"
RENEW_URL        = f"{BASE_URL}/xmgame/game/freeplan/extend/input"
CONF_URL         = f"{BASE_URL}/xmgame/game/freeplan/extend/conf"
DO_URL           = f"{BASE_URL}/xmgame/game/freeplan/extend/do"
IP_CHECK_URL     = "https://api.ipify.org?format=json"

RENEW_THRESHOLD_HOURS = 16

GOST_PROXY = os.environ.get("GOST_PROXY", "")
PROXIES = {"http": "http://127.0.0.1:1080", "https": "http://127.0.0.1:1080"} if GOST_PROXY else {}

TG_BOT = os.environ.get("TG_BOT", "")

BASE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
}

SCRIPT_NAME = os.path.basename(__file__)
_start_time = time.time()


def log(msg):
    print(msg, flush=True)

def divider(label):
    width = 60
    inner = f" {{{label}}} "
    pad_total = width - len(inner)
    pad_l = pad_total // 2
    pad_r = pad_total - pad_l
    log("=" * pad_l + inner + "=" * pad_r)

def elapsed():
    return f"{time.time() - _start_time:.2f}s"

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_remaining(page_html: str) -> tuple:
    """
    返回 (hours, minutes, deadline_str, is_expired)
    正常有剩余：(小时, 分钟, 日期, False)
    已过期：    (-1, -1, 日期, True)
    解析失败：  (-2, -2, 日期, False)
    """
    deadline = re.search(r'<span class="dateLimit">\(([^)]+)\)</span>', page_html)
    dl_str = deadline.group(1) if deadline else "未知"

    # 过期状态：limitOverTxt + 期限切れ
    if "limitOverTxt" in page_html and "期限切れ" in page_html:
        return -1, -1, dl_str, True

    # 正常状态：numberTxt
    numbers = re.findall(r'<span class="numberTxt">(\d+)</span>', page_html)
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1]), dl_str, False

    return -2, -2, dl_str, False


def can_renew(page_html: str) -> bool:
    return "残り契約時間が16時間を切るまで" not in page_html


def notify_tg(result: str, deadline: str):
    if not TG_BOT:
        return
    parts = TG_BOT.split(",", 1)
    if len(parts) != 2:
        return
    chat_id, bot_token = parts[0].strip(), parts[1].strip()
    message = (
        f"🎮 XServer Game 续期通知\n"
        f"🕐 运行时间: {now_str()}\n"
        f"🖥 服务器: {SERVER_NAME}\n"
        f"📅 利用期限: {deadline}\n"
        f"📊 续期结果: {result}"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
            proxies=PROXIES,
        )
        log("📨 TG 推送成功")
    except Exception as e:
        log(f"⚠️ TG 推送失败: {e}")


def finish(success: bool, result: str, deadline: str):
    notify_tg(result, deadline)
    tag = "passed" if success else "failed"
    divider(f"{SCRIPT_NAME} {tag} in {elapsed()}")
    sys.exit(0 if success else 1)


def login(email, password) -> requests.Session:
    email_masked = re.sub(r"(.{2}).*(@.*)", r"\1***\2", email)
    log(f"🔑 正在登录... 账号: {email_masked}")
    session = requests.Session()

    try:
        resp = session.get(LOGIN_PAGE, headers=BASE_HEADERS, timeout=15, proxies=PROXIES)
    except Exception as e:
        log(f"❌ 获取登录页失败: {e}")
        sys.exit(1)

    uniqid_match = re.search(r'name="uniqid"\s+value="([^"]+)"', resp.text)
    if not uniqid_match:
        log("❌ 未找到 uniqid")
        sys.exit(1)
    uniqid = uniqid_match.group(1)

    try:
        session.post(
            LOGIN_URL,
            headers={
                **BASE_HEADERS,
                "content-type": "application/x-www-form-urlencoded",
                "origin": BASE_URL,
                "referer": LOGIN_PAGE,
            },
            data={
                "request_page": "xserver/index",
                "site": "",
                "uniqid": uniqid,
                "memberid": email,
                "user_password": password,
                "service_login": "xserver",
                "action_user_login": "%A5%ED%A5%B0%A5%A4%A5%F3%A4%B9%A4%EB",
            },
            allow_redirects=True,
            timeout=15,
            proxies=PROXIES,
        )
    except Exception as e:
        log(f"❌ 登录请求失败: {e}")
        sys.exit(1)

    if not session.cookies.get("X2SESSID"):
        log("❌ 登录失败，未获取到 X2SESSID")
        sys.exit(1)

    log("✅ 登录成功")
    return session


def jump_to_xmgame(session: requests.Session):
    log("🔗 跳转到游戏面板...")

    try:
        resp = session.get(
            XMGAME_INDEX_URL,
            headers={**BASE_HEADERS, "referer": BASE_URL},
            timeout=15,
            proxies=PROXIES,
            allow_redirects=True,
        )
        resp.encoding = "EUC-JP"
    except Exception as e:
        log(f"❌ 获取 xmgame index 失败: {e}")
        sys.exit(1)

    jumpvps_match = re.search(r'/xapanel/xmgame/jumpvps/\?id=(\d+)', resp.text)
    if not jumpvps_match:
        log("❌ 未找到 jumpvps 链接")
        sys.exit(1)
    server_id = jumpvps_match.group(1)
    log(f"✅ 找到服务器 ID: {server_id}")

    try:
        resp2 = session.get(
            f"{BASE_URL}/xapanel/xmgame/jumpvps/?id={server_id}",
            headers={**BASE_HEADERS, "referer": XMGAME_INDEX_URL},
            timeout=15,
            proxies=PROXIES,
            allow_redirects=True,
        )
        resp2.encoding = "EUC-JP"
    except Exception as e:
        log(f"❌ 获取 jumpvps 失败: {e}")
        sys.exit(1)

    username        = re.search(r'name="username"\s+value="([^"]+)"', resp2.text)
    server_identify = re.search(r'name="server_identify"\s+value="([^"]+)"', resp2.text)
    password        = re.search(r'name="password"\s+value="([^"]+)"', resp2.text)
    service         = re.search(r'name="service"\s+value="([^"]+)"', resp2.text)
    master_panel    = re.search(r'name="master_panel_username"\s+value="([^"]*)"', resp2.text)
    back            = re.search(r'name="back"\s+value="([^"]+)"', resp2.text)

    if not all([username, server_identify, password, service]):
        log("❌ 解析 onetimelogin 表单失败")
        log(f"DEBUG: {resp2.text}")
        sys.exit(1)

    try:
        session.post(
            ONETIMELOGIN_URL,
            headers={
                **BASE_HEADERS,
                "content-type": "application/x-www-form-urlencoded",
                "origin": BASE_URL,
                "referer": f"{BASE_URL}/xapanel/xmgame/jumpvps/?id={server_id}",
            },
            data={
                "username":              username.group(1),
                "server_identify":       server_identify.group(1),
                "password":              password.group(1),
                "service":               service.group(1),
                "master_panel_username": master_panel.group(1) if master_panel else "",
                "back":                  back.group(1) if back else "",
            },
            allow_redirects=True,
            timeout=15,
            proxies=PROXIES,
        )
    except Exception as e:
        log(f"❌ onetimelogin 请求失败: {e}")
        sys.exit(1)

    xmgame_sessid = (session.cookies.get("X2%2Fxmgame_SESSID") or
                     session.cookies.get("X2/xmgame_SESSID"))
    if xmgame_sessid:
        log("✅ 游戏面板 Session 获取成功")
    else:
        log("⚠️ 未检测到 xmgame_SESSID，但继续尝试...")


def fetch_info_page(session: requests.Session) -> str:
    try:
        resp = session.get(
            INFO_URL,
            headers={**BASE_HEADERS, "referer": BASE_URL},
            timeout=15,
            proxies=PROXIES,
            allow_redirects=True,
        )
        resp.encoding = "EUC-JP"
        return resp.text
    except Exception as e:
        log(f"❌ 获取游戏首页失败: {e}")
        sys.exit(1)


def fetch_extend_page(session: requests.Session) -> str:
    try:
        resp = session.get(
            EXTEND_URL,
            headers={**BASE_HEADERS, "referer": INFO_URL},
            timeout=15,
            proxies=PROXIES,
            allow_redirects=True,
        )
        resp.encoding = "EUC-JP"
        return resp.text
    except Exception as e:
        log(f"❌ 获取续期页面失败: {e}")
        sys.exit(1)


def do_renew(session: requests.Session) -> bool:
    log("📝 获取续期表单...")
    try:
        resp = session.get(
            RENEW_URL,
            headers={**BASE_HEADERS, "referer": EXTEND_URL},
            timeout=15,
            proxies=PROXIES,
            allow_redirects=True,
        )
        resp.encoding = "EUC-JP"
    except Exception as e:
        log(f"❌ 获取续期表单失败: {e}")
        return False

    uniqid      = re.search(r'name="uniqid"\s+value="([^"]+)"', resp.text)
    login_token = re.search(r'name="login_token"\s+value="([^"]+)"', resp.text)
    period      = re.search(r'name="period"[^>]*value="(\d+)"', resp.text)

    if not uniqid or not login_token:
        log("❌ 解析续期表单失败")
        log(f"DEBUG: {resp.text[:500]}")
        return False

    period_val = period.group(1) if period else "48"

    log("📤 提交确认页...")
    try:
        resp2 = session.post(
            CONF_URL,
            headers={
                **BASE_HEADERS,
                "content-type": "application/x-www-form-urlencoded",
                "origin": BASE_URL,
                "referer": RENEW_URL,
            },
            data={
                "uniqid":      uniqid.group(1),
                "ethna_csrf":  "",
                "login_token": login_token.group(1),
                "period":      period_val,
            },
            timeout=15,
            proxies=PROXIES,
            allow_redirects=True,
        )
        resp2.encoding = "EUC-JP"
    except Exception as e:
        log(f"❌ 提交确认页失败: {e}")
        return False

    uniqid2 = re.search(r'name="uniqid"\s+value="([^"]+)"', resp2.text)
    if not uniqid2:
        log("❌ 解析确认页表单失败")
        log(f"DEBUG: {resp2.text[:500]}")
        return False

    log("✅ 续期执行完成")
    try:
        session.post(
            DO_URL,
            headers={
                **BASE_HEADERS,
                "content-type": "application/x-www-form-urlencoded",
                "origin": BASE_URL,
                "referer": CONF_URL,
            },
            data={
                "uniqid":     uniqid2.group(1),
                "ethna_csrf": "",
                "period":     period_val,
            },
            timeout=15,
            proxies=PROXIES,
            allow_redirects=True,
        )
    except Exception as e:
        log(f"❌ 执行续期失败: {e}")
        return False

    return True


def run_account(account):
    global SERVER_NAME
    SERVER_NAME = account["name"]
    log(f"{'🛡️ 使用代理模式' if PROXIES else '🌐 直连模式'}")
    divider(f"{SCRIPT_NAME} starts")
    log(f"🕐 运行时间: {now_str()}")
    log(f"🖥 服务器: {SERVER_NAME}")

    log("🌐 验证出口 IP...")
    try:
        resp = requests.get(IP_CHECK_URL, timeout=10, proxies=PROXIES)
        raw_ip = resp.json().get("ip", "未知")
        masked = re.sub(r'\.\d+$', '.**', raw_ip)
        log(f"✅ 出口 IP 确认：{masked}")
    except Exception as e:
        log(f"⚠️ 出口 IP 检测失败: {e}")

    session = login(account["email"], account["password"])
    jump_to_xmgame(session)

    log("📋 读取服务器信息...")
    page_info = fetch_info_page(session)
    h_before, m_before, dl_before, is_expired = parse_remaining(page_info)

    if h_before == -2:
        log("❌ 解析剩余时间失败，页面结构异常")
        log(f"DEBUG: {page_info[:500]}")
        sys.exit(1)

    if is_expired:
        log(f"⚠️ 服务器已过期（{dl_before}），直接尝试续期...")
    else:
        log(f"📅 当前利用期限：{dl_before}")
        log(f"⏳ 剩余时间：{h_before} 小时 {m_before} 分")
        if h_before >= RENEW_THRESHOLD_HOURS:
            log(f"ℹ️  剩余 {h_before} 小时，未低于阈值，无需续期")
            finish(True, "⌛️ 期限未至！", dl_before)

        page_extend = fetch_extend_page(session)
        if not can_renew(page_extend):
            log("⚠️ 页面提示暂不可续期")
            finish(True, "⌛️ 期限未至！", dl_before)

    log("🔄 开始续期...")
    if not do_renew(session):
        finish(False, "❌ 续期失败！", dl_before)

    page_info_after = fetch_info_page(session)
    h_after, m_after, dl_after, expired_after = parse_remaining(page_info_after)
    log(f"📅 续期后利用期限：{dl_after}")
    if not expired_after:
        log(f"⏳ 续期后剩余时间：{h_after} 小时 {m_after} 分")

    if not expired_after and (is_expired or dl_after != dl_before or h_after > h_before):
        log("✅ 续期成功！")
        finish(True, "✅ 续期成功！", dl_after)
    else:
        log("❌ 续期失败，时间未变化")
        finish(False, "❌ 续期失败！", dl_after or dl_before)


def main():
    failed = 0
    for account in ACCOUNTS:
        try:
            run_account(account)
        except SystemExit as e:
            if e.code != 0:
                failed += 1
        except Exception as e:
            failed += 1
            log(f"❌ 账号 {account['name']} 异常: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
