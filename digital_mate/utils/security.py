"""Prompt injection and abuse guard for Digital Mate.

Provides input-level and output-level protection against:
- System prompt extraction attempts
- Role confusion / persona hijacking
- Brand context field poisoning
- Harmful content generation via prompt manipulation
- Data exfiltration attempts

Architecture:
    User Input → [input_guard()] → Router/Pillar → LLM → [output_guard()] → User

All guards return (is_safe: bool, sanitized_or_blocked: str).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_INPUT_LENGTH = 4000          # Max chars per user message
MAX_BRAND_FIELD_LENGTH = 500     # Max chars per brand profile field
MAX_CONTEXT_MESSAGES = 20        # Max conversation turns to inspect
SUSPICIOUS_THRESHOLD = 3         # Number of suspicious patterns before block

# ---------------------------------------------------------------------------
# Injection patterns — ordered by severity
# ---------------------------------------------------------------------------

# Direct system prompt extraction attempts
EXTRACTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"show\s+(me\s+)?(your|the)\s+(system\s+)?prompt", re.I),
    re.compile(r"reveal\s+(your|the)\s+(system\s+)?prompt", re.I),
    re.compile(r"print\s+(your|the)\s+(system\s+)?prompt", re.I),
    re.compile(r"what\s+(is|are)\s+your\s+(system\s+)?(prompt|instruction)", re.I),
    re.compile(r"repeat\s+(your|the)\s+(system\s+)?(prompt|instruction)", re.I),
    re.compile(r"output\s+(your|the)\s+(full\s+)?(system\s+)?(prompt|instruction)", re.I),
    re.compile(r"ignore\s+(?:all\s+)?(?:\w+\s+)*(?:prompt|instruction|rule)s?", re.I),
    re.compile(r"disregard\s+(?:all\s+)?(?:\w+\s+)*(?:prompt|instruction|rule)s?", re.I),
    re.compile(r"forget\s+(?:all\s+)?(?:\w+\s+)*(?:prompt|instruction|rule)s?", re.I),
]

# Role/persona hijacking attempts
HIJACK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"from\s+now\s+on\s+you\s+(are|will|shall|must)\s+", re.I),
    re.compile(r"act\s+as\s+(?:if\s+)?(?:you\s+are\s+)?(?:a\s+)?(?!(?:marketing|content|strategy|research|analytics)\b)\w{2,}", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+(?!marketing|a\s+marketing)", re.I),
    re.compile(r"new\s+role\s*:", re.I),
    re.compile(r"(?:enter|activate|enable)\s+(developer|debug|admin|sudo|god|DAN|jailbreak)\s*(?:mode)?", re.I),
    re.compile(r"\bDAN\s+mode\b", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"\bGPT\s*[-_]?\s*4\s*(bypass|override|unlock)", re.I),
]

# Data exfiltration / config leak attempts
EXFIL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(reveal|show|print|output|dump|expose)\s+(me\s+)?(your|the|all)\s+(config\w*|setting\w*|credential\w*|key|token|secret|api.?key|password)", re.I),
    re.compile(r"(reveal|show|print|output|dump)\s+(your|the)\s+(source|code|implementation)", re.I),
    re.compile(r"(reveal|show|print|output)\s+(your|the)\s+(model|provider|api|endpoint|base.?url)", re.I),
    re.compile(r"(reveal|show|print|output)\s+(the|your)\s+contents?\s+of\s+", re.I),
    re.compile(r"(what|which)\s+(model|llm|api|provider)(\s+\w+)?\s+(are\s+you|do\s+you\s+use)", re.I),
    re.compile(r"(reveal|show|print)\s+(all\s+)?(instructions|rules|guidelines)\s+(you|that)\s+(were|have|has)", re.I),
]

# Harmful content generation attempts (beyond normal marketing)
HARMFUL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(write|create|generate)\s+(a\s+)?(phishing|scam|spam|fake)\s+(email|message|campaign|content)", re.I),
    re.compile(r"(write|create|generate)\s+(a\s+)?(misleading|deceptive|fraudulent)\s+(ad|campaign|content|post)", re.I),
    re.compile(r"(how\s+to|help\s+me)\s+(scam|hack|phish|deceive|manipulate)\s+", re.I),
    re.compile(r"(bypass|circumvent|evade)\s+(content\s+)?(moderation|filter|review|policy)", re.I),
]

# Encoded/obfuscated injection attempts
OBFUSCATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(base64|hex|rot13|encode|decode)\s+(your|the)\s+(prompt|instruction)", re.I),
    re.compile(r"(in\s+)?(latin|pig\s+latin|reverse|backwards|mirror)\s*(text|language|mode)?\s*:", re.I),
    re.compile(r"(translate|convert)\s+(your|the)\s+(prompt|instruction)\s+to\s+", re.I),
]

# Combined pattern lists with severity scores
PATTERN_GROUPS: list[tuple[list[re.Pattern[str]], int, str]] = [
    (EXTRACTION_PATTERNS, 3, "system_prompt_extraction"),
    (HIJACK_PATTERNS, 2, "role_hijack"),
    (EXFIL_PATTERNS, 3, "data_exfiltration"),
    (HARMFUL_PATTERNS, 3, "harmful_content"),
    (OBFUSCATION_PATTERNS, 2, "obfuscation_attempt"),
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    """Result from a guard check."""
    is_safe: bool
    content: str              # sanitized input or block message
    threat_type: str | None   # None if safe
    severity: int             # 0 = safe, 1 = warning, 2 = blocked

    @property
    def is_blocked(self) -> bool:
        return self.severity >= 2


# ---------------------------------------------------------------------------
# Input guard
# ---------------------------------------------------------------------------

def input_guard(text: str, field: str = "message") -> GuardResult:
    """Check user input for prompt injection and abuse patterns.

    Args:
        text: Raw user input to check.
        field: Context label ("message", "brand_name", "brand_industry", etc.)

    Returns:
        GuardResult with is_safe, sanitized content, threat info.
    """
    if not text:
        return GuardResult(is_safe=True, content="", threat_type=None, severity=0)

    # Length check
    max_len = MAX_BRAND_FIELD_LENGTH if field.startswith("brand_") else MAX_INPUT_LENGTH
    if len(text) > max_len:
        text = text[:max_len]
        logger.info("Input truncated: field=%s, len=%d", field, len(text))

    # Scan for injection patterns
    detected_threats: list[tuple[str, int]] = []

    for patterns, severity, threat_name in PATTERN_GROUPS:
        for pattern in patterns:
            if pattern.search(text):
                detected_threats.append((threat_name, severity))
                logger.warning(
                    "Injection detected: field=%s, threat=%s, pattern=%s, text=%s",
                    field, threat_name, pattern.pattern, text[:100],
                )
                break  # One match per group is enough

    # Brand fields get extra scrutiny — they're injected into system prompt
    if field.startswith("brand_"):
        injection_indicators = [
            "ignore", "forget", "disregard", "new instruction",
            "system prompt", "you are now", "act as",
            "---", "===", "###", "```",
            "</system>", "<system>", "[system]",
        ]
        text_lower = text.lower()
        for indicator in injection_indicators:
            if indicator in text_lower:
                detected_threats.append(("brand_context_poisoning", 3))
                logger.warning(
                    "Brand field injection detected: field=%s, indicator=%s",
                    field, indicator,
                )
                break

    # Calculate cumulative severity
    if not detected_threats:
        return GuardResult(is_safe=True, content=text, threat_type=None, severity=0)

    max_severity = max(s for _, s in detected_threats)
    threat_names = list(set(t for t, _ in detected_threats))

    if max_severity >= 2:
        return GuardResult(
            is_safe=False,
            content=_block_message(threat_names[0]),
            threat_type=", ".join(threat_names),
            severity=max_severity,
        )

    # Severity 1 = warning (log but allow — could be false positive)
    return GuardResult(
        is_safe=True,
        content=text,
        threat_type=", ".join(threat_names),
        severity=1,
    )


def sanitize_brand_field(text: str, field_name: str) -> str:
    """Sanitize a brand profile field for safe injection into prompts.

    Strips injection markers, collapses whitespace, and wraps in quotes
    to prevent the value from being interpreted as instructions.

    Args:
        text: Raw brand field value.
        field_name: Name of the field (for logging).

    Returns:
        Sanitized string safe for prompt injection.
    """
    if not text:
        return ""

    # Remove common injection markers
    dangerous_patterns = [
        r"```[\s\S]*?```",        # Code blocks
        r"</?(?:system|user|assistant)>",  # XML-style tags
        r"\[INST\]|\[/INST\]",     # Llama-style tags
        r"<\|.*?\|>",              # ChatML-style tags
        r"---+",                   # Markdown separators
        r"===+",                   # Double-line separators
    ]
    cleaned = text
    for pat in dangerous_patterns:
        cleaned = re.sub(pat, "", cleaned)

    # Collapse multiple newlines/spaces
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"  +", " ", cleaned)
    cleaned = cleaned.strip()

    # Truncate
    if len(cleaned) > MAX_BRAND_FIELD_LENGTH:
        cleaned = cleaned[:MAX_BRAND_FIELD_LENGTH]

    return cleaned


# ---------------------------------------------------------------------------
# Output guard
# ---------------------------------------------------------------------------

def output_guard(text: str) -> GuardResult:
    """Check LLM output for system prompt leaks or harmful content.

    Args:
        text: LLM-generated response to check.

    Returns:
        GuardResult with is_safe and content.
    """
    if not text:
        return GuardResult(is_safe=True, content="", threat_type=None, severity=0)

    # Check for leaked system prompt content
    leak_indicators = [
        "You are the intent classifier for",
        "## Your Expertise\n- Writing engaging social media",
        "## Guidelines\n- Always include relevant hashtags",
        "## Brand Context\n- Brand Name:",
        "You are a senior content strategist",
        "You are a senior marketing strategist",
        "You are a market research analyst",
        "You are a marketing analytics lead",
        "You are Digital Mate — a senior digital marketing specialist",
        "# Who You Are",
        "PILLAR_NAME",
        "build_pillar_messages",
        "ROUTER_SYSTEM_PROMPT",
    ]

    leaked_sections = []
    for indicator in leak_indicators:
        if indicator in text:
            leaked_sections.append(indicator[:50])

    if leaked_sections:
        logger.warning("Output guard: system prompt leak detected — %s", leaked_sections)
        return GuardResult(
            is_safe=False,
            content="I'm not able to share that information. Let me help you with your marketing needs instead! What would you like to work on?",
            threat_type="system_prompt_leak",
            severity=2,
        )

    return GuardResult(is_safe=True, content=text, threat_type=None, severity=0)


# ---------------------------------------------------------------------------
# Rate limiting helpers
# ---------------------------------------------------------------------------

@dataclass
class RateLimitState:
    """Per-chat rate limit tracking."""
    message_count: int = 0
    injection_count: int = 0

    def record_injection(self) -> bool:
        """Record an injection attempt. Returns True if user should be blocked."""
        self.injection_count += 1
        return self.injection_count >= 3

    def reset(self) -> None:
        """Reset counters (call hourly)."""
        self.message_count = 0
        self.injection_count = 0


# ---------------------------------------------------------------------------
# Helper: block messages
# ---------------------------------------------------------------------------

def _block_message(threat_type: str) -> str:
    """Generate user-friendly block message based on threat type."""
    messages = {
        "system_prompt_extraction": (
            "🚫 I can't share my internal instructions. "
            "I'm here to help with your marketing needs — "
            "what would you like to work on?"
        ),
        "role_hijack": (
            "🚫 I'm Digital Mate, your marketing assistant. "
            "I'll stay focused on helping with your marketing! "
            "What do you need?"
        ),
        "data_exfiltration": (
            "🚫 I can't share configuration details. "
            "Let's focus on your marketing strategy — "
            "how can I help?"
        ),
        "harmful_content": (
            "🚫 I can't help with that request. "
            "I'm designed to assist with legitimate marketing activities. "
            "What else can I help you with?"
        ),
        "obfuscation_attempt": (
            "🚫 I noticed something unusual in your message. "
            "Let's keep things straightforward — "
            "what marketing task can I help with?"
        ),
        "brand_context_poisoning": (
            "🚫 Some of the brand profile content couldn't be processed. "
            "Please keep brand details clean and straightforward."
        ),
    }
    return messages.get(threat_type, messages["role_hijack"])
