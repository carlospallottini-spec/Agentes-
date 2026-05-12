"""CLI de chat para el agente del Obrador de Pastelería."""
import sys

from dotenv import load_dotenv

from agent import build_client, responder

BANNER = """
========================================
  Obrador de Pastelería - Asistente
========================================
Escribí tu mensaje. Comandos: 'salir' para terminar, 'reset' para limpiar la conversación.
"""


def main() -> int:
    load_dotenv()
    try:
        client = build_client()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    history: list[dict] = []
    print(BANNER)

    while True:
        try:
            user_input = input("Vos > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"salir", "exit", "quit"}:
            break
        if user_input.lower() == "reset":
            history.clear()
            print("(conversación reiniciada)\n")
            continue

        try:
            reply = responder(client, history, user_input)
        except Exception as e:
            print(f"[error] {e}\n", file=sys.stderr)
            continue

        print(f"\nObrador > {reply}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
