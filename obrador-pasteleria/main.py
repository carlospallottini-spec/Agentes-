"""Entrypoint del servidor — corre uvicorn con la app de webhooks."""
import os

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("webhooks:app", host="0.0.0.0", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
