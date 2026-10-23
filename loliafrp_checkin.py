#!/usr/bin/env python3
"""
Lolia FRP 签到脚本
用法: python loliafrp_checkin.py
环境变量: LOLIAFRP_ACCESS_KEY (JWT Token)
"""
import os
import urllib.request
import urllib.error
import json
import sys
from datetime import datetime

# ============ 配置区域 ============
# 你的 JWT Token
TOKEN = os.getenv("LOLIAFRP_ACCESS_KEY")

API_BASE = "https://api.lolia.link/api/v1"
# ==============================


def api_request(method, path, data=None):
    """发送 API 请求，始终返回 (status|None, dict)"""
    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "lolia-checkin/1.0",
    }

    req_data = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode()
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

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{'='*50}")
    print(f"  Lolia FRP 签到")
    print(f"  时间: {now}")
    print(f"{'='*50}")

    # 1. 获取用户信息
    print("\n[1/2] 获取用户信息...")
    status, data = api_request("GET", "/user/info")
    if status == 200 and data.get("code") == 200:
        info = data["data"]
        print(f"  用户: {info.get('username', 'unknown')}")
        print(f"  今日已签到: {'是' if info.get('today_checked') else '否'}")
        print(f"  流量已用: {info.get('traffic_used', 0) / 1024 / 1024 / 1024:.2f} GB / {info.get('traffic_limit', 0) / 1024 / 1024 / 1024:.2f} GB")
    else:
        print(f"  获取用户信息失败: {data}")

    # 2. 执行签到
    print("\n[2/2] 执行签到...")
    status, data = api_request("POST", "/user/checkin")

    if status is None:
        print(f"  网络错误: {data.get('msg', 'unknown')}")
        return 1

    code = data.get("code", status)
    msg = data.get("msg", "")
    result_data = data.get("data", {})

    if code == 200:
        traffic = result_data.get("traffic_bytes", result_data.get("traffic_gb", 0))
        if "traffic_gb" in result_data:
            traffic = result_data["traffic_gb"] * 1024 * 1024 * 1024
        print(f"  [OK] 签到成功！")
        print(f"  获得流量: {result_data.get('traffic_gb', '?')} GB")
    elif code == 400:
        print(f"  [WARN] {msg}")
        if "traffic_bytes" in result_data:
            print(f"  今日获得流量: {result_data.get('traffic_gb', '?')} GB")
    else:
        print(f"  [FAIL] 签到失败: {msg}")

    print(f"\n{'='*50}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
