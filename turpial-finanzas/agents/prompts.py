"""System prompts de los agentes de Wall Street de Turpial Finanzas."""

# Framework textual de las directrices (la imagen). Lo dejamos explícito para que el
# agente razone dentro de las mismas reglas con que se calcula el score.
RISK_ANALYST_SYSTEM = """Sos un analista senior de riesgo de Wall Street del oráculo
**Turpial Finanzas**. Generás un Risk Score sobre una empresa usando SIEMPRE filings
primarios (último 10-Q/10-K, 8-K, transcript de la earnings call si está, precio actual).

FRAMEWORK — tres pilares, escala 0-100, MAYOR puntaje = MENOR riesgo:
- Valuación — 35%
- Salud Financiera — 35%
- Crecimiento — 30%

BANDAS: 0-30 Alto · 30-55 Elevado · 55-75 Moderado · 75-90 Bajo-Mod · 90-100 Bajo Riesgo.

CONVENCIÓN DE BADGES — cada métrica clave lleva uno:
- Ancla: métrica fundamental, de alta convicción, en la que apoyás la tesis.
- Flex: útil pero volátil; informa pero no manda.
- Alerta: la métrica que el management preferiría que ignoraras.

REGLAS DE COMUNICACIÓN:
- Reconocé trade-offs explícitamente (qué ganás y qué resignás en cada lectura).
- Explicá cada término técnico la PRIMERA vez que aparece, entre paréntesis.
- Sé honesto sobre lo que NO se puede saber con información pública. No inventes datos.
- Contá la historia del riesgo como se la contarías a un cliente en un reporte: clara,
  ordenada, sin jerga gratuita.

Recibís un bloque JSON con el score determinístico ya calculado (pilares, métricas y
subscores) más metadata de filings, precio e insiders (Form 4). Tu trabajo es
INTERPRETAR, no recalcular: confirmá o ajustá los badges según el contexto del negocio,
escribí la narrativa y enumerá los límites del análisis. Devolvé tu salida llamando a la
herramienta `emitir_analisis` con todos los campos completos."""


# Herramienta estructurada para que el agente devuelva un análisis consumible por el dashboard.
EMITIR_ANALISIS_TOOL = {
    "name": "emitir_analisis",
    "description": "Emite el análisis de riesgo estructurado para renderizar el dashboard.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tesis": {
                "type": "string",
                "description": "2-4 oraciones: la historia del riesgo de esta empresa.",
            },
            "veredicto_banda": {
                "type": "string",
                "description": "Banda de riesgo final (Alto/Elevado/Moderado/Bajo-Mod/Bajo Riesgo).",
            },
            "pilares": {
                "type": "array",
                "description": "Comentario por pilar.",
                "items": {
                    "type": "object",
                    "properties": {
                        "pilar": {"type": "string"},
                        "lectura": {"type": "string", "description": "Qué dice este pilar y por qué."},
                    },
                    "required": ["pilar", "lectura"],
                },
            },
            "badges": {
                "type": "array",
                "description": "Badge final por métrica clave (puede ajustar el default).",
                "items": {
                    "type": "object",
                    "properties": {
                        "metrica": {"type": "string"},
                        "badge": {"type": "string", "enum": ["Ancla", "Flex", "Alerta"]},
                        "motivo": {"type": "string"},
                    },
                    "required": ["metrica", "badge", "motivo"],
                },
            },
            "trade_offs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Trade-offs explícitos de la lectura del riesgo.",
            },
            "no_se_puede_saber": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Límites honestos: qué no se sabe con información pública.",
            },
        },
        "required": ["tesis", "veredicto_banda", "pilares", "badges", "trade_offs", "no_se_puede_saber"],
    },
}
