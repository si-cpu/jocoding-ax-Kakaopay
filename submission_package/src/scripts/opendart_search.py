import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET


OPENDART_BASE = "https://opendart.fss.or.kr/api"
DART_VIEWER_BASE = "https://dart.fss.or.kr/dsaf001/main.do"


ANCHOR_KEYWORDS = [
    "생산중단",
    "영업정지",
    "조업중단",
    "주요사항보고",
    "거래소공시",
]


def load_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def require_key() -> str:
    key = os.environ.get("OPENDART_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENDART_API_KEY가 설정되어 있지 않습니다. .env 파일을 확인해주세요.")
    return key


def request_json(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def request_bytes(url: str, params: dict) -> bytes:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def load_corp_codes(api_key: str) -> list[dict]:
    data = request_bytes(f"{OPENDART_BASE}/corpCode.xml", {"crtfc_key": api_key})
    with zipfile.ZipFile(BytesIO(data)) as zf:
        xml_name = zf.namelist()[0]
        xml_data = zf.read(xml_name)
    root = ET.fromstring(xml_data)
    corps = []
    for item in root.findall("list"):
        corps.append(
            {
                "corp_code": text(item, "corp_code"),
                "corp_name": text(item, "corp_name"),
                "stock_code": text(item, "stock_code"),
                "modify_date": text(item, "modify_date"),
            }
        )
    return corps


def text(item, tag: str) -> str:
    found = item.find(tag)
    return "" if found is None or found.text is None else found.text.strip()


def find_corp(corps: list[dict], *, stock_code: Optional[str], corp_name: Optional[str]) -> dict:
    if stock_code:
        exact = [c for c in corps if c["stock_code"] == stock_code]
        if exact:
            return exact[0]
    if corp_name:
        exact = [c for c in corps if c["corp_name"] == corp_name]
        if exact:
            return exact[0]
        contains = [c for c in corps if corp_name in c["corp_name"] and c["stock_code"]]
        if contains:
            return contains[0]
    raise SystemExit("회사 고유번호를 찾지 못했습니다. corp_name 또는 stock_code를 확인해주세요.")


def fetch_disclosures(api_key: str, corp_code: str, bgn_de: str, end_de: str) -> list[dict]:
    all_rows: list[dict] = []
    page_no = 1
    while True:
        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "last_reprt_at": "N",
            "sort": "date",
            "sort_mth": "desc",
            "page_no": str(page_no),
            "page_count": "100",
        }
        data = request_json(f"{OPENDART_BASE}/list.json", params)
        status = data.get("status")
        if status == "013":
            return []
        if status != "000":
            raise SystemExit(f"OpenDART 오류: status={status}, message={data.get('message')}")
        all_rows.extend(data.get("list", []))
        total_page = int(data.get("total_page") or 1)
        if page_no >= total_page:
            return all_rows
        page_no += 1


def classify_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    anchor_rows = []
    other_rows = []
    for row in rows:
        report_nm = row.get("report_nm", "")
        is_anchor = any(k in report_nm for k in ANCHOR_KEYWORDS)
        enriched = {
            "rcept_dt": row.get("rcept_dt", ""),
            "corp_name": row.get("corp_name", ""),
            "stock_code": row.get("stock_code", ""),
            "report_nm": report_nm,
            "rcept_no": row.get("rcept_no", ""),
            "dart_url": f"{DART_VIEWER_BASE}?rcpNo={row.get('rcept_no', '')}",
            "rm": row.get("rm", ""),
        }
        if is_anchor:
            anchor_rows.append(enriched)
        else:
            other_rows.append(enriched)
    return anchor_rows, other_rows


def print_markdown(corp: dict, rows: list[dict], anchor_rows: list[dict], bgn_de: str, end_de: str) -> None:
    print("# OpenDART 공시검색 결과")
    print()
    print(f"- 회사: {corp['corp_name']}")
    print(f"- 종목코드: {corp['stock_code']}")
    print(f"- DART 고유번호: {corp['corp_code']}")
    print(f"- 검색기간: {bgn_de} ~ {end_de}")
    print(f"- 전체 공시 수: {len(rows)}")
    print(f"- 생산중단/영업정지/조업중단/주요사항보고/거래소공시 후보: {len(anchor_rows)}")
    print()
    if anchor_rows:
        print("## 확정 앵커 후보 공시")
        print()
        print("| 접수일 | 보고서명 | 링크 |")
        print("|---|---|---|")
        for row in anchor_rows:
            print(f"| {row['rcept_dt']} | {row['report_nm']} | [DART 원문]({row['dart_url']}) |")
    else:
        print("## 확정 앵커 후보 공시")
        print()
        print("검색기간 내 `생산중단`, `영업정지`, `조업중단`, `주요사항보고서`, `거래소공시` 키워드가 포함된 공시를 찾지 못했습니다.")
        print()
        print("주의: 이는 파업이 없었다는 뜻이 아니라, MVP 기준의 확정 생산중단 앵커 공시를 확인하지 못했다는 뜻입니다.")
    print()
    print("## 최근 공시 일부")
    print()
    print("| 접수일 | 보고서명 |")
    print("|---|---|")
    for row in rows[:20]:
        print(f"| {row.get('rcept_dt', '')} | {row.get('report_nm', '')} |")


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenDART 공시검색 API로 앵커 후보 공시를 조회합니다.")
    parser.add_argument("--corp-name", default="현대자동차")
    parser.add_argument("--stock-code", default="005380")
    parser.add_argument("--bgn-de", required=True)
    parser.add_argument("--end-de", required=True)
    args = parser.parse_args()

    load_env()
    api_key = require_key()
    corps = load_corp_codes(api_key)
    corp = find_corp(corps, stock_code=args.stock_code, corp_name=args.corp_name)
    rows = fetch_disclosures(api_key, corp["corp_code"], args.bgn_de, args.end_de)
    anchor_rows, _ = classify_rows(rows)
    print_markdown(corp, rows, anchor_rows, args.bgn_de, args.end_de)


if __name__ == "__main__":
    main()
