#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
from html.parser import HTMLParser
import os
import re
import sys
import time
from pathlib import Path

from curl_cffi import requests as curl_requests
from DrissionPage import ChromiumOptions, ChromiumPage

BASE_URL = "https://secure.xserver.ne.jp"
LOGIN_PAGE = f"{BASE_URL}/xapanel/login/xmgame"
XMGAME_INDEX_URL = f"{BASE_URL}/xapanel/xmgame/index"
ONETIMELOGIN_URL = f"{BASE_URL}/xmgame/onetimelogin"
INFO_URL = f"{BASE_URL}/xmgame/game/index"
EXTEND_URL = f"{BASE_URL}/xmgame/game/freeplan/extend/index"
RENEW_URL = f"{BASE_URL}/xmgame/game/freeplan/extend/input"
CONF_URL = f"{BASE_URL}/xmgame/game/freeplan/extend/conf"
DO_URL = f"{BASE_URL}/xmgame/game/freeplan/extend/do"
IP_CHECK_URL = "https://ipinfo.io/json"

RENEW_THRESHOLD_HOURS = 4
TG_BOT = os.environ.get("TG_BOT", "")
NEXT_RUN_MINUTES = []
SCRIPT_NAME = os.path.basename(__file__)

XSERVER_GAME_ACCOUNT = os.environ.get("XSERVER_GAME_ACCOUNT", "")
if not XSERVER_GAME_ACCOUNT:
    print("❌ 请设置 GitHub Secret: XSERVER_GAME_ACCOUNT（格式：名称,email,password）")
    sys.exit(1)

ACCOUNTS = []
for item in re.split(r"[\n;]+", XSERVER_GAME_ACCOUNT.strip()):
    item = item.strip()
    if not item:
        continue
    parts = item.split(",", 2)
    if len(parts) != 3:
        print("❌ XSERVER_GAME_ACCOUNT 格式错误，应为：名称,email,password")
        sys.exit(1)
    ACCOUNTS.append({
        "name": parts[0].strip(),
        "email": parts[1].strip(),
        "password": parts[2].strip(),
    })

def log(msg):
    print(msg, flush=True)

def divider(label):
    log("=" * 20 + f" {label} " + "=" * 20)

def get_cst_time():
    return datetime.datetime.now(datetime.timezone.utc).astimezone(
        datetime.timezone(datetime.timedelta(hours=8))
    )

def now_str():
    return get_cst_time().strftime("%Y-%m-%d %H:%M:%S")

def get_exact_cst_time(h, m):
    if h < 0:
        return "未知"
    return (get_cst_time() + datetime.timedelta(hours=h, minutes=m)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

def parse_remaining(page_html):
    deadline = re.search(r'<span class="dateLimit">\(([^)]+)\)</span>', page_html)
    dl_str = deadline.group(1) if deadline else "未知"

    if "limitOverTxt" in page_html and "期限切れ" in page_html:
        return -1, -1, dl_str, True

    numbers = re.findall(r'<span class="numberTxt">(\d+)</span>', page_html)
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1]), dl_str, False

    return -2, -2, dl_str, False

def extract_form_data(html: str) -> dict:
    """用 HTMLParser 解析隐藏字段、提交按钮和 period，避免依赖属性排列顺序。"""
    class FormParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.data = {}
            self.period_options = []
            self.in_period_select = False
            self.current_button = None

        def handle_starttag(self, tag, attrs):
            attrs = {str(k).lower(): (v or "") for k, v in attrs}
            tag = tag.lower()
            if tag == "input":
                name = attrs.get("name", "")
                kind = attrs.get("type", "").lower()
                if name and kind == "hidden":
                    self.data[name] = attrs.get("value", "")
                elif name.startswith("action_") and kind in ("submit", "image", "button"):
                    self.data[name] = attrs.get("value", "1") or "1"
                if name == "period" and attrs.get("value", "").isdigit():
                    self.period_options.append(int(attrs["value"]))
            elif tag == "select":
                self.in_period_select = attrs.get("name", "") == "period"
            elif tag == "option" and self.in_period_select:
                value = attrs.get("value", "")
                if value.isdigit():
                    self.period_options.append(int(value))
            elif tag == "button":
                name = attrs.get("name", "")
                if name.startswith("action_"):
                    self.current_button = (name, attrs.get("value", "1") or "1")

        def handle_endtag(self, tag):
            tag = tag.lower()
            if tag == "select":
                self.in_period_select = False
            elif tag == "button" and self.current_button:
                name, value = self.current_button
                self.data[name] = value
                self.current_button = None

    parser = FormParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception as exc:
        log(f"⚠️ 表单 HTML 解析异常: {exc}")
        return {}
    if parser.period_options:
        parser.data["period"] = str(max(parser.period_options))
    return parser.data

def can_renew(page_html):
    """返回 True=页面看起来可续期，False=明确尚不可续期，None=页面异常/无法判断。"""
    if not page_html or len(page_html.strip()) < 100:
        return None
    lower = page_html.lower()
    if any(marker in lower for marker in ("just a moment", "cf-chl-", "turnstile", "checking your browser")):
        return None
    if any(marker in page_html for marker in ("ログイン", "ログアウト", "login_token")) and "延長" not in page_html:
        return None
    if "残り契約時間が4時間を切るまで" in page_html:
        return False
    # 页面结构发生变化时，不要把“限制提示消失”直接当成可续期。
    # period 用精确匹配（name="period" / <select name="period">），
    # 避免 JS 或注释里的 "period" 字样把异常页面误判为可续期。
    if re.search(r'name=["\']period["\']', page_html, re.IGNORECASE) or \
            "延長" in page_html or "action_game_freeplan_extend" in page_html:
        return True
    return None

def get_proxy():
    proxy = os.getenv("BROWSER_PROXY") or os.getenv("PROXY_HTTP_SERVER") or ""
    return proxy.strip()

def build_options(profile=None):
    co = ChromiumOptions()
    browser_path = os.getenv("BROWSER_PATH", "/usr/bin/google-chrome")
    if os.path.exists(browser_path):
        co.set_browser_path(browser_path)

    profile = profile or os.getenv("CHROME_PROFILE", "./chrome-profile")
    co.set_user_data_path(str(Path(profile).resolve()))

    proxy = get_proxy()
    if proxy:
        co.set_proxy(proxy)
        log(f"🌐 Chrome 代理: {proxy}")

    # GitHub Actions + Xvfb 下运行有头 Chrome。
    co.set_argument("--window-size=1920,1080")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-gpu")
    co.set_argument("--lang=ja-JP,ja,en-US,en")
    # 反自动化：禁用 webdriver 标记、自动化信息栏、默认浏览器检查（首访更接近真实用户）
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--disable-infobars")
    co.set_argument("--no-first-run")
    co.set_argument("--no-default-browser-check")
    co.set_argument("--disable-sync")
    ua = os.getenv("BROWSER_UA", "")
    if ua:
        co.set_argument(f"--user-agent={ua}")
        log(f"🌐 Chrome UA: {ua[:80]}...")

    return co

def wait_page(page, seconds=2):
    try:
        page.wait.load_start()
    except Exception:
        pass
    time.sleep(seconds)

def save_debug(page, account_name, reason):
    out = Path(os.getenv("DEBUG_DIR", "debug"))
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", account_name)
    try:
        page.get_screenshot(str(out / f"{safe}.png"), full_page=True)
    except Exception as e:
        log(f"⚠️ 截图失败: {e}")
    # 不保存原始 HTML：其中可能包含登录令牌、隐藏表单字段或会话相关内容。
    # 只记录不敏感的结构化诊断字段，方便排查问题。
    diag = {
        "reason": reason,
        "url": page.url,
        "time": now_str(),
        "title": "",
        "has_login_url": False,
        "has_password_field": False,
        "has_cf_markers": False,
        "has_turnstile": False,
    }
    try:
        diag["title"] = (page.title or "")[:200]
    except Exception:
        pass
    try:
        diag["has_login_url"] = "/xapanel/login" in page.url.lower()
    except Exception:
        pass
    try:
        diag["has_password_field"] = bool(page.ele('css:input[name="user_password"]'))
    except Exception:
        pass
    try:
        html = (page.html or "").lower()
        diag["has_cf_markers"] = any(
            m in html for m in ("just a moment", "cf-chl-", "turnstile", "checking your browser")
        )
        diag["has_turnstile"] = bool(page.run_js(
            "return !!(document.querySelector('.cf-turnstile, [data-sitekey], "
            "iframe[src*=\"challenges.cloudflare.com\"]'));"
        ))
    except Exception:
        pass
    (out / f"{safe}.txt").write_text(
        "\n".join(f"{k}={v}" for k, v in diag.items()) + "\n",
        encoding="utf-8"
    )

def looks_like_cloudflare(page):
    text = (page.html or "").lower()
    title = ""
    try:
        title = (page.title or "").lower()
    except Exception:
        pass
    markers = [
        "just a moment",
        "checking your browser",
        "verify you are human",
        "turnstile",
        "cf-chl-",
        "cloudflare",
    ]
    return any(x in text or x in title for x in markers)


def has_cloudflare_iframe(page):
    """有些挑战内容在 iframe 里，顶层 HTML 匹配不到字符串，需单独查 iframe/元素。"""
    try:
        r = page.run_js(
            "var f=document.querySelector('iframe[src*=\"challenges.cloudflare.com\"]');"
            "return !!f;"
        )
        if r:
            return True
    except Exception:
        pass
    return False


def _cloudflare_clear(page):
    """轮询判定 CF 挑战是否已清除：文本标记消失 且 无 challenges iframe 且 有 token 或无 turnstile 容器。"""
    if has_cloudflare_iframe(page):
        return False
    if looks_like_cloudflare(page):
        return False
    # 有 Turnstile 容器但还没 token，说明验证未完成
    try:
        tok = page.run_js(
            "var i=document.querySelector('input[name=\"cf-turnstile-response\"]');"
            "return (i&&i.value)||'';"
        )
        if not (isinstance(tok, str) and len(tok) > 20):
            has_ct = page.run_js("return !!document.querySelector('.cf-turnstile');")
            if has_ct:
                return False
    except Exception:
        pass
    return True


def _find_turnstile_rect(page):
    """找到 Turnstile 可点击区域，返回视口坐标 [x, y, w, h]；找不到返回 None。

    优先 iframe（checkbox 实际所在），其次 .cf-turnstile 容器，最后带 data-sitekey 的元素。
    """
    js = """
    var el = document.querySelector('.cf-turnstile iframe[src*="challenges.cloudflare.com"]');
    if (!el || el.getClientRects().length === 0) el = document.querySelector('.cf-turnstile iframe');
    if (!el || el.getClientRects().length === 0) el = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
    if (!el || el.getClientRects().length === 0) el = document.querySelector('.cf-turnstile');
    if (!el || el.getClientRects().length === 0) el = document.querySelector('.turnstile-wrapper');
    if (!el || el.getClientRects().length === 0) el = document.querySelector('[data-sitekey]');
    if (!el) return null;
    var r = el.getBoundingClientRect();
    if (!r || r.width === 0 || r.height === 0) return null;
    return [r.left, r.top, r.width, r.height];
    """
    try:
        rect = page.run_js(js)
        if rect and len(rect) == 4:
            return [float(v) for v in rect]
    except Exception:
        pass
    return None


def _get_turnstile_token(page):
    """读取 cf-turnstile-response 隐藏域 token（存在且足够长才算通过）"""
    try:
        token = page.run_js(
            "var i=document.querySelector('input[name=\"cf-turnstile-response\"]');"
            "return (i&&i.value)||'';"
        )
        return token if isinstance(token, str) and len(token) > 20 else ""
    except Exception:
        return ""


def _click_turnstile(page, rect):
    """点击 Turnstile checkbox：取 iframe/容器中心点，而非固定偏移。"""
    x, y, w, h = rect
    cx = x + max(20, w / 2)
    cy = y + max(20, h / 2)
    log(f"🎯 点击 Turnstile ({int(cx)},{int(cy)})...")
    page.actions.move_to((cx, cy)).click()
    time.sleep(1)


def handle_turnstile(page):
    """Turnstile 坐标点击（xmgame 需要）。

    流程：已有 token → 直接通过；否则定位可点击区域 → 点击 →
    轮询等待 token 出现 / 挑战消失（不再固定等待 3 秒）。
    """
    log("🤖 检查 Turnstile...")
    if _get_turnstile_token(page):
        log("✅ Turnstile 已通过（有 token）")
        return True

    # 登录页未必每次都会出现 Turnstile。没有挑战控件时应继续正常登录，
    # 而不是把“找不到验证码”误判为验证失败。
    try:
        challenge_present = bool(page.run_js(
            "return !!(document.querySelector('.cf-turnstile, [data-sitekey], "
            "iframe[src*=\"challenges.cloudflare.com\"]') || "
            "document.title.toLowerCase().includes('just a moment') || "
            "document.body.innerText.toLowerCase().includes('checking your browser'));"
        ))
    except Exception:
        challenge_present = has_cloudflare_iframe(page) or looks_like_cloudflare(page)
    if not challenge_present:
        log("ℹ️ 当前页面未发现 Turnstile 控件，继续正常流程")
        return True

    for attempt in range(5):
        rect = None
        for _ in range(15):
            rect = _find_turnstile_rect(page)
            if rect:
                break
            time.sleep(1)
        if not rect:
            log(f"⚠️ 第 {attempt+1} 次没找到 Turnstile 容器")
            continue

        _click_turnstile(page, rect)

        # 轮询：最多 15 秒，每 1 秒查一次 token；token 出现即成功
        token = ""
        for _ in range(15):
            token = _get_turnstile_token(page)
            if token:
                break
            time.sleep(1)
        if token:
            # 刚拿到 token 时可能被 CF 重置，再确认一次稳定
            time.sleep(1)
            if _get_turnstile_token(page):
                log("✅ Turnstile 验证通过")
                return True

        log(f"⏳ 第 {attempt+1} 次轮询未通过，重试...")

    log("❌ Turnstile 5 次均未通过")
    try:
        debug_dir = os.getenv("DEBUG_DIR", "./debug")
        os.makedirs(debug_dir, exist_ok=True)
        page.get_screenshot(path=os.path.join(debug_dir, "turnstile_fail.png"))
        log("📸 已保存 turnstile_fail.png")
    except Exception as e:
        log(f"⚠️ 截图失败: {e}")
    return False

def wait_for_challenge(page, account_name):
    """等待 Cloudflare 挑战自动完成 / 人工处理。

    改进点：
    1) 不只查顶层文本，还查 challenges.cloudflare.com iframe；
    2) 轮询间隔 2s，按 TURNSTILE_WAIT_SECONDS 控制总时长；
    3) 挑战期间若出现 Turnstile 容器，自动点击（处理"先 JS 挑战、后 Turnstile"的两段式流程）。
    """
    if not (looks_like_cloudflare(page) or has_cloudflare_iframe(page)):
        return True

    log("🛡️ 检测到 Cloudflare/Turnstile 页面。")
    log("ℹ️ 本程序不会破解或绕过验证码。")
    log("ℹ️ 如果挑战能由正常浏览器自动完成，将继续等待。")

    timeout = int(os.getenv("TURNSTILE_WAIT_SECONDS", "45"))
    end = time.time() + timeout
    clicks = 0            # 已点击次数（最多 3 次）
    last_click_at = 0.0   # 上次点击时间戳
    while time.time() < end:
        time.sleep(2)
        # 出现 Turnstile checkbox 且（尚未点击 / 点击后 10s token 仍未出现）→ 自动点击
        # 处理"点歪了 / token 被 CF 重置"的情况
        rect = _find_turnstile_rect(page)
        token_ok = bool(_get_turnstile_token(page))
        need_click = rect and (clicks == 0 or (not token_ok and time.time() - last_click_at >= 10))
        if need_click and clicks < 3:
            _click_turnstile(page, rect)
            clicks += 1
            last_click_at = time.time()
            continue
        if _cloudflare_clear(page):
            log("✅ Cloudflare 页面已通过/消失")
            return True

    save_debug(page, account_name, "cloudflare_challenge_timeout")
    log(f"❌ Cloudflare 挑战在 {timeout}s 内未完成")
    return False

def find_input(page, name):
    try:
        return page.ele(f'css:input[name="{name}"]')
    except Exception:
        return None

def find_button(page, names):
    for name in names:
        try:
            ele = page.ele(f'css:input[name="{name}"]')
            if ele:
                return ele
        except Exception:
            pass
        try:
            ele = page.ele(f'css:button[name="{name}"]')
            if ele:
                return ele
        except Exception:
            pass
    return None

def click_first_action(page):
    try:
        ele = page.ele('css:input[name^="action_"]')
        if ele:
            ele.click()
            return True
    except Exception:
        pass
    try:
        ele = page.ele('css:button[name^="action_"]')
        if ele:
            ele.click()
            return True
    except Exception:
        pass
    return False

def browser_login(page, account):
    divider(f"登录 {account['name']}")
    page.get(LOGIN_PAGE)
    wait_page(page, 2)

    # xmgame 需要手动点 Turnstile（已处理，无需再 wait_for_challenge）。
    # 若 5 次都失败，刷新页面重试一次（Chrome profile 保留首访信息，二次加载常更容易过 CF）
    if not handle_turnstile(page):
        log("🔄 Turnstile 未通过，刷新页面重试一次...")
        try:
            page.get(LOGIN_PAGE)
            wait_page(page, 2)
        except Exception as e:
            log(f"⚠️ 刷新失败: {e}")
        if not handle_turnstile(page):
            log("❌ Turnstile 未通过（重试后仍失败）")
            return False

    uniqid = find_input(page, "uniqid")
    memberid = find_input(page, "memberid")
    password = find_input(page, "user_password")

    if not memberid or not password:
        save_debug(page, account["name"], "login_form_not_found")
        log("❌ 未找到登录表单")
        return False

    if uniqid:
        log("✅ 找到 uniqid")
    memberid.input(account["email"])
    password.input(account["password"])

    submit = find_button(page, ["action_user_login", "service_login"])
    if not submit:
        # 某些页面提交按钮没有 name，尝试普通 submit。
        try:
            submit = page.ele('css:input[type="submit"]')
        except Exception:
            submit = None

    if not submit:
        save_debug(page, account["name"], "login_submit_not_found")
        log("❌ 未找到登录按钮")
        return False

    submit.click()
    wait_page(page, 3)

    if not wait_for_challenge(page, account["name"]):
        return False

    # 登录成功的标志：URL 离开 login 路径（进入 xapanel/myaccount 等），
    # 且页面不再有密码输入框。原逻辑要求 URL 同时含 login 和 myaccount，
    # 两个条件矛盾，实际上永远不会触发，形同虚设。
    still_on_login = "/xapanel/login" in page.url.lower()
    has_password_field = False
    try:
        has_password_field = bool(page.ele('css:input[name="user_password"]'))
    except Exception:
        pass
    if still_on_login or has_password_field:
        save_debug(page, account["name"], "login_may_have_failed")
        log(f"❌ 登录后仍停留在登录页面（URL: {page.url}）")
        return False

    log("✅ 浏览器登录完成")
    return True

def _get_server_id_http(page):
    """HTTP 快速读取面板 index 页中的 jumpvps 服务器 ID（cf_clearance 有效期内秒开）。"""
    _init_http_cookies(page)
    try:
        r = _http_request("GET", XMGAME_INDEX_URL)
        html = r.text or ""
        if _resp_blocked_by_cf(html):
            return None
        m = re.search(r"/xapanel/xmgame/jumpvps/\?id=(\d+)", html)
        if m:
            return m.group(1)
        m2 = re.search(r"jumpvps/\?id=(\d+)", html)
        return m2.group(1) if m2 else None
    except Exception as e:
        log(f"⚠️ HTTP 读取面板 index 异常: {e}")
        return None


def get_server_id(page):
    # 1. 当前页面直接找（浏览器登录后页面通常已含 jumpvps 链接，零等待）
    m = re.search(r"/xapanel/xmgame/jumpvps/\?id=(\d+)", page.html or "")
    if m:
        return m.group(1)

    # 2. HTTP 快速模式：浏览器已登录+已过盾，直接请求面板 index
    sid = _get_server_id_http(page)
    if sid:
        return sid

    # 3. 回退：浏览器加载面板 index
    page.get(XMGAME_INDEX_URL)
    wait_page(page, 2)

    if not wait_for_challenge(page, "xgame-index"):
        return None

    try:
        links = page.eles('css:a[href*="/xapanel/xmgame/jumpvps/"]')
        for link in links:
            href = link.attr("href") or ""
            m = re.search(r"[?&]id=(\d+)", href)
            if m:
                return m.group(1)
    except Exception:
        pass

    m = re.search(r"/xapanel/xmgame/jumpvps/\?id=(\d+)", page.html or "")
    return m.group(1) if m else None

def open_game(page, account_name):
    server_id = get_server_id(page)
    if not server_id:
        save_debug(page, account_name, "jumpvps_not_found")
        log("❌ 未找到 jumpvps")
        return False

    jump_url = f"{BASE_URL}/xapanel/xmgame/jumpvps/?id={server_id}"

    # 面板会话必须由真实浏览器执行 jumpvps 一次性表单才能建立（HTTP 模拟拿不到
    # 页面 JS 种的会话状态，会导致后续期限读取失败）。已过盾后加载只需数秒。
    page.get(jump_url)
    wait_page(page, 2)

    if not wait_for_challenge(page, account_name):
        return False

    # jumpvps 页面通常会提交一次性登录表单。
    # 优先点击表单的 submit；如果页面自动跳转则直接继续。
    clicked = False
    try:
        submit = page.ele('css:form input[type="submit"]')
        if submit:
            submit.click()
            clicked = True
    except Exception:
        pass

    if clicked:
        wait_page(page, 3)

    if "xmgame" not in page.url.lower() and "secure.xserver.ne.jp" not in page.url.lower():
        save_debug(page, account_name, "unexpected_game_redirect")
        log(f"⚠️ 游戏面板跳转地址异常: {page.url}")

    # 浏览器已真实加载面板（可能种了新 cookie），重置 HTTP 快速模式以便下次从浏览器取最新 cookie
    global _HTTP_INIT, _HTTP_COOKIES
    _HTTP_INIT = False
    _HTTP_COOKIES = {}
    log("✅ 游戏面板页面已打开")
    return True

def _read_info_http(page):
    _init_http_cookies(page)
    try:
        r = _http_request("GET", INFO_URL)
        html = r.text or ""
        if _resp_blocked_by_cf(html):
            return None
        info = parse_remaining(html)
        # 解析不出有效期限（非期限页/登录页/错误页）同样视为失败，让调用方回退浏览器
        if info is None or (info[0] < 0 and info[1] < 0 and not info[3]):
            return None
        return info
    except Exception as e:
        log(f"⚠️ HTTP 读取期限异常: {e}")
        return None


def read_info(page):
    # 优先 HTTP 快速模式（秒读期限）；被 CF 拦或解析失败再回退浏览器
    info = _read_info_http(page)
    if info is not None:
        return info

    # 回退浏览器前重置 HTTP cookie 字典，下次从浏览器取最新 cookie（浏览器会话更完整）
    global _HTTP_INIT, _HTTP_COOKIES
    _HTTP_INIT = False
    _HTTP_COOKIES = {}

    page.get(INFO_URL)
    wait_page(page, 2)

    if not wait_for_challenge(page, "game-info"):
        return None

    html = page.html or ""
    return parse_remaining(html)

def get_browser_ua(page):
    """从当前浏览器读取真实 UA，保证后续 requests 与浏览器指纹一致（避免 CF 二次验证）"""
    try:
        ua = page.run_js("return navigator.userAgent;")
        if isinstance(ua, str) and ua.strip():
            return ua.strip()
    except Exception:
        pass
    return ""


# 同一账号内 HTTP 快速模式共享的 cookie 字典：
# 浏览器登录后 cookie + 响应 Set-Cookie 全部自维护，避免 curl_cffi jar 覆盖显式 header 的行为。
# 每个账号开始时由 run_account 重置，避免账号间 cookie 交叉。
_HTTP_INIT = False
_HTTP_COOKIES = {}  # name -> value
_HTTP_UA = ""       # 浏览器真实 UA，随账号重置


def _proxies_dict():
    proxy = get_proxy()
    return {"http": proxy, "https": proxy} if proxy else {}


def _cookie_header():
    return "; ".join(f"{k}={v}" for k, v in _HTTP_COOKIES.items())


def _update_cookies_from_response(r):
    """把响应的 Set-Cookie 合并进自维护 cookie 字典（兼容多 Set-Cookie）。"""
    try:
        set_cookies = r.headers.get_list("set-cookie")
    except Exception:
        set_cookies = None
    if not set_cookies:
        raw = r.headers.get("set-cookie")
        set_cookies = [raw] if raw else []
    for sc in set_cookies:
        pair = sc.split(";", 1)[0].strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            _HTTP_COOKIES[k.strip()] = v.strip()


def _init_http_cookies(page):
    """首次（或账号重置后）从浏览器 cookie/UA 初始化自维护字典。"""
    global _HTTP_INIT, _HTTP_COOKIES, _HTTP_UA
    if not _HTTP_INIT:
        _HTTP_INIT = True
        _HTTP_COOKIES = {}
        _HTTP_UA = get_browser_ua(page) or ""
        try:
            for ck in page.cookies():
                if ck.get("name"):
                    _HTTP_COOKIES[ck["name"]] = ck["value"]
        except Exception:
            pass


def _http_request(method, url, *, data=None, headers=None, timeout=20):
    """函数式 curl_cffi 请求（每请求独立 TLS 指纹，无 jar 干扰）+ 自维护 cookie。"""
    proxies = _proxies_dict()
    h = dict(headers or {})
    h["Cookie"] = _cookie_header()
    if _HTTP_UA:
        h.setdefault("User-Agent", _HTTP_UA)
    if method == "POST":
        r = curl_requests.post(url, headers=h, data=data, impersonate="chrome",
                               timeout=timeout, proxies=proxies)
    else:
        r = curl_requests.get(url, headers=h, impersonate="chrome",
                              timeout=timeout, proxies=proxies)
    _update_cookies_from_response(r)
    return r


def _resp_blocked_by_cf(text):
    """续期请求若被 CF 拦截，响应是挑战页而非表单页。识别后不要误判为'非续期窗口'。"""
    if not text:
        return False
    t = text.lower()
    return any(m in t for m in ("just a moment", "cf-chl-", "turnstile", "checking your browser"))


def _request_retry(session, method, url, *, retries=2, impersonate="chrome", **kwargs):
    """带简单重试的 HTTP 请求：对 5xx / 超时 / 连接错误自动重试 retries 次。

    统一使用 curl_cffi（模拟 Chrome 真实 TLS 指纹，降低被 Cloudflare 拦截概率）。
    session 传 curl_cffi Session 用会话（保留 cookie/UA）；传 None 用裸请求（同样带指纹）。
    """
    for attempt in range(retries + 1):
        try:
            if session is None:
                r = curl_requests.request(method, url, impersonate=impersonate, **kwargs)
            else:
                r = getattr(session, method.lower())(url, **kwargs)
            if r.ok or r.status_code < 500 or attempt >= retries:
                return r
            log(f"⚠️ {method} {url} HTTP {r.status_code}，重试 {attempt + 1}/{retries}...")
        except Exception as e:
            if attempt >= retries:
                raise
            log(f"⚠️ {method} {url} 异常: {e}，重试 {attempt + 1}/{retries}...")
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{method} {url} 重试后仍失败")


def submit_renewal(page, account_name):
    """混合模式：浏览器已过 Cloudflare，取 cookie 后用 requests 走表单续期"""
    log("🔄 [续期] 从浏览器提取 cookie...")
    try:
        browser_cookies = page.cookies()
        cookie_dict = {ck["name"]: ck["value"] for ck in browser_cookies}
        log(f"🔄 [续期] 拿到 {len(cookie_dict)} 个 cookie")
    except Exception as e:
        log(f"❌ [续期] 取 cookie 失败: {e}")
        return False

    # 关键：UA 与浏览器一致，减少 CF 对"网页过盾但 API 请求 UA 不同"的怀疑
    real_ua = get_browser_ua(page) or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    # curl_cffi + impersonate=chrome：模拟 Chrome 真实 TLS 指纹，续期 HTTP 层不再用
    # requests（其 TLS 指纹与浏览器差异明显，更容易被 Cloudflare 二次拦截）
    session = curl_requests.Session(impersonate="chrome")
    session.headers.update({
        "User-Agent": real_ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    # 浏览器 cookie 以 Cookie header 直接携带（curl_cffi 的 cookie API 与 requests 有差异，
    # 手动 header 最可控；单一站点场景完全够用）
    cookie_header = "; ".join(
        f"{ck['name']}={ck['value']}" for ck in browser_cookies if ck.get("name")
    )
    if cookie_header:
        session.headers.update({"Cookie": cookie_header})

    proxy = get_proxy()
    proxies = {"http": proxy, "https": proxy} if proxy else {}

    try:
        log("🔄 [续期] GET 延长页面...")
        r = _request_retry(session, "GET", EXTEND_URL, headers={"referer": INFO_URL}, timeout=20, proxies=proxies)
        r.encoding = "EUC-JP"
        if not r.ok:
            log(f"❌ [续期] 延长页 HTTP {r.status_code}")
            return False
        if _resp_blocked_by_cf(r.text):
            log("❌ [续期] 延长页被 Cloudflare 拦截（cookie 未通过校验）")
            return False
        eligibility = can_renew(r.text)
        if eligibility is False:
            log("⌛️ 当前仍未进入可续期窗口")
            return None
        if eligibility is None:
            log("❌ [续期] 延长页结构异常或状态无法判断，停止提交以避免误操作")
            return False
        log("🔄 [续期] 可续期，GET 续期输入页...")

        r2 = _request_retry(session, "GET", RENEW_URL, headers={"referer": EXTEND_URL}, timeout=20, proxies=proxies)
        r2.encoding = "EUC-JP"
        if not r2.ok:
            log(f"❌ [续期] 续期输入页 HTTP {r2.status_code}")
            return False
        if _resp_blocked_by_cf(r2.text):
            log("❌ [续期] 续期输入页被 Cloudflare 拦截（cookie 未通过校验）")
            return False
        form_conf = extract_form_data(r2.text)
        log(f"🔄 [续期] 表单字段: {list(form_conf.keys())}")

        if "login_token" not in form_conf:
            lt = re.search(r'name=["\']login_token["\']\s+value=["\']([^"\']+)["\']', r2.text)
            if lt:
                form_conf["login_token"] = lt.group(1)
        if "period" not in form_conf:
            log("❌ [续期] 输入页缺少 period 字段，停止提交")
            return False
        if not any(k.startswith("action_") for k in form_conf.keys()):
            log("❌ [续期] 输入页缺少提交按钮字段，停止提交")
            return False
        if not form_conf.get("login_token"):
            log("❌ [续期] 输入页缺少 login_token，可能会话失效，停止提交")
            return False

        log("🔄 [续期] POST 确认页...")
        time.sleep(1)
        r3 = _request_retry(session, "POST", CONF_URL,
            headers={"content-type": "application/x-www-form-urlencoded", "origin": BASE_URL, "referer": RENEW_URL},
            data=form_conf, timeout=20, proxies=proxies)
        r3.encoding = "EUC-JP"
        if not r3.ok or _resp_blocked_by_cf(r3.text):
            log(f"❌ [续期] 确认页异常 HTTP {r3.status_code}")
            return False
        # 注意：确认页正常会回显 login_token 隐藏域，不能把它当作会话失效标志；
        # 会话失效要看明确的登录提示文案（ログインしてください / ログイン画面）。
        if any(marker in r3.text for marker in ("ログインしてください", "ログイン画面")) and "延長" not in r3.text:
            log("❌ [续期] 确认页疑似会话失效，停止执行")
            return False

        form_do = extract_form_data(r3.text)
        if not form_do.get("login_token"):
            form_do["login_token"] = form_conf.get("login_token", "")
        if not form_do.get("period"):
            form_do["period"] = form_conf.get("period", "")
        if not any(k.startswith("action_") for k in form_do.keys()):
            log("❌ [续期] 确认页缺少执行按钮字段，停止提交")
            return False
        if not form_do.get("login_token") or not form_do.get("period"):
            log("❌ [续期] 确认页缺少必要字段，停止提交")
            return False

        log("🔄 [续期] POST 执行续期...")
        time.sleep(1)
        r4 = _request_retry(session, "POST", DO_URL,
            headers={"content-type": "application/x-www-form-urlencoded", "origin": BASE_URL, "referer": CONF_URL},
            data=form_do, timeout=20, proxies=proxies)
        r4.encoding = "EUC-JP"
        if not r4.ok:
            log(f"❌ [续期] 执行请求 HTTP {r4.status_code}")
            return False
        if _resp_blocked_by_cf(r4.text):
            log("❌ [续期] 执行请求被 Cloudflare 拦截")
            return False
        if any(marker in r4.text for marker in ("ログインしてください", "ログイン画面")):
            log("❌ [续期] 执行结果疑似会话失效")
            return False
        log("🔄 [续期] 请求已发送；最终结果仍以重新读取到的期限为准")
        return True

    except Exception as e:
        log(f"❌ [续期] 请求异常: {e}")
        return False

def update_cf_cron(remaining_hours, remaining_minutes):
    cf_account_id = os.environ.get("CF_ACCOUNT_ID", "")
    cf_script_name = os.environ.get("CF_SCRIPT_NAME", "")
    cf_api_token = os.environ.get("CF_API_TOKEN", "")

    if not all([cf_account_id, cf_script_name, cf_api_token]):
        log("⚠️ 未配置完整 Cloudflare 变量，跳过 Cron 更新")
        return False, "⚠️ 未配置 CF 环境变量", "未知", "未知"

    if remaining_hours < 0:
        cron_str = "0 */2 * * *"
        cst_next = "兜底每2小时"
    else:
        total = remaining_hours * 60 + remaining_minutes
        wait_minutes = max(10, total - 235)
        now = datetime.datetime.now(datetime.timezone.utc)
        next_run = now + datetime.timedelta(minutes=wait_minutes)
        cron_str = f"{next_run.minute} {next_run.hour} {next_run.day} {next_run.month} *"
        cst_next = next_run.astimezone(
            datetime.timezone(datetime.timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S")

    url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/workers/scripts/{cf_script_name}/schedules"
    try:
        resp = _request_retry(None, "PUT", url,
            json=[{"cron": cron_str}],
            headers={
                "Authorization": f"Bearer {cf_api_token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if resp.ok:
            log("✅ Cloudflare Worker Cron 更新成功")
            return True, "✅ 更新成功", cron_str, cst_next
        log(f"❌ Cloudflare Cron 更新失败: HTTP {resp.status_code}")
        return False, f"❌ 更新失败 HTTP {resp.status_code}", cron_str, cst_next
    except Exception as e:
        return False, f"❌ CF API 异常: {e}", cron_str, cst_next

def check_ip_info():
    try:
        proxy = get_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else {}
        r = _request_retry(None, "GET", IP_CHECK_URL, proxies=proxies, timeout=20)
        d = r.json()
        return d.get("ip", "未知"), d.get("country", "未知")
    except Exception:
        return "未知", "未知"

def notify_tg(name, result, raw_dl, cst_dl, remaining, cf_info):
    if not TG_BOT:
        return
    parts = TG_BOT.split(",", 1)
    if len(parts) != 2:
        return
    chat_id, token = parts[0].strip(), parts[1].strip()

    proxy_ip, proxy_country = check_ip_info()
    msg = (
        "🎮 XServer Game 续期通知\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🖥 服务器名称: {name}\n"
        f"📅 到期时间: {raw_dl}\n"
        f"⏱️ CST: {cst_dl}\n"
        f"⏳ 剩余: {remaining}\n"
        f"📊 结果: {result}\n"
        f"🌐 IP: {proxy_ip} ({proxy_country})\n"
        f"☁️ CF Cron: {cf_info.get('status', '未知')}\n"
        f"⚙️ CRON: {cf_info.get('cron', '未知')}\n"
        f"🕐 执行时间: {now_str()}\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    try:
        r = _request_retry(None, "POST",
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=15,
        )
        if r.ok:
            log("📨 TG 推送成功")
        else:
            log(f"⚠️ TG 推送失败 HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log(f"⚠️ TG 推送失败: {e}")

def run_account(page, account):
    global _HTTP_INIT, _HTTP_COOKIES, _HTTP_UA
    _HTTP_INIT = False  # 每个账号独立 cookie/UA，避免账号间交叉
    _HTTP_COOKIES = {}
    _HTTP_UA = ""
    divider(account["name"])

    if not browser_login(page, account):
        return False, "❌ 登录失败", "未知", "未知", "0小时0分"

    if not open_game(page, account["name"]):
        return False, "❌ 游戏面板打开失败", "未知", "未知", "0小时0分"

    info = read_info(page)
    if not info:
        return False, "❌ 无法读取服务器信息", "未知", "未知", "0小时0分"

    h_before, m_before, dl_before, expired = info
    if not expired and (h_before < 0 or m_before < 0):
        log("❌ 服务器期限页面解析失败，禁止继续续期，避免把异常页面误判为到期")
        NEXT_RUN_MINUTES.append(-1)
        return False, "❌ 期限信息解析失败", dl_before, "未知", "未知"

    cst_before = get_exact_cst_time(h_before, m_before)
    remaining_before = f"{h_before} 小时 {m_before} 分"

    if expired:
        log(f"⚠️ 已过期: {dl_before}")
    else:
        log(f"📅 当前利用期限: {dl_before}")
        log(f"⏳ 剩余: {remaining_before}")
        if h_before >= RENEW_THRESHOLD_HOURS:
            NEXT_RUN_MINUTES.append(h_before * 60 + m_before)
            return True, "⌛️ 期限未至（无需续期）", dl_before, cst_before, remaining_before

    log(f"🔄 进入续期流程（剩余 {h_before}h{m_before}m < 阈值 {RENEW_THRESHOLD_HOURS}h）")
    renewed = submit_renewal(page, account["name"])
    log(f"🔄 续期函数返回: {renewed}")
    if renewed is None:
        NEXT_RUN_MINUTES.append(max(0, h_before * 60 + m_before))
        return True, "⌛️ 期限未至（暂不可续期）", dl_before, cst_before, remaining_before
    if not renewed:
        NEXT_RUN_MINUTES.append(-1)
        return False, "❌ 续期页面操作失败", dl_before, cst_before, remaining_before

    time.sleep(3)
    after = read_info(page)
    if not after:
        NEXT_RUN_MINUTES.append(-1)
        return False, "❌ 续期后无法读取状态", dl_before, cst_before, remaining_before

    h_after, m_after, dl_after, expired_after = after
    cst_after = get_exact_cst_time(h_after, m_after)
    remaining_after = f"{h_after} 小时 {m_after} 分"

    success = (expired and not expired_after) or (dl_after != dl_before) or (h_after > h_before)

    if success:
        NEXT_RUN_MINUTES.append(h_after * 60 + m_after)
        return True, "✅ 续期成功！", dl_after, cst_after, remaining_after

    NEXT_RUN_MINUTES.append(-1)
    return False, "❌ 续期后期限未变化", dl_after or dl_before, cst_after, remaining_after

def main():
    failed = 0
    results = []

    try:
        # 每个账号使用独立、临时的 Chrome profile，避免多个账号共用 Cookie/登录态。
        import tempfile
        with tempfile.TemporaryDirectory(prefix="xserver-renew-") as temp_root:
            for index, account in enumerate(ACCOUNTS):
                page = None
                try:
                    profile = Path(temp_root) / f"account-{index + 1}"
                    page = ChromiumPage(build_options(profile=str(profile)))
                    result = run_account(page, account)
                except Exception as e:
                    log(f"❌ {account['name']} 致命异常: {e}")
                    result = (False, f"❌ 致命异常: {e}", "未知", "未知", "0小时0分")
                    NEXT_RUN_MINUTES.append(-1)
                finally:
                    if page is not None:
                        try:
                            page.quit()
                        except Exception:
                            pass

                results.append((account, result))
                if not result[0]:
                    failed += 1

        if not NEXT_RUN_MINUTES or -1 in NEXT_RUN_MINUTES:
            cf = update_cf_cron(-1, -1)
        else:
            minutes = min(NEXT_RUN_MINUTES)
            cf = update_cf_cron(minutes // 60, minutes % 60)

        cf_info = {"status": cf[1], "cron": cf[2], "cst": cf[3]}
        for account, result in results:
            notify_tg(account["name"], result[1], result[2], result[3], result[4], cf_info)
    finally:
        pass

    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
