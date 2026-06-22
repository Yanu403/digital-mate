"""Inline keyboard builders for Telegram bot interactions.

Currently provides feedback keyboards (👍/👎/🔄) attached to pillar responses
so users can rate or regenerate a response via inline button callbacks.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def feedback_keyboard(log_id: int) -> InlineKeyboardMarkup:
    """Build an inline feedback keyboard for a given feedback log entry.

    The keyboard contains three buttons whose callback_data encodes the
    feedback action and the log_id so the callback handler can look up the
    original response:

        👍  →  fb:up:{log_id}
        👎  →  fb:down:{log_id}
        🔄  →  fb:regen:{log_id}

    Args:
        log_id: The feedback_log row ID this keyboard refers to.

    Returns:
        An InlineKeyboardMarkup with a single row of three buttons.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👍", callback_data=f"fb:up:{log_id}"),
                InlineKeyboardButton("👎", callback_data=f"fb:down:{log_id}"),
                InlineKeyboardButton("🔄", callback_data=f"fb:regen:{log_id}"),
            ]
        ]
    )
