#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate and evaluate labelsets for the context engine.

This is a lightweight, generic testbench. It intentionally avoids RSS/LLM/API
calls so we can quickly measure whether the pipeline respects the product
charter: connection path first, no overclaiming, and explicit uncertainty.

The built-in 200 cases are only a starter taxonomy. Real usage should pass a
project-specific labelset via --labelset-json.
"""

import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = PROJECT_ROOT / "scripts" / "context_signal_pipeline.py"
spec = importlib.util.spec_from_file_location("context_signal_pipeline", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


COMPANIES = [
    {"company": "삼성전자", "ticker": "005930", "industry": "반도체/전자"},
    {"company": "SK하이닉스", "ticker": "000660", "industry": "반도체"},
    {"company": "카카오", "ticker": "035720", "industry": "플랫폼/인터넷"},
    {"company": "한화오션", "ticker": "042660", "industry": "조선"},
    {"company": "LG에너지솔루션", "ticker": "373220", "industry": "배터리"},
    {"company": "대한항공", "ticker": "003490", "industry": "항공"},
    {"company": "S-Oil", "ticker": "010950", "industry": "정유"},
    {"company": "현대차", "ticker": "005380", "industry": "자동차"},
]


EVENT_SLOTS = [
    {
        "event": "HBM 수요 확대",
        "date": "2025-04-04",
        "sentence": "{company} HBM 수요 확대 전망이 나왔는데 이미 주가가 많이 오른 상태야.",
        "origin": "산업",
        "direction_by_industry": {"반도체": "혼합 신호", "반도체/전자": "혼합 신호"},
        "default_direction": "불명확",
        "confirmation": "예상/전망",
        "distance_by_industry": {"반도체": "직접", "반도체/전자": "1단계 간접"},
        "default_distance": "관련 낮음",
        "required_data": ["실적", "가격지표", "수급"],
        "counter": "선반영",
    },
    {
        "event": "파운드리 수율 개선",
        "date": "2025-04-04",
        "sentence": "{company} 파운드리 수율 개선 보도가 나왔는데 TSMC 경쟁도 심해졌대.",
        "origin": "산업",
        "direction_by_industry": {"반도체/전자": "혼합 신호", "반도체": "불명확"},
        "default_direction": "관련 낮음",
        "confirmation": "뉴스 확인",
        "distance_by_industry": {"반도체/전자": "직접", "반도체": "관련 낮음"},
        "default_distance": "관련 낮음",
        "required_data": ["실적", "업종지수"],
        "counter": "경쟁 심화",
    },
    {
        "event": "오너 수사",
        "date": "2024-07-23",
        "sentence": "{company} 오너 수사 보도가 회사 지배구조에 악재야?",
        "origin": "오너/지배구조",
        "direction_by_industry": {"플랫폼/인터넷": "악재 신호"},
        "default_direction": "불명확",
        "confirmation": "뉴스 확인",
        "distance_by_industry": {"플랫폼/인터넷": "직접"},
        "default_distance": "관련 낮음",
        "required_data": ["공시", "정책 원문"],
        "counter": "개인 이슈와 법인 리스크 구분",
    },
    {
        "event": "LNG선 수주",
        "date": "2024-02-22",
        "sentence": "{company} LNG선 수주 공시가 났는데 후판 가격도 올랐대.",
        "origin": "기업 내부",
        "direction_by_industry": {"조선": "혼합 신호"},
        "default_direction": "관련 낮음",
        "confirmation": "공식 확인",
        "distance_by_industry": {"조선": "직접"},
        "default_distance": "관련 낮음",
        "required_data": ["공시", "실적", "원자재"],
        "counter": "비용 증가",
    },
    {
        "event": "미국 전기차 보조금 축소",
        "date": "2025-01-20",
        "sentence": "{company} 미국 전기차 보조금 축소 가능성이 수요에 어떤 신호야?",
        "origin": "정책",
        "direction_by_industry": {"배터리": "악재 신호", "자동차": "악재 신호"},
        "default_direction": "불명확",
        "confirmation": "예상/전망",
        "distance_by_industry": {"배터리": "1단계 간접", "자동차": "1단계 간접"},
        "default_distance": "관련 낮음",
        "required_data": ["정책 원문", "실적", "가격지표"],
        "counter": "정책 변경",
    },
    {
        "event": "국제유가 상승",
        "date": "2025-06-13",
        "sentence": "{company} 국제유가 급등 보도가 비용과 마진에 어떤 신호야?",
        "origin": "거시",
        "direction_by_industry": {"항공": "악재 신호", "정유": "혼합 신호", "자동차": "악재 신호"},
        "default_direction": "불명확",
        "confirmation": "데이터 확인",
        "distance_by_industry": {"항공": "1단계 간접", "정유": "1단계 간접", "자동차": "2단계 간접"},
        "default_distance": "관련 낮음",
        "required_data": ["유가", "실적", "환율/금리"],
        "counter": "가격 전가",
    },
    {
        "event": "중국 희토류 수출통제",
        "date": "2025-04-04",
        "sentence": "중국 희토류 수출통제 발표가 {company} 공급망에 직접 악재야?",
        "origin": "국제정세",
        "direction_by_industry": {"반도체": "악재 신호", "반도체/전자": "악재 신호", "배터리": "악재 신호", "자동차": "악재 신호"},
        "default_direction": "관련 낮음",
        "confirmation": "공식 확인",
        "distance_by_industry": {"반도체": "2단계 간접", "반도체/전자": "2단계 간접", "배터리": "2단계 간접", "자동차": "2단계 간접"},
        "default_distance": "관련 낮음",
        "required_data": ["정책 원문", "원자재", "공시"],
        "counter": "대체 조달",
    },
    {
        "event": "생산중단/파업",
        "date": "2025-09-03",
        "sentence": "{company} 노조 파업 가능성 보도가 생산중단으로 이어질 수 있대.",
        "origin": "기업 내부",
        "direction_by_industry": {"자동차": "악재 신호", "조선": "악재 신호"},
        "default_direction": "불명확",
        "confirmation": "예상/전망",
        "distance_by_industry": {"자동차": "직접", "조선": "직접"},
        "default_distance": "관련 낮음",
        "required_data": ["공시", "뉴스 확인"],
        "counter": "타결 가능성",
    },
    {
        "event": "플랫폼 규제 강화",
        "date": "2024-07-23",
        "sentence": "{company} 플랫폼 규제 강화 전망이 광고와 커머스 사업에 부담이야?",
        "origin": "정책",
        "direction_by_industry": {"플랫폼/인터넷": "악재 신호"},
        "default_direction": "관련 낮음",
        "confirmation": "예상/전망",
        "distance_by_industry": {"플랫폼/인터넷": "1단계 간접"},
        "default_distance": "관련 낮음",
        "required_data": ["정책 원문", "실적"],
        "counter": "규제 범위 확인",
    },
    {
        "event": "외국인 대량 순매도",
        "date": "2025-04-04",
        "sentence": "{company} 외국인 대량 순매도와 공매도 증가가 단기 수급에 어떤 신호야?",
        "origin": "수급",
        "direction_by_industry": {},
        "default_direction": "악재 신호",
        "confirmation": "데이터 확인",
        "distance_by_industry": {},
        "default_distance": "수급/감성 관련",
        "required_data": ["수급", "가격지표"],
        "counter": "기초체력과 수급 분리",
    },
]


NOISE_CASES = [
    "오늘 날씨가 좋아서 {company} 주가도 오를까?",
    "{company} 직원 식당 메뉴가 바뀌었다는데 호재야?",
    "커뮤니티에서 {company} 곧 대박이라는 글을 봤어.",
    "{company} 이름이 검색어에 떴는데 이유는 모르겠어.",
    "친구가 {company} 무조건 간다던데 이게 근거야?",
]


ORIGIN_MAP = {
    "기업 내부": "기업 내부",
    "재무/실적": "실적",
    "오너/지배구조": "오너/지배구조",
    "산업/섹터": "산업",
    "산업/경쟁구도": "산업",
    "정책/규제/국가전략": "정책",
    "국제정세/지정학": "국제정세",
    "국제정세/지정학 + 원자재/공급망": "국제정세",
    "거시경제/원자재": "거시",
    "제품 수요/고객사 수요": "산업",
    "분류 불가/확인 필요": "루머",
}


def expected_direction(slot: Dict, industry: str) -> str:
    return slot.get("direction_by_industry", {}).get(industry, slot.get("default_direction", "불명확"))


def expected_distance(slot: Dict, industry: str) -> str:
    return slot.get("distance_by_industry", {}).get(industry, slot.get("default_distance", "관련 낮음"))


def impact_level_from_distance(distance: str) -> int:
    if distance == "직접":
        return 0
    if "1단계" in distance or "1차" in distance:
        return 1
    if "2단계" in distance or "2차" in distance:
        return 2
    if "3단계" in distance or "3차" in distance:
        return 3
    if "테마" in distance or "수급/감성" in distance or "4차" in distance:
        return 4
    return 5


def impact_strength_from_level(level: int) -> str:
    return {0: "강함", 1: "중상", 2: "중간", 3: "낮음", 4: "낮음", 5: "매우 낮음"}.get(level, "매우 낮음")


def direction_permission_from_level(level: int) -> str:
    return "normal" if level <= 2 else "weak" if level in (3, 4) else "observe_only"


def generate_labelset(limit: int = 200) -> List[Dict]:
    cases: List[Dict] = []
    idx = 1
    for slot in EVENT_SLOTS:
        for company in COMPANIES:
            sentence = slot["sentence"].format(company=company["company"])
            direction = expected_direction(slot, company["industry"])
            distance = expected_distance(slot, company["industry"])
            impact_level = impact_level_from_distance(distance)
            cases.append({
                "id": f"LC{idx:03d}",
                "company": company["company"],
                "ticker": company["ticker"],
                "industry": company["industry"],
                "date": slot.get("date"),
                "sentence": sentence,
                "slot_event": slot["event"],
                "expected": {
                    "origin": slot["origin"],
                    "confirmation": slot["confirmation"],
                    "direction": direction,
                    "impact_distance": distance,
                    "impact_level": impact_level,
                    "impact_strength": impact_strength_from_level(impact_level),
                    "direction_permission": direction_permission_from_level(impact_level),
                    "company_relevance": "관련 낮음" if distance == "관련 낮음" else distance,
                    "required_data": slot["required_data"],
                    "safety": "매매추천 없음",
                },
            })
            idx += 1

    # Add mixed and noise variants until the requested size is reached.
    base_count = len(cases)
    for source in cases[:base_count]:
        if len(cases) >= limit:
            break
        mixed_sentence = f"{source['sentence']} 다만 {source['slot_event']} 기대가 이미 선반영됐을 수도 있대."
        mixed = dict(source)
        mixed["id"] = f"LC{idx:03d}"
        mixed["sentence"] = mixed_sentence
        mixed["expected"] = dict(source["expected"])
        if mixed["expected"]["direction"] in ("호재 신호", "악재 신호"):
            mixed["expected"]["direction"] = "혼합 신호"
        mixed["expected"]["required_data"] = list(dict.fromkeys(source["expected"]["required_data"] + ["가격지표", "수급"]))
        cases.append(mixed)
        idx += 1

    company_cycle = COMPANIES * 10
    noise_idx = 0
    while len(cases) < limit:
        company = company_cycle[noise_idx % len(company_cycle)]
        template = NOISE_CASES[noise_idx % len(NOISE_CASES)]
        cases.append({
            "id": f"LC{idx:03d}",
            "company": company["company"],
            "ticker": company["ticker"],
            "industry": company["industry"],
            "date": None,
            "sentence": template.format(company=company["company"]),
            "slot_event": "관련 낮음/노이즈",
            "expected": {
                "origin": "루머",
                "confirmation": "루머/보류",
                "direction": "불명확",
                "impact_distance": "관련 낮음",
                "impact_level": 5,
                "impact_strength": "매우 낮음",
                "direction_permission": "observe_only",
                "company_relevance": "관련 낮음",
                "required_data": ["공식 출처"],
                "safety": "매매추천 없음",
            },
        })
        idx += 1
        noise_idx += 1
    return cases[:limit]


def normalize_origin(origins: List[str]) -> str:
    for origin in origins:
        for needle, label in ORIGIN_MAP.items():
            if needle in origin:
                return label
    return "루머"


def normalize_direction(balance: str) -> str:
    return {
        "호재 중심": "호재 신호",
        "악재 중심": "악재 신호",
        "혼합": "혼합 신호",
        "확인 필요": "불명확",
        "관련 낮음": "관련 낮음",
    }.get(balance, "불명확")


def infer_confirmation(sentence: str, card: Dict) -> str:
    if card.get("official_confirmation"):
        return card["official_confirmation"]
    if any(word in sentence for word in ["루머", "커뮤니티", "친구", "대박", "무조건"]):
        return "루머/보류"
    if any(word in sentence for word in ["가능성", "전망", "예상", "이어질 수"]):
        return "예상/전망"
    if any(word in sentence for word in ["공시", "발표"]):
        return "공식 확인"
    if any(word in sentence for word in ["급등", "순매도", "공매도", "가격", "유가"]):
        return "데이터 확인"
    if any(word in sentence for word in ["보도"]):
        return "뉴스 확인"
    if card.get("issue_types") == ["분석 보류"]:
        return "루머/보류"
    return "뉴스 확인"


def infer_impact_distance(card: Dict) -> str:
    gate = card.get("context_relevance_gate") or {}
    if gate.get("impact_distance"):
        return gate["impact_distance"]
    profile = card.get("company_profile", {})
    industry = profile.get("industry", "미분류")
    sentence = card.get("input", "")
    company = card.get("company", "")
    issue_codes = set(card.get("input_issue_codes", []))
    if card.get("issue_types") == ["분석 보류"]:
        return "관련 낮음"
    if company and company in sentence and issue_codes & {"owner_legal", "order_contract", "strike"}:
        return "직접"
    if issue_codes & {"oil_price_up", "subsidy_cut", "rare_earth_control", "foundry_yield", "hbm_demand"}:
        if industry in ("반도체", "반도체/전자", "배터리", "항공", "정유", "자동차", "조선", "플랫폼/인터넷"):
            return "1단계 간접"
    return "관련 낮음"


def contains_forbidden_recommendation(text: str) -> bool:
    forbidden = ["매수하세요", "매도하세요", "사세요", "파세요", "목표가", "손절가", "무조건 오른다", "무조건 떨어진다"]
    return any(word in text for word in forbidden)


def predict(case: Dict, use_dart: bool = False, dart_before: int = 30, dart_after: int = 10) -> Dict:
    card = core.build_card(
        case["company"],
        case["ticker"],
        case["sentence"],
        event_date=case.get("date"),
        include_rss=False,
        use_llm=False,
        use_dart=use_dart,
        dart_before=dart_before,
        dart_after=dart_after,
    )
    serialized = json.dumps(card, ensure_ascii=False)
    gate = card.get("context_relevance_gate") or {}
    predicted_level = gate.get("impact_level", impact_level_from_distance(infer_impact_distance(card)))
    return {
        "origin": normalize_origin([card.get("official_origin")] if card.get("official_origin") else card.get("origins", [])),
        "confirmation": infer_confirmation(case["sentence"], card),
        "direction": normalize_direction(card.get("signal_balance", "")),
        "impact_distance": infer_impact_distance(card),
        "impact_level": predicted_level,
        "impact_strength": gate.get("impact_strength", impact_strength_from_level(predicted_level)),
        "direction_permission": gate.get("direction_permission", direction_permission_from_level(predicted_level)),
        "company_relevance": infer_impact_distance(card),
        "safety": "안전성 위반" if contains_forbidden_recommendation(serialized) else "매매추천 없음",
        "issue_types": card.get("issue_types", []),
        "questions_count": len(card.get("questions_to_check", [])),
        "guardrail": card.get("interpretation_guardrail"),
        "dart_status": (card.get("dart_event") or {}).get("status"),
        "official_event_type": (card.get("dart_event") or {}).get("official_event_type"),
    }


def score_case(case: Dict, prediction: Dict) -> Dict:
    expected = case["expected"]
    checks = {}
    for key in ["origin", "confirmation", "direction", "impact_distance", "impact_level", "impact_strength", "direction_permission", "safety"]:
        checks[key] = prediction.get(key) == expected.get(key)
    if expected.get("direction") == "불명확" and prediction.get("direction") == "관련 낮음":
        checks["direction"] = True
    if expected.get("direction") == "관련 낮음" and prediction.get("direction") == "불명확":
        checks["direction"] = True
    if expected.get("impact_distance") == "관련 낮음" and prediction.get("impact_distance") == "관련 낮음":
        checks["impact_distance"] = True
    expected_level = expected.get("impact_level")
    predicted_level = prediction.get("impact_level")
    checks["impact_level_within_1"] = (
        isinstance(expected_level, int)
        and isinstance(predicted_level, int)
        and abs(expected_level - predicted_level) <= 1
    )
    failure_types = []
    if not checks["origin"]:
        failure_types.append("출발점 오분류")
    if not checks["confirmation"]:
        failure_types.append("확인도 과신/오분류")
    if not checks["direction"]:
        failure_types.append("방향성 뒤집힘/과단순화")
    if expected.get("impact_distance") == "관련 낮음" and prediction.get("impact_distance") != "관련 낮음":
        failure_types.append("관련 낮음 오판")
    elif not checks["impact_distance"]:
        failure_types.append("영향 거리 과대/과소평가")
    if not checks["impact_level"]:
        failure_types.append("영향 단계 오분류")
    if not checks["direction_permission"]:
        failure_types.append("방향 허용 정책 오분류")
    if expected.get("direction_permission") == "observe_only" and prediction.get("direction") in ("호재 신호", "악재 신호", "혼합 신호"):
        failure_types.append("관찰 전용 단계에서 방향성 과판단")
    if not checks["safety"]:
        failure_types.append("안전성 위반")
    if prediction.get("questions_count", 0) < 3:
        failure_types.append("확인 질문 부족")
    return {
        "id": case["id"],
        "company": case["company"],
        "sentence": case["sentence"],
        "slot_event": case["slot_event"],
        "expected": expected,
        "prediction": prediction,
        "checks": checks,
        "pass": all(checks.values()) and prediction.get("questions_count", 0) >= 3,
        "failure_types": failure_types,
    }


def summarize(results: List[Dict]) -> Dict:
    total = len(results)
    metrics = {}
    for key in ["origin", "confirmation", "direction", "impact_distance", "impact_level", "impact_level_within_1", "impact_strength", "direction_permission", "safety"]:
        metrics[key] = {
            "correct": sum(1 for item in results if item["checks"].get(key)),
            "total": total,
            "accuracy": round(sum(1 for item in results if item["checks"].get(key)) / total, 4),
        }
    related_low = [item for item in results if item["expected"].get("impact_distance") == "관련 낮음"]
    related_low_ok = sum(1 for item in related_low if item["prediction"].get("impact_distance") == "관련 낮음")
    observe_only = [item for item in results if item["expected"].get("direction_permission") == "observe_only"]
    observe_only_ok = sum(1 for item in observe_only if item["prediction"].get("direction") not in ("호재 신호", "악재 신호", "혼합 신호"))
    failure_counts: Dict[str, int] = {}
    for item in results:
        for failure in item["failure_types"]:
            failure_counts[failure] = failure_counts.get(failure, 0) + 1
    return {
        "total": total,
        "passed": sum(1 for item in results if item["pass"]),
        "pass_rate": round(sum(1 for item in results if item["pass"]) / total, 4),
        "metrics": metrics,
        "related_low_guard": {
            "correct": related_low_ok,
            "total": len(related_low),
            "accuracy": round(related_low_ok / len(related_low), 4) if related_low else None,
        },
        "observe_only_guard": {
            "correct": observe_only_ok,
            "total": len(observe_only),
            "accuracy": round(observe_only_ok / len(observe_only), 4) if observe_only else None,
        },
        "dart": {
            "official_match": sum(1 for item in results if item["prediction"].get("dart_status") == "official_match"),
            "not_found": sum(1 for item in results if item["prediction"].get("dart_status") == "not_found"),
            "skipped": sum(1 for item in results if item["prediction"].get("dart_status") == "skipped"),
            "error": sum(1 for item in results if item["prediction"].get("dart_status") == "error"),
        },
        "failure_counts": dict(sorted(failure_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def save_json(payload: Dict, path: Optional[str]) -> Path:
    if path:
        output = Path(path)
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = PROJECT_ROOT / "output" / "labelset" / f"{stamp}_labelset_eval.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def save_markdown(payload: Dict, path: Optional[str]) -> Path:
    if path:
        output = Path(path)
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        output = PROJECT_ROOT / "output" / "labelset" / f"{stamp}_labelset_eval.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = payload["summary"]
    lines = [
        "# 라벨셋 평가 리포트",
        "",
        f"- 생성시각: {payload['generated_at']}",
        f"- 전체 케이스: {summary['total']}",
        f"- 전체 통과: {summary['passed']} / {summary['total']} ({summary['pass_rate']:.1%})",
        "",
        "## 라벨별 정확도",
        "",
        "| 라벨 | 정확 | 전체 | 정확도 |",
        "|---|---:|---:|---:|",
    ]
    for key, metric in summary["metrics"].items():
        lines.append(f"| {key} | {metric['correct']} | {metric['total']} | {metric['accuracy']:.1%} |")
    guard = summary["related_low_guard"]
    guard_accuracy = f"{guard['accuracy']:.1%}" if guard["accuracy"] is not None else "N/A"
    observe_guard = summary["observe_only_guard"]
    observe_guard_accuracy = f"{observe_guard['accuracy']:.1%}" if observe_guard["accuracy"] is not None else "N/A"
    lines += [
        f"| 관련 낮음 방어 | {guard['correct']} | {guard['total']} | {guard_accuracy} |",
        f"| 5차 관찰 전용 방어 | {observe_guard['correct']} | {observe_guard['total']} | {observe_guard_accuracy} |",
        "",
        "## DART 현실 확인",
        "",
        "| 상태 | 건수 |",
        "|---|---:|",
    ]
    for status, count in summary.get("dart", {}).items():
        lines.append(f"| {status} | {count} |")
    lines += [
        "",
        "## 실패 유형",
        "",
        "| 실패 유형 | 건수 |",
        "|---|---:|",
    ]
    for failure, count in summary["failure_counts"].items():
        lines.append(f"| {failure} | {count} |")
    lines += [
        "",
        "## 대표 실패 20건",
        "",
        "| ID | 회사 | 입력 | 기대 단계 | 실제 단계 | 기대 방향 | 실제 방향 | 실패 유형 |",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    failures = [item for item in payload["results"] if not item["pass"]][:20]
    for item in failures:
        sentence = item["sentence"].replace("|", "/")
        lines.append(
            f"| {item['id']} | {item['company']} | {sentence} | "
            f"{item['expected'].get('impact_level')} | {item['prediction'].get('impact_level')} | "
            f"{item['expected']['direction']} | {item['prediction']['direction']} | {', '.join(item['failure_types'])} |"
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


LABELSET_TEMPLATE = {
    "allowed_values": {
        "origin": ["기업 내부", "실적", "오너/지배구조", "산업", "정책", "국제정세", "거시", "수급", "감성", "루머"],
        "confirmation": ["공식 확인", "데이터 확인", "뉴스 확인", "예상/전망", "루머/보류"],
        "direction": ["호재 신호", "악재 신호", "혼합 신호", "불명확", "관련 낮음"],
        "impact_distance": ["직접", "1단계 간접", "2단계 간접", "3단계 이상", "테마 확장", "관련 낮음", "수급/감성 관련"],
        "impact_level": [0, 1, 2, 3, 4, 5],
        "impact_strength": ["강함", "중상", "중간", "낮음", "매우 낮음"],
        "direction_permission": ["normal", "weak", "observe_only"],
        "company_relevance": ["직접 관련", "산업 관련", "공급망 관련", "수급/감성 관련", "관련 낮음"],
        "safety": ["매매추천 없음"],
    },
    "cases": [
        {
            "id": "CASE001",
            "company": "SK하이닉스",
            "ticker": "000660",
            "industry": "반도체",
            "sentence": "SK하이닉스 HBM 수요 확대 전망이 나왔는데 이미 주가가 많이 오른 상태야.",
            "slot_event": "HBM 수요 확대와 선반영 가능성",
            "expected": {
                "origin": "산업",
                "confirmation": "예상/전망",
                "direction": "혼합 신호",
                "impact_distance": "직접",
                "impact_level": 0,
                "impact_strength": "강함",
                "direction_permission": "normal",
                "company_relevance": "직접 관련",
                "required_data": ["실적", "가격지표", "수급"],
                "safety": "매매추천 없음",
            },
        }
    ]
}


def load_labelset(path: str) -> List[Dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases", payload if isinstance(payload, list) else [])
    normalized = []
    for index, case in enumerate(cases, start=1):
        expected = case.get("expected", {})
        normalized.append({
            "id": case.get("id") or f"CASE{index:03d}",
            "company": case["company"],
            "ticker": case.get("ticker"),
            "industry": case.get("industry", "미분류"),
            "date": case.get("date"),
            "sentence": case["sentence"],
            "slot_event": case.get("slot_event") or case.get("event") or "사용자 정의",
            "expected": {
                "origin": expected.get("origin", "루머"),
                "confirmation": expected.get("confirmation", "루머/보류"),
                "direction": expected.get("direction", "불명확"),
                "impact_distance": expected.get("impact_distance", "관련 낮음"),
                "impact_level": expected.get("impact_level", impact_level_from_distance(expected.get("impact_distance", "관련 낮음"))),
                "impact_strength": expected.get("impact_strength", impact_strength_from_level(expected.get("impact_level", impact_level_from_distance(expected.get("impact_distance", "관련 낮음"))))),
                "direction_permission": expected.get("direction_permission", direction_permission_from_level(expected.get("impact_level", impact_level_from_distance(expected.get("impact_distance", "관련 낮음"))))),
                "company_relevance": expected.get("company_relevance", expected.get("impact_distance", "관련 낮음")),
                "required_data": expected.get("required_data", []),
                "safety": expected.get("safety", "매매추천 없음"),
            },
        })
    return normalized


def save_template(path: str) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(LABELSET_TEMPLATE, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def run(limit: int, labelset_json: Optional[str] = None, use_dart: bool = False, dart_before: int = 30, dart_after: int = 10) -> Dict:
    if labelset_json:
        cases = load_labelset(labelset_json)
        source = str(Path(labelset_json))
    else:
        cases = generate_labelset(limit)
        source = "built_in_starter_taxonomy"
    results = [score_case(case, predict(case, use_dart=use_dart, dart_before=dart_before, dart_after=dart_after)) for case in cases]
    return {
        "status": "ok",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "description": "RSS/LLM/API 없이 현재 context pipeline을 라벨셋에 태운 기준선 평가입니다.",
        "labelset_source": source,
        "use_dart": use_dart,
        "dart_before": dart_before,
        "dart_after": dart_after,
        "cases": cases,
        "results": results,
        "summary": summarize(results),
    }


def print_summary(payload: Dict, json_path: Path, md_path: Path) -> None:
    summary = payload["summary"]
    print("# 라벨셋 평가 결과")
    print(f"- 전체 통과: {summary['passed']} / {summary['total']} ({summary['pass_rate']:.1%})")
    for key, metric in summary["metrics"].items():
        print(f"- {key}: {metric['correct']} / {metric['total']} ({metric['accuracy']:.1%})")
    guard = summary["related_low_guard"]
    guard_accuracy = f"{guard['accuracy']:.1%}" if guard["accuracy"] is not None else "N/A"
    print(f"- 관련 낮음 방어: {guard['correct']} / {guard['total']} ({guard_accuracy})")
    observe_guard = summary["observe_only_guard"]
    observe_guard_accuracy = f"{observe_guard['accuracy']:.1%}" if observe_guard["accuracy"] is not None else "N/A"
    print(f"- 5차 관찰 전용 방어: {observe_guard['correct']} / {observe_guard['total']} ({observe_guard_accuracy})")
    if summary.get("dart"):
        print("- DART:")
        for status, count in summary["dart"].items():
            print(f"  - {status}: {count}")
    print("- 실패 유형:")
    for failure, count in summary["failure_counts"].items():
        print(f"  - {failure}: {count}")
    print(f"JSON 저장: {json_path}")
    print(f"Markdown 저장: {md_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="라벨셋을 생성/불러오고 현재 context pipeline을 평가합니다.")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--labelset-json", default=None, help="외부 라벨셋 JSON. 없으면 내장 starter taxonomy를 사용합니다.")
    parser.add_argument("--write-template", default=None, help="외부 라벨셋 작성용 JSON 템플릿만 저장하고 종료합니다.")
    parser.add_argument("--use-dart", action="store_true", help="DART 공식 이벤트 resolver를 포함해 평가합니다.")
    parser.add_argument("--dart-before", type=int, default=30)
    parser.add_argument("--dart-after", type=int, default=10)
    parser.add_argument("--json-output", default=None)
    parser.add_argument("--md-output", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.write_template:
        path = save_template(args.write_template)
        print(f"라벨셋 템플릿 저장: {path}")
        return
    payload = run(args.limit, args.labelset_json, args.use_dart, args.dart_before, args.dart_after)
    json_path = save_json(payload, args.json_output)
    md_path = save_markdown(payload, args.md_output)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_summary(payload, json_path, md_path)


if __name__ == "__main__":
    main()
