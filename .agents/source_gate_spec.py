#!/usr/bin/env python3
"""选型门禁 —— A 组（成熟的项目节）与 C 组（对话文档批次）。

阈值与公共底座在 source_gate.py。
"""

from __future__ import annotations

import re
import tempfile
from datetime import date
from pathlib import Path

from source_gate import (BATCH_VERDICTS, FRESH_MONTHS, LANG_EXCUSE, MAX_BATCH,
                         MIN_BATCH, REJECT_REASONS, STAR_MIN, STAR_TOLERANCE,
                         VERDICTS, Candidate, GateError, Result, digest, fetch,
                         gh_json, is_fresh, months_ago, parse_date, parse_sources,
                         split_extract, unpack)

ARCHIVE = re.compile(r"/archive/([0-9a-fA-F]{40})\.tar\.gz$")
BATCH = re.compile(r"^【模块批次\s*(\d+)】\s*$", re.M)
ENTRY = re.compile(
    r"^-\s*(?P<name>.+?)\s*——\s*判定：\s*(?P<verdict>[^—\s]+)\s*——\s*理由：\s*(?P<reason>.+?)\s*$"
)


# ---------- A 组：成熟的项目节 ----------

def check_spec(spec_path: str, *, today: date | None = None, api=None,
               fetch_fn=None) -> Result:
    res = Result()
    api = api or gh_json
    fetch_fn = fetch_fn or fetch
    try:
        candidates = parse_sources(Path(spec_path).read_text(encoding="utf-8"))
    except (OSError, GateError) as exc:
        res.fail(f"A0 {exc}")
        return res

    res.note(f"候选 {len(candidates)} 条")
    today = today or date.today()
    cutoff = months_ago(today, FRESH_MONTHS)

    flags = [is_fresh(c, cutoff) for c in candidates]
    if any(flags):
        last_fresh = max(i for i, f in enumerate(flags) if f)
        late = [i + 1 for i, f in enumerate(flags) if not f and i < last_fresh]
        if late:
            res.fail(f"A2 排序：第 {late} 条已过 {FRESH_MONTHS} 个月却排在新候选之前")

    for index, cand in enumerate(candidates, 1):
        tag = f"{index}.{cand.repo}"
        check_verdict(res, cand, tag)
        check_live_facts(res, cand, tag, api, today)
        if cand.verdict == "采用":
            check_pin(res, cand, tag, api, fetch_fn)
    return res


def check_verdict(res: Result, cand: Candidate, tag: str) -> None:
    reason = str(cand.reason).strip()
    if cand.verdict not in VERDICTS:
        res.fail(f"A3 {tag} 判定 `{cand.verdict}` 不在 {VERDICTS}")
        return
    if not reason:
        res.fail(f"A3 {tag} 理由为空")
        return
    if cand.verdict != "不采用":
        return
    if LANG_EXCUSE in reason:
        res.fail(f"A3 {tag} 拿「{LANG_EXCUSE}」当不采用的理由")
    elif not any(word in reason for word in REJECT_REASONS):
        res.fail(f"A3 {tag} 理由不在词表 {REJECT_REASONS} 内")


def check_live_facts(res: Result, cand: Candidate, tag: str, api, today: date) -> None:
    try:
        info = api(f"repos/{cand.repo}")
    except GateError as exc:
        res.fail(f"A1 {tag} {exc}")
        return
    real = info.get("stargazers_count")
    if real is None:
        res.fail(f"A1 {tag} 取不回 star")
        return
    live = int(real)
    recorded = int(cand.star)
    if live <= STAR_MIN:
        res.fail(f"A1 {tag} 实时 star={live} 不过硬门槛（须 > {STAR_MIN}）")
        return
    if recorded < STAR_MIN:
        res.fail(f"A1 {tag} 记录 star={recorded} 不过硬门槛（须 > {STAR_MIN}）")
        return
    # star 是实时数：同一份 spec 隔几分钟跑，真实值就会漂。记录值只查
    # 「偏差是否超出容差」——超了才是编的或张冠李戴，漂了不算。
    if abs(recorded - live) > live * STAR_TOLERANCE / 100.0:
        res.fail(f"A1 {tag} 记录 star={recorded}，实时 star={live}"
                 f"（偏差 {abs(recorded - live) * 100.0 / live:.1f}%"
                 f"，容差 {STAR_TOLERANCE:g}%）")
    check_not_future(res, cand.updated, today, f"A8 {tag} updated")
    if str(cand.release or "").strip():
        _, _, published = str(cand.release).partition("@")
        check_not_future(res, published, today, f"A8 {tag} release")


def check_not_future(res: Result, text: str, today: date, tag: str) -> None:
    """记录的日期不能是未来——未来的「最近更新」一定是编的。"""
    raw = str(text).strip()
    if not raw:
        return
    parsed = parse_date(raw)
    if parsed is None:
        res.fail(f"{tag} `{raw}` 不是 ISO 日期")
    elif parsed > today:
        res.fail(f"{tag} `{raw}` 是未来日期")


def check_pin(res: Result, cand: Candidate, tag: str, api, fetch_fn) -> None:
    match = ARCHIVE.search(str(cand.url).strip())
    if match is None:
        res.fail(f"A6 {tag} url 不是 `…/archive/<40位sha>.tar.gz` 形式")
        return
    if match.group(1) != str(cand.pin).strip():
        res.fail(f"A6 {tag} url 里的 sha 与 pin 字段不一致")
        return
    try:
        commit = api(f"repos/{cand.repo}/commits/{cand.pin}")
    except GateError as exc:
        res.fail(f"A4 {tag} {exc}")
        return
    if commit.get("sha") != str(cand.pin).strip():
        res.fail(f"A4 {tag} pin 取不回同一个提交")
        return
    try:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            mine = unpack(fetch_fn(str(cand.url), work / "mine.tar.gz"), work / "mine")
            canon = unpack(
                fetch_fn(f"https://codeload.github.com/{cand.repo}/tar.gz/{cand.pin}",
                         work / "canon.tar.gz"),
                work / "canon")
            left, right = digest(mine), digest(canon)
            if left != right:
                res.fail(f"A6 {tag} 下载物与 pin 快照不一致"
                         f"（多 {len(set(left) - set(right))}、"
                         f"少 {len(set(right) - set(left))}、"
                         f"改 {len([k for k in set(left) & set(right) if left[k] != right[k]])}）")
                return
            check_extract(res, cand, tag, mine, left)
    except GateError as exc:
        res.fail(f"A6 {tag} {exc}")


def check_extract(res: Result, cand: Candidate, tag: str, root: Path,
                  files: dict[str, str]) -> None:
    try:
        rel, _, end = split_extract(cand.extract)
    except GateError as exc:
        res.fail(f"A7 {tag} {exc}")
        return
    if rel not in files:
        res.fail(f"A7 {tag} extract 的路径 `{rel}` 在快照里不存在")
        return
    total = len((root / rel).read_text(encoding="utf-8", errors="replace").splitlines())
    if end > total:
        res.fail(f"A7 {tag} extract 写到第 {end} 行，快照里 `{rel}` 只有 {total} 行")


# ---------- C 组：对话文档批次 ----------

def check_batches(dialogue_path: str) -> Result:
    res = Result()
    try:
        text = Path(dialogue_path).read_text(encoding="utf-8")
    except OSError as exc:
        res.fail(f"C0 读不了对话文档：{exc}")
        return res

    heads = list(BATCH.finditer(text))
    if not heads:
        res.fail("C1 对话文档里没有【模块批次 N】")
        return res

    for order, head in enumerate(heads):
        end = heads[order + 1].start() if order + 1 < len(heads) else len(text)
        lines = [l.strip() for l in text[head.end():end].splitlines()
                 if l.strip().startswith("-")]
        number = head.group(1)
        # 末批是「剩多少发多少」的那批：不足下限放行，超上限照拒。
        # 故「模块本来就只有 2 个」与「偷懒只发 2 个」靠对账区分（见 B5）。
        is_last = order == len(heads) - 1
        if not is_last and not (MIN_BATCH <= len(lines) <= MAX_BATCH):
            res.fail(f"C1 批次 {number} 有 {len(lines)} 个模块，"
                     f"应为 {MIN_BATCH}～{MAX_BATCH} 个")
        if is_last and len(lines) > MAX_BATCH:
            res.fail(f"C1 末批 {number} 有 {len(lines)} 个模块，超过 {MAX_BATCH} 个")
        for line in lines:
            check_entry(res, line, number)
    res.note(f"批次 {len(heads)} 个")
    return res


def check_entry(res: Result, line: str, number: str) -> None:
    match = ENTRY.match(line)
    if match is None:
        res.fail(f"C2 批次 {number} 这条不合格式：{line[:60]}")
        return
    if match.group("verdict") not in BATCH_VERDICTS:
        res.fail(f"C2 批次 {number} 判定 `{match.group('verdict')}` "
                 f"不在 {BATCH_VERDICTS}")


def discussed_modules(dialogue_path: str) -> list[str]:
    """对话文档里讨论过的模块名，按出现顺序。对账用。"""
    try:
        text = Path(dialogue_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(f"读不了对话文档：{exc}") from exc
    names: list[str] = []
    for line in text.splitlines():
        match = ENTRY.match(line.strip())
        if match is not None:
            names.append(match.group("name").strip())
    return names
