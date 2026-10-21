#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ME Frp（幻缘映射）每日自动签到脚本
==================================

功能：
  1. 用「访问秘钥」查询账号当天是否已签到；
  2. 未签到则自动完成 Cap 人机验证（本地计算，无需手动点击）；
  3. 调用签到接口领取流量，结果直接打印到控制台。

用法：
  python mefrp_sign.py            # 执行签到（已签到会自动跳过）
  python mefrp_sign.py --status   # 只查看今日签到状态
  python mefrp_sign.py --force    # 忽略“今日已签到”状态，再请求一次接口

只使用 Python 标准库，无需安装第三方包。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

# ============================ 配置 ============================
ACCESS_KEY = os.getenv("MEFRP_ACCESS_KEY")  # 从 GitHub Secret 读取访问秘钥
if not ACCESS_KEY:
    raise RuntimeError("未设置环境变量 MEFRP_ACCESS_KEY")
API_BASE = "https://api.mefrp.com/api"
CAPTCHA_BASE = "https://captcha.mefrp.com/2bf50e050d"
TIMEOUT = 30          # 单次请求超时（秒）
MAX_ATTEMPTS = 3      # 签到失败重试次数
# =============================================================


def log(message: str) -> None:
    """输出到控制台。"""
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("utf-8", "replace").decode("utf-8", "replace"))


def request_json(url: str, method: str = "GET", payload=None, auth: bool = False):
    """发送 JSON 请求，返回 (HTTP 状态码, 解析后的 JSON)。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.mefrp.com",
        "Referer": "https://www.mefrp.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
        ),
    }
    if auth:
        headers["Authorization"] = f"Bearer {ACCESS_KEY}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络请求失败：{exc.reason}") from exc

    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"接口返回了非 JSON 内容（HTTP {status}）：{raw[:200]}")


# ------------------------- Cap 人机验证 -------------------------
# ME Frp 使用 Cap.js 的 SHA-256 工作量证明验证：
#   1. POST /challenge 取 token 与参数 {c, s, d}；
#   2. 用 Cap 的确定性随机算法生成 c 组 (salt, target)；
#   3. 找到 nonce，使 SHA-256(salt + nonce) 的十六进制前缀等于 target；
#   4. POST /redeem 提交答案，换取 captchaToken。

def _fnv1a(text: str) -> int:
    value = 2166136261
    for ch in text:
        value ^= ord(ch)
        value = (
            value
            + (value << 1)
            + (value << 4)
            + (value << 7)
            + (value << 8)
            + (value << 24)
        ) & 0xFFFFFFFF
    return value


def _rand_str(seed: str, length: int) -> str:
    """复刻 Cap.js 内置的 xorshift 确定性随机字符串。"""
    state = _fnv1a(seed)
    out = ""
    while len(out) < length:
        state = (state ^ ((state << 13) & 0xFFFFFFFF)) & 0xFFFFFFFF
        state = (state ^ (state >> 17)) & 0xFFFFFFFF
        state = (state ^ ((state << 5) & 0xFFFFFFFF)) & 0xFFFFFFFF
        out += format(state, "08x")
    return out[:length]


def _solve_pow(salt: str, target: str) -> int:
    nonce = 0
    while True:
        digest = hashlib.sha256((salt + str(nonce)).encode("utf-8")).hexdigest()
        if digest.startswith(target):
            return nonce
        nonce += 1


def get_captcha_token() -> str:
    _, challenge_resp = request_json(CAPTCHA_BASE + "/challenge", "POST", {})
    challenge = challenge_resp.get("challenge") or {}
    token = challenge_resp.get("token")
    if not token or "c" not in challenge:
        raise RuntimeError(f"获取验证码挑战失败：{challenge_resp}")

    count = int(challenge["c"])
    salt_len = int(challenge["s"])
    diff = int(challenge["d"])

    solutions = []
    for i in range(1, count + 1):
        salt = _rand_str(f"{token}{i}", salt_len)
        target = _rand_str(f"{token}{i}d", diff)
        solutions.append(_solve_pow(salt, target))

    status, redeem = request_json(
        CAPTCHA_BASE + "/redeem", "POST", {"token": token, "solutions": solutions}
    )
    if status != 200 or not redeem.get("success") or not redeem.get("token"):
        raise RuntimeError(f"验证码兑换失败（HTTP {status}）：{redeem}")
    return redeem["token"]


# ---------------------------- 业务 ----------------------------

def get_user_info():
    status, resp = request_json(API_BASE + "/auth/user/info", auth=True)
    if status != 200 or resp.get("code") != 200:
        raise RuntimeError(f"获取用户信息失败（HTTP {status}）：{resp}")
    return resp["data"]


def do_sign() -> int:
    info = get_user_info()
    name = info.get("username") or "未知用户"
    log(f"账号 {name}（ID {info.get('userId')}）查询成功，今日已签到：{info.get('todaySigned')}")

    if info.get("todaySigned"):
        log("今天已经签到过了，无需重复签到。")
        return 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            log(f"第 {attempt}/{MAX_ATTEMPTS} 次尝试：正在完成人机验证……")
            captcha_token = get_captcha_token()
            log("人机验证通过，正在提交签到……")

            status, resp = request_json(
                API_BASE + "/auth/user/sign",
                "POST",
                {"captchaToken": captcha_token},
                auth=True,
            )
            message = resp.get("message", "") if isinstance(resp, dict) else str(resp)

            if status == 200 and resp.get("code") == 200:
                extra = (resp.get("data") or {}).get("extraTraffic")
                log(f"签到成功：{message}" + (f"（+{extra} GB）" if extra is not None else ""))
                latest = get_user_info()
                log(f"当前剩余流量：{latest.get('traffic')}，签到状态：{latest.get('todaySigned')}")
                return 0

            if "已签到" in message:
                log(f"接口提示今日已签到：{message}")
                return 0

            log(f"签到失败（HTTP {status}）：{message or resp}")
        except Exception as exc:  # noqa: BLE001 - 自动任务需要记录所有异常
            log(f"第 {attempt} 次尝试出错：{exc}")

        if attempt < MAX_ATTEMPTS:
            time.sleep(3)

    log("签到未成功，已达到最大重试次数。")
    return 1


def show_status() -> int:
    info = get_user_info()
    log(
        "账号：{username}（ID {userId}）｜今日已签到：{signed}｜剩余流量：{traffic}".format(
            username=info.get("username"),
            userId=info.get("userId"),
            signed="是" if info.get("todaySigned") else "否",
            traffic=info.get("traffic"),
        )
    )
    return 0


def main() -> int:
    args = {arg.lower() for arg in sys.argv[1:]}
    try:
        if "--status" in args or "-s" in args:
            return show_status()
        if "--force" in args or "-f" in args:
            info = get_user_info()
            if info.get("todaySigned"):
                log("注意：--force 已忽略“今日已签到”状态，将再次请求签到接口。")
            else:
                log("今日尚未签到，开始签到。")
            # 直接走签到流程；接口若提示已签到也会被当作成功。
            return _sign_ignoring_state()
        return do_sign()
    except Exception as exc:  # noqa: BLE001
        log(f"执行失败：{exc}")
        return 1


def _sign_ignoring_state() -> int:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            captcha_token = get_captcha_token()
            status, resp = request_json(
                API_BASE + "/auth/user/sign",
                "POST",
                {"captchaToken": captcha_token},
                auth=True,
            )
            message = resp.get("message", "") if isinstance(resp, dict) else str(resp)
            if status == 200 and resp.get("code") == 200:
                extra = (resp.get("data") or {}).get("extraTraffic")
                log(f"签到成功：{message}" + (f"（+{extra} GB）" if extra is not None else ""))
                return 0
            if "已签到" in message:
                log(f"接口提示今日已签到：{message}")
                return 0
            log(f"签到失败（HTTP {status}）：{message or resp}")
        except Exception as exc:  # noqa: BLE001
            log(f"第 {attempt} 次尝试出错：{exc}")
        if attempt < MAX_ATTEMPTS:
            time.sleep(3)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
