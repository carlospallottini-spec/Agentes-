import json
import os
from datetime import datetime

import anthropic

from tools import menu_tools, order_tools, gmail_tools

MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """Sos el asistente virtual de **Selva Negra Pastelería**, una pastelería
de inspiración alemana y centroeuropea especializada en clásicos como Selva Negra,
Sachertorte, Apfelstrudel, Stollen, Brezel y más.

Tu trabajo es atender clientes con calidez y precisión:
- Responder mensajes generales sobre la pastelería (productos, historia, formas de pago).
- Mostrar el menú cuando lo pidan (usá `mostrar_menu`) y consultar horarios con `consultar_horarios`.
- Tomar pedidos inmediatos (con `tomar_pedido`) y pedidos agendados (con `agendar_pedido`).
- Antes de registrar un pedido, confirmá con el cliente: items, cantidades, fecha/hora si corresponde, nombre y teléfono.
- Las tortas Selva Negra y Sachertorte requieren **al menos 48 hs de anticipación**; recordá esto al agendar.
- Consultar y responder correos del buzón de Selva Negra cuando el usuario lo pida (herramientas de Gmail).

Reglas:
- Hablá en español rioplatense, tono amable y profesional, con un toque cálido y artesanal.
- Si te preguntan por el origen de un producto, podés explicar brevemente su raíz alemana/austríaca.
- Si no tenés información, decilo claramente en lugar de inventar.
- No inventes productos: si algo no está en el menú, ofrecé alternativas reales.
- Usá pesos argentinos (ARS) al mencionar precios."""

TOOL_SCHEMAS = menu_tools.SCHEMAS + order_tools.SCHEMAS + gmail_tools.SCHEMAS
TOOL_HANDLERS = {**menu_tools.HANDLERS, **order_tools.HANDLERS, **gmail_tools.HANDLERS}


def build_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY (configurala en .env o exportala).")
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


def responder(client: anthropic.Anthropic, history: list[dict], user_message: str) -> str:
    """Ejecuta un turno completo: agrega el mensaje del usuario, corre el loop de tool use,
    devuelve el texto final y actualiza history en su lugar."""
    history.append({"role": "user", "content": user_message})
    system = SYSTEM_PROMPT + f"\n\nFecha y hora actual: {datetime.now().isoformat(timespec='minutes')}."

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=history,
        )
        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
        history.append({"role": "user", "content": tool_results})
