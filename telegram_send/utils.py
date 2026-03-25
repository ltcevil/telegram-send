import html
import re
from typing import List

from appdirs import AppDirs


def markup(text: str, style: str) -> str:
    ansi_codes = {"bold": "\033[1m", "red": "\033[31m", "green": "\033[32m",
                  "cyan": "\033[36m", "magenta": "\033[35m"}
    return ansi_codes[style] + text + "\033[0m"


def pre_format(text: str) -> str:
    escaped_text = html.escape(text)
    return f"<pre>{escaped_text}</pre>"


def _find_chunk_boundary(text: str, min_length: int, max_length: int) -> int:
    if len(text) <= max_length:
        return len(text)

    window = text[:max_length]
    search_start = min(min_length, len(window))

    for separator in ("\n\n", "\n"):
        split_at = window.rfind(separator, search_start)
        if split_at != -1:
            return split_at + len(separator)

    sentence_boundary = None
    for match in re.finditer(r'[.!?…](?:["”’)\]]+)?(?:\s+|$)', window):
        if match.end() >= search_start:
            sentence_boundary = match.end()
    if sentence_boundary is not None:
        return sentence_boundary

    split_at = window.rfind(" ", search_start)
    if split_at != -1:
        return split_at + 1

    return max_length


def split_message(message: str, max_length: int) -> List[str]:
    """Split large messages on paragraph, sentence, or word boundaries when possible."""
    cleaned = message.strip()
    if not cleaned:
        return []

    if len(cleaned) <= max_length:
        return [cleaned]

    min_length = max(1, max_length // 2)
    messages = []
    remaining = cleaned

    while remaining:
        if len(remaining) <= max_length:
            messages.append(remaining.strip())
            break

        split_at = _find_chunk_boundary(remaining, min_length, max_length)
        chunk = remaining[:split_at].strip()
        if not chunk:
            split_at = max_length
            chunk = remaining[:split_at].strip()

        if chunk:
            messages.append(chunk)
        remaining = remaining[split_at:].lstrip()

    return messages


def get_config_path():
    return AppDirs("telegram-send").user_config_dir + ".conf"
