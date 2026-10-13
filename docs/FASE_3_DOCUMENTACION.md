# 📘 Documentación Técnica - Fase 3: Notificaciones Multicanal Sin Costo (Brevo, Telegram, WhatsApp)
**Proyecto:** Comercial Kenpaku S.A.C. (E-Commerce Siderúrgico & Asesor IA)  
**Fecha:** Octubre 2026  
**Ramas de trabajo:** `maza` (Backend) / `Maza` (Frontend)  
**Commits:** `13b786a` (Backend) / `3332974` (Frontend)  
**Estado:** ✅ 100% Completado, Probado y Pusheado  

---

## 📌 Resumen Ejecutivo
La **Fase 3** aborda la necesidad de comunicación instantánea, transparente y multicanal entre la empresa, el equipo de ventas/almacén y los clientes finales tras registrarse una compra o una actualización logística, **sin generar costos de infraestructura ni suscripciones pagas**:

1. **Email Transaccional (Brevo - ex Sendinblue):**
   - 300 correos diarios 100% gratuitos sin necesidad de tarjeta de crédito ni dominios pagos en fase inicial.
   - Plantillas HTML responsivas corporativas con diseño Kenpaku (azul marino `#0F172A`, detalles en ámbar `#F59E0B`, logo, botón de seguimiento en vivo con token y desglose de materiales con IGV).
2. **Alertas Internas en Tiempo Real (Telegram Bot API):**
   - 100% gratuito e ilimitado para el equipo de ventas, caja y almacén de Puente Piedra.
   - Alerta instantánea en el smartphone del administrador al generarse:
     - Nuevo pedido con montos y modalidad (Recojo en Almacén o Despacho a Obra).
     - Cambio de fase operativa (confirmado, flete cotizado, despachado, etc.).
     - Registro de Reclamo/Queja en el Libro de Reclamaciones (Indecopi).
     - Solicitud de derivación humana desde el Asesor Virtual IA.
3. **Comunicación Directa con Clientes (WhatsApp `wa.me`):**
   - 0 costo de API de Meta/WhatsApp Business Cloud.
   - Enlaces directos pre-redactados para el administrador con un solo clic desde el modal de pedidos, con mensajes profesionales adaptados al estado exacto del pedido (`confirmado`, `flete cotizado`, `listo en almacén`, `camión en camino`, `entregado`).
4. **Arquitectura No Bloqueante y Modo Simulado / Mock Resiliente:**
   - Todas las llamadas externas se ejecutan en segundo plano vía `BackgroundTasks` de FastAPI: el checkout o la acción del admin responden en **menos de 20 ms**.
   - Si no se configuran credenciales en el archivo `.env`, el sistema entra en modo simulación automática (registrando en log), garantizando que las pruebas unitarias y el servidor funcionen al 100% sin arrojar errores `500`.

---

## 🛠️ Detalle de Cambios Realizados

### 1. Backend (FastAPI + SQLAlchemy)

#### A. Configuración Centralizada
- **Archivo:** [`BackKenpaku/BackKenpaku/app/core/config.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/core/config.py)
- Se añadieron las variables de entorno para los canales:
  - `BREVO_API_KEY`: Clave API v3 de Brevo.
  - `SENDER_EMAIL`: Correo verificado del remitente (ej. `ventas@kenpaku.pe` o correo corporativo).
  - `SENDER_NAME`: Nombre del remitente (*Comercial Kenpaku S.A.C.*).
  - `TELEGRAM_BOT_TOKEN`: Token obtenido de `@BotFather`.
  - `TELEGRAM_CHAT_ID`: ID del chat o grupo de ventas/administración.
  - `FRONTEND_URL`: URL base del frontend para enlazar el seguimiento público (`http://localhost:5173` o dominio de producción).

#### B. Servicio de Correo Transaccional (Brevo REST API)
- **Archivo:** [`BackKenpaku/BackKenpaku/app/services/email_service.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/services/email_service.py)
- **Implementación:**
  - Consume la API REST v3 de Brevo (`https://api.brevo.com/v3/smtp/email`) mediante `urllib.request` asíncrono/síncrono nativo (sin dependencias externas pesadas).
  - **Plantilla para Pedido Creado:** Incluye código de pedido, tabla de productos, totales, dirección/modalidad y botón directo con token de seguimiento para que el cliente consulte su pedido sin loguearse.
  - **Plantilla para Cambio de Estado:** Notifica al cliente cada transición (flete cotizado, confirmado, en camino, entregado).
  - **Plantilla para Libro de Reclamaciones (Indecopi):** Notificación formal con código de seguimiento legal de 30 días calendario y detalles del reclamo.
  - **Fallback Silencioso:** Si `BREVO_API_KEY` no está configurado, registra el correo en logger y retorna `True` sin romper el flujo.

#### C. Servicio de Notificaciones Telegram
- **Archivo:** [`BackKenpaku/BackKenpaku/app/services/telegram_service.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/services/telegram_service.py)
- **Implementación:**
  - Envía mensajes formateados con Markdown a la API de Telegram (`https://api.telegram.org/bot<TOKEN>/sendMessage`).
  - **Alerta de Nuevo Pedido:** Resumen con código, cliente, teléfono, total en Soles, modalidad e ítems solicitados.
  - **Alerta de Cambio de Estado:** Notifica al equipo interno el nuevo estado operativo y nota agregada por el operador.
  - **Alerta de Libro de Reclamaciones:** Aviso urgente de reclamo o queja registrada por un consumidor para atención dentro del plazo de ley.
  - **Alerta de Handoff de Chat IA:** Aviso al equipo de ventas cuando un cliente solicita hablar con un asesor humano en vivo.
  - **Fallback Silencioso:** Si `TELEGRAM_BOT_TOKEN` o `TELEGRAM_CHAT_ID` no están configurados, registra la alerta en logger y continúa normalmente.

#### D. Orquestador de Notificaciones Multicanal
- **Archivo:** [`BackKenpaku/BackKenpaku/app/services/notification_service.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/services/notification_service.py)
- Funciones centralizadas:
  - `notify_order_created(order)`: Dispara correo de confirmación al cliente y alerta por Telegram al admin.
  - `notify_order_status_changed(order, new_status, note)`: Dispara correo de actualización al cliente y alerta por Telegram.
  - `notify_claim_created(claim)`: Dispara correo de confirmación legal de reclamo y alerta de alta prioridad por Telegram.
  - `notify_chat_handoff(customer_name, customer_phone, last_message)`: Notifica al vendedor por Telegram para que contacte al cliente de inmediato.

#### E. Integración en Routers vía BackgroundTasks
- **Endpoints conectados:**
  - `POST /api/orders/` ([`orders.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/routers/orders.py)): `background_tasks.add_task(notify_order_created, order)`
  - `PUT /api/admin/orders/{order_id}/status` ([`admin.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/routers/admin.py)): `background_tasks.add_task(notify_order_status_changed, updated_order, status_in.estado, status_in.nota)`
  - `POST /api/claims/` ([`claims.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/routers/claims.py)): `background_tasks.add_task(notify_claim_created, claim)`
  - `POST /api/chat/message` ([`chat.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/routers/chat.py)): `background_tasks.add_task(notify_chat_handoff, ...)` cuando el estado pasa a `escalated`.

---

### 2. Frontend (React 18 + Vite + TailwindCSS)

#### A. Utilidad Avanzada para Enlaces de WhatsApp
- **Archivo:** [`FrontKenpaku/FrontKenpaku/src/utils/whatsapp.js`](file:///c:/Users/alexi/Desktop/Kenpaku/FrontKenpaku/FrontKenpaku/src/utils/whatsapp.js)
- **Normalización de Teléfonos (`normalizePhoneForWhatsApp`):** Convierte cualquier número ingresado a formato internacional peruano `519XXXXXXXX`.
- **Generación Dinámica de Mensajes (`buildStatusWhatsAppUrl`):**
  - Adapta el mensaje al estado exacto:
    - **flete_cotizado:** Comunica el costo de flete calculado y consulta si procede con la reserva.
    - **confirmado:** Confirma validación de pago y reserva física de material en patio.
    - **listo_para_recojo:** Avisa que puede pasar a retirar en almacén de Puente Piedra con su DNI.
    - **despachado:** Avisa que el camión va en camino a obra y que el chofer lo llamará.
    - **entregado:** Agradece la compra y confirma la conformidad.
    - **cancelado:** Informa la anulación y liberación de reserva.
  - Si el pedido cuenta con `tracking_token`, adjunta automáticamente el enlace directo al seguimiento en vivo.

#### B. Barra de Acción de WhatsApp en Panel Administrativo
- **Archivo:** [`FrontKenpaku/FrontKenpaku/src/pages/admin/Orders.jsx`](file:///c:/Users/alexi/Desktop/Kenpaku/FrontKenpaku/FrontKenpaku/src/pages/admin/Orders.jsx)
- Dentro del modal de detalle de cada pedido, se integró un componente visual destacado en color verde esmeralda con el botón **"Avisar al Cliente"**:
  - Abre WhatsApp Web / App con el mensaje pre-cargado listo para enviar.
  - Elimina el error humano de copiar teléfonos o redactar mensajes repetitivos.

---

## 🧪 Certificación y Pruebas Unitarias

### Backend (Pytest)
- **Suite de Pruebas:** [`BackKenpaku/BackKenpaku/app/tests/test_phase3.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/tests/test_phase3.py)
- **Casos probados:**
  1. `test_email_service_mock_when_no_api_key`: Simulación limpia de Brevo sin API key.
  2. `test_telegram_service_mock_when_no_credentials`: Simulación limpia de Telegram sin token.
  3. `test_notify_order_created_orchestration`: Orquestación completa de nuevo pedido.
  4. `test_notify_order_status_changed_orchestration`: Orquestación de cambio de estado.
  5. `test_notify_claim_created_orchestration`: Notificación de reclamo Indecopi con atributos del modelo.
  6. `test_notify_chat_handoff_orchestration`: Notificación de derivación a asesor humano.
  7. `test_orders_router_triggers_background_notification`: Endpoint `/api/orders/` ejecuta background task.
  8. `test_admin_router_triggers_background_status_notification`: Endpoint de cambio de estado ejecuta background task.
- **Resultado Global:** **49 passed, 4 warnings in 3.68s** (100% de la suite de backend pasando).

### Frontend (Vitest)
- **Suite de Pruebas:** [`FrontKenpaku/FrontKenpaku/src/utils/__tests__/whatsapp.test.js`](file:///c:/Users/alexi/Desktop/Kenpaku/FrontKenpaku/FrontKenpaku/src/utils/__tests__/whatsapp.test.js) y [`src/pages/__tests__/Orders.test.jsx`](file:///c:/Users/alexi/Desktop/Kenpaku/FrontKenpaku/FrontKenpaku/src/pages/__tests__/Orders.test.jsx)
- **Casos probados:**
  - Normalización de números con y sin prefijo `51`, guiones, espacios y paréntesis.
  - Retorno seguro de cadena vacía ante números nulos o pedidos inexistentes.
  - Construcción de URLs con formato para todos los estados (`despachado`, `entregado`, `pendiente`, `cancelado`, `flete_cotizado`, `listo_para_recojo`).
  - Renderizado del botón de WhatsApp en el modal del panel admin.
- **Resultado Global:** **33 passed** en 9 suites de pruebas (100% pasando).
- **Build de Producción:** `npm run build` ejecutado exitosamente con Vite (código 0).

---

## ⚙️ Guía de Configuración Opcional (Para Activar Notificaciones Reales)

El sistema ya está funcionando en **modo simulación (mock)**. Para enviar notificaciones reales a clientes y administradores cuando se desee, basta con agregar las siguientes variables en el archivo `.env` del backend ([`BackKenpaku/BackKenpaku/.env`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/.env)):

```env
# --- FASE 3: NOTIFICACIONES REALES (OPCIONAL) ---
# 1. Brevo (Emails transaccionales gratuitos - 300 por día):
# Crear cuenta gratuita en https://app.brevo.com -> SMTP & API -> API Keys -> Generar clave
BREVO_API_KEY=xkeysib-tu-api-key-de-brevo
SENDER_EMAIL=ventas@kenpaku.pe
SENDER_NAME=Comercial Kenpaku S.A.C.

# 2. Telegram Bot (Alertas instantáneas gratuitas al admin):
# Hablar con @BotFather en Telegram -> /newbot -> Obtener Token
# Obtener Chat ID hablando con @userinfobot o agregando el bot a un grupo y consultando https://api.telegram.org/bot<TOKEN>/getUpdates
TELEGRAM_BOT_TOKEN=123456789:ABC-def_tu_bot_token
TELEGRAM_CHAT_ID=-1001234567890

# 3. Frontend Base URL (para enlaces directos de seguimiento en correos):
FRONTEND_URL=http://localhost:5173
```
*(Si no se configuran estas variables, el sistema continuará operando en modo simulado sin ningún error).*

---

## 📋 Resumen de Archivos Modificados / Creados

### Backend (`BackKenpaku`):
- `app/core/config.py` (Modificado)
- `app/services/email_service.py` (Nuevo)
- `app/services/telegram_service.py` (Nuevo)
- `app/services/notification_service.py` (Nuevo)
- `app/routers/orders.py` (Modificado)
- `app/routers/admin.py` (Modificado)
- `app/routers/claims.py` (Modificado)
- `app/routers/chat.py` (Modificado)
- `app/tests/test_phase3.py` (Nuevo)

### Frontend (`FrontKenpaku`):
- `src/utils/whatsapp.js` (Modificado)
- `src/pages/admin/Orders.jsx` (Modificado)
- `src/utils/__tests__/whatsapp.test.js` (Nuevo)
- `src/pages/__tests__/Orders.test.jsx` (Modificado)
