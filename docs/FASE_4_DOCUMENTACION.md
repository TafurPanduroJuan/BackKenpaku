# 📘 Documentación Técnica - Fase 4: Flete y Pago Dentro del Sistema
**Proyecto:** Comercial Kenpaku S.A.C. (E-Commerce Siderúrgico & Asesor IA)  
**Fecha:** Octubre 2026  
**Ramas de trabajo:** `maza` (Backend) / `Maza` (Frontend)  
**Estado:** ✅ 100% Completado, Probado y Verificado  

---

## 📌 Resumen Ejecutivo
La **Fase 4** completa el ciclo comercial y logístico entre el cliente y Comercial Kenpaku directamente dentro de la plataforma, resolviendo dos barreras fundamentales del e-commerce B2B/B2C siderúrgico:

1. **Gestión y Negociación del Flete Pesado a Obra:**
   - Para pedidos con modalidad **Despacho a Obra**, el flete depende del tonelaje de acero y la distancia.
   - El administrador cotiza el flete desde su panel (`flete_cotizado`).
   - El cliente visualiza el desglose exacto (Materiales + Flete + IGV = Total) en su pantalla de seguimiento público y cuenta con botones interactivos para **"Aceptar Flete"** o **"Rechazar / Coordinar"**.
   - Cada decisión se registra en el historial (`OrderEvent`) y envía una alerta instantánea a Telegram.
   - Si el pedido es **Recojo en Almacén Puente Piedra**, el flete se omite automáticamente (`S/ 0.00`).

2. **Pago Manual Sin Comisiones y Carga de Comprobante (Voucher):**
   - Evita las comisiones bancarias del 4% de pasarelas de pago que encarecen el acero estructural.
   - Presenta las cuentas oficiales de Comercial Kenpaku S.A.C.:
     - **Yape / Plin:** `987 654 321` (Titular: Comercial Kenpaku S.A.C.).
     - **BCP Cta Corriente Soles:** `191-2345678-0-12` (CCI: `002-191-002345678012-55`).
     - **BBVA Cta Corriente Soles:** `0011-0123-0100456789` (CCI: `011-123-000100456789-78`).
   - Permite al cliente subir su comprobante digital (JPG, PNG, WEBP o PDF, hasta 5 MB) con almacenamiento en **Supabase Storage** (bucket `vouchers`) o almacenamiento local seguro (`uploads/vouchers/`) como fallback resiliente.
   - Al subir el voucher, el administrador recibe una alerta en Telegram y visualiza el comprobante en su modal de detalle para **"Validar Abono y Confirmar Pedido"** (descontando el stock físico en almacén) o **"Observar Voucher"**.

---

## 🛠️ Detalle de Cambios Realizados

### 1. Backend (FastAPI + SQLAlchemy)

#### A. Configuración de Almacenamiento
- **Archivo:** [`BackKenpaku/BackKenpaku/app/core/config.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/core/config.py)
- Variables añadidas:
  - `SUPABASE_URL`: URL del proyecto Supabase.
  - `SUPABASE_KEY`: Clave API / Service Role de Supabase.
  - `SUPABASE_BUCKET_VOUCHERS`: Nombre del bucket (`vouchers`).
  - `UPLOAD_DIR`: Directorio local para almacenamiento de respaldo (`uploads/vouchers`).
  - `MAX_UPLOAD_SIZE_BYTES`: Límite máximo de 5 MB (`5242880` bytes).

#### B. Servicio de Almacenamiento Resiliente
- **Archivo:** [`BackKenpaku/BackKenpaku/app/services/storage_service.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/services/storage_service.py)
- Sube archivos a la API REST de Supabase Storage si las credenciales existen.
- Si no están configuradas o hay falla de red, guarda en disco local y genera una URL de acceso seguro (`/api/orders/voucher/{filename}`).
- Sanitización de nombres de archivo y generación de identificadores únicos UUID para prevenir sobreescrituras.

#### C. Nuevos Esquemas Pydantic v2
- **Archivo:** [`BackKenpaku/BackKenpaku/app/schemas/order.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/schemas/order.py)
- `FleteDecisionRequest`: `{ decision: "aceptar" | "rechazar", nota?: string }`.
- `VoucherValidationRequest`: `{ aprobado: boolean, nota?: string }`.
- `OrderPublicTrackingResponse`: Actualizado para exponer `voucher_referencia` y `fecha_pago` de forma segura.

#### D. Endpoints Públicos de Flete y Voucher
- **Archivo:** [`BackKenpaku/BackKenpaku/app/routers/orders.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/routers/orders.py)
- `POST /api/orders/tracking/flete-decision`: Registra aceptación o rechazo de flete, actualiza `estado_flete`, añade evento al historial y dispara notificación a Telegram en segundo plano.
- `POST /api/orders/tracking/voucher`: Soporta subida de archivos multipart, valida tipos MIME permitidos y límite de 5 MB, almacena el archivo y vincula `voucher_referencia` y `fecha_pago`.
- `GET /api/orders/voucher/{filename}`: Sirve los comprobantes almacenados localmente con protección anti Path Traversal.

#### E. Endpoints de Validación Administrativa
- **Archivo:** [`BackKenpaku/BackKenpaku/app/routers/admin.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/routers/admin.py)
- `PUT /api/admin/orders/{order_id}/validate-voucher`: Permite a caja aprobar el comprobante (transicionando a `confirmado` y descontando el stock) u observarlo para que el cliente lo reenvíe.

#### F. Alertas de Telegram
- **Archivo:** [`BackKenpaku/BackKenpaku/app/services/notification_service.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/services/notification_service.py)
- `notify_flete_decision(order, decision, nota)`: Alerta instantánea cuando el cliente acepta o rechaza el flete.
- `notify_voucher_uploaded(order, filename)`: Alerta instantánea a caja con monto a verificar y código de pedido.

---

### 2. Frontend (React 18 + Vite + TailwindCSS)

#### A. Métodos de API
- **Archivo:** [`FrontKenpaku/FrontKenpaku/src/api/orders.js`](file:///c:/Users/alexi/Desktop/Kenpaku/FrontKenpaku/FrontKenpaku/src/api/orders.js)
- `submitFleteDecision({ token, codigo, telefono, decision, nota })`
- `uploadOrderVoucher({ token, codigo, telefono, file })`
- `validateOrderVoucher({ orderId, aprobado, nota })`

#### B. Componentes Interactivos en `/seguimiento`
- **Archivo:** [`FrontKenpaku/FrontKenpaku/src/pages/TrackingPage.jsx`](file:///c:/Users/alexi/Desktop/Kenpaku/FrontKenpaku/FrontKenpaku/src/pages/TrackingPage.jsx)
- **Tarjeta de Flete Cotizado:** Desglose del transporte y botones para Aceptar o Rechazar con ingreso de motivo opcional.
- **Tarjeta de Pagos Oficiales:** Pestañas para Yape/Plin, BCP y BBVA con números de cuenta y CCI en Soles.
- **Carga de Voucher con Vista Previa:** Drag & drop con selector de archivo, validación de tamaño (5 MB), previsualización de imagen y botón de envío con estado de carga.
- **Estado de Comprobante Subido:** Banner informativo con enlace directo para revisar el voucher enviado.

#### C. Visor y Aprobación de Voucher en Admin
- **Archivo:** [`FrontKenpaku/FrontKenpaku/src/pages/admin/Orders.jsx`](file:///c:/Users/alexi/Desktop/Kenpaku/FrontKenpaku/FrontKenpaku/src/pages/admin/Orders.jsx)
- En el modal de detalle del pedido, si el cliente subió voucher, se muestra una tarjeta destacada con enlace a documento completo y botón de un solo clic **"Validar Abono y Confirmar Pedido"**.

---

## 🧪 Certificación y Pruebas Unitarias

### Backend (Pytest)
- **Suite de Pruebas:** [`BackKenpaku/BackKenpaku/app/tests/test_phase4.py`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/app/tests/test_phase4.py)
- **Casos probados:**
  1. `test_flete_decision_accept`: Aceptación de flete por el cliente e historización.
  2. `test_flete_decision_reject`: Rechazo de flete con registro de motivo.
  3. `test_flete_decision_invalid_state`: Rechazo 422 si el pedido no está en `flete_cotizado`.
  4. `test_upload_voucher_valid_image`: Subida exitosa de JPG/PNG con generación de URL.
  5. `test_upload_voucher_invalid_mime_type`: Rechazo 400 ante archivos ejecutables o no permitidos.
  6. `test_upload_voucher_empty_file`: Rechazo 400 ante archivos vacíos de 0 bytes.
  7. `test_admin_validate_voucher_approve`: Aprobación en admin pasa a `confirmado` y descuenta stock físico.
  8. `test_admin_validate_voucher_reject`: Rechazo de voucher mantiene estado y no descuenta inventario.
  9. `test_serve_voucher_file_and_traversal_protection`: Consulta local de archivo y bloqueo de ataques Path Traversal (`../..`).
- **Resultado Global:** **58 passed, 5 warnings in 7.36s** (100% de la suite de backend pasando).

### Frontend (Vitest)
- **Suite de Pruebas:** [`FrontKenpaku/FrontKenpaku/src/pages/__tests__/Phase4.test.jsx`](file:///c:/Users/alexi/Desktop/Kenpaku/FrontKenpaku/FrontKenpaku/src/pages/__tests__/Phase4.test.jsx)
- **Casos probados:**
  - Renderizado de la tarjeta de flete con desglose y botones de acción.
  - Llamada a `submitFleteDecision` al hacer clic en aceptar.
  - Renderizado de cuentas bancarias y cambio entre pestañas (Yape, BCP, BBVA).
  - Selección de archivo y envío de voucher con llamada a `uploadOrderVoucher`.
  - Banner de comprobante registrado con enlace a visualización.
  - Visualización directa de las notas y condiciones de flete colocadas por el asesor comercial.
  - Ocultamiento de cuentas bancarias y formulario de carga una vez confirmado / en preparación.
- **Resultado Global:** **40 passed** en 10 suites de pruebas (100% pasando).
- **Build de Producción:** `npm run build` ejecutado exitosamente con Vite (código 0).

---

## 🎨 Mejoras de UX Operativas Incorporadas

1. **Lado del Cliente (`/seguimiento`):**
   - **Transición Dinámica del Stepper:** Al confirmarse el pedido tras el abono, la fase pasa visualmente a **"En Preparación"** (en lugar de permanecer en "Flete Cotizado").
   - **Ocultamiento de Datos Bancarios Post-Pago:** Una vez que caja valida el comprobante, las cuentas bancarias y el dropzone de subida se ocultan, mostrando en su lugar el banner de confirmación: *"Pago Validado por Caja — Pedido en Preparación"* con acceso a su comprobante verificado.
   - **Lectura de Condiciones de Flete:** Las especificaciones ingresadas por el administrador (tipo de camión, descarga a pie de obra, estiba) se muestran en una tarjeta destacada dentro de la cotización de flete.
   - **Línea de Tiempo Invertida (Último Estado Primero):** El historial de eventos ahora se muestra con el estado actual o más reciente al principio con insignia `Estado Actual`, fecha y hora completas, facilitando el seguimiento sin necesidad de scroll.

2. **Lado del Administrador (`/admin/orders`):**
   - **Alerta Visual de Pagos Pendientes:** Los pedidos con voucher subido pendiente de revisión se resaltan en la tabla con fondo esmeralda, borde verde lateral y una insignia animada: `💳 Verificar Pago`. El botón de acción cambia a *"Verificar Pago"*.
   - **Ruta de Fases Operativas (Pipeline Roadmap):** En el modal de detalle del pedido se despliega un mapa visual paso a paso (`Registrado` ➔ `Flete Cotizado` ➔ `En Preparación` ➔ `Despachado` ➔ `Entregado`), destacando las fases completadas, la fase actual y una tarjeta de sugerencia con el próximo paso a ejecutar.
   - **Línea de Tiempo Invertida (Último Estado Primero):** El historial en el modal muestra el evento más reciente en la parte superior con distintivo `Estado Actual` y fecha/hora exacta.

---

## ⚙️ Guía de Configuración Opcional (Supabase Storage)

El sistema almacena automáticamente los comprobantes de forma segura en `uploads/vouchers/`. Si deseas habilitar el almacenamiento en la nube de Supabase:

1. Ingresa a tu panel de **Supabase** (`https://app.supabase.com`).
2. Ve a **Storage** -> **New Bucket** -> Nombre: `vouchers` (público o con políticas de lectura).
3. Agrega en el `.env` del backend ([`BackKenpaku/BackKenpaku/.env`](file:///c:/Users/alexi/Desktop/Kenpaku/BackKenpaku/BackKenpaku/.env)):
   ```env
   SUPABASE_URL=https://avnrnxjmupkybrlzoqla.supabase.co
   SUPABASE_KEY=tu_supabase_anon_o_service_role_key
   SUPABASE_BUCKET_VOUCHERS=vouchers
   ```

---

## 📋 Resumen de Archivos Modificados / Creados

### Backend (`BackKenpaku`):
- `app/core/config.py` (Modificado)
- `app/services/storage_service.py` (Nuevo)
- `app/schemas/order.py` (Modificado)
- `app/services/notification_service.py` (Modificado)
- `app/routers/orders.py` (Modificado)
- `app/routers/admin.py` (Modificado)
- `app/tests/test_phase4.py` (Nuevo)

### Frontend (`FrontKenpaku`):
- `src/api/orders.js` (Modificado)
- `src/pages/TrackingPage.jsx` (Modificado)
- `src/pages/admin/Orders.jsx` (Modificado)
- `src/pages/__tests__/Phase4.test.jsx` (Nuevo)
