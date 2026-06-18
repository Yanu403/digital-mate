"""Input validation and sanitization helpers.

Provides utilities for validating URLs, emails, and cleaning user input.
"""

from __future__ import annotations

import re
import unicodedata


def is_valid_url(text: str) -> bool:
    """Check if a string is a valid URL.

    Args:
        text: String to validate.

    Returns:
        True if the string is a valid URL.
    """
    url_pattern = re.compile(
        r"^https?://"
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"
        r"(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"
        r"localhost|"
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"\[?[A-F0-9]*:[A-F0-9:]+\]?)"
        r"(?::\d+)?"
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )
    return bool(url_pattern.match(text))


def is_valid_email(text: str) -> bool:
    """Check if a string is a valid email address.

    Args:
        text: String to validate.

    Returns:
        True if the string is a valid email address.
    """
    email_pattern = re.compile(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    )
    return bool(email_pattern.match(text))


def sanitize_input(text: str, max_len: int = 5000) -> str:
    """Sanitize user input by removing control characters and truncating.

    Removes Unicode control characters (categories Cc and Cf except
    common whitespace), strips leading/trailing whitespace, and
    truncates to max_len.

    Args:
        text: Raw user input.
        max_len: Maximum allowed length (default 5000).

    Returns:
        Sanitized and truncated string.
    """
    if not text:
        return ""

    # Remove control characters but keep common whitespace
    cleaned_chars: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category in ("Cc", "Cf") and char not in ("\n", "\r", "\t"):
            continue
        cleaned_chars.append(char)

    cleaned = "".join(cleaned_chars)

    # Strip leading/trailing whitespace
    cleaned = cleaned.strip()

    # Truncate to max length
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]

    return cleaned
