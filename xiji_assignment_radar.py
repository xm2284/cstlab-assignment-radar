#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
希冀作业雷达 · cstlab 待交作业与提交完成度监控

平台：中科大 CourseGrading（希冀），部署于 cstlab.jsnu.edu.cn
登录：校园 CAS 统一认证（sid.jsnu.edu.cn）。平台自带的登录入口有图形验证码 + AES 加密，
      脚本直接模拟容易触发风控锁号，所以这里用 Playwright 无头浏览器走 CAS，拿到
      JSESSIONID 之后再切回 requests 干活。

它做三件事：
    1. 登录（无头浏览器走 CAS）
    2. 扫全部课程的在期作业，并逐题检查提交状态（已完成 / 部分完成 / 未开始）
    3. 发 HTML 邮件：未完成的排上面，已完成的排下面

依赖：
    pip install playwright beautifulsoup4 requests
    playwright install chromium

用法：
    cp config.example.json config.json   # 填学号、密码、邮箱授权码
    python xiji_assignment_radar.py

注意：config.json 里是你的真实学号密码，已在 .gitignore 里，别提交。
"""
import asyncio
import json
import os
import re
import smtplib
import sys
import urllib3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

import requests
from bs4 import BeautifulSoup

urllib3.disable_warnings()

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")

BASE_URL = "https://cstlab.jsnu.edu.cn"
CAS_URL = (
    "https://sid.jsnu.edu.cn/cas/login?service="
    "https%3A%2F%2Fcstlab.jsnu.edu.cn%2F"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

CONFIG = {
    "stid": "你的学号",
    "pwd": "你的校园密码",
    "email": {
        "smtp_server": "smtp.qq.com",
        "smtp_port": 465,
        "sender": "你的QQ号@qq.com",
        "auth_code": "QQ邮箱SMTP授权码",
        "receiver": "你的QQ号@qq.com",
    },
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            user = json.load(f)
        CONFIG["stid"] = user.get("stid", CONFIG["stid"])
        CONFIG["pwd"] = user.get("pwd", CONFIG["pwd"])
        CONFIG["email"].update(user.get("email", {}))
    if CONFIG["stid"].startswith("你的") or CONFIG["pwd"].startswith("你的"):
        sys.exit("请在 config.json 里填写学号与密码（参考 config.example.json）。")
    return CONFIG


async def get_session_cookies():
    """用无头浏览器走一次 CAS，拿回已认证的 cookie。"""
    from playwright.async_api import async_playwright

    print("[1/3] 启动无头浏览器，走校园统一认证…")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            # 校园站证书链常不完整，不去校验；不改这个第一次跑必报错
            args=["--ignore-certificate-errors"],
            ignore_default_args=["--enable-automation"],
        )
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        await page.goto(CAS_URL, wait_until="networkidle")
        await asyncio.sleep(3)

        await page.locator(
            "input[placeholder*='校园ID'], input[placeholder*='卡号']"
        ).first.type(CONFIG["stid"], delay=50)
        await page.locator("input[placeholder*='密码']").first.type(
            CONFIG["pwd"], delay=50
        )
        await page.locator("button:has-text('登 录'), button:has-text('登录')").first.click()
        await asyncio.sleep(10)

        cookies = await context.cookies()
        await browser.close()

    if not any(c["name"] == "JSESSIONID" for c in cookies):
        raise RuntimeError("登录异常，没拿到 JSESSIONID。多半是密码变了或被风控拦了。")
    print("  ✓ 统一认证通过")
    return cookies


def check_assignment_detail_status(s, assign_id):
    """进作业详情页，逐题数一遍交没交。"""
    url = f"{BASE_URL}/assignment/index.jsp?assignID={assign_id}"
    r = s.get(url, verify=False, timeout=12)
    soup = BeautifulSoup(r.text, "html.parser")

    total = 0
    submitted = 0
    for tr in soup.find_all("tr"):
        if any(h in tr.get_text() for h in ["提交状态", "题目"]):
            continue
        tds = tr.find_all("td")
        if len(tds) >= 3:
            total += 1
            status = tds[-1].get_text(strip=True)
            if any(k in status for k in ["已提交", "通过", "已评阅"]) and "未" not in status:
                submitted += 1
            elif re.search(r"202\d-\d{2}-\d{2}", status):
                submitted += 1

    if total == 0:
        return {"label": "未开始", "complete": False}
    complete = submitted == total
    if complete:
        label = "✅ 已全部完成"
    elif submitted > 0:
        label = f"🟡 部分完成 ({submitted}/{total})"
    else:
        label = f"🔴 未开始 (0/{total})"
    return {"label": label, "complete": complete}


def parse_course_assigns(s, course_id):
    """抓某门课的在期作业列表，并逐个验证提交状态。"""
    s.get(f"{BASE_URL}/courselist.jsp?courseID={course_id}", verify=False)
    s.get(f"{BASE_URL}/main.jsp", verify=False)
    r = s.get(f"{BASE_URL}/assignment/mainActiveAssigns.jsp", verify=False, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    assignments = []
    for block in soup.find_all("div", class_="main-zy"):
        title_tag = block.find("p", class_="main-title")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)

        time_tag = block.find("div", class_="main-time")
        due = (
            time_tag.get_text(strip=True).replace("作业时间：", "").split(" - ")[1].strip()
            if time_tag and " - " in time_tag.get_text()
            else "未指定"
        )
        countdown_tag = block.find("div", class_="main-time-s")
        countdown = countdown_tag.get_text(strip=True) if countdown_tag else ""

        href_tag = block.find("a", href=True)
        if not href_tag:
            continue
        href = href_tag["href"]
        m = re.search(r"assignID=(\d+)", href)
        if not m:
            continue
        assign_id = m.group(1)

        comp = check_assignment_detail_status(s, assign_id)
        assignments.append(
            {
                "title": title,
                "due": due,
                "countdown": countdown,
                "url": f"{BASE_URL}/{href.lstrip('/')}",
                **comp,
            }
        )
    return assignments


def scan_all_courses(cookies):
    """把所有课程的作业扫一遍。"""
    print("[2/3] 逐门扫描在期作业…")
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Referer": BASE_URL + "/"})
    for c in cookies:
        if "jsnu.edu.cn" in c["domain"]:
            s.cookies.set(c["name"], c["value"], domain=c["domain"])

    r = s.get(f"{BASE_URL}/courselist.jsp?courseID=0", verify=False)
    soup = BeautifulSoup(r.text, "html.parser")

    seen, courses = set(), []
    for a in soup.find_all("a", href=True):
        m = re.search(r"courseID=(\d+)", a["href"])
        if m and m.group(1) != "0" and len(a.get_text(strip=True)) > 1:
            cid = m.group(1)
            if cid not in seen:
                seen.add(cid)
                courses.append((a.get_text(strip=True), cid))

    all_tasks = {}
    for title, cid in courses:
        assigns = parse_course_assigns(s, cid)
        if assigns:
            all_tasks[title] = assigns
        print(f"  · {title}：{len(assigns)} 项")
    return all_tasks


def send_email_report(tasks):
    """未完成排上面、已完成排下面，一封 HTML 邮件。"""
    print("[3/3] 生成并投递邮件…")
    pending, completed = {}, {}
    for course, hws in tasks.items():
        p = [h for h in hws if not h["complete"]]
        c = [h for h in hws if h["complete"]]
        if p:
            pending[course] = p
        if c:
            completed[course] = c

    total_p = sum(len(v) for v in pending.values())
    total_c = sum(len(v) for v in completed.values())

    pending_html = ""
    if total_p > 0:
        pending_html = (
            "<h3 style='color:#d73a49;border-left:4px solid #d73a49;padding-left:10px'>"
            "⚠️ 未完成作业：</h3>"
        )
        for course, hws in pending.items():
            pending_html += (
                f"<div style='margin:10px 0;padding:12px;border:1px solid #ffdce0;"
                f"border-radius:8px'><b>📚 《{course}》</b>"
                f"<table style='width:100%;border-collapse:collapse;font-size:13px'>"
            )
            for hw in hws:
                pending_html += f"""<tr>
<td style='padding:6px;border:1px solid #f1c3c8'><a href='{hw["url"]}'>{hw["title"]}</a></td>
<td style='padding:6px;border:1px solid #f1c3c8'>{hw["label"]}</td>
<td style='padding:6px;border:1px solid #f1c3c8'>{hw["due"]}</td>
<td style='padding:6px;border:1px solid #f1c3c8;color:#d73a49'><b>{hw["countdown"]}</b></td>
</tr>"""
            pending_html += "</table></div>"
    else:
        pending_html = (
            "<div style='background:#e6ffed;padding:15px;border-radius:8px'>"
            "<h3 style='color:#28a745'>🎉 所有作业都完成了！</h3></div>"
        )

    completed_html = ""
    if total_c > 0:
        completed_html = (
            f"<h3 style='color:#28a745;border-left:4px solid #28a745;padding-left:10px;"
            f"margin-top:20px'>✅ 已完成作业（{total_c}项）：</h3>"
        )
        for course, hws in completed.items():
            completed_html += (
                f"<div style='margin:8px 0;padding:10px;background:#f6f8fa;border-radius:8px;"
                f"color:#586069'><b>📚 《{course}》</b><br>"
            )
            for hw in hws:
                completed_html += f"　{hw['title']} · {hw['due']}<br>"
            completed_html += "</div>"

    subject = (
        f"【希冀作业提醒】还有{total_p}项待做" if total_p > 0 else "【希冀作业】全部完成 🎉"
    )
    html = f"""<div style='font-family:"Microsoft YaHei";padding:20px'>
<h2>希冀平台作业每日提醒</h2>
<p>待做: <b style='color:#d73a49'>{total_p}</b> 项 | 已完成: <b style='color:#28a745'>{total_c}</b> 项</p>
{pending_html}{completed_html}
</div>"""

    e = CONFIG["email"]
    msg = MIMEMultipart()
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = e["sender"]
    msg["To"] = e["receiver"]
    msg.attach(MIMEText(html, "html", "utf-8"))

    server = smtplib.SMTP_SSL(e["smtp_server"], e["smtp_port"])
    server.login(e["sender"], e["auth_code"])
    server.sendmail(e["sender"], e["receiver"], msg.as_string())
    server.quit()
    print(f"  ✓ 已发送：待做 {total_p} 项，已完成 {total_c} 项")


def main():
    load_config()
    cookies = asyncio.run(get_session_cookies())
    tasks = scan_all_courses(cookies)
    send_email_report(tasks)


if __name__ == "__main__":
    main()
