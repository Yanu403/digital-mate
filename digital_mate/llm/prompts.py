"""System prompts for the LLM router and each pillar.

Loads prompt templates from digital_mate/prompts/*.md files,
then injects runtime variables ($brand_context, $language_instruction, etc.)
using string.Template (avoids JSON brace conflicts with str.format()).

The .md files are the source of truth for prompt content.
This module handles template rendering and message construction.

Placeholder convention: use $variable_name in .md files (NOT {variable}).
"""

from __future__ import annotations

import logging
from pathlib import Path
from string import Template

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt file loader
# ---------------------------------------------------------------------------

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_AGENT_MD = Path(__file__).parent.parent / "AGENT.md"


def _load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts/ directory.

    Args:
        filename: Name of the .md file (e.g., 'content.md').

    Returns:
        File contents as string.

    Raises:
        FileNotFoundError: If the prompt file doesn't exist.
    """
    path = _PROMPTS_DIR / filename
    if not path.exists():
        logger.error("Prompt file not found: %s", path)
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_agent_definition() -> str:
    """Load the AGENT.md file (bot SOUL/personality).

    Returns:
        AGENT.md contents, or empty string if not found.
    """
    if _AGENT_MD.exists():
        return _AGENT_MD.read_text(encoding="utf-8").strip()
    logger.warning("AGENT.md not found at %s — running without personality context", _AGENT_MD)
    return ""


# ---------------------------------------------------------------------------
# Cached prompt templates (loaded once at import time)
# ---------------------------------------------------------------------------

try:
    ROUTER_SYSTEM_PROMPT: str = _load_prompt("router.md")
    CONTENT_SYSTEM_PROMPT: str = _load_prompt("content.md")
    STRATEGY_SYSTEM_PROMPT: str = _load_prompt("strategy.md")
    RESEARCH_SYSTEM_PROMPT: str = _load_prompt("research.md")
    ANALYTICS_SYSTEM_PROMPT: str = _load_prompt("analytics.md")
    GENERAL_SYSTEM_PROMPT: str = _load_prompt("general.md")
    AGENT_DEFINITION: str = load_agent_definition()
except FileNotFoundError as exc:
    logger.warning("Some prompt files missing (%s) — using fallback prompts", exc)
    # Fallback: minimal prompts so the bot still works
    ROUTER_SYSTEM_PROMPT = "You are an intent classifier. Classify marketing messages into: content, strategy, research, analytics, or general."
    CONTENT_SYSTEM_PROMPT = "You are a content & copywriting specialist."
    STRATEGY_SYSTEM_PROMPT = "You are a marketing strategy specialist."
    RESEARCH_SYSTEM_PROMPT = "You are a market research specialist."
    ANALYTICS_SYSTEM_PROMPT = "You are a marketing analytics specialist."
    GENERAL_SYSTEM_PROMPT = "You are a friendly assistant. Respond briefly and naturally."
    AGENT_DEFINITION = ""

# ---------------------------------------------------------------------------
# Language instructions
# ---------------------------------------------------------------------------

LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "bilingual": (
        "Respond in the same language the user wrote in. "
        "If they write in English, respond in English. "
        "If they write in Indonesian, respond in Indonesian. "
        "If they write in Spanish, respond in Spanish. "
        "If they write in Chinese, respond in Chinese (Simplified). "
        "If they write in Japanese, respond in Japanese. "
        "If they mix languages, respond in the dominant one. "
        "Marketing terms can stay in English even when responding in another language "
        "(e.g., 'conversion rate', 'CTA', 'ROAS')."
    ),
    "en": "Always respond in English. Marketing terms stay in English.",
    "id": (
        "Always respond in Bahasa Indonesia. "
        "Marketing terms can stay in English when the Indonesian equivalent "
        "is awkward or unknown (e.g., 'CTR', 'ROAS', 'funnel')."
    ),
    "es": (
        "Always respond in Spanish. "
        "Marketing terms can stay in English when the Spanish equivalent "
        "is awkward or unknown (e.g., 'CTR', 'ROAS', 'funnel')."
    ),
    "zh": (
        "Always respond in Chinese (Simplified, 简体中文). "
        "Marketing terms can stay in English when the Chinese equivalent "
        "is awkward or unknown (e.g., 'CTR', 'ROAS', 'funnel')."
    ),
    "ja": (
        "Always respond in Japanese (日本語). "
        "Marketing terms can stay in English when the Japanese equivalent "
        "is awkward or unknown (e.g., 'CTR', 'ROAS', 'ファネル')."
    ),
}

# ---------------------------------------------------------------------------
# Brand context template
# ---------------------------------------------------------------------------

BRAND_CONTEXT_TEMPLATE = """## 🏢 Brand Context
- **Brand Name:** $name
- **Industry:** $industry
- **Platforms:** $platform_preference
- **Budget:** $budget_range
- **Stage:** $business_stage
- **Target Audience:** $audience
- **Tone of Voice:** $tone
- **Key Products/Services:** $products
- **Preferred Hashtags:** $hashtags
- **Competitors:** $competitors

Always tailor your response to this brand's context, audience, and tone."""


# ---------------------------------------------------------------------------
# Message builders (used by bot.py and pillars)
# ---------------------------------------------------------------------------

def build_router_messages(
    user_message: str,
    context: list[dict[str, str]],
    language: str = "bilingual",
    bot_name: str = "Digital Mate",
) -> list[dict[str, str]]:
    """Build the message list for the router LLM call.

    Args:
        user_message: The user's current message.
        context: Previous conversation messages.
        language: Language setting.
        bot_name: Bot display name.

    Returns:
        List of message dicts for the LLM.
    """
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["bilingual"])
    system = Template(ROUTER_SYSTEM_PROMPT).safe_substitute(
        bot_name=bot_name,
        language_instruction=lang_instruction,
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    # Include last few context messages for better classification
    for msg in context[-6:]:
        messages.append(msg)

    messages.append({"role": "user", "content": user_message})
    return messages


def build_pillar_messages(
    user_message: str,
    pillar: str,
    context: list[dict[str, str]],
    language: str = "bilingual",
    bot_name: str = "Digital Mate",
    brand_context: str = "",
    search_context: str = "",
    key_facts: str = "",
) -> list[dict[str, str]]:
    """Build the message list for a pillar LLM call.

    Includes AGENT.md personality context + pillar-specific expertise.

    Args:
        user_message: The user's current message.
        pillar: Which pillar prompt to use (content/strategy/research/analytics).
        context: Previous conversation messages.
        language: Language setting.
        bot_name: Bot display name.
        brand_context: Formatted brand profile string.
        search_context: Search results for research pillar.
        key_facts: Formatted key facts string for personalization.

    Returns:
        List of message dicts for the LLM.
    """
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["bilingual"])

    # Build the full brand context (including key facts if provided)
    full_brand_context = build_brand_context_with_facts(brand_context, key_facts)

    prompt_map = {
        "content": CONTENT_SYSTEM_PROMPT,
        "strategy": STRATEGY_SYSTEM_PROMPT,
        "research": RESEARCH_SYSTEM_PROMPT,
        "analytics": ANALYTICS_SYSTEM_PROMPT,
    }

    template = prompt_map.get(pillar, CONTENT_SYSTEM_PROMPT)
    pillar_prompt = Template(template).safe_substitute(
        bot_name=bot_name,
        brand_context=full_brand_context or (
            "## Brand Context\n"
            "No brand profile configured. Respond with best-practice general advice. "
            "Do NOT repeatedly ask the user to set up a brand profile — mention it at most "
            "once per conversation, only if highly relevant. Proceed with the request "
            "using reasonable assumptions."
        ),
        language_instruction=lang_instruction,
        search_context=search_context or "",
    )

    # Combine AGENT personality + pillar expertise into system message
    system_parts: list[str] = []

    if AGENT_DEFINITION:
        system_parts.append(AGENT_DEFINITION)

    system_parts.append(pillar_prompt)
    system = "\n\n---\n\n".join(system_parts)

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    # Include conversation context
    for msg in context[-8:]:
        messages.append(msg)

    messages.append({"role": "user", "content": user_message})
    return messages


def build_general_messages(
    user_message: str,
    context: list[dict[str, str]],
    language: str = "bilingual",
    bot_name: str = "Digital Mate",
    brand_context: str | None = None,
    key_facts: str = "",
) -> list[dict[str, str]]:
    """Build the message list for general (non-pillar) LLM calls.

    Used for chitchat, greetings, and ambiguous messages where a natural
    conversational response is better than a hardcoded one.

    Args:
        user_message: The user's current message.
        context: Previous conversation messages.
        language: Language setting.
        bot_name: Bot display name.
        brand_context: Optional brand context string.
        key_facts: Formatted key facts string for personalization.

    Returns:
        List of message dicts for the LLM.
    """
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["bilingual"])

    # Build the full brand context (including key facts if provided)
    full_brand_context = build_brand_context_with_facts(brand_context or "", key_facts)

    general_prompt = Template(GENERAL_SYSTEM_PROMPT).safe_substitute(
        bot_name=bot_name,
        brand_context=full_brand_context or (
            "## Brand Context\n"
            "No brand profile configured. No need to mention it."
        ),
        language_instruction=lang_instruction,
    )

    system_parts: list[str] = []

    if AGENT_DEFINITION:
        system_parts.append(AGENT_DEFINITION)

    system_parts.append(general_prompt)
    system = "\n\n---\n".join(system_parts)

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]

    for msg in context[-8:]:
        messages.append(msg)

    messages.append({"role": "user", "content": user_message})
    return messages


# ---------------------------------------------------------------------------
# Key facts context
# ---------------------------------------------------------------------------

def build_key_facts_context(facts_text: str) -> str:
    """Wrap key facts text in a formatted section for prompt injection.

    Args:
        facts_text: Pre-formatted facts string (e.g., from KeyFactManager.get_facts_context).

    Returns:
        The facts_text as-is if non-empty, or empty string.
    """
    if not facts_text or not facts_text.strip():
        return ""
    return facts_text


def build_brand_context_with_facts(brand_context: str, key_facts: str) -> str:
    """Combine brand context and key facts into a single context string.

    Args:
        brand_context: Formatted brand profile string (may be empty).
        key_facts: Formatted key facts string (may be empty).

    Returns:
        Combined string with brand context followed by key facts,
        or just whichever section is non-empty.
    """
    parts: list[str] = []
    if brand_context and brand_context.strip():
        parts.append(brand_context.strip())
    facts = build_key_facts_context(key_facts)
    if facts:
        parts.append(facts)
    return "\n\n".join(parts) if parts else ""


def build_brand_context(
    name: str,
    industry: str,
    audience: str,
    tone: str,
    products: str,
    hashtags: str,
    competitors: str = "",
    platform_preference: str = "",
    budget_range: str = "",
    business_stage: str = "",
    key_facts: str = "",
) -> str:
    """Build the brand context string from profile fields.

    Args:
        name: Brand name.
        industry: Industry.
        audience: Target audience.
        tone: Tone of voice.
        products: Key products/services.
        hashtags: Preferred hashtags.
        competitors: Competitor brands.
        platform_preference: Social media platforms used (comma-separated).
        budget_range: Marketing budget tier (micro/small/medium/large/enterprise).
        business_stage: Business journey stage (idea/launch/growth/scale/mature).
        key_facts: Optional key facts string to append after brand info.

    Returns:
        Formatted brand context string, with key facts appended if non-empty.
    """
    base_context = Template(BRAND_CONTEXT_TEMPLATE).safe_substitute(
        name=name,
        industry=industry,
        audience=audience,
        tone=tone,
        products=products,
        hashtags=hashtags,
        competitors=competitors or "Not specified",
        platform_preference=platform_preference or "Not specified",
        budget_range=budget_range or "Not specified",
        business_stage=business_stage or "Not specified",
    )

    # Append key facts section if provided
    facts = build_key_facts_context(key_facts)
    if facts:
        return base_context + "\n\n" + facts
    return base_context
