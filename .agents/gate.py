#!/usr/bin/env python3
"""项目门禁：选型证据、单份 .py 行数（tests/ 除外）、后端测试覆盖率。

用法：
    python3 .agents/gate.py <模块名>/ --spec <spec 路径>
    python3 .agents/gate.py --spec <spec 路径>     # spec 定稿时，只跑选型

输出最后一行：GATE PASS / GATE FAIL。退出码 0 / 1。
覆盖率口径：语句 + 分支合计，低于 95% 判 FAIL；tests/ 自身不计入。
选型的阈值与检查项在 source_gate.py 与 source_gate_delivery.py——本文件不重抄。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_LINES = 300
MIN_COVER = 95.0
TIMEOUT = 600
SKIP_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".tox",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "site-packages",
    # 上游快照必须与 pin 逐字相同，一个字都不能改——不受本项目行数纪律约束
    "第三方",
}
COVERAGE_CONFIG = """[run]
branch = True
data_file = {data_file}
omit =
    */tests/*
[report]
precision = 1
"""


def py_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*.py")
        if not any(part in SKIP_DIRS for part in p.relative_to(root).parts)
    )


def line_count(path: Path) -> tuple[int | None, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, str(exc)
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0), ""


def check_lines(module: Path) -> tuple[bool, str, list[str]]:
    tests = module / "后端代码" / "tests"
    files = [p for p in py_files(module) if tests not in p.parents]
    detail: list[str] = []
    for path in files:
        count, error = line_count(path)
        rel = path.relative_to(module)
        if count is None:
            detail.append(f"  {rel}: 读不了（{error}）")
        elif count > MAX_LINES:
            detail.append(f"  {rel}: {count} 行（上限 {MAX_LINES}）")
    return not detail, f"{len(files)} 个文件（tests/ 不计）", detail


def coverage_env_ok() -> bool:
    probe = subprocess.run(
        [sys.executable, "-c", "import pytest, pytest_cov"],
        capture_output=True,
    )
    return probe.returncode == 0


def check_coverage(module: Path) -> tuple[bool, str, list[str]]:
    src = module / "后端代码"
    tests = src / "tests"
    if not src.is_dir():
        return False, "没有 后端代码/", []
    if not tests.is_dir():
        return False, "没有 后端代码/tests/", []
    if not coverage_env_ok():
        return False, "环境缺 pytest 或 pytest-cov", []

    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "coveragerc"
        config.write_text(
            COVERAGE_CONFIG.format(data_file=Path(tmp) / ".coverage"), encoding="utf-8"
        )
        report = Path(tmp) / "cov.json"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            str(tests),
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            f"--cov={src}",
            f"--cov-config={config}",
            f"--cov-report=json:{report}",
        ]
        try:
            run = subprocess.run(
                cmd, capture_output=True, text=True, cwd=module, timeout=TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return False, f"测试超过 {TIMEOUT} 秒", []

        out = run.stdout + run.stderr
        if not report.exists():
            errors = [l for l in out.splitlines() if l.startswith("E ")]
            detail = errors[:5] or out.strip().splitlines()[-5:]
            return False, "测试收集失败", detail

        try:
            data = json.loads(report.read_text(encoding="utf-8"))
            raw = float(data["totals"]["percent_covered"])
            measured = {Path(module, name).resolve() for name in data["files"]}
        except (ValueError, KeyError, TypeError):
            return False, "覆盖率报告读不了", []

        if run.returncode == 5:
            return False, "tests/ 里没有测试", []
        if run.returncode != 0:
            summary = [l for l in out.splitlines() if " failed" in l or " error" in l]
            return False, f"测试未通过（覆盖率 {raw:.1f}%）", summary[-3:]

        if data["meta"].get("branch_coverage") is not True:
            return False, "分支覆盖没有启用", []
        if data["totals"]["num_statements"] == 0:
            return False, "没有可测代码", []

        expected = {
            p.resolve() for p in py_files(src) if tests not in p.parents
        }
        missing = sorted(expected - measured)
        if missing:
            detail = [f"  {p.relative_to(module)}: 没有纳入测量" for p in missing]
            return False, "有文件没被覆盖率收集到", detail

        if raw < MIN_COVER:
            detail = [
                f"  {name}: "
                f"{f['summary']['missing_lines']} 行 / "
                f"{f['summary']['missing_branches']} 个分支未覆盖"
                for name, f in data["files"].items()
                if f["summary"]["missing_lines"] or f["summary"]["missing_branches"]
            ]
            return False, f"{raw:.1f}% < {MIN_COVER}%", detail

        return True, f"{raw:.1f}%", []


def parse_argv(argv: list[str]) -> tuple[str | None, str | None, str]:
    """参数解析交给标准库 argparse——不手搓。"""
    from source_gate import parse_cli

    ns, error = parse_cli(argv, "gate.py")
    if ns is None:
        return None, None, error
    return ns.module, ns.spec, ""


def run_source(module: str | None, spec: str | None):
    """A 组（spec 定稿时）+ C 组（批次）+ B 组（交付物证）。"""
    if spec is None:
        return None
    from source_gate import Result
    from source_gate_spec import check_batches, check_spec

    spec_path = Path(spec)
    result: Result = check_spec(str(spec_path))
    stem = spec_path.name.removesuffix(".spec.md")
    batch = check_batches(str(spec_path.with_name(f"{stem}.dialogue.md")))
    result.ok = result.ok and batch.ok
    result.lines.extend(batch.lines)

    if module is not None:
        from source_gate_delivery import check_delivery

        delivery = check_delivery(module, str(spec_path))
        result.ok = result.ok and delivery.ok
        result.lines.extend(delivery.lines)
    return result


def main() -> int:
    module_arg, spec, error = parse_argv(sys.argv[1:])
    usage = (
        "用法：python3 .agents/gate.py <模块名>/ --spec <spec 路径>\n"
        "      python3 .agents/gate.py --spec <spec 路径>   # spec 定稿时只跑选型"
    )
    if error or (module_arg is None and spec is None):
        print(usage, file=sys.stderr)
        if error:
            print(error, file=sys.stderr)
        print("GATE FAIL 用法错误")
        return 1
    if module_arg is not None and spec is None:
        print(usage, file=sys.stderr)
        print("门禁必须带 --spec：选型证据是放行条件", file=sys.stderr)
        print("GATE FAIL 缺 --spec")
        return 1

    module: Path | None = None
    if module_arg is not None:
        module = Path(module_arg).resolve()
        if not module.is_dir():
            print(f"没有这个目录：{module}", file=sys.stderr)
            print("GATE FAIL 目录不存在")
            return 1

    source = run_source(module_arg, spec)
    for line in source.lines:
        print(line)
    print(f"SOURCE {'OK' if source.ok else 'FAIL'}")
    if module is None:
        print("GATE PASS" if source.ok else "GATE FAIL")
        return 0 if source.ok else 1

    lines_ok, lines_msg, lines_detail = check_lines(module)
    cov_ok, cov_msg, cov_detail = check_coverage(module)

    print(f"LINES {'OK' if lines_ok else 'FAIL'} ({lines_msg})")
    for line in lines_detail:
        print(line)
    print(f"COV {'OK' if cov_ok else 'FAIL'} {cov_msg}")
    for line in cov_detail:
        print(line)
    passed = source.ok and lines_ok and cov_ok
    print("GATE PASS" if passed else "GATE FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
