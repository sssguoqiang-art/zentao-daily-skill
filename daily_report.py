#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
平台项目每日日报生成脚本 v6
用法：
  python3 daily_report.py                    # 生成 Markdown 报告（原有行为）
  python3 daily_report.py --output json      # 输出结构化 JSON（供 Claude Code Skill 使用）
  python3 daily_report.py --output markdown  # 显式指定 Markdown 模式

依赖：pip install requests
"""

import argparse
import getpass
import json
import os
import re
import sys
import time
import logging
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# ════════════════════════════════════════════════════════════════
#  配置文件管理（账号密码不写在代码里）
# ════════════════════════════════════════════════════════════════

CONFIG_PATH = Path.home() / ".config" / "zentao-daily" / "config.json"

def load_config() -> dict:
    """从配置文件读取连接参数，不存在则提示运行 setup。"""
    if not CONFIG_PATH.exists():
        print("❌ 未找到配置文件，请先运行：")
        print("   python daily_report.py setup")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def run_setup():
    """交互式配置向导，只保存账号密码到本地配置文件。"""
    print("═" * 50)
    print("  禅道日报 · 首次配置")
    print("═" * 50)
    print(f"配置将保存至：{CONFIG_PATH}")
    print()

    account  = input("登录账号：").strip()
    password = getpass.getpass("登录密码（输入不显示）：")

    config = {"account": account, "password": password}

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    CONFIG_PATH.chmod(0o600)

    print()
    print(f"✅ 配置已保存：{CONFIG_PATH}")
    print()
    print("现在可以运行：")
    print("  python daily_report.py --output json   # 验证连接")
    print("  python daily_report.py                 # 生成 Markdown 日报")


# ════════════════════════════════════════════════════════════════
#  运行时配置
# ════════════════════════════════════════════════════════════════

# 禅道地址和项目 ID 固定，无需配置
BASE_URL = "https://cd.baa360.cc:20088/index.php"
PROJECT  = "10"

# --account / --password 传参时存入此处（由 main() 写入）
_CLI_ACCOUNT:  str = ""
_CLI_PASSWORD: str = ""


def _get_conn():
    """账号密码优先级：CLI 参数 > 环境变量 > 配置文件"""
    account  = _CLI_ACCOUNT  or os.environ.get("ZENTAO_ACCOUNT",  "")
    password = _CLI_PASSWORD or os.environ.get("ZENTAO_PASSWORD", "")

    if (not account or not password) and CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        account  = account  or cfg.get("account",  "")
        password = password or cfg.get("password", "")

    if not account or not password:
        print("❌ 未找到账号或密码，请通过以下任意方式提供：")
        print("   1. 运行  python daily_report.py setup")
        print("   2. 传参  python daily_report.py --account xxx --password xxx")
        sys.exit(1)

    return BASE_URL, account, password, PROJECT


# ════════════════════════════════════════════════════════════════
#  其他配置
# ════════════════════════════════════════════════════════════════

OUTPUT_DIR = os.path.expanduser("~/zentao-daily-reports")

# ════════════════════════════════════════════════════════════════
#  常量（不含账号密码，运行时从配置文件加载）
# ════════════════════════════════════════════════════════════════

REPORT_DEPTS = ["美术组", "PHP1组", "PHP2组", "Web组", "Cocos组"]

DEPT_KEY_MAP = {
    "art":   "美术组",
    "cocos": "Cocos组",
    "web":   "Web组",
}

PHPGROUP_DEPT = {"44": "PHP1部", "46": "PHP1部", "47": "PHP2部"}

CATEGORY_CN = {
    "version":   "版本需求",
    "operation": "运维需求",
    "internal":  "内部需求",
}

STATUS_DONE    = {"done", "closed", "cancel"}
STATUS_TESTING = {"waittest", "testing"}
STATUS_DEV     = {"wait", "doing", "pause", "rejected", "reviewing", "unsure"}

ONLINE_BUG_CLASSIFICATIONS = {"1", "2"}

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
#  网络工具
# ════════════════════════════════════════════════════════════════

def _parse_json(raw: str) -> dict:
    raw = re.sub(r'[\x00-\x09\x0b-\x1f\x7f]', ' ', raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        result, i = [], 0
        while i < len(raw):
            if raw[i] == '\\' and i + 1 < len(raw):
                if raw[i+1] in '"\\/ bfnrtu':
                    result.append(raw[i]); result.append(raw[i+1]); i += 2
                else:
                    result.append('\\\\'); i += 1
            else:
                result.append(raw[i]); i += 1
        return json.loads(''.join(result))


def fetch(session: requests.Session, params: dict, label: str = "") -> dict:
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }
    for attempt in range(1, 4):
        try:
            resp = session.get(BASE_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            raw = resp.content.decode("utf-8", errors="replace")
            if not raw.strip():
                raise ValueError(f"空响应（{label}）")
            return _parse_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            log.warning("  解析失败（%s）: %s [%d/3]", label, e, attempt)
            if attempt == 3: raise
            time.sleep(2)
        except requests.RequestException as e:
            log.warning("  请求失败（%s）: %s [%d/3]", label, e, attempt)
            if attempt == 3: raise
            time.sleep(3)


def fetch_pool(session: requests.Session, vid: str, label: str = "") -> dict:
    referer = f"{BASE_URL}?m=pool&f=browse&version={vid}&mode=3&projectSearch={PROJECT}"
    params = {
        "m": "pool", "f": "browse", "version": vid, "mode": "3",
        "title": "", "category": "", "isShowMoreSearch": "0",
        "pm": "", "tester": "0", "status": "", "phpGroup": "",
        "pri": "", "desc": "", "reviewPool": "", "skins": "", "deptCenter": "",
        "timeType": "timeType1", "begin": "", "end": "", "orderBy": "", "stateType": "",
        "tag": "", "onlyWeeklyShow": "0",
        "recTotal": "", "recPerPage": "200", "pageID": "1",
        "projectSearch": PROJECT, "t": "html", "getData": "1",
    }
    headers = {
        "Referer": referer,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }
    for attempt in range(1, 4):
        try:
            resp = session.get(BASE_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            raw = resp.content.decode("utf-8", errors="replace")
            if not raw.strip():
                raise ValueError(f"空响应（{label}）")
            return _parse_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            log.warning("  解析失败（%s）: %s [%d/3]", label, e, attempt)
            if attempt == 3: raise
            time.sleep(2)
        except requests.RequestException as e:
            log.warning("  请求失败（%s）: %s [%d/3]", label, e, attempt)
            if attempt == 3: raise
            time.sleep(3)


def login() -> Tuple[requests.Session, str]:
    log.info("▶ 登录禅道…")
    BASE_URL, ACCOUNT, PASSWORD, PROJECT = _get_conn()
    session = requests.Session()
    session.verify = False
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    data = fetch(session, {
        "m": "user", "f": "login",
        "account": ACCOUNT, "password": PASSWORD, "t": "json",
    }, "login")
    if data.get("status") != "success":
        raise RuntimeError(f"登录失败：{data}")
    token = data["user"]["token"]
    domain = BASE_URL.split("//")[-1].split("/")[0].split(":")[0]
    session.params = {"zentaosid": token}
    session.cookies.set("zentaosid", token, domain=domain)
    log.info("  登录成功 token=%s…", token[:10])
    session.get(BASE_URL.replace("/index.php", ""), params={"m": "my", "f": "index"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    return session, token


# ════════════════════════════════════════════════════════════════
#  版本解析
# ════════════════════════════════════════════════════════════════

def resolve_versions(session: requests.Session) -> Dict:
    log.info("▶ 识别版本信息…")
    _, _, _, PROJECT = _get_conn()
    data = fetch(session, {
        "m": "execution", "f": "all",
        "status": "undone", "orderBy": "order_asc",
        "productID": "0", "getData": "1", "t": "html",
    }, "版本列表")

    today_str = date.today().isoformat()
    all_execs = [
        e for e in data.get("executionStats", [])
        if str(e.get("project")) == PROJECT
        and e.get("end", "") not in ("", "0000-00-00")
        and re.search(r'（\d{4}）', e.get("name", ""))
    ]
    if not all_execs:
        raise RuntimeError("未找到平台部版本，请检查账号权限")

    curr_candidates = [e for e in all_execs if e["end"] >= today_str]
    if not curr_candidates:
        curr_candidates = all_execs
    curr = min(curr_candidates, key=lambda e: e["end"])

    next_candidates = [e for e in all_execs if e["end"] > curr["end"]]
    nxt = min(next_candidates, key=lambda e: e["end"]) if next_candidates else None

    def build(e):
        m = re.search(r'（(\d{4})）', e.get("name", ""))
        end_dt = datetime.strptime(e["end"], "%Y-%m-%d").date()
        return {
            "id":        str(e["id"]),
            "name":      e["name"].strip(),
            "begin":     e.get("begin", ""),
            "end":       e["end"],
            "short":     m.group(1) if m else str(e["id"]),
            "remaining": max(0, (end_dt - date.today()).days),
        }

    curr_info = build(curr)
    next_info = build(nxt) if nxt else None
    log.info("  当前版本：%s（ID=%s），距发布 %d 天",
             curr_info["name"], curr_info["id"], curr_info["remaining"])
    if next_info:
        log.info("  下一版本：%s（ID=%s）", next_info["name"], next_info["id"])
    return {"curr": curr_info, "next": next_info}


# ════════════════════════════════════════════════════════════════
#  数据抓取
# ════════════════════════════════════════════════════════════════

def fetch_version_pools(session: requests.Session, vid: str, label: str) -> Dict:
    log.info("  pool browse：%s…", label)
    raw = fetch_pool(session, vid, label)
    pools = [
        p for p in raw.get("pools", [])
        if p.get("taskStatus") != "cancel"
    ]
    return {
        "pools":        pools,
        "task_details": raw.get("taskDetails", {}),
        "bug_stat":     raw.get("associatedBugStat", {}),
        "pms":          raw.get("pms", {}),
        "users":        raw.get("users", {}),
    }


def fetch_online_bugs(session: requests.Session, vid: str) -> List[dict]:
    log.info("  Bug 管理接口…")
    _, _, _, PROJECT = _get_conn()
    all_bugs: List[dict] = []
    page = 1
    total = None
    while True:
        data = fetch(session, {
            "m": "report", "f": "onlinebug",
            "version": vid, "mode": "1",
            "handleDept": "0", "dept": "0",
            "questionType": "", "deptSearch": "", "scheduleStatus": "",
            "openedBy": "", "deptOwner": "", "type": "",
            "classification": "0", "isContainReanalyze": "0",
            "qaConfirm": "", "title": "", "isShowMoreSearch": "0",
            "recTotal": "", "recPerPage": "200", "pageID": str(page),
            "ids": "", "projectSearch": PROJECT,
            "belongSystem": "", "stateType": "", "severity": "0",
            "t": "html", "getData": "1",
        }, f"onlinebug p{page}")
        bugs = data.get("onlinebug", [])
        all_bugs.extend(bugs)
        if total is None:
            total = int(data.get("stat", {}).get("count", 0))
        log.info("    第%d页：%d / %d", page, len(all_bugs), total)
        if len(all_bugs) >= total or not bugs:
            break
        page += 1
        time.sleep(0.3)
    return all_bugs


# ════════════════════════════════════════════════════════════════
#  辅助函数
# ════════════════════════════════════════════════════════════════

def safe(val) -> str:
    s = str(val) if val is not None else "—"
    s = s.replace("|", "｜").replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or "—"


def fmt_date(d: str) -> str:
    if not d or d == "0000-00-00":
        return "—"
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%m%d")
    except ValueError:
        return d[:10]


def days_overdue(d: str) -> int:
    if not d or d == "0000-00-00":
        return 0
    try:
        return (date.today() - datetime.strptime(d, "%Y-%m-%d").date()).days
    except ValueError:
        return 0


def days_since(d: str) -> int:
    if not d:
        return 0
    try:
        return (date.today() - datetime.strptime(d[:10], "%Y-%m-%d").date()).days
    except ValueError:
        return 0


def get_pm_name(pool: dict, pms: dict) -> str:
    return pms.get(pool.get("pm", "") or "", pool.get("pm", "") or "—")


def get_category(pool: dict) -> str:
    return CATEGORY_CN.get(pool.get("category", ""), pool.get("category", "—"))


def is_unordered(pool: dict) -> bool:
    return str(pool.get("taskID", "") or "") in ("", "0")


def get_subtasks_by_dept(pool: dict, task_details: dict) -> Dict[str, List[dict]]:
    task_id = str(pool.get("taskID", "") or "")
    if not task_id or task_id == "0":
        return {}
    detail = task_details.get(task_id)
    if not isinstance(detail, dict):
        return {}

    php_group = str(pool.get("phpGroup", "") or "")
    result: Dict[str, List[dict]] = {}

    for dept_key, subs in detail.items():
        if dept_key == "devel":
            dept = PHPGROUP_DEPT.get(php_group, "")
        else:
            dept = DEPT_KEY_MAP.get(dept_key, "")
        if dept not in REPORT_DEPTS:
            continue
        if not isinstance(subs, list):
            continue
        valid = [s for s in subs if isinstance(s, dict) and s.get("deleted", "0") != "1"]
        if valid:
            if dept not in result:
                result[dept] = []
            result[dept].extend(valid)

    return result


def build_php_member_map(users: dict) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for group_key, group_members in users.items():
        if not isinstance(group_members, dict):
            continue
        if str(group_key) == "44":
            dept = "PHP1部"
        elif str(group_key) == "47":
            dept = "PHP2部"
        else:
            continue
        for username in group_members:
            if username and username != "0":
                mapping[username] = dept
    return mapping


def count_active_bugs(task_id: str, bug_list: List[dict]) -> int:
    if not task_id or task_id == "0":
        return 0
    return sum(
        1 for b in bug_list
        if str(b.get("mainTaskId", "0")) == task_id
        and b.get("status") == "active"
    )


def sub_order_type(sub: dict) -> str:
    assess = sub.get("storyAssessText", "") or ""
    if re.search(r">是<", assess):
        return "验收单"
    t = sub.get("type", "") or ""
    return {
        "study":   "制作单",
        "devel":   "开发单",
        "web":     "开发单",
        "test":    "开发单",
        "discuss": "讨论单",
    }.get(t, t or "其他")


# ════════════════════════════════════════════════════════════════
#  部门进度统计
# ════════════════════════════════════════════════════════════════

def calc_dept_stats(pools: List[dict], task_details: dict, version_end: str) -> Dict[str, dict]:
    stats = {
        d: {
            "remaining_tasks": 0,
            "remaining_label": "0",
            "total_left":      0.0,
            "total_consumed":  0.0,
            "type_cnt":        Counter(),
        }
        for d in REPORT_DEPTS
    }

    for pool in pools:
        dl = pool.get("deadline", "") or pool.get("deliveryDate", "") or ""
        if not dl or dl == "0000-00-00" or dl > version_end:
            continue

        dept_subs = get_subtasks_by_dept(pool, task_details)
        for dept, subs in dept_subs.items():
            for sub in subs:
                st       = sub.get("status", "")
                left     = float(sub.get("left", 0) or 0)
                consumed = float(sub.get("consumed", 0) or 0)
                stats[dept]["total_consumed"] += consumed
                if st in STATUS_DEV:
                    stats[dept]["remaining_tasks"] += 1
                    stats[dept]["total_left"]      += left
                    stats[dept]["type_cnt"][sub_order_type(sub)] += 1

    for d in REPORT_DEPTS:
        n = stats[d]["remaining_tasks"]
        if n == 0:
            stats[d]["remaining_label"] = "0"
        else:
            detail = "、".join(
                f"{name}{cnt}"
                for name, cnt in stats[d]["type_cnt"].most_common()
            )
            stats[d]["remaining_label"] = f"{n}（{detail}）"

    return stats


# ════════════════════════════════════════════════════════════════
#  各模块数据构建
# ════════════════════════════════════════════════════════════════

def build_delay_rows(pools: List[dict], task_details: dict) -> List[dict]:
    rows: List[dict] = []
    for pool in pools:
        if pool.get("taskStatus") in STATUS_DONE:
            continue
        name = pool.get("title", "")
        cat  = get_category(pool)
        dept_subs = get_subtasks_by_dept(pool, task_details)
        seen: set = set()
        for dept, subs in dept_subs.items():
            for sub in subs:
                if sub.get("status", "") not in STATUS_DEV:
                    continue
                dl = sub.get("deadline", "") or ""
                if not dl or dl == "0000-00-00":
                    continue
                overdue = days_overdue(dl)
                if overdue <= 0:
                    continue
                key = (dept, dl)
                if key not in seen:
                    seen.add(key)
                    rows.append({
                        "req_name":    safe(name),
                        "category":    safe(cat),
                        "dept":        safe(dept),
                        "deadline":    safe(fmt_date(dl)),
                        "overdue_days": overdue,
                    })
    return rows


def build_not_test_rows(pools: List[dict], task_details: dict, version_end: str) -> List[dict]:
    rows: List[dict] = []
    for pool in pools:
        if pool.get("taskStatus") not in STATUS_DEV:
            continue
        dl = pool.get("deadline", "") or pool.get("deliveryDate", "") or ""
        if not dl or dl == "0000-00-00" or dl > version_end:
            continue

        dept_subs = get_subtasks_by_dept(pool, task_details)
        blocked = [
            dept for dept, subs in dept_subs.items()
            if any(s.get("status", "") in STATUS_DEV for s in subs)
        ]
        overdue   = days_overdue(dl)
        dl_str    = fmt_date(dl) + ("⚠" if overdue > 0 else "")
        delay_str = f"超 {overdue}天" if overdue > 0 else "否"
        prog_str  = str(pool.get("progress", "0") or "0").rstrip("%")
        try:
            progress = int(prog_str)
        except ValueError:
            progress = 0

        rows.append({
            "name":          safe(pool.get("title", "")),
            "category":      safe(get_category(pool)),
            "blocked_depts": safe("、".join(blocked) if blocked else "—"),
            "deadline":      safe(dl_str),
            "progress":      progress,
            "delayed":       delay_str,
        })
    return rows


def build_test_focus_rows(pools: List[dict], bug_list: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for pool in pools:
        if pool.get("taskStatus") != "testing":
            continue
        task_id = str(pool.get("taskID", "") or "")
        active  = count_active_bugs(task_id, bug_list)
        env     = pool.get("env", "")
        if active == 0 and env != "require":
            continue
        rows.append({
            "name":        safe(pool.get("title", "")),
            "category":    safe(get_category(pool)),
            "active_bugs": active,
        })
    return rows


def build_online_bug_rows(bug_list: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for b in bug_list:
        if b.get("status") != "active":
            continue
        if str(b.get("classification", "")) not in ONLINE_BUG_CLASSIFICATIONS:
            continue
        rows.append({
            "title":    safe(b.get("title", "")),
            "deadline": safe(fmt_date(b.get("deadline", "") or "")),
        })
    return rows


def build_next_version_data(
    pools: List[dict], task_details: dict, pms: dict,
    version_end: str, php_member_map: Dict[str, str]
) -> Dict:
    DEPT_KEY_MAP_NXT = {
        "art":   "美术部",
        "cocos": "Cocos部",
        "web":   "Web部",
    }
    STATUS_DONE_POOL = {"done", "closed", "cancel"}

    total   = len(pools)
    ordered = sum(1 for p in pools if not is_unordered(p))

    dept_workload: Dict[str, dict] = {
        d: {"tasks": 0, "estimate": 0.0, "tasks_in_v": 0, "estimate_in_v": 0.0}
        for d in REPORT_DEPTS
    }
    unordered_rows: List[dict] = []

    for pool in pools:
        if is_unordered(pool):
            rd = pool.get("recordDate", "") or (pool.get("taskOpenedDate", "") or "")[:10]
            n  = days_since(rd)
            unordered_rows.append({
                "name":     safe(pool.get("title", "")),
                "category": safe(get_category(pool)),
                "pm":       safe(get_pm_name(pool, pms)),
                "desc":     safe(f"记录于 {fmt_date(rd)} · 已 {n} 天" if n > 0 else "需求未转任务"),
            })
            continue

        pool_dl = pool.get("deadline") or pool.get("deliveryDate")
        dl_str  = str(pool_dl) if pool_dl is not None else ""
        if not dl_str or dl_str == "0000-00-00":
            in_v = pool.get("taskStatus", "") not in STATUS_DONE_POOL
        else:
            in_v = dl_str <= version_end

        task_id   = str(pool.get("taskID", "") or "")
        php_group = str(pool.get("phpGroup", "") or "")
        detail    = task_details.get(task_id)
        if not isinstance(detail, dict):
            continue

        dept_est_map: Dict[str, float] = {}

        for dept_key, subs in detail.items():
            if not isinstance(subs, list):
                continue
            if dept_key == "devel":
                if php_group in PHPGROUP_DEPT:
                    dept = PHPGROUP_DEPT[php_group]
                else:
                    dept = ""
                    for sub in subs:
                        if not isinstance(sub, dict):
                            continue
                        for field in ("finishedBy", "assignedTo"):
                            person = sub.get(field, "") or ""
                            inferred = php_member_map.get(person, "")
                            if inferred:
                                dept = inferred
                                break
                        if dept:
                            break
            else:
                dept = DEPT_KEY_MAP_NXT.get(dept_key, "")

            if dept not in REPORT_DEPTS:
                continue

            non_deleted = [s for s in subs if isinstance(s, dict) and s.get("deleted", "0") != "1"]
            if not non_deleted:
                continue
            if all(s.get("status", "") == "cancel" for s in non_deleted):
                continue

            est = sum(float(s.get("estimate", 0) or 0) for s in non_deleted)
            dept_est_map[dept] = dept_est_map.get(dept, 0.0) + est

        for dept, est in dept_est_map.items():
            dept_workload[dept]["tasks"]    += 1
            dept_workload[dept]["estimate"] += est
            if in_v:
                dept_workload[dept]["tasks_in_v"]    += 1
                dept_workload[dept]["estimate_in_v"] += est

    return {
        "total":          total,
        "ordered":        ordered,
        "dept_workload":  dept_workload,
        "unordered_rows": unordered_rows,
    }


# ════════════════════════════════════════════════════════════════
#  ★ 新增：JSON 数据构建（供 Claude Code Skill 使用）
# ════════════════════════════════════════════════════════════════

def build_json_data(
    mode: str,
    curr_vinfo: dict,
    next_vinfo: Optional[dict],
    curr_data: dict,
    next_data: Optional[dict],
    bug_list: List[dict],
    today: date,
    weekday: int,
) -> dict:
    """
    将所有数据整理为结构化 JSON，交给大模型理解分析。
    不做任何格式渲染，保留原始数值，让模型自行推理。
    """
    pools        = curr_data["pools"]
    task_details = curr_data["task_details"]
    pms          = curr_data["pms"]
    v_end        = curr_vinfo["end"]

    # 需求总览
    total  = len(pools)
    done_n = sum(1 for p in pools if p.get("taskStatus") in STATUS_DONE)
    test_n = sum(1 for p in pools if p.get("taskStatus") in STATUS_TESTING)
    dev_n  = sum(1 for p in pools if p.get("taskStatus") in STATUS_DEV)
    wait_n = total - done_n - test_n - dev_n

    # 部门进度
    dept_stats = calc_dept_stats(pools, task_details, v_end)
    dept_stats_list = []
    for dname in REPORT_DEPTS:
        s        = dept_stats[dname]
        left     = s["total_left"]
        consumed = s["total_consumed"]
        total_wh = consumed + left
        pct      = int(consumed / total_wh * 100) if total_wh > 0 else 0
        dept_stats_list.append({
            "dept":                  dname,
            "remaining_tasks_label": s["remaining_label"],
            "remaining_hours":       round(left),
            "progress_pct":          pct,
        })

    # 当前版本数据
    current_version = {
        "name":          curr_vinfo["name"],
        "id":            curr_vinfo["id"],
        "end":           curr_vinfo["end"],
        "remaining_days": curr_vinfo["remaining"],
        "is_release_day": curr_vinfo["remaining"] == 0,
        "mode":          mode,
        "summary": {
            "total":       total,
            "done":        done_n,
            "testing":     test_n,
            "dev":         dev_n,
            "not_started": wait_n,
        },
        "dept_stats":      dept_stats_list,
        "delay_rows":      build_delay_rows(pools, task_details),
        "not_test_rows":   build_not_test_rows(pools, task_details, v_end),
        "test_focus_rows": build_test_focus_rows(pools, bug_list),
        "online_bugs":     build_online_bug_rows(bug_list),
    }

    # 下一版本数据
    next_version = None
    if next_vinfo and next_data:
        nd_pools        = next_data["pools"]
        nd_task_details = next_data["task_details"]
        nd_pms          = next_data["pms"]
        nd_users        = next_data.get("users", {})
        nd_v_end        = next_vinfo["end"]
        php_member_map  = build_php_member_map(nd_users)

        nv = build_next_version_data(nd_pools, nd_task_details, nd_pms, nd_v_end, php_member_map)

        dept_workload_list = []
        for dept in REPORT_DEPTS:
            dw = nv["dept_workload"][dept]
            dept_workload_list.append({
                "dept":             dept,
                "tasks_total":      dw["tasks"],
                "hours_total":      round(dw["estimate"]),
                "tasks_in_version": dw["tasks_in_v"],
                "hours_in_version": round(dw["estimate_in_v"]),
            })

        next_version = {
            "name":           next_vinfo["name"],
            "id":             next_vinfo["id"],
            "end":            next_vinfo["end"],
            "remaining_days": next_vinfo["remaining"],
            "summary": {
                "total":     nv["total"],
                "ordered":   nv["ordered"],
                "unordered": nv["total"] - nv["ordered"],
            },
            "dept_workload":  dept_workload_list,
            "unordered_rows": nv["unordered_rows"],
        }

    return {
        "generated_at":    datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "date":            today.isoformat(),
        "weekday":         WEEKDAY_CN[weekday],
        "current_version": current_version,
        "next_version":    next_version,
    }


# ════════════════════════════════════════════════════════════════
#  Markdown 渲染（原有逻辑保留）
# ════════════════════════════════════════════════════════════════

def tbl(headers: List[str], rows: List[List]) -> str:
    if not rows:
        return ""
    h = "| " + " | ".join(headers) + " |"
    s = "| " + " | ".join("---" for _ in headers) + " |"
    r = ["| " + " | ".join(safe(c) for c in row) + " |" for row in rows]
    return "\n".join([h, s] + r) + "\n"


def get_report_mode(weekday: int) -> str:
    return {
        0: "B_MON", 1: "B_TUE", 2: "RELEASE",
        3: "A", 4: "A", 5: "AB", 6: "SKIP",
    }.get(weekday, "A")


def make_title(today: date, weekday: int) -> str:
    return f"平台项目每日报告 · {today.month}月{today.day}日（{WEEKDAY_CN[weekday]}）"


def render_curr_version(
    pools, task_details, bug_list, pms, curr_vinfo, mode,
) -> List[str]:
    v_end     = curr_vinfo["end"]
    remaining = curr_vinfo["remaining"]

    total   = len(pools)
    done_n  = sum(1 for p in pools if p.get("taskStatus") in STATUS_DONE)
    test_n  = sum(1 for p in pools if p.get("taskStatus") in STATUS_TESTING)
    dev_n   = sum(1 for p in pools if p.get("taskStatus") in STATUS_DEV)
    wait_n  = total - done_n - test_n - dev_n

    dist = f"距发布 **{remaining} 天**" if remaining > 0 else "**今日发布**"

    md: List[str] = []
    md.append(f"**当前版本 {curr_vinfo['name']}** · {dist}\n")
    md.append(
        f"需求总览（版本交付）：共 {total} 项 · "
        f"已完成 {done_n} · 测试中 {test_n} · 开发中 {dev_n} · 未开始 {wait_n}\n"
    )

    dept_stats = calc_dept_stats(pools, task_details, v_end)
    dept_rows  = []
    for dname in REPORT_DEPTS:
        s        = dept_stats[dname]
        left     = s["total_left"]
        consumed = s["total_consumed"]
        total_wh = consumed + left
        pct      = f"{int(consumed / total_wh * 100)}%" if total_wh > 0 else "—"
        dept_rows.append([dname, s["remaining_label"], f"{left:.0f}h", pct])
    md.append(tbl(["部门", "剩余任务", "剩余工时", "总进度（参照工时）"], dept_rows))
    md.append("\n---\n")

    delay_rows = build_delay_rows(pools, task_details)
    if delay_rows:
        md.append(f"**延期情况（{len(delay_rows)}）**\n")
        md.append(tbl(
            ["需求名", "类型", "部门", "截止时间", "超期天数"],
            [[r["req_name"], r["category"], r["dept"], r["deadline"],
              f"超期 {r['overdue_days']} 天"]
             for r in delay_rows]
        ))

    not_test = build_not_test_rows(pools, task_details, v_end)
    nt_n = len(not_test)
    if nt_n > 0 or mode in ("AB", "B_MON", "B_TUE", "RELEASE"):
        md.append(f"\n**未到测试 · 临期（{nt_n}）**\n")
        if not not_test:
            md.append("> 无。\n")
        else:
            md.append(tbl(
                ["需求名", "类型", "部门", "截止日", "进度", "延期"],
                [[r["name"], r["category"], r["blocked_depts"],
                  r["deadline"], f"{r['progress']}%", r["delayed"]]
                 for r in not_test]
            ))

    test_rows = build_test_focus_rows(pools, bug_list)
    tf_n = len(test_rows)
    if tf_n > 0 or mode in ("AB", "B_MON", "B_TUE", "RELEASE"):
        md.append(f"\n**测试关注（{tf_n}）**\n")
        if not test_rows:
            md.append("> 测试中需求均无未关闭 Bug。\n")
        else:
            md.append(tbl(
                ["需求名", "类型", "未关闭Bug"],
                [[r["name"], r["category"], str(r["active_bugs"])] for r in test_rows]
            ))

    online_bugs = build_online_bug_rows(bug_list)
    ob_n = len(online_bugs)
    if ob_n > 0:
        md.append(f"\n**线上Bug（{ob_n}）**\n")
        md.append(tbl(
            ["Bug标题", "截止时间"],
            [[r["title"], r["deadline"]] for r in online_bugs]
        ))

    return md


def render_next_version(next_data: dict, next_vinfo: dict) -> List[str]:
    pools        = next_data["pools"]
    task_details = next_data["task_details"]
    pms          = next_data["pms"]
    users        = next_data.get("users", {})
    v_end        = next_vinfo["end"]

    php_member_map = build_php_member_map(users)
    nv = build_next_version_data(pools, task_details, pms, v_end, php_member_map)
    not_ordered = nv["total"] - nv["ordered"]

    md: List[str] = []
    md.append(f"**下一版本 {next_vinfo['name']}**\n")
    md.append(
        f"需求总览：共 {nv['total']} 项 · "
        f"已下单 {nv['ordered']} · 未下单 {not_ordered}\n"
    )

    md.append("\n**工时总览**\n")
    wl_rows = []
    for dept in REPORT_DEPTS:
        dw = nv["dept_workload"][dept]
        wl_rows.append([
            dept,
            str(dw["tasks"]),
            f"{dw['estimate']:.0f}h",
            str(dw["tasks_in_v"]),
            f"{dw['estimate_in_v']:.0f}h",
        ])
    md.append(tbl(
        ["部门", "任务数", "预估工时", "任务数（版本交付）", "预估工时（版本交付）"],
        wl_rows
    ))

    ur_n = len(nv["unordered_rows"])
    md.append(f"\n**未下单需求（{ur_n}）**\n")
    if not nv["unordered_rows"]:
        md.append("> 无。\n")
    else:
        md.append(tbl(
            ["需求名", "类型", "PM", "说明"],
            [[r["name"], r["category"], r["pm"], r["desc"]]
             for r in nv["unordered_rows"]]
        ))

    return md


def build_markdown_report(
    mode, curr_vinfo, next_vinfo, curr_data, next_data, bug_list, today, weekday,
) -> str:
    pools        = curr_data["pools"]
    task_details = curr_data["task_details"]
    pms          = curr_data["pms"]
    v_end        = curr_vinfo["end"]

    title = make_title(today, weekday)
    md: List[str] = [f"# {title}\n"]

    if mode == "RELEASE":
        done_n      = sum(1 for p in pools if p.get("taskStatus") in STATUS_DONE)
        not_test    = build_not_test_rows(pools, task_details, v_end)
        test_rows   = build_test_focus_rows(pools, bug_list)
        online_bugs = build_online_bug_rows(bug_list)
        env_issues  = [
            p for p in pools
            if p.get("env") == "require" and p.get("taskStatus") not in STATUS_DONE
        ]

        md.append(f"**{curr_vinfo['name']}** · 发布日\n")
        md.append("---\n")
        md.append("## 发布核查清单\n")
        md.append(f"**可直接发布**：{done_n} 项\n")

        nt_n = len(not_test)
        md.append(f"\n**未到测试任务（{nt_n}）**\n")
        if not not_test:
            md.append("> 无。\n")
        else:
            md.append(tbl(
                ["需求名", "类型", "部门", "截止日", "进度", "延期"],
                [[r["name"], r["category"], r["blocked_depts"],
                  r["deadline"], f"{r['progress']}%", r["delayed"]]
                 for r in not_test]
            ))

        tf_n = len(test_rows)
        md.append(f"\n**测试关注（{tf_n}）**\n")
        if not test_rows:
            md.append("> 无未关闭 Bug。\n")
        else:
            md.append(tbl(
                ["需求名", "类型", "未关闭Bug"],
                [[r["name"], r["category"], str(r["active_bugs"])] for r in test_rows]
            ))

        if env_issues:
            md.append(f"\n**环境未合并（{len(env_issues)}）**\n")
            md.append(tbl(
                ["需求名", "类型", "PM"],
                [[safe(p.get("title", "")), safe(get_category(p)), safe(get_pm_name(p, pms))]
                 for p in env_issues]
            ))

        ob_n = len(online_bugs)
        if ob_n > 0:
            md.append(f"\n**线上Bug（{ob_n}）**\n")
            md.append(tbl(
                ["Bug标题", "截止时间"],
                [[r["title"], r["deadline"]] for r in online_bugs]
            ))

        if next_vinfo and next_data:
            md.append("\n---\n")
            md.extend(render_next_version(next_data, next_vinfo))

        return "\n".join(md)

    md.extend(render_curr_version(pools, task_details, bug_list, pms, curr_vinfo, mode))

    if next_vinfo and next_data:
        md.append("\n---\n")
        md.extend(render_next_version(next_data, next_vinfo))

    return "\n".join(md)


# ════════════════════════════════════════════════════════════════
#  主流程
# ════════════════════════════════════════════════════════════════

def get_output_dir() -> Path:
    base = Path(OUTPUT_DIR).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    return base


def run(output_mode: str = "markdown"):
    today   = date.today()
    weekday = today.weekday()
    mode    = get_report_mode(weekday)

    if mode == "SKIP":
        if output_mode == "json":
            print(json.dumps({"error": "今日周日，不生成报告"}, ensure_ascii=False))
        else:
            log.info("今日周日，跳过。")
        return

    log.info("")
    log.info("══════════════════════════════════════════════════════")
    log.info("  %s  模式=%s  输出=%s", make_title(today, weekday), mode, output_mode)
    log.info("══════════════════════════════════════════════════════")

    session, _ = login()
    versions   = resolve_versions(session)
    curr_vinfo = versions["curr"]
    next_vinfo = versions["next"]

    log.info("▶ 抓取数据…")
    curr_data = fetch_version_pools(session, curr_vinfo["id"], curr_vinfo["name"])

    next_data = None
    if next_vinfo and mode != "SKIP":
        next_data = fetch_version_pools(session, next_vinfo["id"], next_vinfo["name"])

    bug_list = fetch_online_bugs(session, curr_vinfo["id"])

    log.info("▶ 生成报告（模式=%s）…", output_mode)

    # ── JSON 输出模式：打印到 stdout，供 Claude Code 消费 ──
    if output_mode == "json":
        result = build_json_data(
            mode=mode,
            curr_vinfo=curr_vinfo,
            next_vinfo=next_vinfo,
            curr_data=curr_data,
            next_data=next_data,
            bug_list=bug_list,
            today=today,
            weekday=weekday,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # ── Markdown 输出模式：写入文件 + 发送邮件 ──
    report_md = build_markdown_report(
        mode=mode,
        curr_vinfo=curr_vinfo,
        next_vinfo=next_vinfo,
        curr_data=curr_data,
        next_data=next_data,
        bug_list=bug_list,
        today=today,
        weekday=weekday,
    )

    out_dir = get_output_dir()
    ts       = datetime.now().strftime("%Y-%m-%d_%H-%M")
    data_dir = out_dir / "data" / ts
    data_dir.mkdir(parents=True, exist_ok=True)

    title    = make_title(today, weekday)
    out_path = out_dir / f"{title}.md"
    out_path.write_text(report_md, encoding="utf-8")

    log.info("")
    log.info("══════════════════════════════════════════════════════")
    log.info("  ✅ 完成！")
    log.info("  📄 报告 → %s", out_path)
    log.info("══════════════════════════════════════════════════════")
    log.info("")


# ════════════════════════════════════════════════════════════════
#  入口
# ════════════════════════════════════════════════════════════════

def main():
    global _CLI_ACCOUNT, _CLI_PASSWORD

    parser = argparse.ArgumentParser(
        description="平台项目每日日报生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python daily_report.py setup                              # 首次配置账号密码
  python daily_report.py --output json                      # 输出 JSON
  python daily_report.py --account xxx --password xxx       # 直接传入账号密码
  python daily_report.py                                    # 生成 Markdown 报告
        """,
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["setup"],
        help="setup：交互式配置账号密码（首次使用）",
    )
    parser.add_argument(
        "--output",
        choices=["json", "markdown"],
        default="markdown",
        help="输出格式：json 或 markdown（默认）",
    )
    parser.add_argument("--account",  default="", help="禅道账号")
    parser.add_argument("--password", default="", help="禅道密码")
    args = parser.parse_args()

    _CLI_ACCOUNT  = args.account
    _CLI_PASSWORD = args.password

    if args.command == "setup":
        run_setup()
        return

    run(output_mode=args.output)


if __name__ == "__main__":
    main()
