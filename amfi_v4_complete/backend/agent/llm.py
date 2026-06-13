"""
AMFI v4 — LLM wrapper
Primary: Ollama + Llama 3.1 (local, offline)
Fallback: Claude API (if ANTHROPIC_API_KEY is set)

Used in exactly two places:
  1. Interpreting SSH diagnostic output
  2. Writing L3 escalation briefs
"""
import logging
import httpx
from backend.config import get_settings

logger   = logging.getLogger("amfi.llm")
settings = get_settings()


async def check_ollama() -> dict:
    """Return Ollama health and model availability."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.ollama_url}/api/tags")
        if r.status_code != 200:
            return {"running": False, "model_available": False, "models": []}
        data   = r.json()
        models = [m["name"] for m in data.get("models", [])]
        available = any(
            settings.ollama_model in m or settings.ollama_model.split(":")[0] in m
            for m in models
        )
        return {"running": True, "model_available": available, "models": models}
    except Exception as e:
        logger.debug("Ollama check failed: %s", e)
        return {"running": False, "model_available": False, "models": []}


async def _call_llm(prompt: str, max_tokens: int = 500) -> str:
    """
    Call the LLM and return the text response.
    Tries Ollama first, falls back to Claude API if configured.
    Returns empty string if both fail (agent continues without AI interpretation).
    """
    import asyncio
    # ── Ollama ─────────────────────────────────────────────────────────────────
    try:
        async with asyncio.timeout(settings.ollama_timeout):
            async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
                r = await client.post(
                    f"{settings.ollama_url}/api/generate",
                    json={
                        "model":  settings.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_predict": max_tokens, "temperature": 0.1},
                    },
                )
            if r.status_code == 200:
                response = r.json().get("response", "").strip()
                if response:
                    logger.debug("Ollama responded (%d chars)", len(response))
                    return response
    except Exception as e:
        logger.debug("Ollama unavailable: %s", e)

    # ── Claude API fallback ────────────────────────────────────────────────────
    if settings.anthropic_api_key:
        try:
            import asyncio
            import anthropic
            client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                max_retries=0,  # don't retry — fail fast on credit/auth errors
            )
            async with asyncio.timeout(15):
                msg = await client.messages.create(
                    model      = "claude-haiku-4-5",
                    max_tokens = max_tokens,
                    messages   = [{"role": "user", "content": prompt}],
                )
            text = msg.content[0].text.strip()
            logger.debug("Claude API responded (%d chars)", len(text))
            return text
        except Exception as e:
            logger.error("Claude API failed: %s", e)

    logger.warning("No AI engine available — returning empty interpretation")
    return ""


async def interpret_diagnostics(
    fault_category: str,
    host: str,
    diagnostic_outputs: dict,
) -> str:
    """
    Ask the LLM to interpret SSH diagnostic output and recommend an action.
    diagnostic_outputs: {command_name: output_text}
    """
    findings = "\n".join(
        f"### {cmd}\n```\n{out[:800]}\n```"
        for cmd, out in diagnostic_outputs.items()
        if out
    )

    prompt = f"""NOC engineer. Diagnose this {fault_category} alert on {host}. Be brief.

{findings}

Reply in 2-3 sentences: root cause, severity, first action to take. No headers."""

    return await _call_llm(prompt, max_tokens=80)


async def write_escalation_brief(
    incident_number: str,
    title: str,
    host: str,
    fault_category: str,
    steps_summary: list[dict],
    ai_interpretation: str,
) -> str:
    """Write an L3 escalation brief — clear summary for an engineer to act on."""
    steps_text = "\n".join(
        f"- Step {s.get('sequence', '?')}: {s.get('action', '?')} — "
        f"{'OK' if s.get('success') else 'FAILED'}: {str(s.get('raw_output', ''))[:200]}"
        for s in steps_summary[-10:]  # last 10 steps
    )

    prompt = f"""Write a concise L3 escalation brief for the following NOC incident.

Incident: {incident_number} — {title}
Host: {host}
Fault Category: {fault_category}

Automated steps taken:
{steps_text}

AI interpretation: {ai_interpretation}

Write the brief in this format:
SUMMARY: (1 sentence — what happened)
IMPACT: (who/what is affected)
ACTIONS TAKEN: (bullet list of what was tried)
LIKELY ROOT CAUSE: (your assessment)
RECOMMENDED NEXT STEP: (what L3 engineer should do first)

Keep it under 200 words. Be direct and technical."""

    return await _call_llm(prompt, max_tokens=150)
