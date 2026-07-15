import csv
import datetime as dt
import json
import sys
import time
import urllib.request


CASES = [
    {
        "company": "삼성전자",
        "ticker": "005930.KS",
        "event_date": "2024-07-08",
        "input": "삼성전자 노조 총파업으로 생산 차질 우려",
        "anchor": "비확정 선행 신호 / 생산중단 후보",
    },
    {
        "company": "SK하이닉스",
        "ticker": "000660.KS",
        "event_date": "2024-07-25",
        "input": "SK하이닉스 2분기 최대 실적 발표",
        "anchor": "확정 앵커 / 실적 발표",
    },
    {
        "company": "카카오",
        "ticker": "035720.KS",
        "event_date": "2024-07-23",
        "input": "카카오 창업자 구속, SM 시세조종 수사 이슈",
        "anchor": "공식 확인 필요 앵커 / 소송·수사",
    },
    {
        "company": "현대차",
        "ticker": "005380.KS",
        "event_date": "2024-07-25",
        "input": "현대차 2분기 실적 발표",
        "anchor": "확정 앵커 / 실적 발표",
    },
    {
        "company": "기아",
        "ticker": "000270.KS",
        "event_date": "2024-07-26",
        "input": "기아 2분기 실적 발표",
        "anchor": "확정 앵커 / 실적 발표",
    },
    {
        "company": "NAVER",
        "ticker": "035420.KS",
        "event_date": "2024-05-10",
        "input": "라인야후 지분 매각 압박 때문에 네이버 악재?",
        "anchor": "비확정/정책 맥락 혼합, 분석 보류 가능",
    },
    {
        "company": "POSCO홀딩스",
        "ticker": "005490.KS",
        "event_date": "2024-01-23",
        "input": "포스코 공장 화재로 일부 생산 차질",
        "anchor": "공식 확인 필요 / 생산중단 후보",
    },
    {
        "company": "LG에너지솔루션",
        "ticker": "373220.KS",
        "event_date": "2024-07-08",
        "input": "LG엔솔 2분기 잠정실적 발표",
        "anchor": "확정 앵커 / 실적 발표",
    },
    {
        "company": "대한항공",
        "ticker": "003490.KS",
        "event_date": "2024-11-28",
        "input": "대한항공 아시아나 합병 승인",
        "anchor": "확정 앵커 / 합병, 정책·규제 맥락",
    },
    {
        "company": "한화오션",
        "ticker": "042660.KS",
        "event_date": "2024-02-22",
        "input": "한화오션 LNG선 대규모 수주",
        "anchor": "확정 앵커 / 공급계약·수주",
    },
]


def timestamp(date_s: str) -> int:
    date = dt.datetime.strptime(date_s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(date.timestamp())


def fetch_prices(ticker: str, start: str, end: str):
    start_dt = dt.datetime.strptime(start, "%Y-%m-%d").date() - dt.timedelta(days=10)
    end_dt = dt.datetime.strptime(end, "%Y-%m-%d").date() + dt.timedelta(days=35)
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{ticker}?period1={timestamp(str(start_dt))}&period2={timestamp(str(end_dt))}&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as res:
        data = json.loads(res.read().decode())
    result = data["chart"]["result"][0]
    rows = []
    timestamps = result.get("timestamp", [])
    quotes = result["indicators"]["quote"][0]
    for i, ts in enumerate(timestamps):
        close = quotes["close"][i]
        if close is None:
            continue
        date = dt.datetime.fromtimestamp(ts, tz=dt.timezone(dt.timedelta(hours=9))).date()
        rows.append((date.isoformat(), float(close)))
    return rows


def event_base_and_offsets(rows, event_date):
    dates = [r[0] for r in rows]
    event_dt = dt.datetime.strptime(event_date, "%Y-%m-%d").date()
    idx = None
    for i, d in enumerate(dates):
        if dt.datetime.strptime(d, "%Y-%m-%d").date() >= event_dt:
            idx = i
            break
    if idx is None:
        raise ValueError("no base date")
    base_date, base_close = rows[idx]
    out = {"base_date": base_date, "base_close": base_close}
    for n in (3, 5, 10):
        target_idx = idx + n
        if target_idx >= len(rows):
            out[f"d{n}_date"] = ""
            out[f"d{n}_close"] = ""
            out[f"d{n}_chg"] = ""
            out[f"d{n}_pct"] = ""
            continue
        date, close = rows[target_idx]
        out[f"d{n}_date"] = date
        out[f"d{n}_close"] = close
        out[f"d{n}_chg"] = close - base_close
        out[f"d{n}_pct"] = (close - base_close) / base_close * 100
    return out


def main():
    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=[
            "company",
            "ticker",
            "input",
            "anchor",
            "event_date",
            "base_date",
            "base_close",
            "d3_date",
            "d3_close",
            "d3_chg",
            "d3_pct",
            "d5_date",
            "d5_close",
            "d5_chg",
            "d5_pct",
            "d10_date",
            "d10_close",
            "d10_chg",
            "d10_pct",
        ],
    )
    writer.writeheader()
    for case in CASES:
        rows = fetch_prices(case["ticker"], case["event_date"], case["event_date"])
        impact = event_base_and_offsets(rows, case["event_date"])
        writer.writerow({**case, **impact})
        time.sleep(0.2)


if __name__ == "__main__":
    main()
