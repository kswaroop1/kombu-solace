"""Wildcard translation helpers for optional native Solace routing."""

from __future__ import annotations


def amqp_topic_binding_to_solace_subscription(binding_key: str) -> str:
    """Translate a safe AMQP/Kombu topic binding to a Solace subscription.

    The default transport mode does not use this function; Kombu owns routing.
    This helper exists to keep any future native routing mode conservative.

    Safe translations:
    - literal words map to literal Solace topic levels
    - `*` maps to Solace `*`
    - terminal `#` maps to Solace `>` only when it follows at least one word

    Non-terminal `#`, bare `#`, and literal Solace wildcard characters inside
    words are rejected because they do not preserve Kombu topic behavior.
    """

    if not binding_key:
        raise ValueError("empty AMQP topic binding cannot be translated safely")

    words = binding_key.split(".")
    translated: list[str] = []
    for index, word in enumerate(words):
        if word == "*":
            translated.append("*")
        elif word == "#":
            if index != len(words) - 1 or index == 0:
                raise ValueError(
                    "AMQP '#' can only be translated when it is the final word "
                    "after a literal prefix"
                )
            translated.append(">")
        else:
            if not word:
                raise ValueError("empty AMQP topic word cannot be translated safely")
            if "/" in word or ">" in word or "*" in word:
                raise ValueError("literal Solace wildcard/topic characters are unsafe")
            translated.append(word)
    return "/".join(translated)

