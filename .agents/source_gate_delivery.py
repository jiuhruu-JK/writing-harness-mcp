#!/usr/bin/env python3
"""选型门禁 —— B 组（任务卡与交付物证）。

由 gate.py 调用：
    .venv/bin/python .agents/gate.py <模块名>/ --spec specs/<日期>-<短名>.spec.md

输出若干明细行，末行 SOURCE OK / SOURCE FAIL，退出码 0 / 1。
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import yaml

from source_gate import (VERDICTS, Candidate, GateError, Result, digest, fetch,
                         parse_cli, parse_sources, unpack)
from source_gate_spec import discussed_modules

STATUSES = ("draft", "ready", "dispatched", "done", "rejected")
CARD_KEYS = ("id", "spec", "status", "source", "verdict", "instruction", "boundary")
SOURCE_KEYS = ("repo", "pin", "url", "extract", "lang")
SELF_MADE = "自造"
DISCARDED = "不要"
CARD_VERDICTS = ("改造", SELF_MADE, DISCARDED)
THIRD_PARTY = "第三方"
VERDICT_LINE = re.compile(
    r"^-\s*候选：\s*(?P<repo>\S+)\s*——\s*结论：\s*(?P<call>[^—\s]+)\s*——\s*理由：\s*(?P<reason>.+?)\s*$"
)
CODELOAD = "https://codeload.github.com/{repo}/tar.gz/{pin}"


def repo_dir_name(repo: str) -> str:
    return str(repo).replace("/", "__")


# ---------- B1 卡片格式 ----------

def validate_card(card: dict, stem: str) -> Result:
    """卡自身的自洽性。对账时对**本 spec 的每一张卡**都跑一遍——
    判「不要」的卡没有模块目录，不会有属于它自己的那一轮门禁。"""
    res = Result()
    missing = [k for k in CARD_KEYS if k not in card]
    if missing:
        res.fail(f"B1 任务卡缺字段：{'、'.join(missing)}")
        return res
    if card["status"] not in STATUSES:
        res.fail(f"B1 status `{card['status']}` 不在 {STATUSES}")
    if card["verdict"] not in CARD_VERDICTS:
        res.fail(f"B1 verdict `{card['verdict']}` 不在 {CARD_VERDICTS}")
    # 判「不要」与 rejected 互锁：讨论过但不要的模块照样建卡存档，不删档
    if card["verdict"] == DISCARDED and card["status"] != "rejected":
        res.fail(f"B1 verdict 是「{DISCARDED}」时，status 必须是 rejected")
    if card["status"] == "rejected" and card["verdict"] != DISCARDED:
        res.fail(f"B1 status 是 rejected 时，verdict 必须是「{DISCARDED}」")
    if str(card["id"]) != stem:
        res.fail(f"B1 id `{card['id']}` 与文件名 `{stem}` 不一致")

    boundary = card["boundary"]
    if not isinstance(boundary, list) or not boundary:
        res.fail("B1 boundary 不是非空列表")
    else:
        for index, item in enumerate(boundary, 1):
            if not isinstance(item, str) or ":" not in item:
                res.fail(f"B1 boundary 第 {index} 条不是 `路径: 一行理由`")
                continue
            path, _, reason = item.rpartition(":")
            if not path.strip() or not reason.strip():
                res.fail(f"B1 boundary 第 {index} 条路径或理由为空")
    return res


def check_card(card_path: Path) -> tuple[Result, dict | None]:
    try:
        card = yaml.safe_load(card_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        res = Result()
        res.fail(f"B1 读不了任务卡：{exc}")
        return res, None
    if not isinstance(card, dict):
        res = Result()
        res.fail("B1 任务卡不是键值对")
        return res, None
    return validate_card(card, card_path.stem), card


# ---------- B2 卡片的上游指向已采用的候选 ----------

def check_source(card: dict, adopted: dict[str, Candidate]) -> Result:
    res = Result()
    source = card.get("source")
    verdict = card.get("verdict")
    if verdict == DISCARDED:
        return res  # 判「不要」的模块没有上游可考，只留档
    if verdict == SELF_MADE:
        if source != SELF_MADE:
            res.fail(f"B2 verdict 是「{SELF_MADE}」时，source 必须正好是字符串 `{SELF_MADE}`")
        return res
    if not isinstance(source, dict):
        res.fail(f"B2 verdict 是「改造」时，source 必须是键值对")
        return res
    missing = [k for k in SOURCE_KEYS if k not in source]
    if missing:
        res.fail(f"B2 source 缺字段：{'、'.join(missing)}")
        return res
    repo = str(source["repo"])
    if repo not in adopted:
        res.fail(f"B2 source.repo `{repo}` 不在 spec 里判定为「采用」的候选内")
    return res


# ---------- B3 第三方快照与 pin 逐字一致 ----------

def check_third_party(card: dict, module: Path, *, fetch_fn=None) -> Result:
    res = Result()
    fetch_fn = fetch_fn or fetch
    store = module / THIRD_PARTY
    verdict = card.get("verdict")
    if verdict != "改造":
        if store.exists() and any(store.iterdir()):
            res.fail(f"B3 verdict 是「{verdict}」，{THIRD_PARTY}/ 下却有东西")
        return res

    source = card.get("source")
    if not isinstance(source, dict) or "repo" not in source or "pin" not in source:
        res.fail("B3 拿不到 source.repo / source.pin")
        return res
    snapshot = store / repo_dir_name(str(source["repo"]))
    if not snapshot.is_dir():
        res.fail(f"B3 盘上没有 `{THIRD_PARTY}/{snapshot.name}/`——"
                 f"「我看过了」不算证据，快照必须在盘上")
        return res
    try:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            canon = unpack(
                fetch_fn(CODELOAD.format(repo=source["repo"], pin=source["pin"]),
                         work / "canon.tar.gz"),
                work / "canon")
            left, right = digest(snapshot), digest(canon)
            if left != right:
                res.fail(f"B3 快照与 pin 快照不一致"
                         f"（多 {len(set(left) - set(right))}、"
                         f"少 {len(set(right) - set(left))}、"
                         f"改 {len([k for k in set(left) & set(right) if left[k] != right[k]])}）")
    except GateError as exc:
        res.fail(f"B3 {exc}")
    return res


# ---------- B4 裁决覆盖全部候选 ----------

def check_verdict_file(spec_path: Path, candidates: list[Candidate]) -> Result:
    res = Result()
    verdict_path = spec_path.with_name(
        spec_path.name.removesuffix(".spec.md") + ".verdict.md")
    try:
        text = verdict_path.read_text(encoding="utf-8")
    except OSError as exc:
        res.fail(f"B4 读不了评判裁决 `{verdict_path.name}`：{exc}")
        return res

    ruled: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        match = VERDICT_LINE.match(line)
        if match is None:
            res.fail(f"B4 裁决这条不合格式：{line[:60]}")
            continue
        if match.group("call") not in VERDICTS:
            res.fail(f"B4 候选 `{match.group('repo')}` 的结论 "
                     f"`{match.group('call')}` 不在 {VERDICTS}")
        ruled[match.group("repo")] = match.group("call")

    for cand in candidates:
        if cand.repo not in ruled:
            res.fail(f"B4 候选 `{cand.repo}` 没有被评判过")
    return res


# ---------- B5 对话文档 ↔ 任务卡对账 ----------

def check_reconciliation(spec_path: Path, cards_dir: Path) -> Result:
    """讨论过的每个模块都要有卡；有卡的每个模块都要被讨论过。"""
    res = Result()
    dialogue = spec_path.with_name(
        spec_path.name.removesuffix(".spec.md") + ".dialogue.md")
    try:
        discussed = discussed_modules(str(dialogue))
    except GateError as exc:
        res.fail(f"B5 {exc}")
        return res

    cards: list[str] = []
    if cards_dir.is_dir():
        for path in sorted(cards_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(data, dict) or Path(str(data.get("spec", ""))).name \
                    != spec_path.name:
                continue
            part = validate_card(data, path.stem)
            res.ok = res.ok and part.ok
            res.lines.extend(part.lines)
            cards.append(str(data.get("id", path.stem)))

    missing = [name for name in discussed if name not in cards]
    extra = [name for name in cards if name not in discussed]
    if missing:
        res.fail(f"B5 对话文档讨论过、却没建卡的模块：{missing}")
    if extra:
        res.fail(f"B5 建了卡、对话文档却没讨论过的模块：{extra}")
    if not discussed and not cards:
        res.fail("B5 对话文档一个模块都没讨论，也没建任何卡")
    res.note(f"对账：讨论 {len(discussed)} 个 / 建卡 {len(cards)} 张")
    return res


def check_delivery(module_arg: str, spec_arg: str, *, today=None, api=None,
                   fetch_fn=None) -> Result:
    module = Path(module_arg)
    spec_path = Path(spec_arg)
    res = Result()

    try:
        candidates = parse_sources(spec_path.read_text(encoding="utf-8"))
    except (OSError, GateError) as exc:
        res.fail(f"B0 {exc}")
        return res
    adopted = {c.repo: c for c in candidates if c.verdict == "采用"}

    card_path = Path("tasks") / f"{module.name}.yaml"
    card_res, card = check_card(card_path)
    res.ok = res.ok and card_res.ok
    res.lines.extend(card_res.lines)
    if card is not None:
        for part in (check_source(card, adopted),
                     check_third_party(card, module, fetch_fn=fetch_fn)):
            res.ok = res.ok and part.ok
            res.lines.extend(part.lines)

    verdict_res = check_verdict_file(spec_path, candidates)
    res.ok = res.ok and verdict_res.ok
    res.lines.extend(verdict_res.lines)

    recon = check_reconciliation(spec_path, Path("tasks"))
    res.ok = res.ok and recon.ok
    res.lines.extend(recon.lines)
    return res


def main(argv: list[str]) -> int:
    ns, error = parse_cli(argv, "source_gate_delivery.py")
    if ns is None or not ns.module or not ns.spec:
        print("用法：source_gate_delivery.py <模块名>/ --spec <spec 路径>",
              file=sys.stderr)
        if error:
            print(error, file=sys.stderr)
        print("SOURCE FAIL 用法错误")
        return 1
    result = check_delivery(ns.module, ns.spec)
    for line in result.lines:
        print(line)
    print("SOURCE OK" if result.ok else "SOURCE FAIL")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
