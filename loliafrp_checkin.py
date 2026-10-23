#!/usr/bin/env python3
"""
Lolia FRP 签到脚本
用法: python loliafrp_checkin.py
环境变量: LOLIAFRP_ACCESS_KEY (JWT Token)
"""
import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime

TOKEN = os.getenv("LOLIAFRP_ACCESS_KEY")
API_BASE = "https://api.lolia.link/api/v1"
GB = 1024 ** 3


def api_request(method, path, data=None):
    """发送 API 请求，始终返回 (status|None, dict)"""
    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "lolia-checkin/1.0",
    }
    payload = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status, raw = resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode()
    except Exception as e:
        return None, {"msg": str(e)}

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        body = {"msg": raw[:200]}

    if not isinstance(body, dict):
        body = {"msg": str(body)}
    return status, body


def main():
    if not TOKEN:
        print("[FAIL] 未设置环境变量 LOLIAFRP_ACCESS_KEY")
        return 1

    print("=" * 50)
    print("  Lolia FRP 每日签到")
    print(f"  时间: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 50)

    # 1. 用户信息
    print("\n[1/2] 获取用户信息...")
    status, data = api_request("GET", "/user/info")
    if status == 200 and data.get("code") == 200:
        info = data.get("data") or {}
        print(f"  用户: {info.get('username', 'unknown')}")
        print(f"  今日已签到: {'是' if info.get('today_checked') else '否'}")
        print(f"  流量已用: {info.get('traffic_used', 0) / GB:.2f} GB / "
              f"{info.get('traffic_limit', 0) / GB:.2f} GB")
        if info.get("today_checked"):
            print("\n[2/2] 今日已签到，跳过。")
            print("\n" + "=" * 50)
            return 0
    else:
        print(f"  获取用户信息失败: {data.get('msg', data)}")

    # 2. 签到
    print("\n[2/2] 执行签到...")
    status, data = api_request("POST", "/user/checkin")
    if status is None:
        print(f"  [FAIL] 网络错误: {data.get('msg', 'unknown')}")
        return 1

    code = data.get("code", status)
    msg = data.get("msg", "")
    result = data.get("data") or {}

    if code == 200:
        if "traffic_gb" in result:
            got_gb = result["traffic_gb"]
        elif "traffic_bytes" in result:
            got_gb = result["traffic_bytes"] / GB
        else:
            got_gb = None
        print("  [OK] 签到成功！")
        if got_gb is not None:
            print(f"  获得流量: {got_gb:.2f} GB")
    elif code == 400:
        print(f"  [WARN] {msg or '今日可能已签到'}")
    else:
        print(f"  [FAIL] 签到失败: {msg or data}")
        print("\n" + "=" * 50)
        return 1

    print("\n" + "=" * 50)
    return 0


if __name__ == "__main__":
    sys.exit(main())
