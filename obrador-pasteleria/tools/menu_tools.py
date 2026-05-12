import json
from pathlib import Path

MENU_PATH = Path(__file__).parent.parent / "data" / "menu.json"


def _load_menu() -> dict:
    with open(MENU_PATH, encoding="utf-8") as f:
        return json.load(f)


def mostrar_menu(categoria: str | None = None) -> str:
    menu = _load_menu()
    if categoria:
        cat = categoria.strip().lower().replace(" ", "_")
        items = menu["categorias"].get(cat)
        if items is None:
            disponibles = ", ".join(menu["categorias"].keys())
            return f"Categoría '{categoria}' no encontrada. Disponibles: {disponibles}"
        return json.dumps(
            {"categoria": cat, "items": items, "moneda": menu["moneda"]},
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(menu, ensure_ascii=False, indent=2)


def consultar_horarios() -> str:
    menu = _load_menu()
    return json.dumps(
        {
            "horarios": menu["horarios"],
            "tiempo_minimo_pedido_torta_horas": menu["tiempo_minimo_pedido_torta_horas"],
            "notas": menu["notas"],
        },
        ensure_ascii=False,
        indent=2,
    )


SCHEMAS = [
    {
        "name": "mostrar_menu",
        "description": (
            "Devuelve el menú del Obrador de Pastelería. Permite filtrar por categoría "
            "o devolver el menú completo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "description": "Categoría a filtrar: 'tortas', 'individuales' o 'panaderia_dulce'. Omitir para menú completo.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "consultar_horarios",
        "description": "Devuelve los horarios de atención y notas relevantes del obrador.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

HANDLERS = {
    "mostrar_menu": mostrar_menu,
    "consultar_horarios": consultar_horarios,
}
