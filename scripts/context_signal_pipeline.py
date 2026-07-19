import argparse
import datetime as dt
import json
import urllib.parse
from email.utils import parsedate_to_datetime
from dataclasses import dataclass, asdict
from typing import Optional


DEPENDENCY_HELP = """
필요 패키지가 없습니다. 아래처럼 설치한 뒤 다시 실행하세요.

python3 -m pip install -r requirements-pipeline.txt
""".strip()


@dataclass
class Signal:
    name: str
    direction: str
    confidence: str
    reason: str


RULES = [
    {
        "keywords": ["공장증설", "증설", "신규 시설투자", "시설투자", "공장"],
        "origin": "기업 내부",
        "issue_type": "공장증설/신규 시설투자",
        "positive": [
            ("생산능력 확대", "추론", "증설은 공급능력 확대 신호일 수 있음"),
            ("장기 매출 성장 기대", "확인 필요", "증설 제품의 수요가 충분하면 성장 신호가 될 수 있음"),
        ],
        "negative": [
            ("CAPEX 부담", "추론", "증설은 투자비 지출을 동반함"),
            ("감가상각 증가", "추론", "설비 가동 이후 비용 부담이 커질 수 있음"),
            ("차입비용 부담", "확인 필요", "외부 차입으로 투자하면 금리 영향을 받을 수 있음"),
        ],
        "questions": [
            "증설 제품의 수요가 실제로 증가 중인가?",
            "투자 자금은 내부자금인가, 차입인가?",
            "정부 보조금 또는 세제 혜택이 있는가?",
            "가동 시점과 매출 기여 시점은 언제인가?",
        ],
    },
    {
        "keywords": ["실적쇼크", "어닝쇼크", "실적 쇼크", "실적 부진"],
        "origin": "재무/실적",
        "issue_type": "실적 쇼크/업황 둔화 신호",
        "positive": [],
        "negative": [
            ("업황 둔화 가능성", "예상/뉴스 확인", "경쟁사 실적쇼크는 같은 업종 수요 둔화 신호일 수 있음"),
            ("투자심리 악화", "예상/뉴스 확인", "동종 기업에 대한 기대가 낮아질 수 있음"),
        ],
        "questions": [
            "경쟁사 실적 부진이 일회성 비용 때문인가, 업황 문제인가?",
            "해당 회사와 경쟁사의 제품/고객군이 겹치는가?",
            "업종 전체 실적 전망도 함께 낮아졌는가?",
        ],
    },
    {
        "keywords": ["희토류", "수출 제한", "수출통제", "수출 통제"],
        "origin": "국제정세/지정학 + 원자재/공급망",
        "issue_type": "원자재 공급망 제한",
        "positive": [
            ("대체 소재/공급망 다변화 기업 관심", "확인 필요", "공급망 재편 과정에서 일부 기업은 관심을 받을 수 있음"),
        ],
        "negative": [
            ("원자재 조달 부담", "공식/데이터 확인 필요", "수출 제한은 공급 부족 또는 가격 상승으로 이어질 수 있음"),
            ("부품/장비 비용 상승 가능성", "추론", "희토류가 들어가는 부품·장비의 비용 부담 가능성"),
            ("공급망 불확실성 증가", "추론", "직접 사용 여부와 무관하게 공급망 리스크가 커질 수 있음"),
        ],
        "path": [
            "중국 희토류 수출 제한",
            "희토류 공급 부족/가격 상승",
            "반도체·전기차·방산 부품/장비 비용 부담 가능",
            "대상 기업의 공급망·원가 리스크 가능",
        ],
        "questions": [
            "해당 기업이 희토류 관련 부품에 얼마나 노출되어 있는가?",
            "대체 조달처나 장기 계약이 있는가?",
            "실제 희토류 가격이 상승했는가?",
            "회사가 직접 영향 또는 대응 계획을 밝힌 적이 있는가?",
        ],
    },
    {
        "keywords": ["파업", "임단협", "노조", "생산 차질", "생산차질"],
        "origin": "기업 내부",
        "issue_type": "비확정 선행 신호 / 생산중단 후보",
        "positive": [
            ("타결/생산재개 가능성", "확인 필요", "노사 이슈는 합의나 철회로 끝날 수도 있음"),
        ],
        "negative": [
            ("생산중단 가능성", "확인 필요", "파업 우려는 생산중단 후보지만 공식 생산중단은 아님"),
            ("생산 차질 우려", "뉴스/예상", "보도나 전망만으로는 기준일 확정이 어려움"),
        ],
        "questions": [
            "OpenDART 또는 회사 공식 생산중단 공시가 있는가?",
            "실제 조업중단일과 생산재개일이 확인되는가?",
            "파업 우려인지, 실제 생산중단인지 구분했는가?",
        ],
    },
    {
        "keywords": ["유가", "국제유가", "원유", "WTI", "브렌트"],
        "origin": "거시경제/원자재",
        "issue_type": "에너지 비용 신호",
        "positive": [
            ("유류할증료/가격 전가 가능성", "확인 필요", "일부 업종은 비용 상승분을 가격에 반영할 수 있음"),
        ],
        "negative": [
            ("연료비/물류비 부담", "데이터 확인 필요", "유가 상승은 에너지 비용 비중이 큰 업종에 부담"),
            ("마진 압박 가능성", "추론", "비용 전가가 어렵다면 이익률에 부담"),
        ],
        "questions": [
            "해당 회사의 원가에서 연료비/물류비 비중이 큰가?",
            "비용 상승분을 가격에 전가할 수 있는 구조인가?",
            "환율 변화가 동시에 비용 부담을 키우는가?",
        ],
    },
    {
        "keywords": ["보조금", "지원금", "세액공제", "IRA", "국가전략", "지원 정책"],
        "origin": "정책/규제/국가전략",
        "issue_type": "정책 지원 신호",
        "positive": [
            ("수요 확대 가능성", "공식 확인 필요", "보조금은 소비자 또는 고객사의 구매 여력을 높일 수 있음"),
            ("투자비 부담 완화", "공식 확인 필요", "세액공제나 보조금은 CAPEX 부담을 낮출 수 있음"),
        ],
        "negative": [
            ("조건 미충족 리스크", "확인 필요", "정책 수혜 조건을 충족하지 못하면 기대가 낮아질 수 있음"),
            ("정책 변경 리스크", "확인 필요", "정권·예산·규정 변화에 따라 지속성이 흔들릴 수 있음"),
        ],
        "questions": [
            "정책 적용 대상에 해당 회사 또는 고객사가 포함되는가?",
            "수혜 조건과 기간은 무엇인가?",
            "이미 주가에 선반영된 기대는 없는가?",
        ],
    },
]


EFFECT_LEVELS = {
    0: "0차 효과: 기준 사건",
    1: "1차 효과: 직접 작용",
    2: "2차 효과: 산업/공급망 파급",
    3: "3차 효과: 외부환경 결합",
    4: "4차 효과: 시장 반응/심리",
}

EMOTION_KEYWORDS = {
    "공포": ["위기", "비상", "급락", "패닉", "붕괴", "손실", "빨간불", "차질", "중단", "공급난", "품귀", "흔들", "봉쇄"],
    "불확실성": ["우려", "가능성", "전망", "불투명", "난항", "변수", "예의주시", "긴장", "통제"],
    "실망": ["부진", "적자", "하회", "쇼크", "둔화", "제외", "축소"],
    "피로감": ["장기화", "반복", "지연", "교착", "난항"],
    "충격": ["구속", "압수수색", "사고", "화재", "리콜", "중단"],
    "기대": ["수혜", "확대", "성장", "개선", "호조", "수주", "최대", "강세"],
    "안도": ["타결", "재개", "해소", "완화", "승인", "합의", "정상화"],
    "과열": ["급등", "폭등", "상한가", "테마", "몰림", "부각"],
    "회복 기대": ["반등", "회복", "턴어라운드", "정상화"],
    "관망": ["주시", "검토", "기다림", "관망", "예의주시"],
}

POSITIVE_KEYWORDS = ["수주", "공급계약", "승인", "흑자", "개선", "확대", "보조금", "수혜", "타결", "재개", "완화", "강세", "반등", "성장"]
NEGATIVE_KEYWORDS = ["파업", "생산 차질", "생산중단", "적자", "쇼크", "구속", "압수수색", "규제", "제외", "유가 상승", "급등", "부담", "우려", "차질", "하락", "순매도", "중단", "통제", "공급난", "품귀", "흔들", "봉쇄", "긴장", "손실"]
UNCERTAIN_KEYWORDS = ["우려", "가능성", "전망", "예상", "검토", "관측", "설", "루머", "불투명"]
CONFIRMED_KEYWORDS = ["공시", "발표", "체결", "승인", "결정", "확정", "구속", "판결", "돌입", "중단"]

CHANNEL_KEYWORDS = {
    "생산": ["생산", "공장", "가동", "파업", "조업"],
    "매출/계약": ["수주", "계약", "매출", "인도", "납품"],
    "비용/마진": ["유가", "비용", "원가", "마진", "감가상각", "차입"],
    "공급망": ["희토류", "공급망", "부품", "조달", "수출통제", "수출 제한"],
    "정책/규제": ["보조금", "규제", "정책", "IRA", "세액공제", "관세"],
    "지배구조/법률": ["오너", "구속", "수사", "압수수색", "경영권", "대표"],
    "수급/심리": ["주가", "순매도", "순매수", "외국인", "기관", "거래량", "급등", "하락"],
    "업황/경쟁": ["경쟁", "업황", "경쟁사", "TSMC", "마이크론", "기아", "삼성중공업"],
}

HISTORICAL_CASES = [
    {
        "case_id": "hyundai_strike_2025_09_03",
        "company": "현대차",
        "date": "2025-09-03",
        "title": "현대차 파업/생산 차질",
        "keywords": ["현대차", "파업", "생산 차질", "생산중단", "노조"],
        "effect_levels": [0, 1, 3, 4],
        "emotions": ["공포", "불확실성", "피로감"],
        "price_note": "+10영업일 -2.48%",
        "context": ["공식 생산중단 공시 확인", "부분파업", "관세/수출 일정 부담 뉴스 동반", "이후 생산재개/타결 확인 필요"],
    },
    {
        "case_id": "samsung_rare_earth_2025_04",
        "company": "삼성전자",
        "date": "2025-04-04",
        "title": "중국 희토류 수출 제한/반도체 공급망",
        "keywords": ["삼성전자", "희토류", "수출 제한", "수출통제", "반도체", "공급망"],
        "effect_levels": [2, 3, 4],
        "emotions": ["불확실성", "공포", "관망"],
        "price_note": "+10영업일 -1.43%",
        "context": ["삼성전자 직접 사건은 아님", "공급망 간접 영향", "미중 관세/수출통제 맥락"],
    },
    {
        "case_id": "korean_air_oil_2025_06",
        "company": "대한항공",
        "date": "2025-06-13",
        "title": "유가 상승/항공 비용 부담",
        "keywords": ["대한항공", "유가", "항공", "중동", "유류할증료"],
        "effect_levels": [1, 3, 4],
        "emotions": ["불확실성", "공포"],
        "price_note": "+10영업일 +8.62%",
        "context": ["유가 부담과 여행 수요/유류할증료를 함께 봐야 함", "중동 분쟁 뉴스 동반"],
    },
    {
        "case_id": "lges_subsidy_2025_01",
        "company": "LG에너지솔루션",
        "date": "2025-01-20",
        "title": "배터리 보조금/IRA 정책 변화",
        "keywords": ["LG에너지솔루션", "LG엔솔", "보조금", "IRA", "배터리", "전기차"],
        "effect_levels": [0, 1, 3, 4],
        "emotions": ["기대", "불확실성", "실망"],
        "price_note": "+10영업일 -9.31%",
        "context": ["보조금 수혜 기대와 제외/축소 리스크가 공존", "실적/설비투자 뉴스 동반"],
    },
    {
        "case_id": "hanwha_ocean_order_2024_02_22",
        "company": "한화오션",
        "date": "2024-02-22",
        "title": "LNG선 수주/조선 업황",
        "keywords": ["한화오션", "LNG선", "수주", "조선", "계약"],
        "effect_levels": [0, 1, 2, 4],
        "emotions": ["기대", "과열"],
        "price_note": "+10영업일 +3.68%",
        "context": ["수주 기대와 조선 업황 뉴스 동반", "경쟁사/선종 뉴스가 섞일 수 있음"],
    },
]


def contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys([value for value in values if value]))


def classify_news_item(title: str, company: str, sentence: str) -> dict:
    text = f"{title} {sentence}"
    channels = [name for name, keywords in CHANNEL_KEYWORDS.items() if contains_any(text, keywords)]
    emotions = [name for name, keywords in EMOTION_KEYWORDS.items() if contains_any(text, keywords)]

    if contains_any(text, POSITIVE_KEYWORDS) and contains_any(text, NEGATIVE_KEYWORDS):
        direction = "혼합 신호"
    elif contains_any(text, POSITIVE_KEYWORDS):
        direction = "호재 신호"
    elif contains_any(text, NEGATIVE_KEYWORDS):
        direction = "악재 신호"
    else:
        direction = "불명확"

    if contains_any(text, CONFIRMED_KEYWORDS):
        confidence = "뉴스 확인/공식 확인 필요"
    elif contains_any(text, UNCERTAIN_KEYWORDS):
        confidence = "예상/전망"
    else:
        confidence = "뉴스 확인"

    if company and company in title:
        relevance = "직접 관련"
    elif contains_any(text, ["업계", "업종", "반도체", "배터리", "항공", "조선", "자동차"]):
        relevance = "업종/공급망 관련"
    elif contains_any(text, ["중국", "미국", "중동", "관세", "유가", "금리", "환율", "보조금", "IRA"]):
        relevance = "거시/정책 관련"
    else:
        relevance = "관련성 확인 필요"

    level = 4
    if company and company in title and contains_any(text, ["파업", "구속", "수주", "공시", "발표", "생산중단", "보조금 제외", "적자전환"]):
        level = 0
    if contains_any(text, ["생산 차질", "생산 중단", "생산중단", "유류할증료", "연료비", "원가", "마진", "실적", "적자", "수주"]):
        level = min(level, 1)
    if contains_any(text, ["부품", "협력사", "그룹", "기아", "공급망", "반도체", "배터리", "방산", "경쟁", "업황"]):
        level = min(level, 2)
    if contains_any(text, ["중국", "미국", "중동", "관세", "수출통제", "수출 제한", "유가", "금리", "환율", "보조금", "IRA", "전쟁", "분쟁"]):
        level = min(level, 3)
    if contains_any(text, ["주가", "순매도", "순매수", "급등", "하락", "테마", "투자심리"]):
        level = 4

    return {
        "effect_level": level,
        "effect_label": EFFECT_LEVELS[level],
        "direction": direction,
        "confidence": confidence,
        "relevance": relevance,
        "channels": unique(channels),
        "emotions": unique(emotions),
        "reason": "뉴스 제목의 키워드를 기준으로 한 1차 룰 기반 분류입니다.",
    }


def enrich_rss_news(rss: dict, company: str, sentence: str) -> dict:
    if rss.get("status") != "ok":
        return rss
    summary = {str(level): {"label": EFFECT_LEVELS[level], "count": 0, "items": []} for level in EFFECT_LEVELS}
    emotion_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    for item in rss.get("items", []):
        signal = classify_news_item(item.get("title", ""), company, sentence)
        item["signal"] = signal
        level_key = str(signal["effect_level"])
        summary[level_key]["count"] += 1
        summary[level_key]["items"].append(item)
        direction_counts[signal["direction"]] = direction_counts.get(signal["direction"], 0) + 1
        for emotion in signal.get("emotions", []):
            emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
    rss["effect_summary"] = summary
    rss["emotion_counts"] = emotion_counts
    rss["direction_counts"] = direction_counts
    return rss


def assess_pre_event_reflection(price: dict, rss: dict) -> dict:
    score = 0
    reasons = []
    price_checks = []
    if price.get("status") == "ok":
        for key, threshold in (("10", 5.0), ("5", 3.0), ("3", 2.0)):
            item = price.get("pre_event", {}).get(key, {})
            if item and item.get("status") != "missing":
                pct = item.get("change_pct", 0.0)
                price_checks.append(item)
                if abs(pct) >= threshold:
                    score += 1
                    direction = "상승" if pct > 0 else "하락"
                    reasons.append(f"T-{key}~T-1 구간 주가 {direction} 폭이 {threshold:.0f}% 기준을 넘었습니다({pct:.2f}%).")
    pre_items = rss.get("buckets", {}).get("pre_window", []) if rss.get("status") == "ok" else []
    if len(pre_items) >= 3:
        score += 1
        reasons.append(f"기준일 전 관련 뉴스 후보가 {len(pre_items)}건입니다.")
    emotional_pre = [item for item in pre_items if item.get("signal", {}).get("emotions")]
    if len(emotional_pre) >= 2:
        score += 1
        reasons.append(f"기준일 전 감정 신호가 있는 뉴스가 {len(emotional_pre)}건입니다.")

    if score >= 4:
        label = "높음"
    elif score >= 2:
        label = "중간"
    else:
        label = "낮음"
    return {
        "score": score,
        "label": label,
        "price_checks": price_checks,
        "pre_news_count": len(pre_items),
        "pre_emotional_news_count": len(emotional_pre),
        "reasons": reasons or ["기준일 전 가격/뉴스/감정 신호만으로는 선반영 가능성이 뚜렷하지 않습니다."],
        "caution": "선반영은 확정 판정이 아니라 가능성 평가입니다. 다른 이슈로 인한 가격 변동일 수 있습니다.",
    }


def match_historical_case(company: str, sentence: str, card: dict) -> dict:
    text = f"{company} {sentence}"
    current_levels = set()
    rss = card.get("rss_news", {})
    if rss.get("status") == "ok":
        current_levels = {item.get("signal", {}).get("effect_level") for item in rss.get("items", []) if item.get("signal")}
        current_levels.discard(None)
    current_emotions = set(rss.get("emotion_counts", {}).keys()) if rss.get("status") == "ok" else set()

    candidates = []
    for case in HISTORICAL_CASES:
        keyword_hits = sum(1 for keyword in case["keywords"] if keyword.lower() in text.lower())
        company_bonus = 2 if company and (company == case["company"] or company in case["keywords"]) else 0
        level_overlap = len(current_levels.intersection(set(case["effect_levels"])))
        emotion_overlap = len(current_emotions.intersection(set(case["emotions"])))
        score = keyword_hits + company_bonus + level_overlap + emotion_overlap
        if score > 0:
            candidates.append((score, case))
    if not candidates:
        return {"status": "no_match", "reason": "현재 입력과 비교할 수 있는 내장 과거 사례가 아직 없습니다."}
    candidates.sort(key=lambda item: item[0], reverse=True)
    score, case = candidates[0]
    case_levels = set(case["effect_levels"])
    return {
        "status": "ok",
        "score": score,
        "case": case,
        "common_effect_levels": sorted(current_levels.intersection(case_levels)),
        "current_only_effect_levels": sorted(current_levels - case_levels),
        "past_only_effect_levels": sorted(case_levels - current_levels),
        "common_emotions": sorted(current_emotions.intersection(set(case["emotions"]))),
        "current_only_emotions": sorted(current_emotions - set(case["emotions"])),
        "comparison_warning": "과거 사례의 가격 반응을 현재에 그대로 대입하면 안 됩니다. 공통점보다 현재와 과거의 차이를 확인해야 합니다.",
    }


def normalize_ticker_for_fdr(ticker: Optional[str]) -> Optional[str]:
    if not ticker:
        return None
    return ticker.replace(".KS", "").replace(".KQ", "").strip()


def fetch_daily_prices(ticker: Optional[str], event_date: str, before_days: int = 20, after_days: int = 30) -> dict:
    if not ticker:
        return {"status": "skipped", "reason": "종목코드가 없어 주가 데이터를 건너뜁니다."}
    try:
        import FinanceDataReader as fdr
    except Exception as exc:
        return {"status": "missing_dependency", "package": "FinanceDataReader", "reason": str(exc), "help": DEPENDENCY_HELP}

    code = normalize_ticker_for_fdr(ticker)
    base = dt.datetime.strptime(event_date, "%Y-%m-%d").date()
    start = base - dt.timedelta(days=before_days)
    end = base + dt.timedelta(days=after_days)
    try:
        df = fdr.DataReader(code, start.isoformat(), end.isoformat())
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}
    if df.empty:
        return {"status": "empty", "reason": "해당 기간의 가격 데이터를 찾지 못했습니다."}

    rows = []
    for idx, row in df.iterrows():
        rows.append(
            {
                "date": idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10],
                "open": float(row.get("Open", 0)),
                "high": float(row.get("High", 0)),
                "low": float(row.get("Low", 0)),
                "close": float(row.get("Close", 0)),
                "volume": int(row.get("Volume", 0)),
            }
        )

    base_idx = None
    for i, row in enumerate(rows):
        if row["date"] >= event_date:
            base_idx = i
            break
    if base_idx is None:
        return {"status": "error", "reason": "기준일 이후 거래일을 찾지 못했습니다."}

    base_row = rows[base_idx]
    pre_event = {}
    previous_idx = base_idx - 1
    for n in (3, 5, 10):
        start_idx = base_idx - n
        if start_idx < 0 or previous_idx < 0:
            pre_event[str(n)] = {"status": "missing"}
            continue
        start = rows[start_idx]
        previous = rows[previous_idx]
        change = previous["close"] - start["close"]
        pct = change / start["close"] * 100 if start["close"] else 0
        pre_event[str(n)] = {
            "window": f"T-{n}~T-1",
            "start_date": start["date"],
            "end_date": previous["date"],
            "start_close": start["close"],
            "end_close": previous["close"],
            "change": change,
            "change_pct": pct,
        }

    offsets = {}
    for n in (3, 5, 10):
        target_idx = base_idx + n
        if target_idx >= len(rows):
            offsets[str(n)] = {"status": "missing"}
            continue
        target = rows[target_idx]
        change = target["close"] - base_row["close"]
        pct = change / base_row["close"] * 100 if base_row["close"] else 0
        offsets[str(n)] = {
            "date": target["date"],
            "close": target["close"],
            "change": change,
            "change_pct": pct,
        }

    return {
        "status": "ok",
        "source": "FinanceDataReader",
        "ticker": ticker,
        "normalized_ticker": code,
        "event_date": event_date,
        "base_date": base_row["date"],
        "base_close": base_row["close"],
        "pre_event": pre_event,
        "offsets": offsets,
    }


def extract_query_terms(company: str, sentence: str) -> list[str]:
    terms = [company]
    for keyword in ["희토류", "수출 제한", "공장증설", "실적쇼크", "파업", "생산 차질", "유가", "보조금"]:
        if keyword in sentence:
            terms.append(keyword)
    if len(terms) == 1:
        terms.extend(sentence.split()[:3])
    return list(dict.fromkeys([term for term in terms if term]))


def fetch_google_news_rss(company: str, sentence: str, event_date: Optional[str] = None, limit: int = 8, before_days: int = 3, after_days: int = 10) -> dict:
    try:
        import feedparser
    except Exception as exc:
        return {"status": "missing_dependency", "package": "feedparser", "reason": str(exc), "help": DEPENDENCY_HELP}

    query = " ".join(extract_query_terms(company, sentence))
    date_filter = None
    if event_date:
        base = dt.datetime.strptime(event_date, "%Y-%m-%d").date()
        after = (base - dt.timedelta(days=before_days)).isoformat()
        before = (base + dt.timedelta(days=after_days + 1)).isoformat()
        date_filter = {"after": after, "before": before}
        query = f"{query} after:{after} before:{before}"
    encoded = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        return {"status": "error", "query": query, "url": url, "reason": str(exc)}

    items = []
    buckets = {"pre_window": [], "event_day": [], "post_window": [], "unknown_date": []}
    base_date = dt.datetime.strptime(event_date, "%Y-%m-%d").date() if event_date else None
    for entry in feed.entries[:limit]:
        published_raw = getattr(entry, "published", "")
        published_date = None
        bucket = "unknown_date"
        if published_raw:
            try:
                published_date = parsedate_to_datetime(published_raw).date().isoformat()
                if base_date:
                    parsed = dt.datetime.strptime(published_date, "%Y-%m-%d").date()
                    if parsed < base_date:
                        bucket = "pre_window"
                    elif parsed == base_date:
                        bucket = "event_day"
                    else:
                        bucket = "post_window"
            except Exception:
                published_date = None
        item = {
            "title": getattr(entry, "title", ""),
            "link": getattr(entry, "link", ""),
            "published": published_raw,
            "published_date": published_date,
            "bucket": bucket,
            "source": getattr(getattr(entry, "source", None), "title", "Google News"),
        }
        items.append(item)
        buckets.setdefault(bucket, []).append(item)
    return {"status": "ok", "query": query, "date_filter": date_filter, "url": url, "items": items, "buckets": buckets}


def match_rules(text: str):
    matched = []
    for rule in RULES:
        if any(keyword.lower() in text.lower() for keyword in rule["keywords"]):
            matched.append(rule)
    return matched


def build_card(company: str, ticker: Optional[str], sentence: str, event_date: Optional[str] = None, include_rss: bool = False, rss_before: int = 3, rss_after: int = 10) -> dict:
    rules = match_rules(sentence)
    positive: list[Signal] = []
    negative: list[Signal] = []
    questions: list[str] = []
    origins = []
    issue_types = []
    paths = []

    for rule in rules:
        origins.append(rule["origin"])
        issue_types.append(rule["issue_type"])
        for name, confidence, reason in rule.get("positive", []):
            positive.append(Signal(name, "호재 신호", confidence, reason))
        for name, confidence, reason in rule.get("negative", []):
            negative.append(Signal(name, "악재 신호", confidence, reason))
        questions.extend(rule.get("questions", []))
        if "path" in rule:
            paths.append(rule["path"])

    if not rules:
        origins = ["분류 불가/확인 필요"]
        issue_types = ["분석 보류"]
        questions = [
            "이 문장이 공식 공시, 뉴스, 전망, 루머 중 어디에서 나온 것인가?",
            "회사명과 구체적인 사건 유형이 명확한가?",
            "기준일로 삼을 수 있는 공식 발표일이 있는가?",
        ]

    signal_balance = "혼합" if positive and negative else "호재 중심" if positive else "악재 중심" if negative else "확인 필요"

    price_reference = fetch_daily_prices(ticker, event_date) if event_date else {"status": "skipped", "reason": "기준일이 없어 가격 참고값을 계산하지 않았습니다."}
    rss_news = fetch_google_news_rss(company, sentence, event_date, before_days=rss_before, after_days=rss_after) if include_rss else {"status": "skipped", "reason": "--rss 옵션이 꺼져 있습니다."}
    rss_news = enrich_rss_news(rss_news, company, sentence)

    card = {
        "company": company,
        "ticker": ticker,
        "input": sentence,
        "origins": list(dict.fromkeys(origins)),
        "issue_types": list(dict.fromkeys(issue_types)),
        "signal_balance": signal_balance,
        "positive_signals": [asdict(s) for s in positive],
        "negative_signals": [asdict(s) for s in negative],
        "impact_paths": paths,
        "questions_to_check": list(dict.fromkeys(questions)),
        "price_reference": price_reference,
        "rss_news": rss_news,
        "pre_event_reflection": assess_pre_event_reflection(price_reference, rss_news),
        "analysis_frame": "anchorless_issue_context_v2",
        "interpretation_guardrail": "이 결과는 호재/악재 결론이나 주가 원인 단정이 아니라, 현재 이슈를 둘러싼 상황 신호 정리입니다.",
    }
    card["historical_comparison"] = match_historical_case(company, sentence, card)
    return card


def format_level_list(levels: list[int]) -> str:
    if not levels:
        return "없음"
    return ", ".join(EFFECT_LEVELS[level] for level in levels if level in EFFECT_LEVELS)


def print_analysis_layers(card: dict) -> None:
    rss = card.get("rss_news", {})
    if rss.get("status") == "ok" and rss.get("effect_summary"):
        print("## 나비효과 단계별 뉴스 신호")
        print()
        for level in range(5):
            summary = rss["effect_summary"].get(str(level), {})
            items = summary.get("items", [])
            if not items:
                continue
            print(f"### {summary.get('label', EFFECT_LEVELS[level])}")
            for item in items[:5]:
                signal = item.get("signal", {})
                date_text = item.get("published_date") or "날짜 없음"
                emotions = ", ".join(signal.get("emotions", [])) or "감정 태그 없음"
                channels = ", ".join(signal.get("channels", [])) or "채널 확인 필요"
                print(f"- {date_text}: {item.get('title', '')}")
                print(f"  - 방향/확인도: {signal.get('direction')} / {signal.get('confidence')}")
                print(f"  - 감정/채널: {emotions} / {channels}")
            print()

        print("## 이슈 감정")
        print()
        emotion_counts = rss.get("emotion_counts", {})
        if emotion_counts:
            for emotion, count in sorted(emotion_counts.items(), key=lambda item: item[1], reverse=True):
                print(f"- {emotion}: {count}건")
        else:
            print("- 뚜렷한 감정 태그를 찾지 못했습니다.")
        print()

    reflection = card.get("pre_event_reflection", {})
    if reflection:
        print("## 선반영 가능성")
        print()
        print(f"- 판정: {reflection.get('label')} (점수 {reflection.get('score')})")
        for check in reflection.get("price_checks", []):
            print(f"- {check['window']} 가격 변화: {check['change']:,.0f} / {check['change_pct']:.2f}% ({check['start_date']} → {check['end_date']})")
        print(f"- 기준일 전 RSS 후보: {reflection.get('pre_news_count', 0)}건")
        print(f"- 기준일 전 감정 뉴스: {reflection.get('pre_emotional_news_count', 0)}건")
        for reason in reflection.get("reasons", []):
            print(f"- {reason}")
        print(f"- 주의: {reflection.get('caution')}")
        print()

    comparison = card.get("historical_comparison", {})
    print("## 과거 유사 사례 비교")
    print()
    if comparison.get("status") == "ok":
        case = comparison["case"]
        print(f"- 유사 사례: {case['title']} ({case['date']}, {case['company']})")
        print(f"- 과거 가격 참고: {case['price_note']}")
        print(f"- 공통 나비효과 단계: {format_level_list(comparison.get('common_effect_levels', []))}")
        print(f"- 현재에만 잡힌 단계: {format_level_list(comparison.get('current_only_effect_levels', []))}")
        print(f"- 과거에만 기록된 단계: {format_level_list(comparison.get('past_only_effect_levels', []))}")
        common_emotions = ", ".join(comparison.get("common_emotions", [])) or "없음"
        current_only_emotions = ", ".join(comparison.get("current_only_emotions", [])) or "없음"
        print(f"- 공통 감정: {common_emotions}")
        print(f"- 현재 차별 감정: {current_only_emotions}")
        print("- 과거 상황 메모:")
        for ctx in case.get("context", []):
            print(f"  - {ctx}")
        print(f"- 주의: {comparison.get('comparison_warning')}")
    else:
        print(f"- {comparison.get('reason')}")
    print()


def print_markdown(card: dict) -> None:
    print(f"# 이슈 신호 카드: {card['company']}")
    print()
    if card.get("ticker"):
        print(f"- 종목코드: {card['ticker']}")
    print(f"- 입력 문장: {card['input']}")
    print(f"- 출발점: {', '.join(card['origins'])}")
    print(f"- 이슈 유형: {', '.join(card['issue_types'])}")
    print(f"- 신호 균형: {card['signal_balance']}")
    print()

    print("## 호재 신호")
    print()
    if card["positive_signals"]:
        for signal in card["positive_signals"]:
            print(f"- {signal['name']} ({signal['confidence']}): {signal['reason']}")
    else:
        print("- 뚜렷한 호재 신호를 찾지 못했습니다.")
    print()

    print("## 악재 신호")
    print()
    if card["negative_signals"]:
        for signal in card["negative_signals"]:
            print(f"- {signal['name']} ({signal['confidence']}): {signal['reason']}")
    else:
        print("- 뚜렷한 악재 신호를 찾지 못했습니다.")
    print()

    if card["impact_paths"]:
        print("## 영향 경로")
        print()
        for path in card["impact_paths"]:
            print(" → ".join(path))
        print()

    price = card.get("price_reference", {})
    if price.get("status") == "ok":
        print("## 가격 참고")
        print()
        print(f"- 기준 거래일: {price['base_date']}")
        print(f"- 기준 종가: {price['base_close']:,.0f}")
        for n in ("3", "5", "10"):
            item = price["offsets"].get(n, {})
            if item.get("status") == "missing":
                print(f"- +{n}영업일: 데이터 부족")
            else:
                print(f"- +{n}영업일 ({item['date']}): {item['change']:,.0f} / {item['change_pct']:.2f}%")
        print()
    elif price.get("status") not in (None, "skipped"):
        print("## 가격 참고")
        print()
        print(f"- {price.get('status')}: {price.get('reason')}")
        if price.get("help"):
            print(f"- 설치 안내: {price['help']}")
        print()

    rss = card.get("rss_news", {})
    if rss.get("status") == "ok":
        print("## RSS 동시 뉴스 후보")
        print()
        print(f"- 검색어: {rss['query']}")
        if rss.get("date_filter"):
            print(f"- 날짜 필터: {rss['date_filter']['after']} ~ {rss['date_filter']['before']}")
        bucket_labels = [
            ("pre_window", "기준일 전"),
            ("event_day", "기준일 당일"),
            ("post_window", "기준일 후"),
            ("unknown_date", "날짜 확인 불가"),
        ]
        for bucket_key, bucket_label in bucket_labels:
            bucket_items = rss.get("buckets", {}).get(bucket_key, [])
            if not bucket_items:
                continue
            print()
            print(f"### {bucket_label}")
            for item in bucket_items:
                date_text = item.get("published_date") or item.get("published") or "날짜 없음"
                print(f"- {date_text}: {item['title']}")
        print()
    elif rss.get("status") not in (None, "skipped"):
        print("## RSS 동시 뉴스 후보")
        print()
        print(f"- {rss.get('status')}: {rss.get('reason')}")
        if rss.get("help"):
            print(f"- 설치 안내: {rss['help']}")
        print()

    print_analysis_layers(card)

    print("## 추가 확인 질문")
    print()
    for question in card["questions_to_check"]:
        print(f"- {question}")
    print()

    print("## 해석 주의")
    print()
    print(card["interpretation_guardrail"])


def main() -> None:
    parser = argparse.ArgumentParser(description="이슈 문장을 상황 신호 카드로 분해합니다.")
    parser.add_argument("--company", required=True)
    parser.add_argument("--ticker")
    parser.add_argument("--sentence", required=True)
    parser.add_argument("--date", help="가격 참고값 계산 기준일입니다. 예: 2025-09-03")
    parser.add_argument("--rss", action="store_true", help="Google News RSS 동시 뉴스 후보를 붙입니다.")
    parser.add_argument("--rss-before", type=int, default=3, help="RSS 검색 시작 범위: 기준일 전 N일")
    parser.add_argument("--rss-after", type=int, default=10, help="RSS 검색 종료 범위: 기준일 후 N일")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력합니다.")
    args = parser.parse_args()

    card = build_card(args.company, args.ticker, args.sentence, args.date, args.rss, args.rss_before, args.rss_after)
    if args.json:
        print(json.dumps(card, ensure_ascii=False, indent=2))
    else:
        print_markdown(card)


if __name__ == "__main__":
    main()
