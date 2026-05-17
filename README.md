# Agentes de pastelería

Dos asistentes virtuales independientes para pastelerías, que responden mensajes de **WhatsApp** e **Instagram** usando Claude (`claude-opus-4-7`).

Cada agente vive en su propia carpeta — código, menú, pedidos y configuración son independientes.

| Carpeta | Negocio | Detalle |
|---|---|---|
| [`obrador-pasteleria/`](./obrador-pasteleria) | Obrador de Pastelería | Pastelería argentina clásica (tortas, individuales, panadería dulce). 24 hs de anticipación para tortas. |
| [`selva-negra/`](./selva-negra) | Selva Negra Pastelería | Pastelería alemana / centroeuropea (Selva Negra, Sachertorte, Apfelstrudel, Stollen). 48 hs para tortas Selva Negra y Sachertorte. |

## Capacidades de cada agente

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

## Sobre TikTok

TikTok **no tiene API pública de DMs** disponible para terceros, por lo que esta solución no responde por TikTok. Si en el futuro se necesita interacción con TikTok, la única vía oficial es la Content Posting API + Display API (publicar videos y responder comentarios, no DMs).

## Modelo

Ambos agentes usan `claude-opus-4-7` con tool use. El costo aproximado por conversación es de fracciones de centavo (depende del largo).
