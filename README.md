# Agentes

Proyectos independientes de agentes: dos asistentes de pastelería que responden **WhatsApp**
e **Instagram** con Claude, y una plataforma de inversión con motor cuantitativo propio.

Cada proyecto vive en su propia carpeta — código, datos y configuración son independientes.

| Carpeta | Negocio | Detalle |
|---|---|---|
| [`obrador-pasteleria/`](./obrador-pasteleria) | Obrador de Pastelería | Pastelería argentina clásica (tortas, individuales, panadería dulce). 24 hs de anticipación para tortas. |
| [`selva-negra/`](./selva-negra) | Selva Negra Pastelería | Pastelería alemana / centroeuropea (Selva Negra, Sachertorte, Apfelstrudel, Stollen). 48 hs para tortas Selva Negra y Sachertorte. |
| [`turpial-finanzas/`](./turpial-finanzas) | Turpial Finanzas | Plataforma de inversión multi-activo: Risk Score de acciones, agente IA con datos reales y **motor cuantitativo** (Ornstein-Uhlenbeck, half-life, cadenas de Markov, cointegración de pares y backtest walk-forward). |

## Capacidades de cada agente de pastelería

- **Responde mensajes generales**: productos, horarios, ubicación, formas de pago.
- **Muestra el menú** filtrado por categoría o completo.
- **Toma pedidos inmediatos** (retiro en el día).
- **Agenda pedidos** para una fecha y hora futuras, respetando el tiempo mínimo de anticipación.
- **Recuerda la conversación** de cada cliente por separado (hilos independientes por número de WhatsApp o usuario de Instagram).

## Arquitectura

```
Cliente envía mensaje
  ↓ (WhatsApp Business / Instagram DM)
Meta Webhook
  ↓ (HTTPS POST)
Servicio FastAPI (Railway / Render / VPS)
  ↓
Agente Claude con tool use
  ↓ (mostrar_menu, tomar_pedido, etc.)
Respuesta de texto
  ↓
Meta Graph API → Cliente recibe la respuesta
```

## Cómo deployar

Cada carpeta tiene su propio `README.md` con instrucciones paso a paso para Railway + Meta Developers:

- [Deploy del Obrador](./obrador-pasteleria/README.md#deploy-en-railway)
- [Deploy de Selva Negra](./selva-negra/README.md#deploy-en-railway)

Resumen:

1. **Hosting**: deployar cada carpeta como un servicio separado en Railway. La config (`railway.json`) ya está incluida.
2. **Cuentas Meta**: cada bakery necesita su propia app en Meta Developers, con su número de WhatsApp Business e Instagram Business conectado a una página de Facebook.
3. **Variables de entorno**: pegar las claves (Anthropic + Meta) en el panel de variables del hosting.
4. **Webhooks**: registrar `https://<url-del-servicio>/webhook/whatsapp` y `https://<url-del-servicio>/webhook/instagram` en Meta, usando un `META_VERIFY_TOKEN` que vos elijas.

## Turpial Finanzas

La plataforma de inversión tiene su propio README con el detalle de la arquitectura, la API
y el motor cuantitativo: [`turpial-finanzas/README.md`](./turpial-finanzas/README.md), y la
matemática de los modelos estocásticos en
[`turpial-finanzas/docs/quant.md`](./turpial-finanzas/docs/quant.md).

## Sobre TikTok

TikTok **no tiene API pública de DMs** disponible para terceros, por lo que esta solución no responde por TikTok. Si en el futuro se necesita interacción con TikTok, la única vía oficial es la Content Posting API + Display API (publicar videos y responder comentarios, no DMs).

## Modelo

Ambos agentes usan `claude-opus-4-7` con tool use. El costo aproximado por conversación es de fracciones de centavo (depende del largo).
