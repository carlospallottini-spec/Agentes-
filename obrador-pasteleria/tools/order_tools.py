import json
import uuid
from datetime import datetime
from pathlib import Path

ORDERS_PATH = Path(__file__).parent.parent / "data" / "orders.json"


def _load_orders() -> list[dict]:
    if not ORDERS_PATH.exists():
        return []
    with open(ORDERS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_orders(orders: list[dict]) -> None:
    ORDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ORDERS_PATH, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)


def tomar_pedido(cliente: str, telefono: str, items: list, notas: str = "") -> str:
    pedido = {
        "id": f"PED-{uuid.uuid4().hex[:8].upper()}",
        "tipo": "inmediato",
        "cliente": cliente,
        "telefono": telefono,
        "items": items,
        "notas": notas,
        "fecha_creacion": datetime.now().isoformat(timespec="seconds"),
        "estado": "registrado",
    }
    orders = _load_orders()
    orders.append(pedido)
    _save_orders(orders)
    return json.dumps({"ok": True, "pedido": pedido}, ensure_ascii=False, indent=2)


def agendar_pedido(
    cliente: str,
    telefono: str,
    items: list,
    fecha_entrega: str,
    hora_entrega: str,
    notas: str = "",
) -> str:
    pedido = {
        "id": f"PED-{uuid.uuid4().hex[:8].upper()}",
        "tipo": "agendado",
        "cliente": cliente,
        "telefono": telefono,
        "items": items,
        "fecha_entrega": fecha_entrega,
        "hora_entrega": hora_entrega,
        "notas": notas,
        "fecha_creacion": datetime.now().isoformat(timespec="seconds"),
        "estado": "agendado",
    }
    orders = _load_orders()
    orders.append(pedido)
    _save_orders(orders)
    return json.dumps({"ok": True, "pedido": pedido}, ensure_ascii=False, indent=2)


def listar_pedidos(estado: str | None = None) -> str:
    orders = _load_orders()
    if estado:
        orders = [o for o in orders if o.get("estado") == estado]
    return json.dumps(orders, ensure_ascii=False, indent=2)


_ITEMS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "ID del producto del menú (ej. 'T01')."},
            "nombre": {"type": "string", "description": "Nombre del producto."},
            "cantidad": {"type": "integer", "minimum": 1},
        },
        "required": ["nombre", "cantidad"],
    },
    "description": "Lista de items del pedido.",
}

SCHEMAS = [
    {
        "name": "tomar_pedido",
        "description": "Registra un pedido inmediato (para retiro en el día o ya preparado). Confirmá los datos con el cliente antes de llamar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cliente": {"type": "string", "description": "Nombre del cliente."},
                "telefono": {"type": "string", "description": "Teléfono o canal de contacto."},
                "items": _ITEMS_SCHEMA,
                "notas": {"type": "string", "description": "Comentarios o pedidos especiales (alergias, mensaje, etc.)."},
            },
            "required": ["cliente", "telefono", "items"],
        },
    },
    {
        "name": "agendar_pedido",
        "description": "Agenda un pedido para una fecha y hora específicas (ej. torta encargada). Recordá que las tortas requieren al menos 24 hs de anticipación.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cliente": {"type": "string"},
                "telefono": {"type": "string"},
                "items": _ITEMS_SCHEMA,
                "fecha_entrega": {"type": "string", "description": "Fecha de retiro/entrega en formato YYYY-MM-DD."},
                "hora_entrega": {"type": "string", "description": "Hora de retiro/entrega en formato HH:MM (24 hs)."},
                "notas": {"type": "string"},
            },
            "required": ["cliente", "telefono", "items", "fecha_entrega", "hora_entrega"],
        },
    },
    {
        "name": "listar_pedidos",
        "description": "Lista los pedidos registrados, opcionalmente filtrando por estado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "estado": {
                    "type": "string",
                    "enum": ["registrado", "agendado", "entregado", "cancelado"],
                    "description": "Filtrar por estado (opcional).",
                }
            },
            "required": [],
        },
    },
]

HANDLERS = {
    "tomar_pedido": tomar_pedido,
    "agendar_pedido": agendar_pedido,
    "listar_pedidos": listar_pedidos,
}
