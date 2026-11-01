"""选型门禁的同步测试。全部离线：网络层由 api / fetch_fn 注入。"""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from datetime import date
from pathlib import Path

import pytest
import yaml

import gate as sg_gate
import source_gate as sg
import source_gate_delivery as sgd
import source_gate_spec as sgs

PIN = "a" * 40
REPO = "acme/tool"
SNAPSHOT = {"src/core.py": "l1\nl2\nl3\nl4\nl5\n", "README.md": "hi\n"}
TODAY = date(2026, 10, 31)


def tarball(path: Path, files: dict[str, str], top: str = "proj-abc") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            blob = text.encode()
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
    return path


def api_of(star: int = 5000, sha: str = PIN):
    def api(path: str) -> dict:
        if "/commits/" in path:
            return {"sha": sha}
        return {"stargazers_count": star}
    return api


def fetch_of(files: dict[str, str] | None = None, top: str = "proj-abc"):
    def fetch_fn(url: str, dest: Path) -> Path:
        return tarball(Path(dest), files if files is not None else SNAPSHOT, top)
    return fetch_fn


def fetch_split(mine: dict[str, str], canon: dict[str, str]):
    """两个地址返回不同内容——用来造出「下载物与 pin 快照不一致」。"""
    def fetch_fn(url: str, dest: Path) -> Path:
        return tarball(Path(dest), canon if "codeload" in url else mine)
    return fetch_fn


def spec_body(**over) -> str:
    entry = {
        "repo": REPO, "star": 5000, "updated": "2026-10-01",
        "release": "1.0.0@2026-09-01", "lang": "Python",
        "pin": PIN, "url": f"https://github.com/{REPO}/archive/{PIN}.tar.gz",
        "extract": "src/core.py:1-3", "verdict": "采用", "reason": "覆盖全部要求",
    }
    entry.update(over)
    body = yaml.safe_dump([entry], allow_unicode=True, sort_keys=False)
    return f"## 原话\n\n原始诉求。\n\n## 成熟的项目\n\n```yaml\n{body}```\n"


def write_spec(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "2026-10-31-demo.spec.md"
    path.write_text(text, encoding="utf-8")
    return path


def run_spec(tmp_path: Path, text: str, **kw) -> sg.Result:
    return sgs.check_spec(str(write_spec(tmp_path, text)),
                         today=TODAY, api=api_of(), fetch_fn=fetch_of(), **kw)


# ---------- 纯函数 ----------

@pytest.mark.parametrize("today,expected", [
    (date(2026, 10, 31), date(2026, 7, 31)),
    (date(2026, 5, 31), date(2026, 2, 28)),
    (date(2026, 1, 15), date(2025, 10, 15)),
    (date(2026, 3, 31), date(2025, 12, 31)),
])
def test_months_ago(today, expected):
    assert sg.months_ago(today, 3) == expected


def test_split_extract_range_and_single():
    assert sg.split_extract("a/b.py:10-20") == ("a/b.py", 10, 20)
    assert sg.split_extract("a/b.py:7") == ("a/b.py", 7, 7)


@pytest.mark.parametrize("bad", ["no-colon", "a/b.py:x-y", "a/b.py:5-1", "a/b.py:0", ":1-2"])
def test_split_extract_rejects(bad):
    with pytest.raises(sg.GateError):
        sg.split_extract(bad)


def test_is_fresh_uses_update_or_release():
    def make(updated: str, release: str) -> sg.Candidate:
        return sg.Candidate(repo=REPO, star=5000, updated=updated, lang="Python",
                            pin=PIN, url="u", extract="e", verdict="采用",
                            reason="r", release=release)

    cutoff = sg.months_ago(TODAY, 3)
    assert sg.is_fresh(make("2026-10-01", "1.0@2020-01-01"), cutoff)
    assert sg.is_fresh(make("2020-01-01", "1.0@2026-09-01"), cutoff)
    assert not sg.is_fresh(make("2020-01-01", "1.0@2020-01-01"), cutoff)


# ---------- A 组 ----------

def test_spec_missing_section(tmp_path):
    result = run_spec(tmp_path, "## 原话\n\n没有候选。\n")
    assert not result.ok
    assert "没有「成熟的项目」节" in result.lines[0]


def test_spec_missing_field(tmp_path):
    entry = {"repo": REPO, "star": 5000}
    text = f"## 成熟的项目\n\n```yaml\n{yaml.safe_dump([entry])}```\n"
    result = run_spec(tmp_path, text)
    assert not result.ok
    assert "缺字段" in result.lines[0]


def test_spec_pass(tmp_path):
    assert run_spec(tmp_path, spec_body()).ok


def test_fabricated_star_fails(tmp_path):
    result = sgs.check_spec(str(write_spec(tmp_path, spec_body(star=9999))),
                           today=TODAY, api=api_of(star=5000), fetch_fn=fetch_of())
    assert not result.ok
    assert any("记录 star=9999" in line for line in result.lines)


def test_star_below_threshold_fails(tmp_path):
    result = sgs.check_spec(str(write_spec(tmp_path, spec_body())),
                           today=TODAY, api=api_of(star=1000), fetch_fn=fetch_of())
    assert not result.ok
    assert any("硬门槛" in line for line in result.lines)


def test_star_drift_within_tolerance_passes(tmp_path):
    """star 是实时数：隔几分钟跑，真实值就会漂。漂在容差内不算编造。"""
    result = sgs.check_spec(str(write_spec(tmp_path, spec_body(star=5052))),
                            today=TODAY, api=api_of(star=5054), fetch_fn=fetch_of())
    assert result.ok, result.lines


def test_star_drift_over_tolerance_fails(tmp_path):
    """漂过容差就是编造或张冠李戴。"""
    result = sgs.check_spec(str(write_spec(tmp_path, spec_body(star=5500))),
                            today=TODAY, api=api_of(star=5054), fetch_fn=fetch_of())
    assert not result.ok
    assert any("容差" in line for line in result.lines)


def test_recorded_star_below_threshold_fails(tmp_path):
    """实时过了门槛、记录没过——记录本身错了。"""
    result = sgs.check_spec(str(write_spec(tmp_path, spec_body(star=999))),
                            today=TODAY, api=api_of(star=1050), fetch_fn=fetch_of())
    assert not result.ok
    assert any("记录 star=999" in line for line in result.lines)


# ---------- 网络层：抖动重试，真实答复不重试 ----------

def test_gh_json_retries_flaky_network(monkeypatch):
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return subprocess.CompletedProcess(cmd, 1, "", 'Get "…": EOF')
        return subprocess.CompletedProcess(cmd, 0, '{"a": 1}', "")

    monkeypatch.setattr(sg.subprocess, "run", fake_run)
    monkeypatch.setattr(sg.time, "sleep", lambda _: None)
    assert sg.gh_json("repos/x/y") == {"a": 1}
    assert calls["n"] == 3


def test_gh_json_does_not_retry_real_answer(monkeypatch):
    """GitHub 的 4xx 是真实答复，不是网抖，重试只是白等。"""
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 1, "", "HTTP 404: Not Found")

    monkeypatch.setattr(sg.subprocess, "run", fake_run)
    monkeypatch.setattr(sg.time, "sleep", lambda _: None)
    with pytest.raises(sg.GateError):
        sg.gh_json("repos/x/y")
    assert calls["n"] == 1


def test_gh_json_gives_up_after_retries(monkeypatch):
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 1, "", 'Get "…": EOF')

    monkeypatch.setattr(sg.subprocess, "run", fake_run)
    monkeypatch.setattr(sg.time, "sleep", lambda _: None)
    with pytest.raises(sg.GateError):
        sg.gh_json("repos/x/y")
    assert calls["n"] == sg.RETRY


class _FakeResponse:
    def __init__(self, blob: bytes):
        self._blob = blob

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._blob


def test_fetch_retries_then_succeeds(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("IncompleteRead(30015488 bytes read)")
        return _FakeResponse(b"data")

    monkeypatch.setattr(sg.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sg.time, "sleep", lambda _: None)
    dest = tmp_path / "x.bin"
    assert sg.fetch("http://e/x", dest) == dest
    assert calls["n"] == 3
    assert dest.read_bytes() == b"data"


def test_fetch_gives_up_after_retries(tmp_path, monkeypatch):
    def always_fail(request, timeout):
        raise OSError("boom")

    monkeypatch.setattr(sg.urllib.request, "urlopen", always_fail)
    monkeypatch.setattr(sg.time, "sleep", lambda _: None)
    with pytest.raises(sg.GateError):
        sg.fetch("http://e/x", tmp_path / "x.bin")


def test_language_excuse_fails(tmp_path):
    result = run_spec(tmp_path, spec_body(verdict="不采用", reason="语言不同，不好用"))
    assert not result.ok
    assert any("语言不同" in line for line in result.lines)


def test_reason_off_vocabulary_fails(tmp_path):
    result = run_spec(tmp_path, spec_body(verdict="不采用", reason="我不喜欢"))
    assert not result.ok
    assert any("不在词表" in line for line in result.lines)


def test_reason_in_vocabulary_passes(tmp_path):
    result = run_spec(tmp_path, spec_body(verdict="不采用", reason="停更或归档：两年没动"))
    assert result.ok


def test_license_is_not_a_filter(tmp_path):
    """许可不是用户定的判据：GPL 的候选照列，门禁不许挡。"""
    assert run_spec(tmp_path, spec_body(license="GPL-3.0")).ok


def test_sorting_stale_before_fresh_fails(tmp_path):
    stale = yaml.safe_load(spec_body(updated="2020-01-01", release="1.0@2020-01-01")
                           .split("```yaml\n")[1].split("```")[0])
    fresh = yaml.safe_load(spec_body().split("```yaml\n")[1].split("```")[0])
    text = ("## 成熟的项目\n\n```yaml\n"
            + yaml.safe_dump(stale + fresh, allow_unicode=True, sort_keys=False)
            + "```\n")
    result = run_spec(tmp_path, text)
    assert not result.ok
    assert any("A2 排序" in line for line in result.lines)


def test_extract_out_of_range_fails(tmp_path):
    result = run_spec(tmp_path, spec_body(extract="src/core.py:1-999"))
    assert not result.ok
    assert any("A7" in line for line in result.lines)


def test_extract_path_missing_fails(tmp_path):
    result = run_spec(tmp_path, spec_body(extract="src/nope.py:1-2"))
    assert not result.ok
    assert any("不存在" in line for line in result.lines)


def test_url_sha_mismatch_fails(tmp_path):
    result = run_spec(tmp_path, spec_body(url="https://github.com/acme/tool/archive/"
                                              + "b" * 40 + ".tar.gz"))
    assert not result.ok
    assert any("与 pin 字段不一致" in line for line in result.lines)


def test_snapshot_mismatch_fails(tmp_path):
    result = sgs.check_spec(str(write_spec(tmp_path, spec_body())), today=TODAY,
                           api=api_of(),
                           fetch_fn=fetch_split(SNAPSHOT, {"src/other.py": "x\n"}))
    assert not result.ok
    assert any("与 pin 快照不一致" in line for line in result.lines)


def test_pin_not_a_commit_fails(tmp_path):
    result = sgs.check_spec(str(write_spec(tmp_path, spec_body())), today=TODAY,
                           api=api_of(sha="c" * 40), fetch_fn=fetch_of())
    assert not result.ok
    assert any("A4" in line for line in result.lines)


def test_api_error_fails_closed(tmp_path):
    def boom(path: str) -> dict:
        raise sg.GateError("gh api 炸了")

    result = sgs.check_spec(str(write_spec(tmp_path, spec_body())), today=TODAY,
                           api=boom, fetch_fn=fetch_of())
    assert not result.ok
    assert any("炸了" in line for line in result.lines)


# ---------- C 组 ----------

def batches(*groups: list[str]) -> str:
    out = []
    for index, group in enumerate(groups, 1):
        out.append(f"【模块批次 {index}】")
        out.extend(group)
    return "\n".join(out) + "\n"


GOOD = ["- A —— 判定：保留 —— 理由：覆盖要求 1",
        "- B —— 判定：不要 —— 理由：与要求 2 无关",
        "- C —— 判定：改造 —— 理由：只取其中一段"]


def test_batches_ok(tmp_path):
    path = tmp_path / "d.dialogue.md"
    path.write_text(batches(GOOD), encoding="utf-8")
    assert sgs.check_batches(str(path)).ok


def test_batches_too_few_fails(tmp_path):
    path = tmp_path / "d.dialogue.md"
    path.write_text(batches(GOOD[:2], GOOD), encoding="utf-8")
    result = sgs.check_batches(str(path))
    assert not result.ok
    assert any("C1 批次 1" in line for line in result.lines)


def test_batches_last_is_exempt(tmp_path):
    path = tmp_path / "d.dialogue.md"
    path.write_text(batches(GOOD, GOOD[:1]), encoding="utf-8")
    assert sgs.check_batches(str(path)).ok


def test_batches_over_max_fails(tmp_path):
    path = tmp_path / "d.dialogue.md"
    path.write_text(batches(GOOD + ["- D —— 判定：自造 —— 理由：谁都没有",
                                    "- E —— 判定：自造 —— 理由：谁都没有"]),
                    encoding="utf-8")
    result = sgs.check_batches(str(path))
    assert not result.ok
    assert any("超过" in line for line in result.lines)


def test_batches_missing_marker_fails(tmp_path):
    path = tmp_path / "d.dialogue.md"
    path.write_text("随便写写\n", encoding="utf-8")
    result = sgs.check_batches(str(path))
    assert not result.ok
    assert any("没有【模块批次" in line for line in result.lines)


def test_batches_bad_line_fails(tmp_path):
    path = tmp_path / "d.dialogue.md"
    path.write_text(batches(GOOD[:2] + ["- D 判定保留"]), encoding="utf-8")
    result = sgs.check_batches(str(path))
    assert not result.ok
    assert any("不合格式" in line for line in result.lines)


def test_batches_bad_verdict_fails(tmp_path):
    path = tmp_path / "d.dialogue.md"
    path.write_text(batches(GOOD[:2] + ["- D —— 判定：随便 —— 理由：x"]),
                    encoding="utf-8")
    result = sgs.check_batches(str(path))
    assert not result.ok
    assert any("不在" in line for line in result.lines)


def test_batches_missing_file_fails(tmp_path):
    result = sgs.check_batches(str(tmp_path / "nope.dialogue.md"))
    assert not result.ok


# ---------- B 组 ----------

def card(**over) -> dict:
    base = {
        "id": "demo", "spec": "specs/2026-10-31-demo.spec.md", "status": "draft",
        "source": {"repo": REPO, "pin": PIN,
                   "url": f"https://github.com/{REPO}/archive/{PIN}.tar.gz",
                   "extract": "src/core.py:1-3", "lang": "Python"},
        "verdict": "改造", "instruction": "做点什么\n",
        "boundary": ["demo/后端代码/命令.py: 入口薄壳"],
    }
    base.update(over)
    return base


def write_card(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "tasks" / "demo.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path


def test_card_ok(tmp_path):
    assert sgd.check_card(write_card(tmp_path, card()))[0].ok


def test_card_missing_field_fails(tmp_path):
    payload = card()
    del payload["boundary"]
    result, _ = sgd.check_card(write_card(tmp_path, payload))
    assert not result.ok
    assert any("缺字段" in line for line in result.lines)


def test_card_bad_boundary_fails(tmp_path):
    result, _ = sgd.check_card(write_card(tmp_path, card(boundary=["没有冒号"])))
    assert not result.ok
    assert any("路径: 一行理由" in line for line in result.lines)


def test_card_id_mismatch_fails(tmp_path):
    result, _ = sgd.check_card(write_card(tmp_path, card(id="other")))
    assert not result.ok
    assert any("不一致" in line for line in result.lines)


def test_card_bad_status_fails(tmp_path):
    result, _ = sgd.check_card(write_card(tmp_path, card(status="whatever")))
    assert not result.ok


def test_source_repo_not_adopted_fails():
    result = sgd.check_source(card(source={"repo": "someone/else", "pin": PIN, "url": "u",
                                           "extract": "e", "lang": "Python"}), {})
    assert not result.ok
    assert any("判定为「采用」" in line for line in result.lines)


def test_source_self_made_ok():
    assert sgd.check_source(card(verdict="自造", source="自造"), {}).ok


def test_source_self_made_mismatch_fails():
    result = sgd.check_source(card(verdict="自造", source={"repo": REPO}), {})
    assert not result.ok


def test_third_party_missing_fails(tmp_path):
    result = sgd.check_third_party(card(), tmp_path, fetch_fn=fetch_of())
    assert not result.ok
    assert any("不算证据" in line for line in result.lines)


def test_third_party_match_passes(tmp_path):
    target = tmp_path / "第三方" / "acme__tool"
    for name, text in SNAPSHOT.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert sgd.check_third_party(card(), tmp_path, fetch_fn=fetch_of()).ok


def test_third_party_mismatch_fails(tmp_path):
    target = tmp_path / "第三方" / "acme__tool"
    target.mkdir(parents=True)
    (target / "src").mkdir()
    (target / "src" / "core.py").write_text("被改过了\n", encoding="utf-8")
    result = sgd.check_third_party(card(), tmp_path, fetch_fn=fetch_of())
    assert not result.ok
    assert any("不一致" in line for line in result.lines)


def test_self_made_but_third_party_present_fails(tmp_path):
    (tmp_path / "第三方").mkdir()
    (tmp_path / "第三方" / "x.txt").write_text("x", encoding="utf-8")
    result = sgd.check_third_party(card(verdict="自造", source="自造"), tmp_path)
    assert not result.ok


def test_discarded_card_with_snapshot_names_real_verdict(tmp_path):
    """报错文案要写卡片真实的 verdict，不能硬编码成「自造」。"""
    (tmp_path / "第三方").mkdir()
    (tmp_path / "第三方" / "x.txt").write_text("x", encoding="utf-8")
    result = sgd.check_third_party(card(verdict="不要", source="不要"), tmp_path)
    assert not result.ok
    assert any("「不要」" in line for line in result.lines)


def test_verdict_file_missing_candidate_fails(tmp_path):
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.verdict.md").write_text(
        "- 候选：other/repo —— 结论：采用 —— 理由：x\n", encoding="utf-8")
    result = sgd.check_verdict_file(spec, sg.parse_sources(spec.read_text(encoding="utf-8")))
    assert not result.ok
    assert any("没有被评判过" in line for line in result.lines)


def test_verdict_file_ok(tmp_path):
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.verdict.md").write_text(
        f"- 候选：{REPO} —— 结论：采用 —— 理由：覆盖全部要求\n", encoding="utf-8")
    result = sgd.check_verdict_file(spec, sg.parse_sources(spec.read_text(encoding="utf-8")))
    assert result.ok, result.lines


def test_verdict_file_absent_fails(tmp_path):
    spec = write_spec(tmp_path, spec_body())
    result = sgd.check_verdict_file(spec, sg.parse_sources(spec.read_text(encoding="utf-8")))
    assert not result.ok


# ---------- 入口 ----------

def test_spec_gate_main_writes_pass(tmp_path, capsys, monkeypatch):
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.dialogue.md").write_text(batches(GOOD), encoding="utf-8")
    monkeypatch.setattr(sgs, "check_spec",
                        lambda path, **kw: sg.Result(True, []))
    assert sg.main(["--spec", str(spec)]) == 0
    assert "SOURCE OK" in capsys.readouterr().out


def test_spec_gate_main_usage_error(capsys):
    assert sg.main([]) == 1
    assert "SOURCE FAIL" in capsys.readouterr().out


def test_delivery_main_usage_error(capsys):
    assert sgd.main([]) == 1
    assert "SOURCE FAIL" in capsys.readouterr().out


def test_delivery_main_requires_spec(capsys):
    assert sgd.main(["demo"]) == 1
    assert "SOURCE FAIL" in capsys.readouterr().out


def test_spec_gate_main_missing_spec_file(capsys):
    assert sg.main(["--spec", "/tmp/根本没有这个 spec.md"]) == 1
    assert "SOURCE FAIL" in capsys.readouterr().out


def test_verdict_file_ignores_heading_lines(tmp_path):
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.verdict.md").write_text(
        f"# 评判裁决\n\n- 候选：{REPO} —— 结论：采用 —— 理由：x\n", encoding="utf-8")
    result = sgd.check_verdict_file(
        spec, sg.parse_sources(spec.read_text(encoding="utf-8")))
    assert result.ok, result.lines


def test_reconciliation_without_tasks_dir(tmp_path, monkeypatch):
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.dialogue.md").write_text(batches(GOOD),
                                                          encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = sgd.check_reconciliation(spec, Path("tasks"))
    assert not result.ok
    assert any("却没建卡" in line for line in result.lines)


def test_reconciliation_skips_broken_and_foreign_cards(tmp_path, monkeypatch):
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.dialogue.md").write_text(batches(GOOD),
                                                          encoding="utf-8")
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "坏.yaml").write_text("a: [没闭合\n", encoding="utf-8")
    foreign = card(id="外来的")
    foreign["spec"] = "specs/别的功能.spec.md"
    (tasks / "外来的.yaml").write_text(
        yaml.safe_dump(foreign, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = sgd.check_reconciliation(spec, Path("tasks"))
    assert not result.ok
    assert any("却没建卡" in line for line in result.lines)


# ---------- 底座错误分支 ----------

def test_parse_date_rejects_garbage():
    assert sg.parse_date("不是日期") is None


def test_days_in_month_december():
    assert sg.months_ago(date(2026, 12, 31), 0) == date(2026, 12, 31)


def test_gh_json_missing_binary(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("没有 gh")
    monkeypatch.setattr(sg.subprocess, "run", boom)
    with pytest.raises(sg.GateError):
        sg.gh_json("repos/x/y")


def test_gh_json_nonzero_exit(monkeypatch):
    class Done:
        returncode, stdout, stderr = 1, "", "炸了"

    monkeypatch.setattr(sg.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(sg.GateError):
        sg.gh_json("repos/x/y")


def test_gh_json_bad_json(monkeypatch):
    class Done:
        returncode, stdout, stderr = 0, "不是 json", ""

    monkeypatch.setattr(sg.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(sg.GateError):
        sg.gh_json("repos/x/y")


def test_fetch_failure(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise OSError("网络断了")
    monkeypatch.setattr(sg.urllib.request, "urlopen", boom)
    with pytest.raises(sg.GateError):
        sg.fetch("https://example.com/x", tmp_path / "o.tar.gz")


def test_unpack_rejects_two_tops(tmp_path):
    blob = tmp_path / "b.tar.gz"
    with tarfile.open(blob, "w:gz") as tar:
        for top in ("one", "two"):
            data = b"x"
            info = tarfile.TarInfo(f"{top}/a.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    with pytest.raises(sg.GateError):
        sg.unpack(blob, tmp_path / "out")


def test_parse_sources_rejects_non_list():
    with pytest.raises(sg.GateError):
        sg.parse_sources("## 成熟的项目\n\n```yaml\nhello\n```\n")


def test_parse_sources_rejects_scalar_entry():
    with pytest.raises(sg.GateError):
        sg.parse_sources("## 成熟的项目\n\n```yaml\n- 5\n```\n")


def test_parse_sources_requires_fence():
    with pytest.raises(sg.GateError):
        sg.parse_sources("## 成熟的项目\n\n没有代码块\n")


def test_parse_sources_rejects_empty_section():
    with pytest.raises(sg.GateError):
        sg.parse_sources("## 成熟的项目\n\n```yaml\n[]\n```\n")


# ---------- A 组剩余分支 ----------

def test_reason_blank_fails(tmp_path):
    result = run_spec(tmp_path, spec_body(reason="   "))
    assert not result.ok
    assert any("理由为空" in line for line in result.lines)


def test_verdict_value_illegal(tmp_path):
    result = run_spec(tmp_path, spec_body(verdict="随便"))
    assert not result.ok
    assert any("不在" in line for line in result.lines)


def test_api_without_star_field(tmp_path):
    result = sgs.check_spec(str(write_spec(tmp_path, spec_body())), today=TODAY,
                            api=lambda path: {}, fetch_fn=fetch_of())
    assert not result.ok
    assert any("取不回 star" in line for line in result.lines)


def test_url_not_archive_form(tmp_path):
    result = run_spec(tmp_path, spec_body(url="https://example.com/x.zip"))
    assert not result.ok
    assert any("archive" in line for line in result.lines)


def test_extract_without_colon(tmp_path):
    result = run_spec(tmp_path, spec_body(extract="没有冒号"))
    assert not result.ok
    assert any("A7" in line for line in result.lines)


def test_entry_blank_reason_fails(tmp_path):
    path = tmp_path / "d.dialogue.md"
    path.write_text("【模块批次 1】\n- A —— 判定：保留 —— 理由：   \n", encoding="utf-8")
    result = sgs.check_batches(str(path))
    assert not result.ok


# ---------- B 组剩余分支 ----------

def test_card_unreadable(tmp_path):
    result, payload = sgd.check_card(tmp_path / "nope.yaml")
    assert not result.ok and payload is None


def test_card_not_a_mapping(tmp_path):
    path = tmp_path / "tasks" / "demo.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    result, _ = sgd.check_card(path)
    assert not result.ok
    assert any("不是键值对" in line for line in result.lines)


def test_card_boundary_not_a_list(tmp_path):
    result, _ = sgd.check_card(write_card(tmp_path, card(boundary="nope")))
    assert not result.ok
    assert any("非空列表" in line for line in result.lines)


def test_card_boundary_blank_reason(tmp_path):
    result, _ = sgd.check_card(write_card(tmp_path, card(boundary=["a.py:   "])))
    assert not result.ok


def test_card_verdict_illegal(tmp_path):
    result, _ = sgd.check_card(write_card(tmp_path, card(verdict="乱写")))
    assert not result.ok


def test_source_missing_keys():
    result = sgd.check_source(card(source={"repo": REPO}), {REPO: None})
    assert not result.ok
    assert any("缺字段" in line for line in result.lines)


def test_source_not_a_mapping():
    result = sgd.check_source(card(source=["x"]), {})
    assert not result.ok


def test_third_party_without_repo(tmp_path):
    result = sgd.check_third_party(card(source="自造"), tmp_path)
    assert not result.ok
    assert any("拿不到" in line for line in result.lines)


def test_third_party_fetch_error(tmp_path):
    (tmp_path / "第三方" / "acme__tool").mkdir(parents=True)

    def boom(url, dest):
        raise sg.GateError("下不动")

    result = sgd.check_third_party(card(), tmp_path, fetch_fn=boom)
    assert not result.ok
    assert any("下不动" in line for line in result.lines)


def test_verdict_file_bad_line(tmp_path):
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.verdict.md").write_text(
        "- 候选 acme/tool 结论 采用\n", encoding="utf-8")
    result = sgd.check_verdict_file(
        spec, sg.parse_sources(spec.read_text(encoding="utf-8")))
    assert not result.ok
    assert any("不合格式" in line for line in result.lines)


def test_verdict_file_blank_reason_is_bad_format(tmp_path):
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.verdict.md").write_text(
        f"- 候选：{REPO} —— 结论：采用 —— 理由：   \n", encoding="utf-8")
    result = sgd.check_verdict_file(
        spec, sg.parse_sources(spec.read_text(encoding="utf-8")))
    assert not result.ok
    assert any("不合格式" in line for line in result.lines)


# ---------- check_delivery 端到端 ----------

def build_workspace(tmp_path: Path) -> Path:
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.dialogue.md").write_text(
        "【模块批次 1】\n- demo —— 判定：改造 —— 理由：照上游逻辑重写\n",
        encoding="utf-8")
    (tmp_path / "2026-10-31-demo.verdict.md").write_text(
        f"- 候选：{REPO} —— 结论：采用 —— 理由：覆盖全部要求\n", encoding="utf-8")
    snapshot = tmp_path / "demo" / "第三方" / "acme__tool"
    for name, text in SNAPSHOT.items():
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (tmp_path / "demo" / "后端代码" / "tests").mkdir(parents=True, exist_ok=True)
    write_card(tmp_path, card())
    return spec


def test_check_delivery_passes(tmp_path, monkeypatch):
    spec = build_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = sgd.check_delivery("demo", str(spec), fetch_fn=fetch_of())
    assert result.ok, result.lines


def test_check_delivery_missing_card(tmp_path, monkeypatch):
    spec = build_workspace(tmp_path)
    (tmp_path / "tasks" / "demo.yaml").unlink()
    monkeypatch.chdir(tmp_path)
    result = sgd.check_delivery("demo", str(spec), fetch_fn=fetch_of())
    assert not result.ok


def test_check_delivery_bad_spec(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = sgd.check_delivery("demo", str(tmp_path / "nope.spec.md"))
    assert not result.ok
    assert any("B0" in line for line in result.lines)


def test_delivery_main_passes(tmp_path, monkeypatch, capsys):
    spec = build_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sgd, "fetch", fetch_of())
    assert sgd.main(["demo", "--spec", str(spec)]) == 0
    assert "SOURCE OK" in capsys.readouterr().out


# ---------- 二轮返工：验收打回的 5 条 ----------

def test_license_field_ignored_by_gate(tmp_path):
    """GPL 也好、实时值对不上也好，门禁都不管——许可不在用户定的判据里。"""

    def api_with_license(path: str) -> dict:
        if "/commits/" in path:
            return {"sha": PIN}
        return {"stargazers_count": 5000, "license": {"spdx_id": "BSD-3-Clause"}}

    result = sgs.check_spec(str(write_spec(tmp_path, spec_body(license="GPL-3.0"))),
                            today=TODAY, api=api_with_license, fetch_fn=fetch_of())
    assert result.ok, result.lines


def test_future_updated_date_fails(tmp_path):
    result = run_spec(tmp_path, spec_body(updated="2030-01-01"))
    assert not result.ok
    assert any("未来日期" in line for line in result.lines)


def test_future_release_date_fails(tmp_path):
    result = run_spec(tmp_path, spec_body(release="9.9.9@2030-01-01"))
    assert not result.ok
    assert any("A8" in line for line in result.lines)


def test_non_date_updated_fails(tmp_path):
    result = run_spec(tmp_path, spec_body(updated="昨天"))
    assert not result.ok
    assert any("不是 ISO 日期" in line for line in result.lines)


def test_discarded_card_with_rejected_passes(tmp_path):
    payload = card(verdict="不要", status="rejected", source="不要")
    result, _ = sgd.check_card(write_card(tmp_path, payload))
    assert result.ok, result.lines


def test_discarded_without_rejected_fails(tmp_path):
    result, _ = sgd.check_card(write_card(tmp_path, card(verdict="不要", source="不要")))
    assert not result.ok
    assert any("status 必须是 rejected" in line for line in result.lines)


def test_rejected_without_discarded_fails(tmp_path):
    result, _ = sgd.check_card(write_card(tmp_path, card(status="rejected")))
    assert not result.ok
    assert any("verdict 必须是" in line for line in result.lines)


def test_discarded_card_skips_source(tmp_path):
    result = sgd.check_source(card(verdict="不要", source="不要"), {})
    assert result.ok


def test_verdict_conclusion_off_vocabulary_fails(tmp_path):
    spec = write_spec(tmp_path, spec_body())
    (tmp_path / "2026-10-31-demo.verdict.md").write_text(
        f"- 候选：{REPO} —— 结论：随便 —— 理由：x\n", encoding="utf-8")
    result = sgd.check_verdict_file(
        spec, sg.parse_sources(spec.read_text(encoding="utf-8")))
    assert not result.ok
    assert any("不在" in line for line in result.lines)


def test_reconciliation_missing_card_fails(tmp_path, monkeypatch):
    spec = build_workspace(tmp_path)
    (tmp_path / "2026-10-31-demo.dialogue.md").write_text(
        "【模块批次 1】\n- demo —— 判定：改造 —— 理由：x\n"
        "- 另一个 —— 判定：改造 —— 理由：y\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = sgd.check_delivery("demo", str(spec), fetch_fn=fetch_of())
    assert not result.ok
    assert any("却没建卡的模块" in line for line in result.lines)


def test_reconciliation_extra_card_fails(tmp_path, monkeypatch):
    spec = build_workspace(tmp_path)
    (tmp_path / "2026-10-31-demo.dialogue.md").write_text(
        "【模块批次 1】\n- 别的 —— 判定：改造 —— 理由：x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = sgd.check_delivery("demo", str(spec), fetch_fn=fetch_of())
    assert not result.ok
    assert any("却没讨论过" in line for line in result.lines)


def test_reconciliation_no_dialogue_fails(tmp_path, monkeypatch):
    spec = build_workspace(tmp_path)
    (tmp_path / "2026-10-31-demo.dialogue.md").unlink()
    monkeypatch.chdir(tmp_path)
    result = sgd.check_delivery("demo", str(spec), fetch_fn=fetch_of())
    assert not result.ok
    assert any("B5" in line for line in result.lines)


def test_reconciliation_validates_every_card(tmp_path, monkeypatch):
    """判「不要」的卡没有模块目录、没有属于它自己的那一轮门禁，必须由对账连带校验。"""
    spec = build_workspace(tmp_path)
    other = tmp_path / "tasks" / "别的.yaml"
    payload = card(id="别的", verdict="不要", source="不要")  # status 仍是 draft
    other.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                     encoding="utf-8")
    (tmp_path / "2026-10-31-demo.dialogue.md").write_text(
        "【模块批次 1】\n- demo —— 判定：改造 —— 理由：x\n"
        "- 别的 —— 判定：不要 —— 理由：y\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = sgd.check_delivery("demo", str(spec), fetch_fn=fetch_of())
    assert not result.ok
    assert any("status 必须是 rejected" in line for line in result.lines)


def test_unpack_wraps_tar_error(tmp_path):
    blob = tmp_path / "not-a-tar.tar.gz"
    blob.write_bytes("<html>网关错误页</html>".encode())
    with pytest.raises(sg.GateError):
        sg.unpack(blob, tmp_path / "out")


def test_parse_cli_rejects_bad_argument():
    ns, error = sg.parse_cli(["--nope"], "probe")
    assert ns is None and error


# ---------- CLI 参数解析（argparse） ----------

@pytest.mark.parametrize("argv,module,spec", [
    ([], None, None),
    (["demo/"], "demo/", None),
    (["demo/", "--spec", "s.md"], "demo/", "s.md"),
    (["--spec", "s.md"], None, "s.md"),
    (["--spec", "s.md", "demo/"], "demo/", "s.md"),
])
def test_gate_parse_argv(argv, module, spec):
    assert sg_gate.parse_argv(argv) == (module, spec, "")


@pytest.mark.parametrize("argv", [["--spec"], ["a", "b"], ["--nope"]])
def test_gate_parse_argv_rejects(argv):
    got_module, got_spec, error = sg_gate.parse_argv(argv)
    assert (got_module, got_spec) == (None, None) and error


def test_gate_main_reports_missing_dir_before_network(tmp_path, monkeypatch, capsys):
    """模块目录不存在就立刻报错，不白跑一遍全量网络校验。"""
    monkeypatch.setattr(sys, "argv",
                        ["gate.py", "没这个目录/", "--spec", "s.md"])
    assert sg_gate.main() == 1
    captured = capsys.readouterr()
    assert "目录不存在" in captured.out + captured.err
