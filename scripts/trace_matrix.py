"""Sinh ma trận truy vết yêu cầu - mã - test (SRS mục 11.2, 11.4) ra docs/05_ma_tran_truy_vet.md.

Nguồn dữ liệu:
- docs/srs/test_cases.csv     : 72 test case nghiệp vụ của SRS mục 11.3
- docs/srs/requirements.csv   : yêu cầu FR / NFR (chương 5, 6, 9) kèm use case và test case theo bảng 11.17-11.38
- tests/*.py                  : mỗi hàm test ghi mã TC trong dòng chú thích "# TC-... (SRS 11.3)" ngay trên hàm
                                hoặc trong docstring; mã FR / NFR nhắc trong hàm cũng được ghi nhận
- app/, prompts/              : nơi mã nguồn nhắc tới mã yêu cầu (cột "Có trong mã")

Chạy:
    python -m scripts.trace_matrix          # chỉ dò mã nguồn và test
    python -m scripts.trace_matrix --run    # chạy pytest rồi ghi kết quả đạt / không đạt từng test
"""
import argparse
import csv
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TC_RE = re.compile(r"\bTC-[A-Z]{3}-\d{2}\b")
REQ_RE = re.compile(r"\b(?:N?FR)-[A-Z]{3}-\d{2}\b")


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def scan_tests() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Trả về (TC -> [test], yêu cầu -> [test]); test ghi dạng tests/file.py::ten_ham."""
    by_tc, by_req = defaultdict(list), defaultdict(list)
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines):
            m = re.match(r"def (test_\w+)\(", line)
            if not m:
                continue
            name = f"tests/{path.name}::{m.group(1)}"
            # chú thích và decorator ngay phía trên hàm
            head, j = [], i - 1
            while j >= 0 and (lines[j].startswith(("#", "@", " ", "]", ")")) and lines[j].strip()):
                head.append(lines[j])
                j -= 1
            # thân hàm đến hàm kế tiếp
            body, k = [], i + 1
            while k < len(lines) and not re.match(r"(def |class |@|# =+|# -+)", lines[k]):
                body.append(lines[k])
                k += 1
            doc = "\n".join(body[:3])
            tcs = set(TC_RE.findall("\n".join(h for h in head if "SRS 11.3" in h) + "\n" + doc))
            for tc in tcs:
                by_tc[tc].append(name)
            for req in set(REQ_RE.findall("\n".join(head) + "\n".join(body))):
                by_req[req].append(name)
    return by_tc, by_req


def scan_code() -> dict[str, list[str]]:
    found = defaultdict(set)
    for folder, pattern in (("app", "*.py"), ("frontend/src", "*.jsx"), ("prompts", "*.md")):
        for path in (ROOT / folder).rglob(pattern):
            for req in set(REQ_RE.findall(path.read_text(encoding="utf-8"))):
                found[req].add(str(path.relative_to(ROOT)).replace("\\", "/"))
    return {k: sorted(v) for k, v in found.items()}


def run_pytest() -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "result.xml"
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}"],
                       cwd=ROOT, check=False)
        status = {}
        for case in ET.parse(xml).getroot().iter("testcase"):
            module = case.get("classname", "").replace(".", "/") + ".py"
            func = case.get("name", "").split("[")[0]
            failed = case.find("failure") is not None or case.find("error") is not None
            skipped = case.find("skipped") is not None
            key = f"{module}::{func}"
            prev = status.get(key, "Đạt")
            status[key] = "Không đạt" if failed or prev == "Không đạt" else ("Bỏ qua" if skipped else prev)
        return status


def md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def build(run: bool) -> str:
    tcs = read_csv(ROOT / "docs/srs/test_cases.csv")
    reqs = read_csv(ROOT / "docs/srs/requirements.csv")
    by_tc, by_req_test = scan_tests()
    code = scan_code()
    results = run_pytest() if run else {}

    def status_of(tests: list[str]) -> str:
        if not tests:
            return "Chưa có test"
        if not results:
            return "Có test"
        states = {results.get(t, "Không thấy") for t in tests}
        return "Không đạt" if "Không đạt" in states else ("Đạt" if states <= {"Đạt"} else ", ".join(sorted(states)))

    out = [f"# Ma trận truy vết yêu cầu, mã nguồn và kiểm thử",
           "",
           f"Sinh tự động bằng `python -m scripts.trace_matrix{' --run' if run else ''}` ngày {date.today():%d/%m/%Y}. "
           "Đừng sửa tay: thêm mã test case vào chú thích `# TC-xxx-nn (SRS 11.3)` ngay trên hàm test rồi chạy lại.",
           "",
           "Theo SRS mục 11.2, một yêu cầu được xem là hoàn thành khi có mã, có test đạt và có dòng trong ma trận này.",
           ""]

    tc_done = sum(1 for t in tcs if by_tc.get(t["id"]) and status_of(by_tc[t["id"]]) in ("Đạt", "Có test"))
    high = [r for r in reqs if r["id"].startswith("FR") and r["priority"] == "Cao"]
    out += ["## 1. Tổng hợp", "",
            "| Chỉ số | Giá trị |", "|---|---|",
            f"| Test case nghiệp vụ (SRS 11.3) có test tự động{' đạt' if run else ''} | {tc_done} / {len(tcs)} |",
            f"| Yêu cầu chức năng (FR) có nhắc trong mã nguồn | "
            f"{sum(1 for r in reqs if r['id'].startswith('FR') and r['id'] in code)} / "
            f"{sum(1 for r in reqs if r['id'].startswith('FR'))} |",
            f"| Yêu cầu chức năng ưu tiên Cao có test | "
            f"{sum(1 for r in high if _tests_for_req(r, by_tc, by_req_test))} / {len(high)} |",
            ""]
    if results:
        total = len(results)
        passed = sum(1 for v in results.values() if v == "Đạt")
        out += [f"Lần chạy pytest: {passed} / {total} hàm test đạt.", ""]

    out += ["## 2. Test case nghiệp vụ (SRS 11.3) và test tự động", "",
            "| Mã | Tên | Kết quả mong đợi | Test tự động | Trạng thái |", "|---|---|---|---|---|"]
    for t in tcs:
        tests = sorted(set(by_tc.get(t["id"], [])))
        out.append(f"| {t['id']} | {md_escape(t['name'])} | {md_escape(t['expected'])} | "
                   f"{'<br>'.join(f'`{x}`' for x in tests) or '-'} | {status_of(tests)} |")

    out += ["", "## 3. Yêu cầu, use case, mã nguồn và test", "",
            "Cột *Test* gồm test của các test case SRS gắn với yêu cầu và các test nhắc trực tiếp mã yêu cầu.", "",
            "| Yêu cầu | Ưu tiên | Use case | Test case SRS | Có trong mã | Test | Trạng thái |",
            "|---|---|---|---|---|---|---|"]
    for r in reqs:
        tests = _tests_for_req(r, by_tc, by_req_test)
        files = code.get(r["id"], [])
        out.append(f"| {r['id']} | {r['priority']} | {r['use_case'] or '-'} | {r['srs_test_cases'] or '-'} | "
                   f"{'<br>'.join(f'`{f}`' for f in files[:3]) + (' ...' if len(files) > 3 else '') or '-'} | "
                   f"{len(tests)} test | {status_of(tests) if tests else ('Có mã, chưa có test' if files else '-')} |")
    out.append("")
    return "\n".join(out)


def _tests_for_req(r: dict, by_tc: dict, by_req_test: dict) -> list[str]:
    tests = set(by_req_test.get(r["id"], []))
    for tc in TC_RE.findall(r.get("srs_test_cases") or ""):
        tests |= set(by_tc.get(tc, []))
    return sorted(tests)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true", help="chạy pytest và ghi kết quả từng test")
    parser.add_argument("--out", default="docs/05_ma_tran_truy_vet.md")
    args = parser.parse_args()
    text = build(args.run)
    (ROOT / args.out).write_text(text, encoding="utf-8")
    print(f"Đã ghi {args.out}")


if __name__ == "__main__":
    main()
