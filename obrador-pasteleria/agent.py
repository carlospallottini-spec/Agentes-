import json
import os
from datetime import datetime

import anthropic

from tools import menu_tools, order_tools

MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """Sos el asistente virtual del **Obrador de Pastelería**, un obrador artesanal,
respondiendo por redes sociales (WhatsApp e Instagram).

Tu trabajo es atender clientes con calidez y precisión:
- Responder mensajes generales sobre el obrador (productos, ubicación, formas de pago).
- Mostrar el menú cuando lo pidan (usá `mostrar_menu`) y consultar horarios con `consultar_horarios`.
- Tomar pedidos inmediatos (con `tomar_pedido`) y pedidos agendados (con `agendar_pedido`).
- Antes de registrar un pedido, confirmá con el cliente: items, cantidades, fecha/hora si corresponde, nombre y teléfono.
- Las tortas requieren al menos 24 hs de anticipación; recordá esto al agendar.

Reglas para redes sociales:
- Respuestas **breves** (la gente lee en el celular). Ideal: 2-4 oraciones, listas cortas.
- Hablá en español rioplatense, tono amable y profesional.
- No uses formato Markdown complejo: WhatsApp acepta *negrita* con asteriscos simples y nada más.
- Si no tenés información, decilo claramente en lugar de inventar.
- No inventes productos: si algo no está en el menú, ofrecé alternativas reales.
- Usá pesos argentinos (ARS) al mencionar precios."""

TOOL_SCHEMAS = menu_tools.SCHEMAS + order_tools.SCHEMAS
TOOL_HANDLERS = {**menu_tools.HANDLERS, **order_tools.HANDLERS}


def build_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY (configurala en .env o en el hosting).")
    return anthropic.Anthropic(api_key=api_key)


def _execute_tool(name: str, tool_input: dict) -> str:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Herramienta desconocida: {name}"}, ensure_ascii=False)
    try:
        return handler(**tool_input)
    except TypeError as e:
        return json.dumps({"error": f"Argumentos inválidos para {name}: {e}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Error ejecutando {name}: {e}"}, ensure_ascii=False)


def _block_to_dict(block) -> dict:
    """Convierte un ContentBlock del SDK a dict serializable para persistencia."""
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)


def responder(client: anthropic.Anthropic, history: list[dict], user_message: str) -> str:
    """Ejecuta un turno completo. Devuelve la respuesta de texto final y actualiza history."""
    history.append({"role": "user", "content": user_message})
    system = SYSTEM_PROMPT + f"\n\nFecha y hora actual: {datetime.now().isoformat(timespec='minutes')}."

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=history,
        )
        history.append({"role": "assistant", "content": [_block_to_dict(b) for b in response.content]})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text").strip()

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _execute_tool(block.name, dict(block.input))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        history.append({"role": "user", "content": tool_results})
