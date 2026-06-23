"""Cliente base de Claude con loop de tool-use, compartido por los agentes."""
from __future__ import annotations

import json
import os

import anthropic

from config import MODEL


def build_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY (configurala en .env o en el hosting).")
    return anthropic.Anthropic(api_key=api_key)


def run_single_tool(client: anthropic.Anthropic, system: str, user_content: str,
                    tool: dict, max_tokens: int = 4096) -> dict:
    """Le pide al modelo que responda EXCLUSIVAMENTE llamando a `tool`.

    Devuelve el dict de input de esa tool call (el análisis estructurado).
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": user_content}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return dict(block.input)
    raise RuntimeError("El modelo no devolvió la tool call esperada.")


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
