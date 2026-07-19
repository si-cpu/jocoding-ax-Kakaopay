#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI situation-to-market impact map pipeline.

This script intentionally does not try to predict prices or recommend trades.
It creates a structured hypothesis map: situation -> impact layers -> candidate
industries/stocks -> verification checkpoints, then saves JSON and a readable PDF.
"""

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = PROJECT_ROOT / "scripts" / "context_signal_pipeline.py"

spec = importlib.util.spec_from_file_location("context_signal_pipeline", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

SITUATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "situation": {"type": "string"},
        "market": {"type": "string"},
        "as_of_date": {"type": "string"},
        "one_line_thesis": {"type": "string"},
        "dominant_frame": {"type": "string"},
        "layers": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "effect_level": {"type": "integer", "enum": [0, 1, 2, 3, 4]},
                    "label": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "ticker": {"type": "string"},
                                "category": {"type": "string"},
                                "direction": {"type": "string", "enum": ["호재 후보", "악재 후보", "혼합 신호", "관련 낮음", "불명확"]},
                                "sensitivity": {"type": "string", "enum": ["매우 높음", "높음", "중상", "중간", "중하", "낮음", "불명확"]},
                                "confidence": {"type": "string", "enum": ["높음", "중간", "낮음"]},
                                "reason": {"type": "string"},
                                "transmission_path": {"type": "array", "items": {"type": "string"}},
                                "verification_data": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["name", "ticker", "category", "direction", "sensitivity", "confidence", "reason", "transmission_path", "verification_data"],
                        },
                    },
                },
                "required": ["effect_level", "label", "items"],
            },
        },
        "opposite_cases": {"type": "array", "items": {"type": "string"}},
        "key_checkpoints": {"type": "array", "items": {"type": "string"}},
        "cautions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["situation", "market", "as_of_date", "one_line_thesis", "dominant_frame", "layers", "opposite_cases", "key_checkpoints", "cautions"],
}


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", text).strip("_")
    return slug[:max_len] or "situation"


def known_company_context() -> list[dict]:
    rows = []
    for ticker, profile in core.COMPANY_PROFILES.items():
        rows.append({
            "ticker": ticker,
            "company": profile.get("company"),
            "industry": profile.get("industry"),
            "exposures": profile.get("exposures", []),
            "business_segments": profile.get("business_segments", {}),
            "issue_sensitivity": profile.get("issue_sensitivity", {}),
        })
    return rows


def call_openai_with_schema(prompt: str, schema: dict, model: str, timeout: int = 90) -> dict:
    core.load_local_env(str(PROJECT_ROOT / ".env"))
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"status": "skipped", "reason": "OPENAI_API_KEY 환경변수가 없어 상황 지도를 생성하지 못했습니다."}
    body = {
        "model": model,
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "situation_impact_map",
                "schema": schema,
                "strict": True,
            }
        },
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:700]
        return {"status": "error", "reason": f"OpenAI API HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}
    text = core.extract_response_text(payload)
    if not text:
        return {"status": "error", "reason": "OpenAI 응답에서 텍스트를 찾지 못했습니다.", "raw_status": payload.get("status")}
    try:
        result = json.loads(text)
    except Exception as exc:
        return {"status": "error", "reason": f"상황 지도 JSON 파싱 실패: {exc}", "raw_text": text[:1200]}
    result["status"] = "ok"
    result["model"] = model
    return result


def build_prompt(situation: str, market: str, as_of_date: Optional[str], max_candidates: int) -> str:
    return json.dumps({
        "role": "market_situation_impact_mapper",
        "instruction": (
            "투자 추천이나 가격 예측을 하지 말고, 입력된 상황이 시장 안에서 어떤 산업과 종목군으로 번질 수 있는지 가설 지도를 만든다. "
            "항상 후보/가능성/확인 필요 표현을 사용한다. 주가 원인을 단정하지 않는다. "
            "0차는 기준 사건, 1차는 직접 영향, 2차는 산업/공급망 파급, 3차는 거시/정책/인프라 파급, 4차는 시장심리/수급 반응이다. "
            "알고 있는 종목코드는 ticker에 넣고, 모르면 빈 문자열로 둔다. "
            "각 항목은 왜 영향을 받을 수 있는지 transmission_path와 verification_data를 반드시 포함한다. "
            f"전체 후보는 핵심 후보 위주로 최대 {max_candidates}개 정도로 압축한다."
        ),
        "situation": situation,
        "market": market,
        "as_of_date": as_of_date or "미지정",
        "known_company_context": known_company_context(),
        "output_language": "ko-KR",
    }, ensure_ascii=False)


def normalize_map(result: dict, situation: str, market: str, as_of_date: Optional[str]) -> dict:
    result.setdefault("situation", situation)
    result.setdefault("market", market)
    result.setdefault("as_of_date", as_of_date or "미지정")
    result.setdefault("layers", [])
    result.setdefault("opposite_cases", [])
    result.setdefault("key_checkpoints", [])
    result.setdefault("cautions", [])
    for layer in result.get("layers", []):
        for item in layer.get("items", []):
            name = item.get("name", "")
            ticker = item.get("ticker", "")
            if not ticker:
                for code, profile in core.COMPANY_PROFILES.items():
                    if name == profile.get("company") or name in profile.get("aliases", []):
                        item["ticker"] = code
                        break
            item.setdefault("stock_card_command", stock_card_command(item.get("name", ""), item.get("ticker", ""), situation, as_of_date))
    return result


def stock_card_command(company: str, ticker: str, situation: str, as_of_date: Optional[str]) -> str:
    if not company or not ticker:
        return ""
    date_part = f" --date {as_of_date}" if as_of_date else ""
    return f"python3 scripts/context_signal_pipeline.py --company {company} --ticker {ticker} --sentence \"{situation}\"{date_part} --rss --llm"


def build_situation_map(situation: str, market: str, as_of_date: Optional[str], model: str, max_candidates: int) -> dict:
    prompt = build_prompt(situation, market, as_of_date, max_candidates)
    result = call_openai_with_schema(prompt, SITUATION_SCHEMA, model)
    if result.get("status") != "ok":
        return result
    return normalize_map(result, situation, market, as_of_date)


def save_json(result: dict, situation: str, output_path: Optional[str]) -> Path:
    if output_path:
        path = Path(output_path)
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = PROJECT_ROOT / "output" / "situation" / f"{stamp}_{slugify(situation)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def format_markdown(result: dict) -> str:
    if result.get("status") != "ok":
        return f"# 상황 파급 지도 생성 실패\n\n- {result.get('status')}: {result.get('reason')}\n"
    lines = [
        f"# 상황 파급 지도: {result.get('situation')}",
        "",
        f"- 시장: {result.get('market')}",
        f"- 기준일: {result.get('as_of_date')}",
        f"- 모델: {result.get('model')}",
        f"- 핵심 관점: {result.get('dominant_frame')}",
        f"- 한 줄 요약: {result.get('one_line_thesis')}",
        "",
    ]
    for layer in sorted(result.get("layers", []), key=lambda x: x.get("effect_level", 99)):
        lines += [f"## {layer.get('effect_level')}차 - {layer.get('label')}", ""]
        for item in layer.get("items", []):
            ticker = f" / {item.get('ticker')}" if item.get("ticker") else ""
            lines.append(f"- {item.get('name')}{ticker}")
            lines.append(f"  - 분류: {item.get('category')} / 방향: {item.get('direction')} / 민감도: {item.get('sensitivity')} / 확신도: {item.get('confidence')}")
            lines.append(f"  - 이유: {item.get('reason')}")
            if item.get("transmission_path"):
                lines.append(f"  - 경로: {' -> '.join(item.get('transmission_path', []))}")
            if item.get("verification_data"):
                lines.append(f"  - 확인 데이터: {', '.join(item.get('verification_data', []))}")
            if item.get("stock_card_command"):
                lines.append(f"  - 상세 카드: `{item.get('stock_card_command')}`")
        lines.append("")
    if result.get("opposite_cases"):
        lines += ["## 반대/예외 시나리오", ""] + [f"- {x}" for x in result["opposite_cases"]] + [""]
    if result.get("key_checkpoints"):
        lines += ["## 핵심 확인 데이터", ""] + [f"- {x}" for x in result["key_checkpoints"]] + [""]
    if result.get("cautions"):
        lines += ["## 해석 주의", ""] + [f"- {x}" for x in result["cautions"]] + [""]
    return "\n".join(lines)


def register_korean_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = [
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                pdfmetrics.registerFont(TTFont("Korean", candidate))
                return "Korean"
            except Exception:
                continue
    return "Helvetica"


def save_pdf(result: dict, situation: str, output_path: Optional[str]) -> Optional[Path]:
    if result.get("status") != "ok":
        return None
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

    if output_path:
        path = Path(output_path)
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = PROJECT_ROOT / "output" / "pdf" / f"{stamp}_{slugify(situation)}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    font = register_korean_font()
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleKo", parent=styles["Title"], fontName=font, fontSize=21, leading=27, textColor=colors.HexColor("#14213D"), spaceAfter=8)
    h2 = ParagraphStyle("H2Ko", parent=styles["Heading2"], fontName=font, fontSize=14, leading=18, textColor=colors.HexColor("#1F4E79"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("BodyKo", parent=styles["BodyText"], fontName=font, fontSize=9.3, leading=13.2, alignment=TA_LEFT)
    small = ParagraphStyle("SmallKo", parent=body, fontSize=8, leading=11, textColor=colors.HexColor("#555555"))
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=14*mm, bottomMargin=14*mm)
    story = []
    story.append(Paragraph(f"상황 파급 지도", title))
    story.append(Paragraph(result.get("situation", ""), h2))
    meta = f"시장: {result.get('market')} | 기준일: {result.get('as_of_date')} | 모델: {result.get('model')}"
    story.append(Paragraph(meta, small))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>핵심 관점</b>: {result.get('dominant_frame')}", body))
    story.append(Paragraph(f"<b>한 줄 요약</b>: {result.get('one_line_thesis')}", body))
    story.append(Spacer(1, 8))

    for layer in sorted(result.get("layers", []), key=lambda x: x.get("effect_level", 99)):
        story.append(Paragraph(f"{layer.get('effect_level')}차 - {layer.get('label')}", h2))
        rows = [[Paragraph("대상", body), Paragraph("방향/민감도", body), Paragraph("근거와 확인 데이터", body)]]
        for item in layer.get("items", []):
            name = item.get("name", "") + (f"<br/>{item.get('ticker')}" if item.get("ticker") else "")
            dir_text = f"{item.get('direction')}<br/>민감도 {item.get('sensitivity')}<br/>확신도 {item.get('confidence')}"
            path_text = " -> ".join(item.get("transmission_path", []))
            verify = ", ".join(item.get("verification_data", []))
            detail = f"{item.get('reason')}<br/><font color='#666666'>경로: {path_text}</font><br/><font color='#666666'>확인: {verify}</font>"
            rows.append([Paragraph(name, body), Paragraph(dir_text, body), Paragraph(detail, body)])
        table = Table(rows, colWidths=[34*mm, 34*mm, 102*mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2F8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#14213D")),
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5D8DC")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FBFCFC")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)
        story.append(Spacer(1, 6))

    if result.get("opposite_cases"):
        block = [Paragraph("반대/예외 시나리오", h2)]
        for x in result["opposite_cases"]:
            block.append(Paragraph(f"- {x}", body))
        story.append(KeepTogether(block))
    if result.get("key_checkpoints"):
        block = [Paragraph("핵심 확인 데이터", h2)]
        for x in result["key_checkpoints"]:
            block.append(Paragraph(f"- {x}", body))
        story.append(KeepTogether(block))
    cautions = result.get("cautions") or ["투자 추천이 아니라 상황 가설 지도입니다.", "가격 원인을 단정하지 않습니다."]
    block = [Paragraph("해석 주의", h2)]
    for x in cautions:
        block.append(Paragraph(f"- {x}", body))
    story.append(KeepTogether(block))
    doc.build(story)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 상황 파급 지도와 PDF 리포트를 생성합니다.")
    parser.add_argument("--situation", default=None, help="분석할 시장 상황/사건 문장")
    parser.add_argument("--from-json", default=None, help="기존 상황 지도 JSON에서 PDF/출력을 다시 생성합니다. API를 호출하지 않습니다.")
    parser.add_argument("--market", default="한국 주식시장", help="대상 시장")
    parser.add_argument("--date", default=None, help="기준일. 예: 2025-04-04")
    parser.add_argument("--model", default=None, help="OpenAI 모델. 기본값은 OPENAI_MODEL 또는 gpt-5-mini")
    parser.add_argument("--max-candidates", type=int, default=8, help="상황 지도 후보 수 힌트")
    parser.add_argument("--json-output", default=None, help="JSON 저장 경로")
    parser.add_argument("--pdf-output", default=None, help="PDF 저장 경로")
    parser.add_argument("--no-pdf", action="store_true", help="PDF 생성을 건너뜁니다")
    parser.add_argument("--json", action="store_true", help="표준 출력도 JSON으로 출력합니다")
    args = parser.parse_args()
    if not args.situation and not args.from_json:
        parser.error("--situation 또는 --from-json 중 하나가 필요합니다.")

    core.load_local_env(str(PROJECT_ROOT / ".env"))
    if args.from_json:
        source_path = Path(args.from_json)
        result = json.loads(source_path.read_text(encoding="utf-8"))
        situation_for_path = result.get("situation") or args.situation or source_path.stem
        json_path = source_path
    else:
        model = args.model or os.environ.get("OPENAI_MODEL") or "gpt-5-mini"
        result = build_situation_map(args.situation, args.market, args.date, model, args.max_candidates)
        situation_for_path = args.situation
        json_path = save_json(result, situation_for_path, args.json_output)
    pdf_path = None if args.no_pdf else save_pdf(result, situation_for_path, args.pdf_output)
    result["json_path"] = str(json_path)
    if pdf_path:
        result["pdf_path"] = str(pdf_path)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(result))
        print(f"\nJSON 저장: {json_path}")
        if pdf_path:
            print(f"PDF 저장: {pdf_path}")


if __name__ == "__main__":
    main()
