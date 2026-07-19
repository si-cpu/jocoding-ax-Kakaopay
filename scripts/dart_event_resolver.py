#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resolve official company events with OpenDART disclosures.

This module is intentionally narrow: it does not try to classify every market
issue. It only locks company-direct events when OpenDART has a matching
disclosure, then lets the context engine handle broader industry/macro issues.
"""

import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPENDART_PATH = PROJECT_ROOT / "scripts" / "opendart_search.py"
spec = importlib.util.spec_from_file_location("opendart_search", OPENDART_PATH)
opendart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(opendart)


DART_EVENT_RULES = [
    {
        "event_type": "수주/공급계약",
        "issue_codes": ["order_contract"],
        "input_keywords": ["수주", "공급계약", "LNG선", "계약"],
        "report_keywords": ["단일판매", "공급계약", "수주", "계약체결"],
        "origin": "기업 내부",
    },
    {
        "event_type": "생산중단",
        "issue_codes": ["strike"],
        "input_keywords": ["생산중단", "생산 차질", "파업", "노조", "임단협"],
        "report_keywords": ["생산중단", "영업정지", "조업중단"],
        "origin": "기업 내부",
    },
    {
        "event_type": "생산재개",
        "issue_codes": ["strike"],
        "input_keywords": ["생산재개", "타결", "합의", "재개"],
        "report_keywords": ["생산재개", "영업재개"],
        "origin": "기업 내부",
    },
    {
        "event_type": "시설투자/공장증설",
        "issue_codes": [],
        "input_keywords": ["공장증설", "증설", "신규 시설투자", "시설투자", "공장"],
        "report_keywords": ["신규시설투자", "시설투자", "투자판단"],
        "origin": "기업 내부",
    },
    {
        "event_type": "배당",
        "issue_codes": [],
        "input_keywords": ["배당", "현금배당", "주식배당"],
        "report_keywords": ["현금ㆍ현물배당", "배당결정", "주식배당"],
        "origin": "재무/실적",
    },
    {
        "event_type": "자사주",
        "issue_codes": [],
        "input_keywords": ["자사주", "자기주식"],
        "report_keywords": ["자기주식", "자사주"],
        "origin": "재무/실적",
    },
    {
        "event_type": "증자/감자",
        "issue_codes": [],
        "input_keywords": ["증자", "유상증자", "무상증자", "감자"],
        "report_keywords": ["유상증자", "무상증자", "감자결정"],
        "origin": "재무/실적",
    },
    {
        "event_type": "소송/제재",
        "issue_codes": ["owner_legal"],
        "input_keywords": ["소송", "제재", "수사", "압수수색", "구속", "오너"],
        "report_keywords": ["소송", "횡령", "배임", "제재", "기소", "검찰", "법원"],
        "origin": "오너/지배구조",
    },
]


def contains_any(text: str, keywords: List[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def yyyymmdd(value: str) -> str:
    return value.replace("-", "")


def date_window(center: Optional[str], before_days: int, after_days: int) -> tuple[str, str]:
    if center:
        base = dt.datetime.strptime(center, "%Y-%m-%d").date()
    else:
        base = dt.date.today()
    return (
        (base - dt.timedelta(days=before_days)).strftime("%Y%m%d"),
        (base + dt.timedelta(days=after_days)).strftime("%Y%m%d"),
    )


def infer_candidate_rules(sentence: str, issue_codes: Optional[List[str]] = None) -> List[Dict]:
    issue_codes = issue_codes or []
    candidates = []
    for rule in DART_EVENT_RULES:
        if contains_any(sentence, rule["input_keywords"]) or any(code in issue_codes for code in rule["issue_codes"]):
            candidates.append(rule)
    return candidates


def row_to_public(row: Dict) -> Dict:
    return {
        "rcept_dt": row.get("rcept_dt", ""),
        "corp_name": row.get("corp_name", ""),
        "stock_code": row.get("stock_code", ""),
        "report_nm": row.get("report_nm", ""),
        "rcept_no": row.get("rcept_no", ""),
        "dart_url": f"{opendart.DART_VIEWER_BASE}?rcpNo={row.get('rcept_no', '')}",
        "rm": row.get("rm", ""),
    }


def match_disclosures(rows: List[Dict], candidate_rules: List[Dict]) -> List[Dict]:
    matches = []
    for row in rows:
        report_nm = row.get("report_nm", "")
        for rule in candidate_rules:
            if contains_any(report_nm, rule["report_keywords"]):
                public = row_to_public(row)
                public["event_type"] = rule["event_type"]
                public["origin"] = rule["origin"]
                public["match_rule"] = {
                    "input_keywords": rule["input_keywords"],
                    "report_keywords": rule["report_keywords"],
                }
                matches.append(public)
                break
    return matches


def sort_matches(matches: List[Dict], event_date: Optional[str]) -> List[Dict]:
    if not event_date:
        return matches
    target = dt.datetime.strptime(yyyymmdd(event_date), "%Y%m%d").date()

    def key(row: Dict) -> tuple[int, int]:
        try:
            row_date = dt.datetime.strptime(row.get("rcept_dt", ""), "%Y%m%d").date()
            distance = abs((row_date - target).days)
        except Exception:
            distance = 999999
        correction_penalty = 1 if "기재정정" in row.get("report_nm", "") else 0
        return (distance, correction_penalty)

    return sorted(matches, key=key)


def resolve_dart_event(
    company: str,
    ticker: Optional[str],
    sentence: str,
    event_date: Optional[str] = None,
    issue_codes: Optional[List[str]] = None,
    before_days: int = 30,
    after_days: int = 10,
    env_path: Optional[str] = None,
) -> Dict:
    """Return official DART match if a company-direct event is found."""
    candidate_rules = infer_candidate_rules(sentence, issue_codes)
    if not candidate_rules:
        return {
            "status": "skipped",
            "reason": "DART로 확정하기 적합한 기업 직접 이벤트 후보가 아닙니다.",
            "candidate_event_types": [],
        }

    opendart.load_env(env_path or str(PROJECT_ROOT / ".env"))
    api_key = opendart.require_key()
    bgn_de, end_de = date_window(event_date, before_days, after_days)
    corps = opendart.load_corp_codes(api_key)
    corp = opendart.find_corp(corps, stock_code=ticker, corp_name=company)
    rows = opendart.fetch_disclosures(api_key, corp["corp_code"], bgn_de, end_de)
    matches = sort_matches(match_disclosures(rows, candidate_rules), event_date)
    if not matches:
        return {
            "status": "not_found",
            "reason": "검색 기간 내 입력 이슈와 맞는 DART 공시를 찾지 못했습니다.",
            "company": corp["corp_name"],
            "ticker": corp["stock_code"],
            "corp_code": corp["corp_code"],
            "window": {"bgn_de": bgn_de, "end_de": end_de},
            "candidate_event_types": [rule["event_type"] for rule in candidate_rules],
            "recent_disclosures": [row_to_public(row) for row in rows[:10]],
        }
    lead = matches[0]
    return {
        "status": "official_match",
        "origin": lead["origin"],
        "confirmation": "공식 확인",
        "official_event_type": lead["event_type"],
        "event_date": lead["rcept_dt"],
        "company": corp["corp_name"],
        "ticker": corp["stock_code"],
        "corp_code": corp["corp_code"],
        "window": {"bgn_de": bgn_de, "end_de": end_de},
        "lead_disclosure": lead,
        "matches": matches[:10],
        "match_count": len(matches),
    }


def print_summary(result: Dict) -> None:
    print("# DART 이벤트 확인 결과")
    print(f"- 상태: {result.get('status')}")
    print(f"- 설명: {result.get('reason', result.get('official_event_type', ''))}")
    if result.get("status") == "official_match":
        lead = result["lead_disclosure"]
        print(f"- 공식 이벤트: {result['official_event_type']}")
        print(f"- 접수일: {lead['rcept_dt']}")
        print(f"- 보고서명: {lead['report_nm']}")
        print(f"- 링크: {lead['dart_url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenDART로 입력 문장의 기업 직접 이벤트를 공식 확인합니다.")
    parser.add_argument("--company", required=True)
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--sentence", required=True)
    parser.add_argument("--date", default=None)
    parser.add_argument("--before-days", type=int, default=30)
    parser.add_argument("--after-days", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = resolve_dart_event(
        args.company,
        args.ticker,
        args.sentence,
        event_date=args.date,
        before_days=args.before_days,
        after_days=args.after_days,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_summary(result)


if __name__ == "__main__":
    main()
