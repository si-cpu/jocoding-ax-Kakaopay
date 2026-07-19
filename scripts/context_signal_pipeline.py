import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import importlib.util
from email.utils import parsedate_to_datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional


DEPENDENCY_HELP = """
필요 패키지가 없습니다. 아래처럼 설치한 뒤 다시 실행하세요.

python3 -m pip install -r requirements-pipeline.txt
""".strip()


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DART_RESOLVER_PATH = PROJECT_ROOT / "scripts" / "dart_event_resolver.py"
_DART_RESOLVER_MODULE = None


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
    {
        "keywords": ["플랫폼 규제", "플랫폼법", "온라인 플랫폼", "광고 규제", "커머스 규제"],
        "origin": "정책/규제/국가전략",
        "issue_type": "플랫폼 규제 신호",
        "positive": [],
        "negative": [
            ("규제 비용/사업 확장성 부담", "뉴스/공식 확인 필요", "플랫폼 규제 강화는 광고·커머스·수수료 정책과 사업 확장성에 부담이 될 수 있음"),
            ("정책 불확실성", "확인 필요", "법안 단계와 실제 시행 범위에 따라 영향이 달라질 수 있음"),
        ],
        "questions": [
            "규제안이 법안 발의, 정부 발표, 실제 시행 중 어느 단계인가?",
            "광고·커머스·수수료 등 어떤 사업부가 직접 대상인가?",
            "동종 플랫폼 기업에도 같은 조건으로 적용되는가?",
        ],
    },

    {
        "keywords": ["HBM", "고대역폭메모리", "엔비디아", "NVIDIA", "AI 반도체", "AI 서버"],
        "origin": "산업/섹터 + 고객사 밸류체인",
        "issue_type": "HBM/AI 반도체 수요 신호",
        "positive": [
            ("AI 서버 메모리 수요 확대", "뉴스/데이터 확인 필요", "HBM 수요 증가는 메모리 업체의 고부가 제품 기대를 키울 수 있음"),
            ("고객사 공급망 진입 기대", "확인 필요", "엔비디아 등 핵심 고객 공급 여부에 따라 기업별 영향이 크게 달라짐"),
        ],
        "negative": [
            ("인증/점유율 미확인 리스크", "확인 필요", "수요가 커져도 해당 회사가 실제 물량을 확보했는지는 별도 확인이 필요함"),
            ("경쟁사 점유율 확대 리스크", "뉴스 확인", "동일 업종 안에서도 누가 수혜를 가져가는지에 따라 방향이 갈릴 수 있음"),
        ],
        "questions": [
            "해당 회사가 HBM 공급 인증 또는 양산 공급을 공식 확인했는가?",
            "HBM 매출 비중과 이익 기여도가 어느 정도인가?",
            "경쟁사 대비 점유율 변화가 확인되는가?",
        ],
    },
    {
        "keywords": ["메모리 가격", "D램", "DRAM", "낸드", "NAND", "메모리 업황"],
        "origin": "산업/섹터",
        "issue_type": "메모리 가격/업황 신호",
        "positive": [
            ("메모리 가격 상승 기대", "데이터 확인 필요", "메모리 가격 상승은 메모리 비중이 큰 회사의 매출/마진 기대에 긍정적일 수 있음"),
        ],
        "negative": [
            ("업황 둔화/가격 하락 리스크", "데이터 확인 필요", "가격 하락이나 재고 증가는 메모리 업체 실적에 부담이 될 수 있음"),
        ],
        "questions": [
            "DRAM/NAND 가격 지표가 실제로 개선 중인가?",
            "재고 수준과 고객사 주문 흐름은 어떤가?",
            "해당 회사의 메모리 매출/이익 비중은 어느 정도인가?",
        ],
    },
    {
        "keywords": ["파운드리", "수율", "위탁생산", "TSMC"],
        "origin": "산업/경쟁구도",
        "issue_type": "파운드리 경쟁/수율 신호",
        "positive": [
            ("수율 개선 기대", "확인 필요", "파운드리 수율 개선은 수주·마진 기대를 높일 수 있음"),
        ],
        "negative": [
            ("경쟁 열위 리스크", "뉴스 확인", "TSMC 등 경쟁사 우위가 부각되면 파운드리 노출 기업에 부담이 될 수 있음"),
        ],
        "questions": [
            "해당 회사가 파운드리 사업에 직접 노출되어 있는가?",
            "수율 개선이 공식적으로 확인됐는가?",
            "경쟁사 대비 고객 수주 흐름이 바뀌었는가?",
        ],
    },
    {
        "keywords": ["스마트폰", "갤럭시", "아이폰", "모바일", "휴대폰"],
        "origin": "제품 수요/고객사 수요",
        "issue_type": "스마트폰/모바일 수요 신호",
        "positive": [
            ("완제품/부품 수요 개선", "데이터 확인 필요", "스마트폰 판매 호조는 완제품 업체와 모바일 부품 공급망에 긍정적일 수 있음"),
        ],
        "negative": [
            ("모바일 수요 둔화", "데이터 확인 필요", "스마트폰 판매 부진은 완제품과 모바일 부품 수요에 부담이 될 수 있음"),
        ],
        "questions": [
            "해당 회사가 완제품 판매에 직접 노출되어 있는가, 부품 공급망에 간접 노출되어 있는가?",
            "판매량/출하량 데이터가 실제로 확인되는가?",
            "프리미엄/중저가 제품 믹스 변화가 있는가?",
        ],
    },

    {
        "keywords": ["수주", "공급계약", "LNG선", "계약 체결", "대규모 계약"],
        "origin": "기업 내부",
        "issue_type": "수주/공급계약",
        "positive": [
            ("수주잔고/매출 가시성 개선", "공시 확인 필요", "수주는 향후 매출과 일감 확보 기대를 만들 수 있음"),
            ("업황 기대 강화", "뉴스 확인", "동종 수주 뉴스가 반복되면 업황 기대가 커질 수 있음"),
        ],
        "negative": [
            ("수익성 확인 필요", "확인 필요", "계약 규모가 커도 선가·원가·납기 조건에 따라 이익 기여가 달라질 수 있음"),
        ],
        "questions": [
            "공급계약 공시 또는 회사 공식 발표가 있는가?",
            "계약 규모와 기존 매출 대비 비중은 어느 정도인가?",
            "수익성, 납기, 원가 상승 조건은 확인됐는가?",
        ],
    },
    {
        "keywords": ["오너", "구속", "수사", "압수수색", "경영권", "대표 교체", "김범수"],
        "origin": "기업 내부",
        "issue_type": "지배구조/법률 리스크",
        "positive": [],
        "negative": [
            ("경영 불확실성", "뉴스 확인/공식 확인 필요", "오너·경영진 수사 이슈는 의사결정과 투자심리에 부담이 될 수 있음"),
            ("규제·법률 리스크", "확인 필요", "수사나 재판의 범위와 회사 직접 영향 여부를 확인해야 함"),
        ],
        "questions": [
            "개인 이슈인지 회사 법인 리스크인지 구분됐는가?",
            "공식 수사/법원 발표 또는 회사 공시가 있는가?",
            "사업 운영, 인허가, 지배구조에 직접 영향이 있는가?",
        ],
    },
    {
        "keywords": ["외국인", "기관", "순매도", "순매수", "공매도", "보호예수", "MSCI", "지수 편입", "블록딜"],
        "origin": "수급/시장구조",
        "issue_type": "수급/시장구조 신호",
        "positive": [
            ("수급 개선 가능성", "데이터 확인 필요", "순매수·지수 편입 등은 단기 수급에 긍정적으로 작용할 수 있음"),
        ],
        "negative": [
            ("수급 부담 가능성", "데이터 확인 필요", "순매도·공매도·보호예수 해제 등은 단기 수급 부담이 될 수 있음"),
        ],
        "questions": [
            "거래소/수급 데이터로 실제 순매수·순매도 규모가 확인되는가?",
            "일회성 거래인지 지속 흐름인지 확인했는가?",
            "시장 전체 외국인 수급과 같은 방향인지 비교했는가?",
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


COMPANY_PROFILES = {
    "005930": {
        "company": "삼성전자",
        "industry": "반도체/전자",
        "aliases": ["삼성전자", "삼성"],
        "exposures": ["반도체", "스마트폰", "수출", "환율", "공급망", "희토류", "AI"],
        "business_segments": {
            "memory": "high",
            "hbm": "medium_high",
            "foundry": "medium_high",
            "smartphone": "high",
            "consumer_electronics": "medium",
        },
        "issue_sensitivity": {
            "memory_price": "high",
            "hbm_demand": "medium_high",
            "foundry_yield": "high",
            "smartphone_demand": "high",
            "ai_server_demand": "medium_high",
            "rare_earth_control": "medium",
        },
    },
    "000660": {
        "company": "SK하이닉스",
        "industry": "반도체",
        "aliases": ["SK하이닉스", "하이닉스", "SK hynix"],
        "exposures": ["메모리", "DRAM", "NAND", "HBM", "AI", "엔비디아", "수출", "환율"],
        "business_segments": {
            "memory": "very_high",
            "dram": "very_high",
            "nand": "high",
            "hbm": "very_high",
            "foundry": "low",
            "smartphone": "low",
        },
        "issue_sensitivity": {
            "memory_price": "very_high",
            "hbm_demand": "very_high",
            "foundry_yield": "low",
            "smartphone_demand": "medium_low",
            "ai_server_demand": "very_high",
            "rare_earth_control": "medium",
        },
    },
    "005380": {"company": "현대차", "industry": "자동차", "aliases": ["현대차", "현대자동차"], "exposures": ["자동차", "수출", "환율", "관세", "노사", "부품", "전기차"]},
    "003490": {"company": "대한항공", "industry": "항공", "aliases": ["대한항공"], "exposures": ["항공", "유가", "환율", "여객", "화물", "유류할증료"]},
    "010950": {"company": "S-Oil", "industry": "정유", "aliases": ["S-Oil", "에쓰오일", "에스오일"], "exposures": ["유가", "정제마진", "재고평가", "환율"]},
    "373220": {"company": "LG에너지솔루션", "industry": "배터리", "aliases": ["LG에너지솔루션", "LG엔솔"], "exposures": ["배터리", "전기차", "보조금", "IRA", "리튬", "설비투자"]},
    "042660": {"company": "한화오션", "industry": "조선", "aliases": ["한화오션"], "exposures": ["조선", "LNG선", "수주", "선가", "방산", "환율", "후판"]},
    "035720": {"company": "카카오", "industry": "플랫폼/인터넷", "aliases": ["카카오", "김범수"], "exposures": ["플랫폼", "광고", "커머스", "규제", "오너", "지배구조"]},
}

ISSUE_TYPE_KEYWORDS = {
    "oil_price_up": ["유가", "유가 상승", "국제유가", "유가 급등", "원유", "브렌트", "WTI"],
    "subsidy_expand": ["보조금 확대", "지원금 증가", "세액공제 확대", "보조금", "AMPC"],
    "subsidy_cut": ["보조금 제외", "보조금 축소", "보조금 폐지", "IRA 축소", "제외", "폐지"],
    "rare_earth_control": ["희토류", "수출 제한", "수출통제", "수출 통제"],
    "memory_price": ["메모리 가격", "D램 가격", "DRAM 가격", "낸드 가격", "NAND 가격", "메모리 업황", "D램", "DRAM", "낸드", "NAND"],
    "hbm_demand": ["HBM", "고대역폭메모리", "엔비디아", "NVIDIA", "AI 반도체", "AI 서버"],
    "foundry_yield": ["파운드리", "수율", "TSMC", "위탁생산"],
    "smartphone_demand": ["스마트폰", "갤럭시", "아이폰", "모바일", "휴대폰"],
    "strike": ["파업", "노조", "임단협", "생산 차질", "생산중단"],
    "order_contract": ["수주", "공급계약", "LNG선", "계약", "인도"],
    "owner_legal": ["오너", "구속", "수사", "압수수색", "김범수", "법원"],
    "platform_regulation": ["플랫폼 규제", "플랫폼법", "온라인 플랫폼", "광고 규제", "커머스 규제"],
    "flow_sell": ["순매도", "대량 매도", "공매도", "보호예수", "블록딜"],
    "flow_buy": ["순매수", "대량 매수", "지수 편입", "MSCI 편입"],
}

CANONICAL_ORIGIN_BY_ISSUE_CODE = {
    "order_contract": "기업 내부",
    "strike": "기업 내부",
    "owner_legal": "오너/지배구조",
    "hbm_demand": "산업",
    "foundry_yield": "산업",
    "memory_price": "산업",
    "smartphone_demand": "산업",
    "subsidy_expand": "정책",
    "subsidy_cut": "정책",
    "platform_regulation": "정책",
    "rare_earth_control": "국제정세",
    "oil_price_up": "거시",
    "flow_sell": "수급",
    "flow_buy": "수급",
}

CANONICAL_ORIGIN_TEXT_MAP = {
    "기업 내부": "기업 내부",
    "재무/실적": "실적",
    "실적": "실적",
    "오너/지배구조": "오너/지배구조",
    "산업/섹터 + 고객사 밸류체인": "산업",
    "산업/섹터": "산업",
    "산업/경쟁구도": "산업",
    "제품 수요/고객사 수요": "산업",
    "정책/규제/국가전략": "정책",
    "국제정세/지정학 + 원자재/공급망": "국제정세",
    "국제정세/지정학": "국제정세",
    "거시경제/원자재": "거시",
    "수급/시장구조": "수급",
    "감성": "감성",
    "분류 불가/확인 필요": "루머",
}

INDUSTRY_DIRECTION_RULES = {
    "oil_price_up": {
        "항공": ("악재 신호", "항공사는 유류비 비중이 커 유가 상승이 비용/마진 부담으로 작용할 수 있음"),
        "정유": ("혼합 신호", "정유사는 재고평가 이익과 정제마진에는 긍정일 수 있으나 수요 둔화와 마진 변동을 함께 봐야 함"),
        "자동차": ("악재 신호", "유가 상승은 소비심리와 운행비 부담을 통해 자동차 수요에 부담이 될 수 있음"),
        "배터리": ("불명확", "유가 상승은 전기차 상대 매력에는 긍정일 수 있지만 원가/시장심리와 함께 봐야 함"),
    },
    "subsidy_expand": {
        "배터리": ("호재 신호", "배터리 산업은 전기차 보조금·세액공제 확대가 수요와 투자비 부담 완화 기대로 이어질 수 있음"),
        "자동차": ("호재 신호", "전기차 보조금 확대는 판매 수요에 긍정적으로 작용할 수 있음"),
    },
    "subsidy_cut": {
        "배터리": ("악재 신호", "보조금 제외·축소·폐지는 전기차 수요와 배터리 업체 기대에 부담이 될 수 있음"),
        "자동차": ("악재 신호", "보조금 제외·축소는 전기차 판매 조건에 부담이 될 수 있음"),
    },
    "rare_earth_control": {
        "반도체/전자": ("악재 신호", "희토류 수출통제는 부품·장비 공급망과 원가 불확실성을 키울 수 있음"),
        "반도체": ("악재 신호", "희토류 수출통제는 반도체 소재·장비 공급망 불확실성을 키울 수 있음"),
        "배터리": ("악재 신호", "희토류·핵심광물 통제는 소재 조달 부담으로 이어질 수 있음"),
        "자동차": ("악재 신호", "전기차 모터·부품 공급망 부담 가능성이 있음"),
    },
    "strike": {
        "자동차": ("악재 신호", "완성차 생산 차질과 출고 지연 우려가 직접 발생할 수 있음"),
        "조선": ("악재 신호", "조선업 파업은 생산 일정과 인도 지연 우려로 이어질 수 있음"),
    },
    "order_contract": {
        "조선": ("호재 신호", "조선사의 수주는 수주잔고와 향후 매출 가시성 개선으로 해석될 수 있음"),
    },
    "owner_legal": {
        "플랫폼/인터넷": ("악재 신호", "오너·경영진 수사 이슈는 지배구조와 경영 불확실성, 규제 리스크로 해석될 수 있음"),
    },
    "platform_regulation": {
        "플랫폼/인터넷": ("악재 신호", "플랫폼 규제 강화는 광고·커머스·수수료 정책과 사업 확장성에 부담이 될 수 있음"),
    },
    "flow_sell": {
        "default": ("악재 신호", "대량 순매도·공매도·보호예수 해제는 단기 수급 부담 신호일 수 있음"),
    },
    "flow_buy": {
        "default": ("호재 신호", "대량 순매수·지수 편입은 단기 수급 개선 신호일 수 있음"),
    },
}

INDUSTRY_KEYWORDS = {
    "반도체/전자": ["반도체", "HBM", "메모리", "D램", "DRAM", "낸드", "NAND", "파운드리", "전자", "스마트폰", "갤럭시", "TSMC", "마이크론", "엔비디아"],
    "반도체": ["반도체", "HBM", "메모리", "D램", "DRAM", "낸드", "NAND", "AI 반도체", "엔비디아", "마이크론"],
    "자동차": ["자동차", "현대차", "기아", "전기차", "부품사", "완성차"],
    "항공": ["항공", "여객", "화물", "유류할증료", "공항"],
    "정유": ["정유", "정제마진", "원유", "석유"],
    "배터리": ["배터리", "전기차", "IRA", "AMPC", "리튬", "양극재"],
    "조선": ["조선", "LNG선", "선박", "선가", "카타르", "삼성중공업", "HD현대중", "HD현대重"],
    "플랫폼/인터넷": ["플랫폼", "카카오", "네이버", "오너", "김범수", "규제"],
}


def get_company_profile(company: str, ticker: Optional[str]) -> dict:
    code = normalize_ticker_for_fdr(ticker) if ticker else None
    if code and code in COMPANY_PROFILES:
        return COMPANY_PROFILES[code]
    for profile in COMPANY_PROFILES.values():
        if company == profile["company"] or company in profile.get("aliases", []):
            return profile
    return {"company": company, "industry": "미분류", "aliases": [company], "exposures": []}


def detect_issue_codes(text: str) -> list[str]:
    # 더 구체적인 악재/축소 표현이 일반 정책 지원 표현보다 우선한다.
    # 예: "보조금 폐지"는 보조금이라는 단어를 포함하지만 확대/수혜가 아니라 축소 리스크다.
    priority = [
        "subsidy_cut",
        "flow_sell",
        "owner_legal",
        "platform_regulation",
        "strike",
        "rare_earth_control",
        "hbm_demand",
        "foundry_yield",
        "smartphone_demand",
        "memory_price",
        "oil_price_up",
        "order_contract",
        "subsidy_expand",
        "flow_buy",
    ]
    detected = [code for code in priority if contains_any(text, ISSUE_TYPE_KEYWORDS.get(code, []))]
    if "subsidy_cut" in detected and "subsidy_expand" in detected:
        detected.remove("subsidy_expand")
    return detected


def normalize_origin_text(origin: Optional[str]) -> str:
    if not origin:
        return "루머"
    for needle, label in CANONICAL_ORIGIN_TEXT_MAP.items():
        if needle in origin:
            return label
    return "루머"


def canonical_origin(origins: list[str], issue_codes: list[str], official_origin: Optional[str] = None) -> str:
    if official_origin:
        return normalize_origin_text(official_origin)
    for code in issue_codes:
        if code in CANONICAL_ORIGIN_BY_ISSUE_CODE:
            return CANONICAL_ORIGIN_BY_ISSUE_CODE[code]
    for origin in origins:
        label = normalize_origin_text(origin)
        if label != "루머":
            return label
    return "루머"


def industry_direction(issue_codes: list[str], industry: str) -> Optional[dict]:
    for code in issue_codes:
        rules = INDUSTRY_DIRECTION_RULES.get(code, {})
        if industry in rules:
            direction, reason = rules[industry]
            return {"issue_code": code, "direction": direction, "reason": reason, "source": "industry_rule"}
        if "default" in rules:
            direction, reason = rules["default"]
            return {"issue_code": code, "direction": direction, "reason": reason, "source": "default_industry_rule"}
    return None


SENSITIVITY_LABELS = {
    "very_high": "매우 높음",
    "high": "높음",
    "medium_high": "중상",
    "medium": "중간",
    "medium_low": "중하",
    "low": "낮음",
}

ISSUE_SEGMENT_HINTS = {
    "memory_price": ["memory", "dram", "nand"],
    "hbm_demand": ["hbm", "memory"],
    "foundry_yield": ["foundry"],
    "smartphone_demand": ["smartphone"],
    "rare_earth_control": ["memory", "foundry", "smartphone"],
}

ISSUE_COMPANY_REASONS = {
    "memory_price": "메모리 가격/업황 이슈는 메모리 매출·이익 비중이 높은 회사일수록 민감도가 커짐",
    "hbm_demand": "HBM·AI 서버 수요 이슈는 HBM 노출도와 주요 고객 공급망 위치에 따라 민감도가 달라짐",
    "foundry_yield": "파운드리 수율/경쟁 이슈는 파운드리 사업 노출이 큰 회사에 더 직접적임",
    "smartphone_demand": "스마트폰 수요 이슈는 완제품 또는 모바일 부품 노출이 있는 회사에 더 직접적임",
    "rare_earth_control": "희토류/공급망 통제 이슈는 직접 사용 여부와 사업부별 공급망 의존도 확인이 필요함",
}


ISSUE_RELEVANCE_ROUTES = {
    "hbm_demand": {
        "label": "HBM/AI 반도체 수요 파급",
        "industries": {"반도체": 1, "반도체/전자": 1},
        "segments": ["hbm"],
        "exposure_keywords": ["HBM", "AI", "엔비디아", "메모리", "반도체"],
        "path": ["AI/HBM 수요", "HBM 공급사/메모리 업체", "해당 회사의 HBM·메모리 노출"],
    },
    "foundry_yield": {
        "label": "파운드리 수율/경쟁 파급",
        "industries": {"반도체/전자": 1},
        "segments": ["foundry"],
        "path": ["파운드리 수율/경쟁", "위탁생산 경쟁력", "파운드리 사업 노출 회사"],
    },
    "memory_price": {
        "label": "메모리 업황 파급",
        "industries": {"반도체": 1, "반도체/전자": 1},
        "segments": ["memory", "dram", "nand"],
        "path": ["메모리 가격/재고", "메모리 업체 매출·마진", "메모리 사업 노출 회사"],
    },
    "subsidy_cut": {
        "label": "전기차/배터리 정책 축소 파급",
        "industries": {"배터리": 1, "자동차": 1},
        "exposure_keywords": ["배터리", "전기차", "보조금", "IRA"],
        "path": ["정책 지원 축소", "전기차 수요/투자 조건 변화", "배터리·자동차 노출 회사"],
    },
    "subsidy_expand": {
        "label": "전기차/배터리 정책 지원 파급",
        "industries": {"배터리": 1, "자동차": 1},
        "exposure_keywords": ["배터리", "전기차", "보조금", "IRA"],
        "path": ["정책 지원 확대", "전기차 수요/투자 조건 개선", "배터리·자동차 노출 회사"],
    },
    "oil_price_up": {
        "label": "유가/에너지 비용 파급",
        "industries": {"항공": 1, "정유": 1, "자동차": 2},
        "exposure_keywords": ["유가", "원유", "정제마진", "유류할증료", "항공"],
        "path": ["국제유가 상승", "연료비·정제마진·소비심리 변화", "에너지 비용/수요 노출 회사"],
    },
    "rare_earth_control": {
        "label": "희토류/공급망 통제 파급",
        "industries": {"반도체": 2, "반도체/전자": 2, "배터리": 2, "자동차": 2},
        "exposure_keywords": ["공급망", "희토류", "반도체", "배터리", "전기차"],
        "path": ["희토류 수출통제", "소재·부품 조달 불확실성", "공급망 노출 회사"],
    },
    "order_contract": {
        "label": "수주/공급계약 직접 이벤트",
        "industries": {"조선": 0},
        "exposure_keywords": ["수주", "LNG선", "선박", "조선", "방산"],
        "path": ["수주/공급계약", "수주잔고·매출 가시성", "계약 당사 회사"],
    },
    "strike": {
        "label": "파업/생산차질 직접 이벤트",
        "industries": {"자동차": 0, "조선": 0},
        "exposure_keywords": ["노사", "파업", "생산", "조업"],
        "path": ["노사 이슈", "생산 차질 가능성", "생산 노출 회사"],
    },
    "owner_legal": {
        "label": "오너/지배구조 직접 이벤트",
        "industries": {"플랫폼/인터넷": 0},
        "exposure_keywords": ["오너", "지배구조", "규제", "플랫폼"],
        "path": ["오너/경영진 법률 이슈", "지배구조·경영 불확실성", "회사 신뢰/사업 운영"],
    },
    "platform_regulation": {
        "label": "플랫폼 규제 정책 파급",
        "industries": {"플랫폼/인터넷": 1},
        "exposure_keywords": ["플랫폼", "광고", "커머스", "규제"],
        "path": ["플랫폼 규제 강화", "광고·커머스 정책 부담", "플랫폼 사업 노출 회사"],
    },
    "flow_sell": {
        "label": "수급/시장구조 직접 신호",
        "universal_if_company_mentioned": True,
        "universal_impact_level": 4,
        "path": ["수급 데이터", "단기 매물 부담", "해당 종목 거래 흐름"],
    },
    "flow_buy": {
        "label": "수급/시장구조 직접 신호",
        "universal_if_company_mentioned": True,
        "universal_impact_level": 4,
        "path": ["수급 데이터", "단기 매수 유입", "해당 종목 거래 흐름"],
    },
}


def issue_context_relevance_gate(issue_codes: list[str], profile: dict, text: str) -> dict:
    """Check whether the company sits inside the issue's propagation route.

    This runs before strong direction wording. A news keyword can be important
    in the market, but if the company's industry/exposure is outside the route,
    we should not force a bullish/bearish label onto that company.
    """
    def level_meta(level: int) -> dict:
        strength = {
            0: "강함",
            1: "중상",
            2: "중간",
            3: "낮음",
            4: "낮음",
            5: "매우 낮음",
        }.get(level, "매우 낮음")
        permission = "normal" if level <= 2 else "weak" if level in (3, 4) else "observe_only"
        distance = "직접" if level == 0 else f"{level}차 영향"
        if level <= 3:
            legacy_distance = "직접" if level == 0 else f"{level}단계 간접"
        elif level == 4:
            legacy_distance = "테마 확장"
        else:
            legacy_distance = "관련 낮음"
        return {
            "impact_level": level,
            "impact_strength": strength,
            "direction_permission": permission,
            "impact_distance": legacy_distance,
            "impact_label": distance,
        }

    if not issue_codes:
        meta = level_meta(5)
        return {
            "status": "no_issue",
            "relevance": "관련 낮음",
            **meta,
            "reason": "입력에서 인식된 이슈 코드가 없어 회사별 방향성을 판단하지 않습니다.",
            "matched_routes": [],
        }

    industry = profile.get("industry", "미분류")
    exposures = profile.get("exposures", [])
    segments = profile.get("business_segments", {})
    aliases = profile.get("aliases", [])
    company_mentioned = contains_any(text, aliases)
    matched = []

    for code in issue_codes:
        route = ISSUE_RELEVANCE_ROUTES.get(code)
        if not route:
            continue

        if route.get("universal_if_company_mentioned") and company_mentioned:
            universal_level = route.get("universal_impact_level", 0)
            matched.append({
                "issue_code": code,
                "route": route["label"],
                "impact_level": universal_level,
                "relevance": "수급/감성 관련",
                "path": route.get("path", []),
                "reason": "회사명이 포함된 종목 수급/시장구조 신호입니다.",
            })
            continue

        level = None
        reason = None
        segment_hits = [segment for segment in route.get("segments", []) if segment in segments and segments.get(segment) != "low"]
        if segment_hits:
            strongest = max([segments.get(segment) for segment in segment_hits], key=lambda value: {"very_high": 5, "high": 4, "medium_high": 3, "medium": 2, "medium_low": 1, "low": 0}.get(value, -1))
            level = 0 if strongest in ("very_high", "high") else 1
            reason = "회사 사업부 노출도가 이슈 파급 경로와 맞습니다."
        elif route.get("industries", {}).get(industry) is not None:
            level = route.get("industries", {}).get(industry)
            reason = f"{industry} 업종이 이슈 파급 경로에 포함됩니다."
        elif contains_any(" ".join(exposures), route.get("exposure_keywords", [])):
            level = 2
            reason = "회사 노출 키워드가 이슈 파급 경로와 맞습니다."

        if level is not None:
            relevance = "직접 관련" if level == 0 else "산업/공급망 관련"
            matched.append({
                "issue_code": code,
                "route": route["label"],
                "impact_level": level,
                "relevance": relevance,
                "path": route.get("path", []),
                "reason": reason,
            })

    if not matched:
        meta = level_meta(5)
        return {
            "status": "ok",
            "relevance": "관련 낮음",
            **meta,
            "reason": f"{industry} 업종/노출도가 입력 이슈의 1~3차 파급 경로에 바로 걸리지 않아 5차 관찰 영향으로 낮춥니다.",
            "matched_routes": [],
        }

    matched.sort(key=lambda item: item["impact_level"])
    lead = matched[0]
    meta = level_meta(lead["impact_level"])
    return {
        "status": "ok",
        "relevance": lead["relevance"],
        **meta,
        "reason": lead["reason"],
        "matched_routes": matched,
    }


def company_specific_assessment(issue_codes: list[str], profile: dict) -> Optional[dict]:
    sensitivities = profile.get("issue_sensitivity", {})
    segments = profile.get("business_segments", {})
    matches = []
    for code in issue_codes:
        sensitivity = sensitivities.get(code)
        if not sensitivity:
            continue
        segment_hits = []
        for segment in ISSUE_SEGMENT_HINTS.get(code, []):
            if segment in segments:
                segment_hits.append({
                    "segment": segment,
                    "weight": segments[segment],
                    "weight_label": SENSITIVITY_LABELS.get(segments[segment], segments[segment]),
                })
        matches.append({
            "issue_code": code,
            "sensitivity": sensitivity,
            "sensitivity_label": SENSITIVITY_LABELS.get(sensitivity, sensitivity),
            "reason": ISSUE_COMPANY_REASONS.get(code, "회사별 사업 포트폴리오 기준으로 민감도를 다르게 봅니다."),
            "segment_hits": segment_hits,
        })
    if not matches:
        return None
    rank = {"very_high": 5, "high": 4, "medium_high": 3, "medium": 2, "medium_low": 1, "low": 0}
    matches.sort(key=lambda item: rank.get(item["sensitivity"], -1), reverse=True)
    lead = matches[0]
    return {
        "status": "ok",
        "company": profile.get("company"),
        "industry": profile.get("industry", "미분류"),
        "lead_issue_code": lead["issue_code"],
        "sensitivity": lead["sensitivity"],
        "sensitivity_label": lead["sensitivity_label"],
        "reason": lead["reason"],
        "matches": matches,
    }


def assess_relevance(title: str, profile: dict) -> tuple[str, str]:
    aliases = profile.get("aliases", [])
    industry = profile.get("industry", "미분류")
    exposures = profile.get("exposures", [])
    if contains_any(title, aliases):
        return "직접 관련", "회사명/별칭이 제목에 포함됨"
    if industry != "미분류" and contains_any(title, INDUSTRY_KEYWORDS.get(industry, [])):
        return "업종 관련", f"{industry} 관련 키워드가 제목에 포함됨"
    if contains_any(title, exposures):
        return "노출도 관련", "회사의 주요 노출 변수와 관련된 키워드가 제목에 포함됨"
    if contains_any(title, ["중국", "미국", "중동", "관세", "유가", "금리", "환율", "보조금", "IRA", "수출통제", "수출 제한"]):
        return "거시/정책 관련", "거시·정책 키워드가 제목에 포함됨"
    return "관련 낮음", "회사·업종·노출도 키워드와 직접 연결이 약함"

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
    {
        "case_id": "kakao_owner_legal_2024_07_23",
        "company": "카카오",
        "date": "2024-07-23",
        "title": "오너 구속/지배구조 리스크",
        "keywords": ["카카오", "김범수", "오너", "구속", "수사", "지배구조"],
        "effect_levels": [0, 3, 4],
        "emotions": ["충격", "불확실성", "공포"],
        "price_note": "+10영업일 -2.19%",
        "context": ["오너 개인 이슈와 회사 운영 리스크 구분 필요", "규제/플랫폼 업황 뉴스 동반 여부 확인 필요"],
    },
]


def contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys([value for value in values if value]))


def load_dart_resolver():
    global _DART_RESOLVER_MODULE
    if _DART_RESOLVER_MODULE is not None:
        return _DART_RESOLVER_MODULE
    spec = importlib.util.spec_from_file_location("dart_event_resolver", DART_RESOLVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _DART_RESOLVER_MODULE = module
    return module


def normalize_dart_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def classify_news_item(title: str, company: str, sentence: str, profile: Optional[dict] = None) -> dict:
    title_text = title
    profile = profile or get_company_profile(company, None)
    title_issue_codes = detect_issue_codes(title_text)
    context_issue_codes = detect_issue_codes(sentence)
    issue_codes = unique(title_issue_codes + context_issue_codes)
    channels = [name for name, keywords in CHANNEL_KEYWORDS.items() if contains_any(title_text, keywords)]
    emotions = [name for name, keywords in EMOTION_KEYWORDS.items() if contains_any(title_text, keywords)]

    if contains_any(title_text, POSITIVE_KEYWORDS) and contains_any(title_text, NEGATIVE_KEYWORDS):
        direction = "혼합 신호"
    elif contains_any(title_text, POSITIVE_KEYWORDS):
        direction = "호재 신호"
    elif contains_any(title_text, NEGATIVE_KEYWORDS):
        direction = "악재 신호"
    else:
        direction = "불명확"

    if contains_any(title_text, CONFIRMED_KEYWORDS):
        confidence = "뉴스 확인/공식 확인 필요"
    elif contains_any(title_text, UNCERTAIN_KEYWORDS):
        confidence = "예상/전망"
    else:
        confidence = "뉴스 확인"

    relevance, relevance_reason = assess_relevance(title, profile)
    propagation_gate = issue_context_relevance_gate(issue_codes, profile, title_text)
    # 개별 RSS 제목에 이슈 키워드가 직접 잡힐 때만 산업별 방향 룰을 강하게 적용한다.
    # 입력 문장의 이슈를 모든 뉴스에 덮어씌우면 관련 없는 기사까지 같은 호재/악재로 오염된다.
    company_assessment = company_specific_assessment(title_issue_codes or context_issue_codes, profile)
    override = industry_direction(title_issue_codes, profile.get("industry", "미분류"))
    if propagation_gate.get("direction_permission") == "observe_only":
        direction = "불명확"
        relevance = "관련 낮음"
        relevance_reason = propagation_gate.get("reason", relevance_reason)
        direction_reason = "회사가 해당 이슈의 가까운 파급 경로 밖에 있어 5차 관찰 영향으로만 표시하고 방향성을 판단하지 않습니다."
    elif override and relevance != "관련 낮음":
        direction = override["direction"]
        direction_reason = override["reason"]
    else:
        context_override = industry_direction(context_issue_codes, profile.get("industry", "미분류"))
        if context_override and relevance in ("직접 관련", "업종 관련", "노출도 관련"):
            direction_reason = f"입력 이슈의 업종 룰 참고: {context_override['reason']}"
        else:
            direction_reason = "뉴스 제목의 키워드를 기준으로 한 1차 룰 기반 분류입니다."

    level = 4
    if company and company in title and contains_any(title_text, ["파업", "구속", "수주", "공시", "발표", "생산중단", "보조금 제외", "적자전환"]):
        level = 0
    if contains_any(title_text, ["생산 차질", "생산 중단", "생산중단", "유류할증료", "연료비", "원가", "마진", "실적", "적자", "수주"]):
        level = min(level, 1)
    if contains_any(title_text, ["부품", "협력사", "그룹", "기아", "공급망", "반도체", "배터리", "방산", "경쟁", "업황"]):
        level = min(level, 2)
    if contains_any(title_text, ["중국", "미국", "중동", "관세", "수출통제", "수출 제한", "유가", "금리", "환율", "보조금", "IRA", "전쟁", "분쟁"]):
        level = min(level, 3)
    if contains_any(title_text, ["주가", "순매도", "순매수", "급등", "하락", "테마", "투자심리"]):
        level = 4

    return {
        "effect_level": level,
        "effect_label": EFFECT_LEVELS[level],
        "issue_codes": issue_codes,
        "title_issue_codes": title_issue_codes,
        "context_issue_codes": context_issue_codes,
        "direction": direction,
        "confidence": confidence,
        "relevance": relevance,
        "relevance_reason": relevance_reason,
        "industry": profile.get("industry", "미분류"),
        "industry_direction_rule": override,
        "context_relevance_gate": propagation_gate,
        "company_specific_assessment": company_assessment,
        "channels": unique(channels),
        "emotions": unique(emotions),
        "reason": direction_reason,
    }


def enrich_rss_news(rss: dict, company: str, sentence: str, profile: Optional[dict] = None) -> dict:
    if rss.get("status") != "ok":
        return rss
    summary = {str(level): {"label": EFFECT_LEVELS[level], "count": 0, "items": []} for level in EFFECT_LEVELS}
    emotion_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    for item in rss.get("items", []):
        signal = classify_news_item(item.get("title", ""), company, sentence, profile)
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


LLM_ASSESSMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer"},
                    "relevance": {"type": "string", "enum": ["직접 관련", "업종 관련", "노출도 관련", "거시/정책 관련", "관련 낮음"]},
                    "direction": {"type": "string", "enum": ["호재 신호", "악재 신호", "혼합 신호", "불명확"]},
                    "effect_level": {"type": "integer", "enum": [0, 1, 2, 3, 4]},
                    "emotion_tags": {"type": "array", "items": {"type": "string"}},
                    "issue_types": {"type": "array", "items": {"type": "string"}},
                    "company_sensitivity": {"type": "string", "enum": ["매우 높음", "높음", "중상", "중간", "중하", "낮음", "불명확"]},
                    "confidence": {"type": "string", "enum": ["높음", "중간", "낮음"]},
                    "reason": {"type": "string"},
                    "checkpoints": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["index", "relevance", "direction", "effect_level", "emotion_tags", "issue_types", "company_sensitivity", "confidence", "reason", "checkpoints"],
            },
        },
        "summary": {"type": "string"},
        "cautions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["items", "summary", "cautions"],
}


def load_local_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def extract_response_text(payload: dict) -> str:
    if payload.get("output_text"):
        return payload["output_text"]
    parts = []
    for output in payload.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in ("output_text", "text") and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def call_openai_structured(prompt: str, model: str, timeout: int = 45, retries: int = 1) -> dict:
    load_local_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"status": "skipped", "reason": "OPENAI_API_KEY 환경변수가 없어 LLM 평가를 건너뜁니다."}

    body = {
        "model": model,
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "stock_context_news_assessment",
                "schema": LLM_ASSESSMENT_SCHEMA,
                "strict": True,
            }
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_error = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout + attempt * 30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            last_error = f"OpenAI API HTTP {exc.code}: {detail}"
            if 400 <= exc.code < 500 and exc.code != 429:
                return {"status": "error", "reason": last_error, "attempts": attempt + 1}
        except Exception as exc:
            last_error = str(exc)
    else:
        return {"status": "error", "reason": last_error or "OpenAI API 호출 실패", "attempts": retries + 1}

    output_text = extract_response_text(payload)
    if not output_text:
        return {"status": "error", "reason": "OpenAI 응답에서 텍스트를 찾지 못했습니다.", "raw_status": payload.get("status")}
    try:
        parsed = json.loads(output_text)
    except Exception as exc:
        return {"status": "error", "reason": f"LLM JSON 파싱 실패: {exc}", "raw_text": output_text[:1000]}
    parsed["status"] = "ok"
    parsed["model"] = model
    parsed["attempts"] = attempt + 1
    return parsed


def build_llm_news_prompt(company: str, sentence: str, profile: dict, items: list[dict]) -> str:
    compact_items = []
    for index, item in enumerate(items):
        compact_items.append({
            "index": index,
            "title": item.get("title", ""),
            "date": item.get("published_date"),
            "source": item.get("source"),
            "rule_signal": item.get("signal", {}),
        })
    return json.dumps(
        {
            "role": "stock_context_signal_classifier",
            "instruction": (
                "너는 투자 추천을 하지 않는다. 뉴스 제목을 회사/산업/노출도 관점의 상황 신호로만 분류한다. "
                "주가 원인을 단정하지 말고, 직접 관련/간접 관련/관련 낮음을 구분한다. "
                "같은 업종 내 기업별 사업 포트폴리오 차이를 반드시 반영한다. "
                "여러 이슈가 섞인 제목은 issue_types에 복수로 표시하고, reason에는 왜 그렇게 봤는지 짧게 쓴다."
            ),
            "effect_level_definition": {
                "0": "기준 사건: 회사 자체의 공식/직접 사건",
                "1": "직접 작용: 매출·비용·생산·계약에 바로 닿는 신호",
                "2": "산업/공급망 파급: 동종업계·경쟁사·공급망 신호",
                "3": "외부환경 결합: 정책·거시·국제정세·원자재 신호",
                "4": "시장 반응/심리: 주가·수급·테마·심리 신호",
            },
            "company": company,
            "input_sentence": sentence,
            "company_profile": profile,
            "news_items": compact_items,
            "output_language": "ko-KR",
        },
        ensure_ascii=False,
    )


def attach_llm_assessment(rss: dict, company: str, sentence: str, profile: dict, model: str, limit: int = 8) -> dict:
    if rss.get("status") != "ok":
        rss["llm_assessment"] = {"status": "skipped", "reason": "RSS 뉴스가 없어 LLM 평가를 건너뜁니다."}
        return rss
    items = rss.get("items", [])[:limit]
    if not items:
        rss["llm_assessment"] = {"status": "skipped", "reason": "LLM으로 평가할 뉴스가 없습니다."}
        return rss
    prompt = build_llm_news_prompt(company, sentence, profile, items)
    assessment = call_openai_structured(prompt, model, retries=1)
    rss["llm_assessment"] = assessment
    if assessment.get("status") != "ok":
        return rss
    for llm_item in assessment.get("items", []):
        index = llm_item.get("index")
        if isinstance(index, int) and 0 <= index < len(items):
            items[index]["llm_signal"] = llm_item
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
        "observation_label": {"높음": "뚜렷함", "중간": "관찰됨", "낮음": "약함/없음"}.get(label, "약함/없음"),
        "price_checks": price_checks,
        "pre_news_count": len(pre_items),
        "pre_emotional_news_count": len(emotional_pre),
        "reasons": reasons or ["기준일 전 가격/뉴스/감정 신호만으로는 선행 가격 움직임이 뚜렷하지 않습니다."],
        "caution": "선행 가격 움직임은 원인 판정이 아니라 관찰값입니다. 다른 이슈로 인한 가격 변동일 수 있습니다.",
    }


def price_move_direction(change_pct: Optional[float], threshold: float = 2.0) -> str:
    if change_pct is None:
        return "unknown"
    if change_pct >= threshold:
        return "up"
    if change_pct <= -threshold:
        return "down"
    return "flat"


def expected_price_direction(signal_balance: str) -> str:
    return {
        "호재 중심": "up",
        "악재 중심": "down",
    }.get(signal_balance, "none")


def find_primary_post_move(price: dict) -> dict:
    if price.get("status") != "ok":
        return {"status": "missing", "reason": "가격 참고값이 없어 기준일 이후 움직임을 비교하지 않았습니다."}
    offsets = price.get("offsets", {})
    for key in ("3", "5", "10"):
        item = offsets.get(key, {})
        if item and item.get("status") != "missing":
            change_pct = item.get("change_pct")
            return {
                "status": "ok",
                "window": f"T~T+{key}",
                "date": item.get("date"),
                "change": item.get("change"),
                "change_pct": change_pct,
                "direction": price_move_direction(change_pct),
            }
    return {"status": "missing", "reason": "기준일 이후 3·5·10영업일 가격 데이터를 찾지 못했습니다."}


def find_primary_pre_move(price: dict) -> dict:
    if price.get("status") != "ok":
        return {"status": "missing", "reason": "가격 참고값이 없어 기준일 전 움직임을 비교하지 않았습니다."}
    pre_event = price.get("pre_event", {})
    for key in ("10", "5", "3"):
        item = pre_event.get(key, {})
        if item and item.get("status") != "missing":
            change_pct = item.get("change_pct")
            return {
                "status": "ok",
                "window": item.get("window", f"T-{key}~T-1"),
                "start_date": item.get("start_date"),
                "end_date": item.get("end_date"),
                "change": item.get("change"),
                "change_pct": change_pct,
                "direction": price_move_direction(change_pct),
            }
    return {"status": "missing", "reason": "기준일 전 3·5·10영업일 가격 데이터를 찾지 못했습니다."}


def build_candidate(kind: str, label: str, evidence: str, confidence: str, guardrail: str = "단일 원인으로 확정할 수 없습니다.") -> dict:
    return {
        "type": kind,
        "label": label,
        "evidence": evidence,
        "confidence": confidence,
        "guardrail": guardrail,
    }


def explain_market_contradiction(card: dict) -> dict:
    price = card.get("price_reference", {})
    expected = expected_price_direction(card.get("signal_balance", ""))
    post = find_primary_post_move(price)
    pre = find_primary_pre_move(price)
    issue_codes = set(card.get("input_issue_codes", []))
    positives = card.get("positive_signals", [])
    negatives = card.get("negative_signals", [])
    candidates = []

    if post.get("status") != "ok":
        return {
            "status": "skipped",
            "reason": post.get("reason"),
            "guardrail": "뉴스 방향과 가격 움직임의 불일치는 가격 데이터가 있을 때만 관찰합니다.",
        }

    actual = post.get("direction")
    if expected == "none":
        alignment = "direction_not_asserted"
    elif actual == "flat":
        alignment = "muted_response"
    elif expected == actual:
        alignment = "aligned"
    else:
        alignment = "contradiction"

    if alignment == "contradiction" and pre.get("status") == "ok":
        pre_pct = pre.get("change_pct") or 0.0
        if expected == "down" and actual == "up" and pre_pct <= -3.0:
            candidates.append(build_candidate(
                "prior_price_move",
                "악재 선행 하락 후 반등 가능성",
                f"{pre['window']} 가격 변화 {pre_pct:.2f}% 이후 {post['window']} {post['change_pct']:.2f}% 움직임",
                "중간",
                "악재가 먼저 반영됐다고 단정하지 말고, 같은 기간 다른 호재·시장 반등·수급을 함께 확인해야 합니다.",
            ))
        elif expected == "up" and actual == "down" and pre_pct >= 3.0:
            candidates.append(build_candidate(
                "prior_price_move",
                "호재 선행 상승/차익실현 가능성",
                f"{pre['window']} 가격 변화 +{pre_pct:.2f}% 이후 {post['window']} {post['change_pct']:.2f}% 움직임",
                "중간",
                "호재가 선반영됐다고 단정하지 말고, 실적 기대치·수급·시장 하락을 함께 확인해야 합니다.",
            ))

    if positives and negatives:
        candidates.append(build_candidate(
            "offsetting_signals",
            "호재와 악재가 동시에 존재",
            f"호재 신호 {len(positives)}개, 악재 신호 {len(negatives)}개가 함께 잡혔습니다.",
            "중간",
            "뉴스 개수보다 각 신호의 공식성·규모·시점을 우선 비교해야 합니다.",
        ))

    if issue_codes & {"flow_sell", "flow_buy"}:
        candidates.append(build_candidate(
            "flow_pressure",
            "수급/포지셔닝 압력",
            "입력 문장에서 순매도·순매수·공매도·지수 편입 같은 시장 구조 신호가 잡혔습니다.",
            "낮음",
            "수급은 기업 가치 원인이라기보다 가격 압력 또는 시장 반응층으로 분리해 봐야 합니다.",
        ))

    if alignment in {"contradiction", "muted_response"}:
        candidates.append(build_candidate(
            "expectation_gap",
            "예상치와 실제의 차이",
            "표면적으로 호재/악재여도 시장 기대보다 강하거나 약했는지 별도 확인이 필요합니다.",
            "낮음",
            "컨센서스, 가이던스, 직전 주가 기대를 확인하기 전에는 판단을 보류합니다.",
        ))
        candidates.append(build_candidate(
            "market_or_sector_move",
            "시장/업종 동반 움직임",
            "종목 고유 이슈가 아니라 시장·업종 전체 반등/하락일 수 있습니다.",
            "낮음",
            "KOSPI/KOSDAQ, 업종지수, 주요 경쟁사 수익률과 비교해야 합니다.",
        ))

    if not candidates:
        candidates.append(build_candidate(
            "no_strong_contradiction",
            "뚜렷한 불일치 후보 없음",
            f"이슈 방향과 {post['window']} 가격 움직임이 크게 어긋난 신호는 약합니다.",
            "낮음",
            "가격 움직임의 원인을 단일 뉴스로 확정하지 않습니다.",
        ))

    return {
        "status": "ok",
        "news_direction": card.get("signal_balance"),
        "expected_price_direction": expected,
        "post_event_price_move": post,
        "pre_event_price_move": pre,
        "alignment": alignment,
        "candidates": candidates,
        "summary": "뉴스/이슈 방향과 가격 움직임이 어긋날 때 가능한 설명 후보를 정리합니다.",
        "guardrail": "불일치 해석은 원인 확정이 아니라 후보 지도입니다.",
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
    for keyword in ["희토류", "수출 제한", "공장증설", "실적쇼크", "파업", "생산 차질", "유가", "보조금", "수주", "LNG선", "오너", "수사", "순매도", "외국인", "HBM", "엔비디아", "파운드리", "수율", "스마트폰", "갤럭시", "메모리", "D램", "DRAM", "낸드", "NAND"]:
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


def build_card(
    company: str,
    ticker: Optional[str],
    sentence: str,
    event_date: Optional[str] = None,
    include_rss: bool = False,
    rss_before: int = 3,
    rss_after: int = 10,
    use_llm: bool = False,
    llm_model: Optional[str] = None,
    use_dart: bool = False,
    dart_before: int = 30,
    dart_after: int = 10,
) -> dict:
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

    company_profile = get_company_profile(company, ticker)
    input_issue_codes = detect_issue_codes(sentence)
    context_relevance_gate = issue_context_relevance_gate(input_issue_codes, company_profile, sentence)
    dart_event = {"status": "skipped", "reason": "--dart 옵션이 꺼져 있습니다."}
    if use_dart:
        if context_relevance_gate.get("direction_permission") == "observe_only":
            dart_event = {
                "status": "skipped",
                "reason": "입력 이슈가 이 회사에는 5차 관찰 영향으로 분류되어 DART 공식 이벤트 잠금을 적용하지 않았습니다.",
            }
        else:
            try:
                dart_resolver = load_dart_resolver()
                dart_event = dart_resolver.resolve_dart_event(
                    company,
                    ticker,
                    sentence,
                    event_date=event_date,
                    issue_codes=input_issue_codes,
                    before_days=dart_before,
                    after_days=dart_after,
                )
            except Exception as exc:
                dart_event = {"status": "error", "reason": str(exc)}
    if dart_event.get("status") == "official_match":
        origins = [dart_event.get("origin", "기업 내부")] + origins
        issue_types = [dart_event.get("official_event_type", "DART 공식 공시")] + issue_types
        event_date = normalize_dart_date(dart_event.get("event_date")) or event_date
        for signal in positive + negative:
            if signal.confidence in ("공시 확인 필요", "공식 확인 필요", "뉴스 확인/공식 확인 필요"):
                signal.confidence = "DART 공식 확인"
        questions = list(dict.fromkeys([
            "DART 공식 공시의 세부 조건과 규모를 확인했는가?",
            "공시 이후 같은 기간의 추가 공시나 정정 공시가 있는가?",
            "공시 내용이 실제 매출·비용·현금흐름에 미치는 시점은 언제인가?",
        ] + questions))
    company_context_assessment = company_specific_assessment(input_issue_codes, company_profile)
    signal_balance = "혼합" if positive and negative else "호재 중심" if positive else "악재 중심" if negative else "확인 필요"
    if context_relevance_gate.get("direction_permission") == "observe_only":
        signal_balance = "확인 필요"
        positive = []
        negative = []
        questions = list(dict.fromkeys(questions + [
            "이 회사가 입력 이슈의 가까운 파급 경로 안에 실제로 포함되는가?",
            "회사 사업보고서나 매출 비중에서 해당 이슈 노출도가 확인되는가?",
            "5차 관찰 영향 이상의 실제 사업 연결고리가 있는가?",
        ]))
    else:
        card_direction_rule = industry_direction(input_issue_codes, company_profile.get("industry", "미분류"))
        if card_direction_rule and card_direction_rule.get("issue_code") not in {"order_contract"}:
            if card_direction_rule["direction"] == "호재 신호":
                signal_balance = "호재 중심"
            elif card_direction_rule["direction"] == "악재 신호":
                signal_balance = "악재 중심"
            elif card_direction_rule["direction"] == "혼합 신호":
                signal_balance = "혼합"
            else:
                signal_balance = "확인 필요"
    price_reference = fetch_daily_prices(ticker, event_date) if event_date else {"status": "skipped", "reason": "기준일이 없어 가격 참고값을 계산하지 않았습니다."}
    rss_news = fetch_google_news_rss(company, sentence, event_date, before_days=rss_before, after_days=rss_after) if include_rss else {"status": "skipped", "reason": "--rss 옵션이 꺼져 있습니다."}
    rss_news = enrich_rss_news(rss_news, company, sentence, company_profile)
    selected_llm_model = llm_model or os.environ.get("OPENAI_MODEL") or "gpt-5-mini"
    if use_llm:
        rss_news = attach_llm_assessment(rss_news, company, sentence, company_profile, selected_llm_model)
    else:
        rss_news["llm_assessment"] = {"status": "skipped", "reason": "--llm 옵션이 꺼져 있습니다."}

    raw_origins = list(dict.fromkeys(origins))
    canonical_origin_value = canonical_origin(
        raw_origins,
        input_issue_codes,
        dart_event.get("origin") if dart_event.get("status") == "official_match" else None,
    )

    card = {
        "company": company,
        "ticker": ticker,
        "input": sentence,
        "company_profile": company_profile,
        "input_issue_codes": input_issue_codes,
        "dart_event": dart_event,
        "official_origin": dart_event.get("origin") if dart_event.get("status") == "official_match" else None,
        "official_confirmation": dart_event.get("confirmation") if dart_event.get("status") == "official_match" else None,
        "context_relevance_gate": context_relevance_gate,
        "company_context_assessment": company_context_assessment,
        "raw_origins": raw_origins,
        "origins": [canonical_origin_value],
        "canonical_origin": canonical_origin_value,
        "issue_types": list(dict.fromkeys(issue_types)),
        "signal_balance": signal_balance,
        "positive_signals": [asdict(s) for s in positive],
        "negative_signals": [asdict(s) for s in negative],
        "impact_paths": paths,
        "questions_to_check": list(dict.fromkeys(questions)),
        "price_reference": price_reference,
        "rss_news": rss_news,
        "pre_event_reflection": assess_pre_event_reflection(price_reference, rss_news),
        "llm_model": selected_llm_model if use_llm else None,
        "analysis_frame": "market_contradiction_explainer_v1",
        "interpretation_guardrail": "이 결과는 호재/악재 결론이나 주가 원인 단정이 아니라, 뉴스·공시·가격·수급이 어긋날 때 가능한 설명 후보를 정리한 것입니다.",
    }
    card["market_contradiction"] = explain_market_contradiction(card)
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
                print(f"  - 관련성: {signal.get('relevance')} ({signal.get('relevance_reason')})")
                print(f"  - 감정/채널: {emotions} / {channels}")
                if signal.get("industry_direction_rule"):
                    print(f"  - 산업별 방향 룰: {signal['industry_direction_rule']['reason']}")
                if signal.get("company_specific_assessment"):
                    assessment = signal["company_specific_assessment"]
                    print(f"  - 기업별 2차 판단: 민감도 {assessment['sensitivity_label']} / {assessment['reason']}")
                if item.get("llm_signal"):
                    llm = item["llm_signal"]
                    emotions_llm = ", ".join(llm.get("emotion_tags", [])) or "없음"
                    issue_types_llm = ", ".join(llm.get("issue_types", [])) or "없음"
                    print(f"  - LLM 보조판단: {llm.get('direction')} / 관련성 {llm.get('relevance')} / {llm.get('effect_level')}차 / 민감도 {llm.get('company_sensitivity')} / 확신도 {llm.get('confidence')}")
                    print(f"    - 이슈/감정: {issue_types_llm} / {emotions_llm}")
                    print(f"    - 근거: {llm.get('reason')}")
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
        print("## 선행 가격 움직임 관찰")
        print()
        print(f"- 관찰 강도: {reflection.get('observation_label', reflection.get('label'))} (점수 {reflection.get('score')})")
        for check in reflection.get("price_checks", []):
            print(f"- {check['window']} 가격 변화: {check['change']:,.0f} / {check['change_pct']:.2f}% ({check['start_date']} → {check['end_date']})")
        print(f"- 기준일 전 RSS 후보: {reflection.get('pre_news_count', 0)}건")
        print(f"- 기준일 전 감정 뉴스: {reflection.get('pre_emotional_news_count', 0)}건")
        for reason in reflection.get("reasons", []):
            print(f"- {reason}")
        print(f"- 주의: {reflection.get('caution')}")
        print()

    contradiction = card.get("market_contradiction", {})
    if contradiction:
        print("## 뉴스-가격 불일치 설명 후보")
        print()
        if contradiction.get("status") == "ok":
            post = contradiction.get("post_event_price_move", {})
            pre = contradiction.get("pre_event_price_move", {})
            print(f"- 뉴스/이슈 방향: {contradiction.get('news_direction')}")
            print(f"- 정렬 상태: {contradiction.get('alignment')}")
            print(f"- 기준일 이후 가격: {post.get('window')} / {post.get('change_pct', 0):.2f}%")
            if pre.get("status") == "ok":
                print(f"- 기준일 이전 가격: {pre.get('window')} / {pre.get('change_pct', 0):.2f}%")
            print("- 설명 후보:")
            for candidate in contradiction.get("candidates", []):
                print(f"  - {candidate.get('label')} ({candidate.get('confidence')})")
                print(f"    - 근거: {candidate.get('evidence')}")
                print(f"    - 주의: {candidate.get('guardrail')}")
            print(f"- 가드레일: {contradiction.get('guardrail')}")
        else:
            print(f"- 상태: 건너뜀")
            print(f"- 설명: {contradiction.get('reason')}")
            print(f"- 가드레일: {contradiction.get('guardrail')}")
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
    profile = card.get("company_profile", {})
    if profile:
        print(f"- 산업/노출도: {profile.get('industry', '미분류')} / {', '.join(profile.get('exposures', [])) or '노출도 미정'}")
        segments = profile.get("business_segments", {})
        if segments:
            segment_text = ", ".join(f"{name}:{SENSITIVITY_LABELS.get(weight, weight)}" for name, weight in segments.items())
            print(f"- 세부 사업 노출도: {segment_text}")
    context_assessment = card.get("company_context_assessment")
    if context_assessment:
        print(f"- 기업별 2차 판단: {context_assessment['lead_issue_code']} 민감도 {context_assessment['sensitivity_label']} / {context_assessment['reason']}")
    print(f"- 입력 문장: {card['input']}")
    print(f"- 출발점: {', '.join(card['origins'])}")
    print(f"- 이슈 유형: {', '.join(card['issue_types'])}")
    print(f"- 신호 균형: {card['signal_balance']}")
    print()

    dart_event = card.get("dart_event", {})
    if dart_event:
        print("## DART 공식 확인")
        print()
        status = dart_event.get("status")
        if status == "official_match":
            lead = dart_event.get("lead_disclosure", {})
            print(f"- 상태: 공식 공시 매칭")
            print(f"- 공식 이벤트: {dart_event.get('official_event_type')}")
            print(f"- 접수일: {lead.get('rcept_dt')}")
            print(f"- 보고서명: {lead.get('report_nm')}")
            print(f"- DART 링크: {lead.get('dart_url')}")
        elif status == "not_found":
            print(f"- 상태: 공식 공시 미발견")
            print(f"- 설명: {dart_event.get('reason')}")
            print(f"- 후보 이벤트: {', '.join(dart_event.get('candidate_event_types', [])) or '없음'}")
        elif status == "error":
            print(f"- 상태: DART 확인 실패")
            print(f"- 설명: {dart_event.get('reason')}")
        else:
            print(f"- 상태: 건너뜀")
            print(f"- 설명: {dart_event.get('reason')}")
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
        llm_assessment = rss.get("llm_assessment", {})
        if llm_assessment:
            print("## LLM 보조판단")
            print()
            if llm_assessment.get("status") == "ok":
                print(f"- 모델: {llm_assessment.get('model')}")
                print(f"- 요약: {llm_assessment.get('summary')}")
                cautions = llm_assessment.get("cautions", [])
                if cautions:
                    print("- 주의:")
                    for caution in cautions:
                        print(f"  - {caution}")
            else:
                print(f"- {llm_assessment.get('status')}: {llm_assessment.get('reason')}")
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
    parser.add_argument("--llm", action="store_true", help="OpenAI API로 RSS 뉴스 보조판단을 붙입니다. OPENAI_API_KEY가 필요합니다.")
    parser.add_argument("--llm-model", default=None, help="LLM 보조판단에 사용할 모델입니다. 기본값은 OPENAI_MODEL 또는 gpt-5-mini입니다.")
    parser.add_argument("--dart", action="store_true", help="OpenDART로 기업 직접 이벤트 공시를 공식 확인합니다. OPENDART_API_KEY가 필요합니다.")
    parser.add_argument("--dart-before", type=int, default=30, help="DART 검색 시작 범위: 기준일 전 N일")
    parser.add_argument("--dart-after", type=int, default=10, help="DART 검색 종료 범위: 기준일 후 N일")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력합니다.")
    args = parser.parse_args()

    card = build_card(
        args.company,
        args.ticker,
        args.sentence,
        args.date,
        args.rss,
        args.rss_before,
        args.rss_after,
        args.llm,
        args.llm_model,
        args.dart,
        args.dart_before,
        args.dart_after,
    )
    if args.json:
        print(json.dumps(card, ensure_ascii=False, indent=2))
    else:
        print_markdown(card)


if __name__ == "__main__":
    main()
