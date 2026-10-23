"""LLM access for AI warm-up scripts (BYOK, OpenAI-compatible).

The user brings their own endpoint: base_url + model are plain settings,
the API key is stored Fernet-encrypted through :mod:`secrets_crypto` and
is never returned by any read path or written to logs. Generation happens
only when the user clicks "generate" — never inside the scheduler — and a
failed generation stores nothing.

The model only ever returns *intents* (see :mod:`warmup_script`); this
module's job is transport, prompting and response extraction.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import httpx

from . import warmup, warmup_script
from .secrets_crypto import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

SETTING_BASE_URL = "llm_base_url"
SETTING_MODEL = "llm_model"
SETTING_API_KEY = "llm_api_key"
SETTING_EXECUTOR_MODEL = "llm_executor_model"
SETTING_EXECUTOR_EFFORT = "llm_executor_effort"

BATCH_SIZE = 5
_MAX_ATTEMPTS = 2

GetSetting = Callable[[str], "str | None"]
SetSetting = Callable[[str, str], None]


class LlmError(Exception):
    """Base class for LLM configuration/generation failures."""


class LlmNotConfiguredError(LlmError):
    """No usable LLM configuration (missing base_url/model/key)."""


class LlmGenerationError(LlmError):
    """The endpoint failed or returned nothing usable after retries."""


# ── Configuration ───────────────────────────────────────────────────────────


def read_config(get_setting: GetSetting) -> dict[str, str] | None:
    """Full config including the decrypted key, or None when incomplete.

    Internal use only — never serialize the result towards the API layer.
    """
    base_url = (get_setting(SETTING_BASE_URL) or "").strip().rstrip("/")
    model = (get_setting(SETTING_MODEL) or "").strip()
    api_key = decrypt_value(get_setting(SETTING_API_KEY))
    if not base_url or not model or not api_key:
        return None
    return {"base_url": base_url, "model": model, "api_key": api_key}


def read_executor_config(get_setting: GetSetting) -> dict[str, str] | None:
    """The AI driver's executor model choice, or None when not chosen yet.

    Shares the connection above (base_url + key); only the model differs —
    the driver wants a cheap, fast model (e.g. claude-haiku-5-5), while
    script generation can use a stronger one. ``effort`` may be empty
    (provider default).
    """
    model = (get_setting(SETTING_EXECUTOR_MODEL) or "").strip()
    if not model:
        return None
    return {
        "model": model,
        "effort": (get_setting(SETTING_EXECUTOR_EFFORT) or "").strip(),
    }


def config_status(get_setting: GetSetting) -> dict[str, Any]:
    """What the settings UI may see: where/what, never the key itself."""
    return {
        "configured": read_config(get_setting) is not None,
        "base_url": (get_setting(SETTING_BASE_URL) or "").strip().rstrip("/") or None,
        "model": (get_setting(SETTING_MODEL) or "").strip() or None,
        "has_api_key": bool(decrypt_value(get_setting(SETTING_API_KEY))),
        "executor_model": (get_setting(SETTING_EXECUTOR_MODEL) or "").strip() or None,
        "executor_effort": (get_setting(SETTING_EXECUTOR_EFFORT) or "").strip() or None,
    }


def save_config(
    set_setting: SetSetting,
    *,
    base_url: str,
    model: str,
    api_key: str | None = None,
    executor_model: str = "",
    executor_effort: str = "",
) -> None:
    """Persist base_url/model; the key is write-only (set when provided)."""
    set_setting(SETTING_BASE_URL, base_url.strip())
    set_setting(SETTING_MODEL, model.strip())
    set_setting(SETTING_EXECUTOR_MODEL, executor_model.strip())
    set_setting(SETTING_EXECUTOR_EFFORT, executor_effort.strip())
    if api_key:
        set_setting(SETTING_API_KEY, encrypt_value(api_key) or "")


# ── Prompting ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "你是一个浏览行程编剧，为一个浏览器画像编排日常的公开网页浏览剧本，"
    "像真人一样打开网站、搜索感兴趣的东西、停留阅读。"
    "你只能输出 JSON，不要输出任何解释文字、不要输出 Markdown 代码围栏。"
    "剧本里不允许出现 URL、账号、密码，也不允许登录、下单、发帖、点赞、关注等动作——"
    "只有访问主页、搜索、停留阅读这三类意图。"
)


def build_messages(profile: dict[str, Any], persona: str | None) -> list[dict[str, str]]:
    """Assemble the generation prompt from profile data.

    The persona is user free text: it is passed strictly as data inside a
    delimited block, and the compiler downstream whitelists everything the
    model returns, so persona text can steer themes but never actions.
    """
    locale = str(profile.get("locale") or "en-US")
    language = locale.split("-")[0]
    targets = []
    for platform_id in profile.get("warmup_targets") or []:
        entry = warmup.TARGET_CATALOG.get(platform_id)
        if entry:
            targets.append({
                "id": platform_id,
                "name": entry["name"],
                "has_search": bool(entry.get("search")),
            })
    context = {
        "persona": persona or "（未填写人格，按地区与语言编排普通日常浏览）",
        "locale": locale,
        "language": language,
        "targets": targets,
    }
    instructions = (
        f"请生成 {BATCH_SIZE} 个互不相同的剧本，组成一周的浏览安排。\n"
        "画像资料（仅作编排依据，不要复述）：\n"
        f"{json.dumps(context, ensure_ascii=False)}\n\n"
        "输出格式（严格遵守）：\n"
        '{"scripts": [{"theme": "一句话主题", "intents": [意图, ...]}, ...]}\n'
        "每个剧本 4 到 7 个意图。意图只有两种：\n"
        '- {"type": "target", "platform": "<targets 里的 id>", "query": "<搜索词>", '
        '"dwell": "short|medium|long", "follow": true|false}\n'
        '- {"type": "generic", "dwell": "short|medium|long", "follow": true|false}\n'
        "规则：platform 只能用上面 targets 里给出的 id；has_search 为 false 的平台不要给 query；"
        "generic 表示浏览与 locale 相符的新闻/天气/百科类站点，不需要写明网址；"
        "query 用该画像语言书写，2 到 6 个词，贴合人格与主题；"
        "每个剧本至少包含 1 个 target 意图（targets 为空时除外）；主题之间要有明显区别。"
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": instructions},
    ]


# ── Generation ──────────────────────────────────────────────────────────────


def extract_json(text: str) -> Any:
    """Pull the JSON value out of a model reply (fences/prose tolerated).

    Shared with other LLM consumers (e.g. sentence_profile): every caller
    still validates the extracted value against its own white-list schema.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = min(
        (i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0),
        default=-1,
    )
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if start < 0 or end <= start:
        raise LlmGenerationError("LLM 返回内容里没有 JSON")
    try:
        return json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LlmGenerationError(f"LLM 返回的 JSON 无法解析（{exc.msg}）") from exc


def parse_scripts(text: str) -> list[dict[str, Any]]:
    """Response text → normalized ``[{theme, intents}]`` (may be empty)."""
    return warmup_script.validate_scripts_payload(extract_json(text))


async def chat_completion(
    config: dict[str, str],
    messages: list[dict[str, str]],
    *,
    transport: httpx.AsyncBaseTransport | None,
) -> str:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0, connect=10.0),
        transport=transport,
    ) as client:
        resp = await client.post(
            f"{config['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {config['api_key']}"},
            json={
                "model": config["model"],
                "messages": messages,
                "temperature": 0.8,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise LlmGenerationError("LLM 返回了空内容")
    return content


async def generate_batch(
    profile: dict[str, Any],
    *,
    get_setting: GetSetting,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Generate one batch of compiled scripts for a profile.

    Returns ``{"model", "persona", "scripts": [{theme, intents, steps}]}``
    with only the scripts that compiled to a non-empty plan. Raises
    :class:`LlmNotConfiguredError` without any network call when the LLM
    is not configured, and :class:`LlmGenerationError` after one retry —
    in both cases nothing is stored anywhere.
    """
    config = read_config(get_setting)
    if config is None:
        raise LlmNotConfiguredError(
            "尚未配置 LLM：请先在设置里填写接口地址、模型和 API 密钥。"
        )
    persona_raw = profile.get("warmup_persona")
    persona = persona_raw.strip() if isinstance(persona_raw, str) and persona_raw.strip() else None
    messages = build_messages(profile, persona)

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            text = await chat_completion(config, messages, transport=transport)
            compiled: list[dict[str, Any]] = []
            for script in parse_scripts(text):
                steps = warmup_script.compile_intents(profile, script["intents"])
                if steps:
                    compiled.append({
                        "theme": script["theme"],
                        "intents": script["intents"],
                        "steps": steps,
                    })
            if not compiled:
                raise LlmGenerationError("LLM 返回的剧本没有可执行的意图")
            return {"model": config["model"], "persona": persona, "scripts": compiled}
        except (httpx.HTTPError, KeyError, IndexError, TypeError, LlmGenerationError) as exc:
            last_error = exc
            logger.info(
                "LLM script generation attempt %d failed: %s",
                attempt + 1, type(exc).__name__,
            )
    if isinstance(last_error, LlmGenerationError):
        raise last_error
    raise LlmGenerationError(
        f"LLM 生成失败（{type(last_error).__name__ if last_error else '未知错误'}），请稍后重试。"
    )


# Backwards-compatible private names (the helpers above are the public,
# shared API; these aliases keep older imports working).
_extract_json = extract_json
_chat_completion = chat_completion
