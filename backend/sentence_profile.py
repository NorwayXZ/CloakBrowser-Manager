"""One-sentence profile creation （一句话建号）: sentence → spec → profile.

The user types one sentence ("建个美国号，西雅图，平时喜欢露营和摄影").
An LLM — or, with no key configured, a keyword rule parser — only ever
produces a strict JSON *spec*: country, city, interests, persona notes,
purpose. This module validates that spec against static white-list
tables and assembles it deterministically into profile fields using the
same trusted machinery as disposable identities (device template library,
region timezone/locale defaults, the recommended new-profile preset, the
warm-up target catalog).

The model never writes profile fields: anything it invents outside the
tables is dropped or rejected here, and assembly is a pure function, so
the draft preview and the confirm-time re-validation share one code path.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime
from typing import Any

from . import device_templates, llm_client, warmup
from .fingerprint_options import RECOMMENDED_NEW_PROFILE_OPTIONS
from .proxy_geo import COUNTRY_LOCALE_DEFAULTS, suggested_locale, suggested_timezone

logger = logging.getLogger(__name__)

MAX_SENTENCE_LEN = 500
MAX_INTERESTS = 6
MAX_WARMUP_TARGETS = 4
PERSONA_NOTES_MAX = 80
PURPOSE_MAX = 40


class SentenceParseError(Exception):
    """The sentence could not be turned into a spec (user-facing detail)."""


class SentenceValidationError(Exception):
    """A client-supplied assembled payload failed confirm-time checks."""


# ── Country tables ──────────────────────────────────────────────────────────
# Country set = proxy_geo.COUNTRY_LOCALE_DEFAULTS (26). Chinese names drive
# rule parsing and generated profile names; keywords are literal substrings
# (matched case-insensitively) for the no-LLM fallback parser.

COUNTRY_NAMES_ZH: dict[str, str] = {
    "AR": "阿根廷", "AU": "澳大利亚", "BR": "巴西", "CA": "加拿大",
    "CN": "中国", "DE": "德国", "ES": "西班牙", "FR": "法国",
    "GB": "英国", "HK": "香港", "ID": "印度尼西亚", "IN": "印度",
    "IT": "意大利", "JP": "日本", "KR": "韩国", "MX": "墨西哥",
    "MY": "马来西亚", "NL": "荷兰", "PH": "菲律宾", "RU": "俄罗斯",
    "SG": "新加坡", "TH": "泰国", "TR": "土耳其", "TW": "台湾",
    "US": "美国", "VN": "越南",
}

COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "AR": ["阿根廷", "Argentina"],
    "AU": ["澳大利亚", "澳洲", "Australia"],
    "BR": ["巴西", "Brazil"],
    "CA": ["加拿大", "Canada"],
    "CN": ["中国", "China"],
    "DE": ["德国", "Germany", "Deutschland"],
    "ES": ["西班牙", "Spain"],
    "FR": ["法国", "France"],
    "GB": ["英国", "英格兰", "United Kingdom", "Britain", "UK"],
    "HK": ["香港", "Hong Kong"],
    "ID": ["印度尼西亚", "印尼", "Indonesia"],
    "IN": ["印度", "India"],
    "IT": ["意大利", "Italy"],
    "JP": ["日本", "Japan"],
    "KR": ["韩国", "南韩", "Korea"],
    "MX": ["墨西哥", "Mexico"],
    "MY": ["马来西亚", "大马", "Malaysia"],
    "NL": ["荷兰", "Netherlands", "Holland"],
    "PH": ["菲律宾", "Philippines"],
    "RU": ["俄罗斯", "Russia"],
    "SG": ["新加坡", "Singapore"],
    "TH": ["泰国", "Thailand"],
    "TR": ["土耳其", "Türkiye", "Turkey"],
    "TW": ["台湾", "臺灣", "Taiwan"],
    "US": ["美国", "美帝", "美利坚", "United States", "USA", "America"],
    "VN": ["越南", "Vietnam"],
}


# ── City table ──────────────────────────────────────────────────────────────
# Profiles have no city-level fingerprint field; a city only (a) picks the
# timezone inside multi-timezone countries, (b) flavours the generated
# name/persona, (c) lands in the notes via the original sentence. Cities
# outside this table are dropped with a warning — never invented.
# country → {English canonical name: {"zh": 中文名， "tz": IANA timezone}}

CITY_TABLE: dict[str, dict[str, dict[str, str]]] = {
    "US": {
        "Seattle": {"zh": "西雅图", "tz": "America/Los_Angeles"},
        "Los Angeles": {"zh": "洛杉矶", "tz": "America/Los_Angeles"},
        "San Francisco": {"zh": "旧金山", "tz": "America/Los_Angeles"},
        "San Diego": {"zh": "圣地亚哥", "tz": "America/Los_Angeles"},
        "Portland": {"zh": "波特兰", "tz": "America/Los_Angeles"},
        "Las Vegas": {"zh": "拉斯维加斯", "tz": "America/Los_Angeles"},
        "Phoenix": {"zh": "凤凰城", "tz": "America/Phoenix"},
        "Denver": {"zh": "丹佛", "tz": "America/Denver"},
        "Chicago": {"zh": "芝加哥", "tz": "America/Chicago"},
        "Houston": {"zh": "休斯顿", "tz": "America/Chicago"},
        "Dallas": {"zh": "达拉斯", "tz": "America/Chicago"},
        "Austin": {"zh": "奥斯汀", "tz": "America/Chicago"},
        "New York": {"zh": "纽约", "tz": "America/New_York"},
        "Boston": {"zh": "波士顿", "tz": "America/New_York"},
        "Miami": {"zh": "迈阿密", "tz": "America/New_York"},
        "Atlanta": {"zh": "亚特兰大", "tz": "America/New_York"},
        "Washington": {"zh": "华盛顿", "tz": "America/New_York"},
        "Honolulu": {"zh": "檀香山", "tz": "Pacific/Honolulu"},
        "Anchorage": {"zh": "安克雷奇", "tz": "America/Anchorage"},
    },
    "CA": {
        "Vancouver": {"zh": "温哥华", "tz": "America/Vancouver"},
        "Toronto": {"zh": "多伦多", "tz": "America/Toronto"},
        "Montreal": {"zh": "蒙特利尔", "tz": "America/Toronto"},
        "Calgary": {"zh": "卡尔加里", "tz": "America/Edmonton"},
        "Winnipeg": {"zh": "温尼伯", "tz": "America/Winnipeg"},
    },
    "AU": {
        "Sydney": {"zh": "悉尼", "tz": "Australia/Sydney"},
        "Melbourne": {"zh": "墨尔本", "tz": "Australia/Melbourne"},
        "Brisbane": {"zh": "布里斯班", "tz": "Australia/Brisbane"},
        "Perth": {"zh": "珀斯", "tz": "Australia/Perth"},
        "Adelaide": {"zh": "阿德莱德", "tz": "Australia/Adelaide"},
    },
    "BR": {
        "São Paulo": {"zh": "圣保罗", "tz": "America/Sao_Paulo"},
        "Rio de Janeiro": {"zh": "里约热内卢", "tz": "America/Sao_Paulo"},
        "Manaus": {"zh": "马瑙斯", "tz": "America/Manaus"},
        "Recife": {"zh": "累西腓", "tz": "America/Recife"},
    },
    "MX": {
        "Mexico City": {"zh": "墨西哥城", "tz": "America/Mexico_City"},
        "Cancún": {"zh": "坎昆", "tz": "America/Cancun"},
        "Tijuana": {"zh": "蒂华纳", "tz": "America/Tijuana"},
        "Monterrey": {"zh": "蒙特雷", "tz": "America/Monterrey"},
    },
    "RU": {
        "Moscow": {"zh": "莫斯科", "tz": "Europe/Moscow"},
        "Saint Petersburg": {"zh": "圣彼得堡", "tz": "Europe/Moscow"},
        "Novosibirsk": {"zh": "新西伯利亚", "tz": "Asia/Novosibirsk"},
        "Yekaterinburg": {"zh": "叶卡捷琳堡", "tz": "Asia/Yekaterinburg"},
        "Vladivostok": {"zh": "海参崴", "tz": "Asia/Vladivostok"},
    },
    "ID": {
        "Jakarta": {"zh": "雅加达", "tz": "Asia/Jakarta"},
        "Denpasar": {"zh": "登巴萨", "tz": "Asia/Makassar"},
        "Jayapura": {"zh": "查亚普拉", "tz": "Asia/Jayapura"},
    },
    "ES": {
        "Madrid": {"zh": "马德里", "tz": "Europe/Madrid"},
        "Barcelona": {"zh": "巴塞罗那", "tz": "Europe/Madrid"},
        "Tenerife": {"zh": "特内里费", "tz": "Atlantic/Canary"},
    },
    "JP": {
        "Tokyo": {"zh": "东京", "tz": "Asia/Tokyo"},
        "Osaka": {"zh": "大阪", "tz": "Asia/Tokyo"},
    },
    "GB": {"London": {"zh": "伦敦", "tz": "Europe/London"}},
    "FR": {"Paris": {"zh": "巴黎", "tz": "Europe/Paris"}},
    "DE": {
        "Berlin": {"zh": "柏林", "tz": "Europe/Berlin"},
        "Munich": {"zh": "慕尼黑", "tz": "Europe/Berlin"},
    },
    "KR": {"Seoul": {"zh": "首尔", "tz": "Asia/Seoul"}},
    "TW": {
        "Taipei": {"zh": "台北", "tz": "Asia/Taipei"},
        "Kaohsiung": {"zh": "高雄", "tz": "Asia/Taipei"},
    },
    "HK": {"Hong Kong": {"zh": "香港", "tz": "Asia/Hong_Kong"}},
    "SG": {"Singapore": {"zh": "新加坡", "tz": "Asia/Singapore"}},
    "CN": {
        "Beijing": {"zh": "北京", "tz": "Asia/Shanghai"},
        "Shanghai": {"zh": "上海", "tz": "Asia/Shanghai"},
        "Shenzhen": {"zh": "深圳", "tz": "Asia/Shanghai"},
        "Guangzhou": {"zh": "广州", "tz": "Asia/Shanghai"},
    },
    "TH": {"Bangkok": {"zh": "曼谷", "tz": "Asia/Bangkok"}},
    "VN": {
        "Hanoi": {"zh": "河内", "tz": "Asia/Ho_Chi_Minh"},
        "Ho Chi Minh City": {"zh": "胡志明市", "tz": "Asia/Ho_Chi_Minh"},
    },
    "IN": {
        "Mumbai": {"zh": "孟买", "tz": "Asia/Kolkata"},
        "Delhi": {"zh": "德里", "tz": "Asia/Kolkata"},
    },
    "IT": {"Rome": {"zh": "罗马", "tz": "Europe/Rome"}},
    "NL": {"Amsterdam": {"zh": "阿姆斯特丹", "tz": "Europe/Amsterdam"}},
    "PH": {"Manila": {"zh": "马尼拉", "tz": "Asia/Manila"}},
    "MY": {"Kuala Lumpur": {"zh": "吉隆坡", "tz": "Asia/Kuala_Lumpur"}},
    "TR": {"Istanbul": {"zh": "伊斯坦布尔", "tz": "Europe/Istanbul"}},
    "AR": {"Buenos Aires": {"zh": "布宜诺斯艾利斯", "tz": "America/Argentina/Buenos_Aires"}},
}


def _build_city_lookup() -> dict[str, tuple[str, str]]:
    """Any city name (English canonical or Chinese) → (country, canonical)."""
    lookup: dict[str, tuple[str, str]] = {}
    for country, cities in CITY_TABLE.items():
        for canonical, info in cities.items():
            lookup[canonical.lower()] = (country, canonical)
            lookup[info["zh"]] = (country, canonical)
    return lookup


_CITY_LOOKUP = _build_city_lookup()


def city_timezone(country: str, city: str | None) -> str | None:
    if not city:
        return None
    info = CITY_TABLE.get(country, {}).get(city)
    return info["tz"] if info else None


def city_name_zh(country: str, city: str | None) -> str | None:
    if not city:
        return None
    info = CITY_TABLE.get(country, {}).get(city)
    return info["zh"] if info else None


# ── Interest vocabulary ─────────────────────────────────────────────────────
# Closed set of neutral interest tags. An interest only (a) chooses which
# catalog platforms warm-up visits more and (b) flavours persona/name text.
# It never produces a URL and never touches fingerprint fields. Table-external
# words may live on in persona_notes as plain text, nothing more.

INTERESTS: dict[str, dict[str, Any]] = {
    "camping": {
        "zh": "露营", "label": "露营户外", "targets": ["youtube", "google"],
        "keywords": ["露营", "户外", "徒步", "野营", "帐篷", "登山", "camping", "hiking"],
    },
    "photography": {
        "zh": "摄影", "label": "摄影", "targets": ["youtube", "google"],
        "keywords": ["摄影", "拍照", "相机", "拍摄", "单反", "微单", "photography"],
    },
    "gaming": {
        "zh": "游戏", "label": "游戏电竞", "targets": ["youtube", "x"],
        "keywords": ["游戏", "电竞", "打游戏", "主机游戏", "gaming", "esports"],
    },
    "shopping": {
        "zh": "购物", "label": "购物", "targets": ["amazon", "ebay"],
        "keywords": ["购物", "海淘", "买东西", "shopping"],
    },
    "cooking": {
        "zh": "美食", "label": "美食做饭", "targets": ["youtube", "google"],
        "keywords": ["美食", "做饭", "烹饪", "下厨", "烘焙", "菜谱", "cooking"],
    },
    "music": {
        "zh": "音乐", "label": "音乐", "targets": ["youtube"],
        "keywords": ["音乐", "听歌", "乐队", "钢琴", "吉他", "music"],
    },
    "movies": {
        "zh": "影视", "label": "影视", "targets": ["youtube", "x"],
        "keywords": ["电影", "影视", "追剧", "看剧", "美剧", "韩剧", "movies"],
    },
    "reading": {
        "zh": "阅读", "label": "阅读", "targets": ["google"],
        "keywords": ["阅读", "读书", "看书", "小说", "文学", "reading"],
    },
    "fitness": {
        "zh": "健身", "label": "健身运动", "targets": ["youtube"],
        "keywords": ["健身", "跑步", "运动", "瑜伽", "撸铁", "游泳", "fitness"],
    },
    "tech": {
        "zh": "科技", "label": "科技数码", "targets": ["youtube", "google", "x"],
        "keywords": ["科技", "数码", "电脑", "编程", "程序员", "tech"],
    },
    "travel": {
        "zh": "旅行", "label": "旅行", "targets": ["youtube", "google"],
        "keywords": ["旅行", "旅游", "出游", "travel"],
    },
    "social": {
        "zh": "社交", "label": "社交", "targets": ["facebook", "x"],
        "keywords": ["社交", "交友", "social"],
    },
    "pets": {
        "zh": "宠物", "label": "宠物", "targets": ["youtube", "facebook"],
        "keywords": ["宠物", "养猫", "养狗", "猫咪", "狗狗", "铲屎官", "pets"],
    },
    "cars": {
        "zh": "汽车", "label": "汽车", "targets": ["youtube", "ebay"],
        "keywords": ["汽车", "开车", "自驾", "改装车", "cars"],
    },
}

_DISPOSABLE_KEYWORDS = ("一次性", "用完即焚", "阅后即焚", "临时身份", "临时号")
_QUANTITY_RE = re.compile(r"(?:[两三四五六七八九十]|\d+)\s*个号|批量")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def _clean_text(raw: Any, limit: int) -> str | None:
    if not isinstance(raw, str):
        return None
    cleaned = _WHITESPACE.sub(" ", _CONTROL_CHARS.sub(" ", raw)).strip()
    if not cleaned:
        return None
    return cleaned[:limit].strip() or None


# ── Spec validation ─────────────────────────────────────────────────────────


def validate_spec(data: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Normalize a raw spec payload into the strict spec shape.

    Returns ``(spec, warnings)``; ``spec`` is None when the country is
    missing or outside the 26-country table — the country is the
    foundation of assembly, so there is no degraded guess. Unknown keys
    are dropped, wrong-typed values are dropped, free text is truncated.
    Out-of-table interests/cities are dropped with a warning (the words
    may still live in persona_notes as plain text).
    """
    warnings: list[str] = []
    if not isinstance(data, dict):
        return None, warnings
    country_raw = data.get("country")
    country = country_raw.strip().upper() if isinstance(country_raw, str) else ""
    if country not in COUNTRY_LOCALE_DEFAULTS:
        return None, warnings

    city: str | None = None
    city_raw = data.get("city")
    if isinstance(city_raw, str) and city_raw.strip():
        hit = _CITY_LOOKUP.get(city_raw.strip().lower()) or _CITY_LOOKUP.get(city_raw.strip())
        if hit and hit[0] == country:
            city = hit[1]
        else:
            warnings.append(f"城市「{city_raw.strip()}」未收录，已按国家默认时区")

    interests: list[str] = []
    dropped_interests = 0
    raw_interests = data.get("interests")
    if isinstance(raw_interests, list):
        for item in raw_interests:
            if isinstance(item, str) and item in INTERESTS:
                if item not in interests:
                    interests.append(item)
            elif isinstance(item, str) and item.strip():
                dropped_interests += 1
    if dropped_interests:
        warnings.append(f"有 {dropped_interests} 个兴趣不在词表内，已忽略")
    interests = interests[:MAX_INTERESTS]

    disposable_raw = data.get("disposable")
    spec = {
        "country": country,
        "city": city,
        "interests": interests,
        "persona_notes": _clean_text(data.get("persona_notes"), PERSONA_NOTES_MAX),
        "purpose": _clean_text(data.get("purpose"), PURPOSE_MAX),
        "disposable": disposable_raw if isinstance(disposable_raw, bool) else False,
    }
    return spec, warnings


# ── Rule-based fallback parser ──────────────────────────────────────────────


def _keyword_spans(text: str, keywords: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for keyword in keywords:
        needle = keyword.lower()
        if not needle:
            continue
        start = text.find(needle)
        while start >= 0:
            spans.append((start, start + len(needle)))
            start = text.find(needle, start + 1)
    return spans


def _drop_contained(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Drop spans strictly contained in a longer span (印度 inside 印度尼西亚）."""
    kept: list[tuple[int, int, str]] = []
    for span in spans:
        start, end, _ = span
        contained = any(
            other is not span
            and other[0] <= start and end <= other[1]
            and (other[1] - other[0]) > (end - start)
            for other in spans
        )
        if not contained:
            kept.append(span)
    return kept


def parse_sentence_rules(sentence: str) -> tuple[dict[str, Any], list[str]]:
    """Keyword-only parse for when no LLM is available (or it failed).

    Honest by construction: only literal table keywords are recognized.
    Raises :class:`SentenceParseError` with a user-facing Chinese detail
    when no country can be determined or several countries compete —
    it never guesses.
    """
    text = (sentence or "").strip()
    if not text:
        raise SentenceParseError("请先输入一句话，例如「建个美国号，西雅图，平时喜欢露营和摄影」")
    lowered = text.lower()
    warnings: list[str] = []

    country_spans: list[tuple[int, int, str]] = []
    for code, keywords in COUNTRY_KEYWORDS.items():
        for start, end in _keyword_spans(lowered, keywords):
            country_spans.append((start, end, code))
    countries = {code for _, _, code in _drop_contained(country_spans)}

    city_hits: list[tuple[int, str, str]] = []  # (position, country, canonical)
    for name, (city_country, canonical) in _CITY_LOOKUP.items():
        start = lowered.find(name.lower())
        if start >= 0:
            city_hits.append((start, city_country, canonical))
    city_countries = {country for _, country, _ in city_hits}

    if len(countries) > 1:
        names = "、".join(COUNTRY_NAMES_ZH[c] for c in sorted(countries))
        raise SentenceParseError(f"句子里出现了多个国家（{names}），请只保留一个国家再试")
    if countries:
        country = next(iter(countries))
    elif len(city_countries) == 1:
        country = next(iter(city_countries))
    elif len(city_countries) > 1:
        names = "、".join(COUNTRY_NAMES_ZH[c] for c in sorted(city_countries))
        raise SentenceParseError(f"句子里的城市分属多个国家（{names}），请写明国家再试")
    else:
        raise SentenceParseError("没认出国家，请在句子里写明国家，例如「美国」「日本」")

    city: str | None = None
    own_cities = sorted(hit for hit in city_hits if hit[1] == country)
    if own_cities:
        city = own_cities[0][2]
        distinct = {hit[2] for hit in own_cities}
        if len(distinct) > 1:
            warnings.append(f"识别到多个城市，已取「{city_name_zh(country, city)}」")

    interest_hits: list[tuple[int, str]] = []
    for interest_id, info in INTERESTS.items():
        positions = [
            pos for kw in info["keywords"]
            if (pos := lowered.find(kw.lower())) >= 0
        ]
        if positions:
            interest_hits.append((min(positions), interest_id))
    interests = [iid for _, iid in sorted(interest_hits)][:MAX_INTERESTS]

    if _QUANTITY_RE.search(text):
        warnings.append("一次只建一个画像，数量词已忽略")

    spec = {
        "country": country,
        "city": city,
        "interests": interests,
        "persona_notes": None,
        "purpose": None,
        "disposable": any(keyword in text for keyword in _DISPOSABLE_KEYWORDS),
    }
    return spec, warnings


# ── LLM parsing ─────────────────────────────────────────────────────────────

_PARSE_SYSTEM_PROMPT = (
    "你是一个信息抽取器，从用户的一句话里抽取建号规格。"
    "你只能输出 JSON，不要输出任何解释文字、不要输出 Markdown 代码围栏。"
    "所有字段只能从用户消息给出的清单里选，清单之外的值一律不要输出。"
)

_MAX_PARSE_ATTEMPTS = 2


def build_parse_messages(sentence: str) -> list[dict[str, str]]:
    """Assemble the extraction prompt; the allowed lists are data blocks."""
    countries = [
        {"code": code, "name": COUNTRY_NAMES_ZH[code]}
        for code in sorted(COUNTRY_LOCALE_DEFAULTS)
    ]
    cities = {
        code: list(cities) for code, cities in sorted(CITY_TABLE.items())
    }
    interests = [
        {"id": interest_id, "name": info["label"]}
        for interest_id, info in INTERESTS.items()
    ]
    instructions = (
        f"句子：{sentence}\n\n"
        f"可选国家（country 只能填 code）：{json.dumps(countries, ensure_ascii=False)}\n"
        f"可选城市（按国家分组，city 只能填该国分组里的英文名）：{json.dumps(cities, ensure_ascii=False)}\n"
        f"可选兴趣（interests 只能填 id，最多 {MAX_INTERESTS} 个）：{json.dumps(interests, ensure_ascii=False)}\n\n"
        "输出 JSON 格式（严格遵守）：\n"
        '{"country": "US", "city": "Seattle 或 null", "interests": ["camping"], '
        '"persona_notes": "一句话人设补充或 null", "purpose": "用途或 null", "disposable": false}\n'
        "规则：country 必填且只能用清单里的 code；city 只能是该国分组里的城市，"
        "句子没提到城市就给 null；interests 只选句子明确提到的；"
        "persona_notes 提炼句子里的人设描述（不超过 40 字），没有就给 null；"
        "purpose 是这句话说明的用途，没有就给 null；"
        "disposable 仅当句子明说一次性、临时、用完即焚时为 true，否则 false；"
        "句子里没提到的信息不要编造。"
    )
    return [
        {"role": "system", "content": _PARSE_SYSTEM_PROMPT},
        {"role": "user", "content": instructions},
    ]


async def parse_sentence(
    sentence: str,
    *,
    get_setting: llm_client.GetSetting,
    transport: Any = None,
) -> dict[str, Any]:
    """Sentence → ``{"source", "spec", "warnings"}``.

    LLM first when configured (main configured model, never the executor
    model); any LLM failure — transport, garbage, out-of-table country —
    degrades to the keyword parser with the degradation noted in
    ``warnings``. Raises :class:`SentenceParseError` only when even the
    keyword parser cannot determine a country.
    """
    config = llm_client.read_config(get_setting)
    if config is not None:
        messages = build_parse_messages(sentence)
        for attempt in range(_MAX_PARSE_ATTEMPTS):
            try:
                text = await llm_client.chat_completion(config, messages, transport=transport)
                spec, spec_warnings = validate_spec(llm_client.extract_json(text))
                if spec is not None:
                    return {"source": "llm", "spec": spec, "warnings": spec_warnings}
                logger.info("Sentence parse attempt %d: spec failed validation", attempt + 1)
            except Exception as exc:  # transport / extraction — degrade, never surface raw
                logger.info(
                    "Sentence parse attempt %d failed: %s", attempt + 1, type(exc).__name__,
                )
        try:
            spec, rule_warnings = parse_sentence_rules(sentence)
        except SentenceParseError:
            raise SentenceParseError(
                "AI 解析失败，且关键词也没认出国家，请在句子里写明国家，例如「美国」「日本」"
            ) from None
        return {
            "source": "fallback",
            "spec": spec,
            "warnings": ["AI 解析失败，已改用关键词解析（理解有限）", *rule_warnings],
        }

    spec, rule_warnings = parse_sentence_rules(sentence)
    return {
        "source": "fallback",
        "spec": spec,
        "warnings": ["未配置 AI，已用关键词解析（理解有限）", *rule_warnings],
    }


# ── Assembly (spec → profile fields) ────────────────────────────────────────


def _pick_template(used_template_ids: set) -> dict[str, Any]:
    """An unused device template when one remains, else a random one."""
    candidates = [
        tpl for tpl in device_templates.list_templates()
        if tpl["id"] not in used_template_ids
    ]
    return secrets.choice(candidates) if candidates else device_templates.random_template()


def generate_profile_name(spec: dict[str, Any], *, now: datetime | None = None) -> str:
    """「西雅图 · 露营摄影 10-23-a1b2」— place + first interests +防撞后缀.

    The profiles.name column has no unique constraint, so uniqueness comes
    from the timestamp + random suffix, same as disposable identities.
    """
    now = now or datetime.now()
    country = spec["country"]
    place = city_name_zh(country, spec.get("city")) or COUNTRY_NAMES_ZH[country]
    shorts = [INTERESTS[i]["zh"] for i in spec.get("interests") or []][:2]
    suffix = f"{now.strftime('%m-%d')}-{secrets.token_hex(2)}"
    if shorts:
        return f"{place} · {''.join(shorts)} {suffix}"
    return f"{place} {suffix}"


def assemble_spec(
    spec: dict[str, Any],
    *,
    sentence: str,
    used_template_ids: set,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble a validated spec into profile fields (pure, no I/O).

    Every value comes from the trusted tables: template library for
    hardware, region defaults (or the city table) for timezone/locale,
    the recommended preset for fingerprint options, the interest table
    for warm-up targets. The LLM's only influence is which table entries
    were selected.
    """
    country = spec["country"]
    city = spec.get("city")
    timezone = city_timezone(country, city) or suggested_timezone(country) or "America/New_York"
    locale = suggested_locale(country) or "en-US"
    tpl = _pick_template(used_template_ids)

    targets: list[str] = []
    for interest_id in spec.get("interests") or []:
        for target in INTERESTS[interest_id]["targets"]:
            if target in warmup.TARGET_CATALOG and target not in targets:
                targets.append(target)
    targets = targets[:MAX_WARMUP_TARGETS]
    if not targets:
        targets = ["google", "youtube"]

    place_zh = city_name_zh(country, city) or COUNTRY_NAMES_ZH[country]
    shorts = [INTERESTS[i]["zh"] for i in spec.get("interests") or []]
    bits: list[str] = []
    if shorts:
        bits.append("喜欢" + "、".join(shorts[:4]))
    if spec.get("persona_notes"):
        bits.append(spec["persona_notes"])
    persona = f"{place_zh}，{'，'.join(bits)}"[:200] if bits else None

    notes = f"一句话建号：{sentence}"
    if spec.get("purpose"):
        notes += f"（用途：{spec['purpose']}）"

    assembled = {
        "name": generate_profile_name(spec, now=now),
        "platform": "windows",
        "device_profile": tpl["id"],
        "screen_width": tpl["screen_width"],
        "screen_height": tpl["screen_height"],
        "gpu_vendor": tpl["gpu_vendor"],
        "gpu_renderer": tpl["gpu_renderer"],
        "hardware_concurrency": tpl["hardware_concurrency"],
        "device_memory": tpl["device_memory"],
        "timezone": timezone,
        "locale": locale,
        "warmup_targets": targets,
        "warmup_enabled": True,
        "warmup_persona": persona,
        "notes": notes,
        "disposable": bool(spec.get("disposable")),
        "fingerprint_options": dict(RECOMMENDED_NEW_PROFILE_OPTIONS),
    }
    return {"assembled": assembled, "warnings": []}


# ── Confirm-time re-validation ──────────────────────────────────────────────

_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}-[A-Za-z]{2}$")
_IANA_TIMEZONES: frozenset | None = None


def _iana_timezones() -> frozenset:
    global _IANA_TIMEZONES
    if _IANA_TIMEZONES is None:
        from zoneinfo import available_timezones

        _IANA_TIMEZONES = frozenset(available_timezones())
    return _IANA_TIMEZONES


def _regenerate_name(sentence: str, *, now: datetime | None = None) -> str:
    try:
        spec, _ = parse_sentence_rules(sentence)
        return generate_profile_name(spec, now=now)
    except SentenceParseError:
        now = now or datetime.now()
        return f"一句话建号 {now.strftime('%m-%d')}-{secrets.token_hex(2)}"


def validate_assembled(
    payload: Any,
    *,
    sentence: str,
    used_template_ids: set,
    now: datetime | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Re-validate a client-returned assembly before it may create a profile.

    The preview payload is never trusted: hardware fields are rewritten
    from the template library, warm-up targets must be a subset of the
    catalog, fingerprint options are forced to the recommended preset,
    and the timezone must be a real IANA name. A template that got taken
    between draft and confirm is swapped for another unused one (with a
    warning) instead of failing the creation.
    """
    warnings: list[str] = []
    if not isinstance(payload, dict):
        raise SentenceValidationError("组装结果格式不对，请重新生成预览")

    template_id = payload.get("device_profile")
    tpl = device_templates.get_template(template_id) if isinstance(template_id, str) else None
    if tpl is None:
        raise SentenceValidationError("设备模板不存在，请重新生成预览")
    if tpl["id"] in used_template_ids:
        candidates = [
            item for item in device_templates.list_templates()
            if item["id"] not in used_template_ids
        ]
        if candidates:
            tpl = secrets.choice(candidates)
            warnings.append("预览时选中的设备模板已被其他画像占用，已自动换成另一台")
        else:
            tpl = device_templates.random_template()
            warnings.append("设备模板已被占用且暂无空闲模板，已另选一台（可能与现有画像共用模板）")

    timezone = payload.get("timezone")
    if not isinstance(timezone, str) or timezone not in _iana_timezones():
        raise SentenceValidationError("时区不合法，请重新生成预览")
    locale = payload.get("locale")
    if not isinstance(locale, str) or not _LOCALE_RE.fullmatch(locale.strip()):
        raise SentenceValidationError("语言区域不合法，请重新生成预览")
    locale = locale.strip()

    targets: list[str] = []
    raw_targets = payload.get("warmup_targets")
    if isinstance(raw_targets, list):
        for item in raw_targets:
            if isinstance(item, str) and item in warmup.TARGET_CATALOG and item not in targets:
                targets.append(item)
    targets = targets[:MAX_WARMUP_TARGETS]

    name = _clean_text(payload.get("name"), 100)
    if not name:
        name = _regenerate_name(sentence, now=now)

    fields = {
        "name": name,
        "platform": "windows",
        "device_profile": tpl["id"],
        "screen_width": tpl["screen_width"],
        "screen_height": tpl["screen_height"],
        "gpu_vendor": tpl["gpu_vendor"],
        "gpu_renderer": tpl["gpu_renderer"],
        "hardware_concurrency": tpl["hardware_concurrency"],
        "device_memory": tpl["device_memory"],
        "timezone": timezone,
        "locale": locale,
        "fingerprint_options": dict(RECOMMENDED_NEW_PROFILE_OPTIONS),
        "disposable": 1 if payload.get("disposable") is True else 0,
        "warmup_enabled": bool(payload.get("warmup_enabled")) and bool(targets),
        "warmup_targets": targets,
        "warmup_persona": _clean_text(payload.get("warmup_persona"), 200),
        "notes": _clean_text(payload.get("notes"), 2000),
    }
    return fields, warnings


# ── Choice lists for the preview dialog ─────────────────────────────────────


def options_payload() -> dict[str, Any]:
    """Static choice lists the preview dialog edits against."""
    return {
        "countries": [
            {
                "code": code,
                "name": COUNTRY_NAMES_ZH[code],
                "locale": suggested_locale(code),
                "timezone": suggested_timezone(code),
            }
            for code in sorted(COUNTRY_LOCALE_DEFAULTS)
        ],
        "cities": {
            code: [
                {"name": name, "name_zh": info["zh"], "timezone": info["tz"]}
                for name, info in cities.items()
            ]
            for code, cities in sorted(CITY_TABLE.items())
        },
        "interests": [
            {"id": interest_id, "name": info["label"], "targets": list(info["targets"])}
            for interest_id, info in INTERESTS.items()
        ],
        "targets": [
            {"id": platform_id, "name": entry["name"]}
            for platform_id, entry in warmup.TARGET_CATALOG.items()
        ],
    }
