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

    return {
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
        "price_reference": fetch_daily_prices(ticker, event_date) if event_date else {"status": "skipped", "reason": "기준일이 없어 가격 참고값을 계산하지 않았습니다."},
        "rss_news": fetch_google_news_rss(company, sentence, event_date, before_days=rss_before, after_days=rss_after) if include_rss else {"status": "skipped", "reason": "--rss 옵션이 꺼져 있습니다."},
        "analysis_frame": "anchorless_issue_context",
        "interpretation_guardrail": "이 결과는 호재/악재 결론이나 주가 원인 단정이 아니라, 현재 이슈를 둘러싼 상황 신호 정리입니다.",
    }


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
