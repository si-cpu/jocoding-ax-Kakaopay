#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch company context report generator.

Runs stock-context cards for multiple companies/situations and creates one PDF.
"""

import argparse
import datetime as dt
import importlib.util
import json
import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = PROJECT_ROOT / "scripts" / "context_signal_pipeline.py"
spec = importlib.util.spec_from_file_location("context_signal_pipeline", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

DEFAULT_CASES = [
    {
        "label": "SK하이닉스 - HBM 수요 확대",
        "company": "SK하이닉스",
        "ticker": "000660",
        "sentence": "엔비디아 HBM 수요 확대는 SK하이닉스에 어떤 상황 신호야?",
        "date": "2025-04-04",
    },
    {
        "label": "삼성전자 - 파운드리 수율/경쟁구도",
        "company": "삼성전자",
        "ticker": "005930",
        "sentence": "파운드리 수율 개선과 HBM 경쟁구도 변화는 삼성전자에 어떤 상황 신호야?",
        "date": "2025-04-04",
    },
    {
        "label": "카카오 - 오너 수사/지배구조 리스크",
        "company": "카카오",
        "ticker": "035720",
        "sentence": "카카오 오너 수사 이슈가 플랫폼 사업과 주가 심리에 어떤 상황 신호야?",
        "date": "2024-07-23",
    },
    {
        "label": "한화오션 - LNG선 수주/조선 업황",
        "company": "한화오션",
        "ticker": "042660",
        "sentence": "LNG선 수주 확대와 조선 업황 개선은 한화오션에 어떤 상황 신호야?",
        "date": "2024-02-22",
    },
    {
        "label": "LG에너지솔루션 - 전기차 보조금 축소",
        "company": "LG에너지솔루션",
        "ticker": "373220",
        "sentence": "미국 전기차 보조금 축소와 IRA 정책 변화는 LG에너지솔루션에 어떤 상황 신호야?",
        "date": "2025-01-20",
    },
]


def slugify(text: str, max_len: int = 70) -> str:
    return (re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", text).strip("_") or "batch")[:max_len]


def summarize_card(card: dict) -> dict:
    rss = card.get("rss_news", {})
    llm = rss.get("llm_assessment", {})
    llm_counts = {"호재 신호": 0, "악재 신호": 0, "혼합 신호": 0, "불명확": 0}
    relevance_counts = {}
    if llm.get("status") == "ok":
        for item in llm.get("items", []):
            llm_counts[item.get("direction", "불명확")] = llm_counts.get(item.get("direction", "불명확"), 0) + 1
            relevance_counts[item.get("relevance", "불명확")] = relevance_counts.get(item.get("relevance", "불명확"), 0) + 1
    else:
        for item in rss.get("items", []):
            signal = item.get("signal", {})
            llm_counts[signal.get("direction", "불명확")] = llm_counts.get(signal.get("direction", "불명확"), 0) + 1
            relevance_counts[signal.get("relevance", "불명확")] = relevance_counts.get(signal.get("relevance", "불명확"), 0) + 1
    price = card.get("price_reference", {})
    offsets = price.get("offsets", {}) if price.get("status") == "ok" else {}
    assessment = card.get("company_context_assessment") or {}
    fallback_assessment = infer_context_sensitivity(card)
    llm_summary = llm.get("summary") if llm.get("status") == "ok" else llm.get("reason")
    if llm_summary and "timed out" in str(llm_summary).lower():
        llm_summary = "LLM 판단 시간이 초과되어 규칙 기반 백업 신호를 표시했습니다."
    return {
        "company": card.get("company"),
        "ticker": card.get("ticker"),
        "input": card.get("input"),
        "industry": card.get("company_profile", {}).get("industry", "미분류"),
        "canonical_origin": card.get("canonical_origin") or ", ".join(card.get("origins", [])),
        "issue_types": card.get("issue_types", []),
        "signal_balance": card.get("signal_balance"),
        "company_sensitivity": assessment.get("sensitivity_label") or fallback_assessment.get("sensitivity_label") or "미분류",
        "company_issue_code": assessment.get("lead_issue_code") or fallback_assessment.get("lead_issue_code") or "미분류",
        "dart_status": (card.get("dart_event") or {}).get("status"),
        "dart_event_type": (card.get("dart_event") or {}).get("official_event_type"),
        "llm_status": llm.get("status"),
        "llm_summary": llm_summary,
        "direction_counts": llm_counts,
        "relevance_counts": relevance_counts,
        "price_3d": offsets.get("3", {}),
        "price_5d": offsets.get("5", {}),
        "price_10d": offsets.get("10", {}),
        "pre_reflection": card.get("pre_event_reflection", {}),
        "market_contradiction": card.get("market_contradiction", {}),
        "questions": card.get("questions_to_check", [])[:4],
    }


def infer_context_sensitivity(card: dict) -> dict:
    profile = card.get("company_profile", {})
    industry = profile.get("industry")
    issue_codes = card.get("input_issue_codes", [])
    table = {
        ("플랫폼/인터넷", "owner_legal"): ("높음", "owner_legal"),
        ("조선", "order_contract"): ("높음", "order_contract"),
        ("배터리", "subsidy_cut"): ("높음", "subsidy_cut"),
        ("배터리", "subsidy_expand"): ("높음", "subsidy_expand"),
        ("항공", "oil_price_up"): ("높음", "oil_price_up"),
        ("정유", "oil_price_up"): ("중상", "oil_price_up"),
        ("자동차", "strike"): ("높음", "strike"),
    }
    for code in issue_codes:
        if (industry, code) in table:
            label, lead = table[(industry, code)]
            return {"sensitivity_label": label, "lead_issue_code": lead}
    return {}


def run_cases(cases: list[dict], use_llm: bool, use_dart: bool, rss_before: int, rss_after: int) -> dict:
    results = []
    for case in cases:
        card = core.build_card(
            case["company"],
            case["ticker"],
            case["sentence"],
            case["date"],
            include_rss=True,
            rss_before=rss_before,
            rss_after=rss_after,
            use_llm=use_llm,
            llm_model=None,
            use_dart=use_dart,
        )
        results.append({"case": case, "summary": summarize_card(card), "card": card})
    return {
        "status": "ok",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "use_llm": use_llm,
        "use_dart": use_dart,
        "rss_before": rss_before,
        "rss_after": rss_after,
        "cases": results,
        "guardrail": "투자 추천이나 가격 원인 단정이 아니라, 회사별 상황 신호와 뉴스-가격 불일치 설명 후보 정리입니다.",
    }


def save_json(report: dict, output: Optional[str]) -> Path:
    if output:
        path = Path(output)
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = PROJECT_ROOT / "output" / "company_batch" / f"{stamp}_five_company_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def register_korean_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for candidate in [
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]:
        if Path(candidate).exists():
            try:
                pdfmetrics.registerFont(TTFont("Korean", candidate))
                return "Korean"
            except Exception:
                continue
    return "Helvetica"


def pct_text(item: dict) -> str:
    if not item or item.get("status") == "missing":
        return "데이터 부족"
    return f"{item.get('change_pct', 0):.2f}% ({item.get('date')})"


def pct_short(item: dict) -> str:
    if not item or item.get("status") == "missing":
        return "부족"
    return f"{item.get('change_pct', 0):.2f}%"


def save_pdf(report: dict, output: Optional[str]) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

    if output:
        path = Path(output)
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = PROJECT_ROOT / "output" / "pdf" / f"{stamp}_five_company_context.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    font = register_korean_font()
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleKo", parent=styles["Title"], fontName=font, fontSize=20, leading=26, textColor=colors.HexColor("#14213D"), spaceAfter=8)
    h2 = ParagraphStyle("H2Ko", parent=styles["Heading2"], fontName=font, fontSize=13.5, leading=17, textColor=colors.HexColor("#1F4E79"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("BodyKo", parent=styles["BodyText"], fontName=font, fontSize=8.8, leading=12.2)
    small = ParagraphStyle("SmallKo", parent=body, fontSize=7.6, leading=10.5, textColor=colors.HexColor("#555555"))
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=14*mm, leftMargin=14*mm, topMargin=13*mm, bottomMargin=13*mm)
    story = []
    case_count = len(report.get("cases", []))
    story.append(Paragraph(f"{case_count}개 기업 시장 불일치 해석 리포트", title))
    story.append(Paragraph(f"생성시각: {report.get('generated_at')} | LLM 사용: {report.get('use_llm')} | DART 사용: {report.get('use_dart')} | RSS: -{report.get('rss_before')}일/+{report.get('rss_after')}일", small))
    story.append(Paragraph(report.get("guardrail", ""), small))
    story.append(Spacer(1, 8))

    overview = [[Paragraph("회사", body), Paragraph("상황", body), Paragraph("출발점/신호", body), Paragraph("불일치 후보", body), Paragraph("+10영업일", body)]]
    for entry in report["cases"]:
        s = entry["summary"]
        contradiction = s.get("market_contradiction", {})
        candidates = contradiction.get("candidates", []) if contradiction.get("status") == "ok" else []
        candidate_text = "<br/>".join(f"- {c.get('label')}({c.get('confidence')})" for c in candidates[:2]) or contradiction.get("reason") or "없음"
        overview.append([
            Paragraph(f"{s['company']}<br/>{s['ticker']}", body),
            Paragraph(s["input"], body),
            Paragraph(f"{s['canonical_origin']} / {s['signal_balance']}<br/>민감도 {s['company_sensitivity']}<br/>{', '.join(s['issue_types'])}", body),
            Paragraph(candidate_text, body),
            Paragraph(pct_short(s["price_10d"]), body),
        ])
    table = Table(overview, colWidths=[24*mm, 61*mm, 38*mm, 42*mm, 25*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2F8")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5D8DC")),
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FBFCFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 8))

    for entry in report["cases"]:
        s = entry["summary"]
        block = [Paragraph(f"{s['company']} - {entry['case']['label']}", h2)]
        block.append(Paragraph(f"<b>상황</b>: {s['input']}", body))
        block.append(Paragraph(f"<b>출발점/산업/이슈</b>: {s['canonical_origin']} / {s['industry']} / {', '.join(s['issue_types'])}", body))
        block.append(Paragraph(f"<b>DART</b>: {s.get('dart_status') or '없음'} {s.get('dart_event_type') or ''}", body))
        block.append(Paragraph(f"<b>LLM 요약</b>: {s.get('llm_summary') or '없음'}", body))
        pre = s.get("pre_reflection", {})
        block.append(Paragraph(f"<b>선행 가격 움직임</b>: {pre.get('observation_label') or pre.get('label')} (점수 {pre.get('score')})", body))
        block.append(Paragraph(f"<b>가격 참고</b>: +3 {pct_text(s['price_3d'])}, +5 {pct_text(s['price_5d'])}, +10 {pct_text(s['price_10d'])}", body))
        contradiction = s.get("market_contradiction", {})
        if contradiction.get("status") == "ok":
            candidates = contradiction.get("candidates", [])
            candidate_text = "; ".join(f"{c.get('label')}({c.get('confidence')})" for c in candidates[:3]) or "없음"
            block.append(Paragraph(f"<b>뉴스-가격 불일치</b>: {contradiction.get('alignment')} / {candidate_text}", body))
        else:
            block.append(Paragraph(f"<b>뉴스-가격 불일치</b>: {contradiction.get('reason') or '가격 데이터 부족'}", body))
        if s.get("questions"):
            block.append(Paragraph("<b>확인 질문</b>: " + "; ".join(s["questions"]), small))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 5))

    doc.build(story)
    return path


def print_summary(report: dict, json_path: Path, pdf_path: Path) -> None:
    print(f"# {len(report.get('cases', []))}개 기업 시장 불일치 해석")
    print()
    for entry in report["cases"]:
        s = entry["summary"]
        print(f"## {s['company']} / {s['ticker']}")
        print(f"- 상황: {s['input']}")
        print(f"- 출발점/이슈: {s['canonical_origin']} / {', '.join(s['issue_types'])}")
        print(f"- 신호 균형: {s['signal_balance']} / 기업 민감도: {s['company_sensitivity']}")
        print(f"- DART 상태: {s.get('dart_status')}")
        print(f"- LLM 상태: {s['llm_status']}")
        print(f"- LLM 요약: {s.get('llm_summary')}")
        print(f"- 방향 카운트: {s['direction_counts']}")
        print(f"- 가격 참고: +3 {pct_text(s['price_3d'])}, +5 {pct_text(s['price_5d'])}, +10 {pct_text(s['price_10d'])}")
        contradiction = s.get("market_contradiction", {})
        print(f"- 불일치 상태: {contradiction.get('alignment') or contradiction.get('status')}")
        if contradiction.get("status") == "ok":
            print(f"- 설명 후보: {[c.get('label') for c in contradiction.get('candidates', [])[:3]]}")
        print()
    print(f"JSON 저장: {json_path}")
    print(f"PDF 저장: {pdf_path}")


def refresh_report_summaries(report: dict) -> dict:
    for entry in report.get("cases", []):
        if "card" in entry:
            entry["summary"] = summarize_card(entry["card"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="여러 회사 상황 신호와 시장 불일치 해석 batch 리포트를 생성합니다.")
    parser.add_argument("--cases-json", default=None, help="사용자 정의 케이스 JSON 파일")
    parser.add_argument("--from-json", default=None, help="기존 결과 JSON으로 PDF/요약만 재생성")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--dart", action="store_true")
    parser.add_argument("--rss-before", type=int, default=3)
    parser.add_argument("--rss-after", type=int, default=10)
    parser.add_argument("--json-output", default=None)
    parser.add_argument("--pdf-output", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.from_json:
        report = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        report = refresh_report_summaries(report)
    else:
        cases = DEFAULT_CASES
        if args.cases_json:
            cases = json.loads(Path(args.cases_json).read_text(encoding="utf-8"))
        core.load_local_env(str(PROJECT_ROOT / ".env"))
        report = run_cases(cases, use_llm=not args.no_llm, use_dart=args.dart, rss_before=args.rss_before, rss_after=args.rss_after)
    json_path = save_json(report, args.json_output)
    pdf_path = save_pdf(report, args.pdf_output)
    report["json_path"] = str(json_path)
    report["pdf_path"] = str(pdf_path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_summary(report, json_path, pdf_path)


if __name__ == "__main__":
    main()
