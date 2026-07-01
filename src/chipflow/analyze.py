"""LLM 分析步驟(provider-agnostic)。

讀 prompts/analyst_handoff.md + handoff.json → 呼叫 LLM → 產出當日研判。
金鑰走環境變數(見 .env.example)。實際 SDK 呼叫以 import 保護,未安裝時給明確錯誤。
"""
from __future__ import annotations

import json
import os


def render_prompt(template: str, handoff: dict) -> str:
    return template.replace("{{HANDOFF_JSON}}",
                            json.dumps(handoff, ensure_ascii=False, indent=2))


def analyze(handoff: dict, prompt_template: str, cfg: dict) -> dict:
    llm = cfg.get("llm", {})
    provider = llm.get("provider", "anthropic")
    model = llm.get("model", "")
    max_tokens = int(llm.get("max_tokens", 4096))
    prompt = render_prompt(prompt_template, handoff)

    if provider == "anthropic":
        text = _anthropic(prompt, model, max_tokens)
    elif provider == "openai":
        text = _openai(prompt, model, max_tokens)
    elif provider == "local":
        text = _local(prompt, model, max_tokens)
    else:
        raise ValueError(f"unknown llm.provider: {provider}")

    return {"provider": provider, "model": model,
            "as_of_date": handoff.get("as_of_date"), "analysis_md": text}


def _anthropic(prompt: str, model: str, max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("pip install anthropic") from e
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY 未設定，請在 .env 或環境變數中設定")
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _openai(prompt: str, model: str, max_tokens: int) -> str:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("pip install openai") from e
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    r = client.chat.completions.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content or ""


def _local(prompt: str, model: str, max_tokens: int) -> str:
    """OpenAI 相容本地端點(vLLM/Ollama 等),base url 走 LOCAL_LLM_BASE_URL。"""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("pip install openai") from e
    client = OpenAI(base_url=os.environ["LOCAL_LLM_BASE_URL"], api_key="local")
    r = client.chat.completions.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}])
    return r.choices[0].message.content or ""
