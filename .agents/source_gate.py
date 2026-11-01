#!/usr/bin/env python3
"""选型门禁的公共底座：阈值、数据结构、纯解析、网络与包工具。

检查项分两处：
    source_gate_spec.py     —— A 组（成熟的项目节）+ C 组（对话文档批次）
    source_gate_delivery.py —— B 组（任务卡与交付物证）

单独跑 spec 侧：
    .venv/bin/python .agents/source_gate.py --spec specs/<日期>-<短名>.spec.md

本文件是全部阈值的单一事实源；文档引用本文件路径，不重抄数字。
网络抖动重试有限次（见 `RETRY`），GitHub 的 4xx 真实答复不重试；最终仍失败、
缺依赖一律 fail closed。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - 环境缺依赖
    yaml = None

# ---- 阈值：单一事实源。改行为只改这里。 ----
STAR_MIN = 1000
STAR_TOLERANCE = 5.0  # star 是实时数，允许的漂移百分比；超出即判编造
FRESH_MONTHS = 3
MIN_BATCH = 3
MAX_BATCH = 4
SECTION = "成熟的项目"
VERDICTS = ("采用", "不采用")
BATCH_VERDICTS = ("保留", "不要", "改造", "自造")
REJECT_REASONS = ("停更或归档", "能力不匹配", "依赖过重")
LANG_EXCUSE = "语言不同"
CANDIDATE_KEYS = ("repo", "star", "updated", "lang", "pin", "url",
                  "extract", "verdict", "reason")
TIMEOUT = 30
UA = {"User-Agent": "dsh-source-gate"}
RETRY = 3          # 网抖重试次数
RETRY_SLEEP = 1.0  # 重试退避基数（秒），第 n 次等 n × 基数

FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
HEADING = re.compile(rf"^#+\s*{SECTION}\s*$", re.M)


class GateError(Exception):
    """门禁自身跑不动。调用方一律 fail closed。"""


@dataclass
class Result:
    ok: bool = True
    lines: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.lines.append(f"FAIL {msg}")

    def note(self, msg: str) -> None:
        self.lines.append(f"     {msg}")


@dataclass
class Candidate:
    repo: str
    star: int
    updated: str
    lang: str
    pin: str
    url: str
    extract: str
    verdict: str
    reason: str
    release: str = ""


# ---------- 纯函数 ----------

def months_ago(today: date, months: int) -> date:
    total = today.year * 12 + (today.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(today.day, _days_in_month(year, month)))


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(str(text).strip()[:10])
    except ValueError:
        return None


def is_fresh(cand: Candidate, cutoff: date) -> bool:
    """最近 FRESH_MONTHS 个月内有源码更新，或有正式版本发布。二者取或。"""
    updated = parse_date(cand.updated)
    if updated is not None and updated >= cutoff:
        return True
    release = str(cand.release or "")
    return "@" in release and (parse_date(release.split("@", 1)[1]) or date.min) >= cutoff


def split_extract(extract: str) -> tuple[str, int, int]:
    """`路径:起-止` 或 `路径:行` → (路径, 起, 止)。"""
    text = str(extract).strip()
    if ":" not in text:
        raise GateError(f"extract `{extract}` 不是 `路径:行区间` 形式")
    path, _, span = text.rpartition(":")
    if not path:
        raise GateError(f"extract `{extract}` 缺路径")
    span = span.strip()
    if "-" in span:
        left, _, right = span.partition("-")
        try:
            start, end = int(left), int(right)
        except ValueError as exc:
            raise GateError(f"extract `{extract}` 的行号不是整数") from exc
    else:
        try:
            start = end = int(span)
        except ValueError as exc:
            raise GateError(f"extract `{extract}` 的行号不是整数") from exc
    if start < 1 or end < start:
        raise GateError(f"extract `{extract}` 的行区间非法")
    return path, start, end


def parse_sources(spec_text: str) -> list[Candidate]:
    if yaml is None:
        raise GateError("缺 PyYAML，跑 .venv/bin/python -m pip install pyyaml")
    heading = HEADING.search(spec_text)
    if heading is None:
        raise GateError(f"spec 里没有「{SECTION}」节")
    block = FENCE.search(spec_text, heading.end())
    if block is None:
        raise GateError(f"「{SECTION}」节后面没有 YAML 代码块")
    data = yaml.safe_load(block.group(1))
    if not isinstance(data, list) or not data:
        raise GateError(f"「{SECTION}」节不是非空列表")
    out: list[Candidate] = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise GateError(f"第 {index} 条候选不是键值对")
        missing = [k for k in CANDIDATE_KEYS if k not in item]
        if missing:
            raise GateError(f"第 {index} 条候选缺字段：{'、'.join(missing)}")
        keep = {k: v for k, v in item.items() if k in Candidate.__dataclass_fields__}
        out.append(Candidate(**keep))
    return out


# ---------- 网络与包：可注入，便于离线测试 ----------

def _real_answer(text: str) -> bool:
    """带 `HTTP <码>` 的是 GitHub 的真实答复，不是网络抖动，不该重试。"""
    return "HTTP " in text


def gh_json(path: str) -> dict:
    last = f"gh api {path} 跑不动"
    for attempt in range(1, RETRY + 1):
        try:
            run = subprocess.run(["gh", "api", path], capture_output=True,
                                 text=True, timeout=TIMEOUT * 2)
        except (OSError, subprocess.TimeoutExpired) as exc:
            last = f"跑不动 gh api {path}：{exc}"
        else:
            if run.returncode == 0:
                try:
                    return json.loads(run.stdout)
                except ValueError as exc:
                    raise GateError(f"gh api {path} 返回的不是 JSON") from exc
            last = f"gh api {path} 失败：{run.stderr.strip()[:200]}"
            if _real_answer(last):
                break
        if attempt < RETRY:
            time.sleep(RETRY_SLEEP * attempt)
    raise GateError(last)


def fetch(url: str, dest: Path) -> Path:
    request = urllib.request.Request(url, headers=UA)
    last = f"下载失败 {url}：未知错误"
    for attempt in range(1, RETRY + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT * 8) as response:
                dest.write_bytes(response.read())
            return dest
        except Exception as exc:  # noqa: BLE001 - 任何下载失败都 fail closed
            last = f"下载失败 {url}：{exc}"
        if attempt < RETRY:
            time.sleep(RETRY_SLEEP * attempt)
    raise GateError(last)


def unpack(blob: Path, dest: Path) -> Path:
    """解包，返回顶层目录。包坏了也走 GateError——fail closed 不能漏。"""
    try:
        with tarfile.open(blob, "r:gz") as tar:
            tar.extractall(dest, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise GateError(f"包解不开（不是 gzip/tar？）：{exc}") from exc
    tops = [p for p in sorted(dest.iterdir()) if p.is_dir()]
    if len(tops) != 1:
        raise GateError(f"包结构异常：顶层目录 {len(tops)} 个")
    return tops[0]


def digest(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return out


def parse_cli(argv: list[str], prog: str) -> tuple[argparse.Namespace | None, str]:
    """三个入口共用的参数解析——用标准库 argparse，不手搓。"""
    parser = argparse.ArgumentParser(prog=prog, add_help=False)
    parser.add_argument("module", nargs="?", default=None)
    parser.add_argument("--spec", default=None)
    try:
        return parser.parse_args(argv), ""
    except SystemExit:
        return None, "参数不合法"


def main(argv: list[str]) -> int:
    ns, error = parse_cli(argv, "source_gate.py")
    if ns is None or not ns.spec:
        print("用法：source_gate.py --spec <spec 路径>", file=sys.stderr)
        if error:
            print(error, file=sys.stderr)
        print("SOURCE FAIL 用法错误")
        return 1
    from source_gate_spec import check_batches, check_spec

    spec = Path(ns.spec)
    stem = spec.name.removesuffix(".spec.md")
    result = check_spec(str(spec))
    batch = check_batches(str(spec.with_name(f"{stem}.dialogue.md")))
    result.ok = result.ok and batch.ok
    result.lines.extend(batch.lines)
    for line in result.lines:
        print(line)
    print("SOURCE OK" if result.ok else "SOURCE FAIL")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
