# Comercial Kenpaku S.A.C. - Backend E-Commerce & Asesor Virtual IA (RAG)

API RESTful desarrollada desde cero para **Comercial Kenpaku S.A.C.**, MYPE peruana ubicada en Puente Piedra (Lima) especializada en la venta de tubos, perfiles, fierros y planchas de acero.

---

## 🛠️ Stack Tecnológico
- **Lenguaje / Framework**: Python 3.11+ / FastAPI
- **Configuración y Validación**: Pydantic v2 & `pydantic-settings`
- **ORM & Migraciones**: SQLAlchemy 2.0 & Alembic
- **Base de Datos & Búsqueda Vectorial**: PostgreSQL + Extensión `pgvector` (Supabase)
- **IA & Embeddings**: Google Gemini API (`gemini-2.5-flash` y `gemini-embedding-001`)
- **Seguridad & Autenticación**: JWT (`python-jose` / `PyJWT`) con contraseñas encriptadas con `bcrypt`
- **Notificaciones**: Brevo (correo al cliente) y Bot de Telegram (alertas al dueño)
- **Comprobantes de pago**: Supabase Storage (con almacenamiento local de respaldo)
- **Tareas programadas**: GitHub Actions (cron externo, cada hora)
- **Pruebas Unitarias & Linting**: `pytest` + `httpx`, `ruff`
- **Despliegue**: Dockerfile & `render.yaml` (Render Free/Starter)

---

## 📁 Estructura del Proyecto

```
kenpaku-backend/
├── app/
│   ├── main.py            # Inicialización FastAPI, CORS, rutas y manejador global de errores
│   ├── core/              # Configuración (pydantic-settings), seguridad JWT y rate limit
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── rate_limit.py
│   │   └── prompts.py
│   ├── db/                # Sesiones, modelos ORM de SQLAlchemy 2.0 y base declarativa
│   │   ├── session.py
│   │   ├── base.py
│   │   └── models.py
│   ├── schemas/           # Esquemas Pydantic v2 (product, order, chat, claim, auth, admin)
│   ├── routers/           # Endpoints HTTP (/api/health, products, categories, orders, chat, claims, auth, admin)
│   ├── services/          # Lógica de negocio (RAG, LLM, anonimizador, WhatsApp, ordenes, embeddings)
│   └── tests/             # Suite de 81 pruebas automatizadas
├── alembic/               # Migraciones de base de datos PostgreSQL/pgvector
│   ├── env.py
│   └── versions/001_initial.py
├── scripts/
│   └── seed.py            # Carga inicial idempotente de productos de acero, fichas y admin
├── .env.example           # Plantilla de variables de entorno
├── requirements.txt       # Lista de dependencias de Python
├── Dockerfile             # Contenedor optimizado para producción
├── render.yaml            # Configuración para despliegue automático en Render
└── README.md              # Guía completa de uso y arquitectura
```

---

## 📋 Reglas de Negocio y Cumplimiento Normativo

### 1. Precios y Moneda (PEN con IGV 18%)
- Todos los precios están registrados en Soles Peruanos (PEN) con el 18% de IGV incluido.
- Los montos se recálculan **siempre en el servidor** consumiendo los datos oficiales de la base de datos (los precios enviados por el cliente se ignoran estrictamente).
- Fórmula en `Decimal` (`ROUND_HALF_UP`):
  $$\text{subtotal} = \text{round}\left(\frac{\text{total}}{1.18}, 2\right)$$
  $$\text{igv} = \text{round}(\text{total} - \text{subtotal}, 2)$$

### 2. Gestión de Stock en Pedidos
- Al registrar un pedido (`POST /api/orders`) se exige `acepto_privacidad == true` (de lo contrario HTTP 422) y se valida el stock disponible menos el reservado. Si no alcanza, responde HTTP 409.
- **Reserva de stock**: el pedido nace en `pendiente` y reserva el stock por 48 horas (`stock_reservado`).
- **Confirmación**: al validar el voucher (estado `confirmado`) se descuenta el stock físico y se libera la reserva.
- **Cancelación**: desde `pendiente` o `flete_cotizado` solo libera la reserva; desde `confirmado` devuelve el stock al inventario.
- **Estados terminales**: `entregado` y `cancelado` no admiten cambios.

### 2.1 Flujo de estados
- **Despacho**: `pendiente` → `flete_cotizado` → `confirmado` → `despachado` → `entregado`
- **Recojo en tienda**: `pendiente` → `confirmado` → `listo_para_recojo` → `entregado`
- `cancelado` puede ocurrir en cualquier punto antes de `entregado`.
- Todo cambio de estado pasa por `transition_order_status`, que registra el historial (`order_events`) y dispara los avisos.

### 2.2 Automatización (cron)
- `POST /api/cron/process-scheduled-tasks` (protegido con `X-Cron-Secret`) corre cada hora desde GitHub Actions.
- A las 24 h sin respuesta envía un recordatorio por correo (una sola vez por pedido).
- A las 48 h sin confirmar cancela el pedido, libera el stock y avisa al cliente y al dueño.
- Cada ejecución hace un `SELECT 1` para evitar que Supabase pause el proyecto.

### 2.3 Panel del administrador
- `GET /api/admin/action-required`: flete por cotizar, vouchers por validar, pedidos por vencer y reclamos pendientes.
- `GET /api/admin/orders?estado=...&q=...`: filtro por estado y búsqueda por código o teléfono.

### 2.4 Validación de entradas
- Nombre: solo letras, espacios, puntos, guiones y apóstrofes.
- Teléfono: celular peruano de 9 dígitos que empiece con 9 (se normaliza quitando espacios, guiones y prefijo +51).
- Documento del reclamo: 8 a 12 caracteres alfanuméricos.
- Límites de longitud en dirección, observaciones y textos del reclamo.
- **Decisión de Arquitectura**: El pedido se crea inicialmente en estado `pendiente` y **NO descuenta stock de inmediato**. El descuento de stock se ejecuta únicamente cuando el Administrador pasa el estado del pedido a `confirmado`. Si el pedido confirmado es posteriormente `cancelado`, el stock se restituye automáticamente a la base de datos.

### 3. Asesor Virtual de IA (RAG)
- **Embeddings Vectoriales (1536 dims)**: Generados a partir del texto concatenado: `nombre + categoría + acabado + medida + espesor + ficha_tecnica`. **No incluye precio ni stock** (debido a su variabilidad).
- **Lectura en Tiempo Real**: Precio y stock se leen directamente de PostgreSQL en tiempo real al construir las tarjetas de respuesta.
- **Regla de Derivación (Handoff)**: Si la búsqueda por distancia coseno de `pgvector` no encuentra productos por debajo del umbral de distancia (`RAG_MAX_DISTANCE`), **NO se llama a la API del LLM**; la API responde inmediatamente con `handoff: true` y una URL prellenada a WhatsApp para atención humana.
- **Ley 29733 (Protección de Datos)**: Todo mensaje de usuario es procesado por `anonymizer.py` reemplazando DNI, RUC, teléfonos, correos y direcciones por marcadores `[DNI]`, `[RUC]`, `[TEL]`, `[EMAIL]`, `[DIRECCION]` antes de guardarse en `chat_logs`.
- **Ley 31814 (Uso de IA)**: Toda respuesta del chat incluye la marca explícita `generated_by_ai: true`.

---

## ⚡ Instalación y Ejecución Local

1. **Clonar e ingresar al proyecto**:
   ```bash
   git clone <URL_DEL_REPOSITORIO>
   cd kenpaku-backend
   ```

2. **Crear entorno virtual e instalar dependencias**:
   ```bash
   python -m venv venv
   # En Windows:
   venv\Scripts\activate
   # En Linux/macOS:
   source venv/bin/activate

   pip install -r requirements.txt
   ```

3. **Configurar variables de entorno**:
   ```bash
   cp .env.example .env
   ```
   Edita `.env` con tus credenciales (Supabase PostgreSQL, OpenAI API Key, JWT Secret).

4. **Ejecutar migraciones y semillado**:
   ```bash
   alembic upgrade head
   python scripts/seed.py
   ```

5. **Iniciar el servidor local**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   Documentación interactiva disponible en: `http://localhost:8000/docs`

6. **Ejecutar Pruebas Automatizadas**:
   ```bash
   python -m pytest
   ```

---

## ⚙️ Variables de Entorno (`.env`)

| Variable | Descripción | Valor por Defecto / Ejemplo |
| :--- | :--- | :--- |
| `PROJECT_NAME` | Nombre del proyecto API | `"Comercial Kenpaku S.A.C. API"` |
| `ENV` | Entorno de ejecución | `"development"` |
| `DATABASE_URL` | Cadena de conexión PostgreSQL (Supabase) | `"postgresql://postgres:[PASS]@db.[REF].supabase.co:5432/postgres"` |
| `GEMINI_API_KEY` | Clave de la API de Gemini | `""` |
| `GEMINI_MODEL` | Modelo de chat | `"gemini-2.5-flash"` |
| `GEMINI_EMBEDDING_MODEL` | Modelo de embeddings | `"gemini-embedding-001"` |
| `JWT_SECRET` | Clave secreta para firma de JWT | Generar una propia (mín. 32 caracteres) |
| `JWT_EXPIRE_MINUTES` | Expiración del token JWT (minutos) | `120` |
| `CORS_ORIGINS` | Orígenes permitidos (separados por coma) | `"https://front-kenpaku.vercel.app,http://localhost:5173"` |
| `FRONTEND_URL` | URL del frontend para enlaces de seguimiento | `"http://localhost:5173"` |
| `WHATSAPP_NUMBER` | Número para derivación | `"51987654321"` |
| `STOCK_LOW_THRESHOLD` | Umbral de 'pocas_unidades' | `10` |
| `RAG_MAX_DISTANCE` | Umbral máximo de distancia coseno | `0.5` |
| `BREVO_API_KEY` | Clave de Brevo para correos | `""` |
| `SENDER_EMAIL` / `SENDER_NAME` | Remitente verificado en Brevo | `"ventas@kenpaku.pe"` |
| `TELEGRAM_BOT_TOKEN` | Token del bot de alertas | `""` |
| `TELEGRAM_CHAT_ID` | Chat o grupo que recibe las alertas | `""` |
| `SUPABASE_URL` / `SUPABASE_KEY` | Acceso a Supabase Storage | `""` |
| `SUPABASE_BUCKET_VOUCHERS` | Bucket privado de vouchers | `"vouchers"` |
| `CRON_SECRET` | Secreto del endpoint de cron | Generar uno propio |
| `CRON_REMINDER_HOURS` / `CRON_EXPIRATION_HOURS` | Horas para recordatorio y vencimiento | `24` / `48` |
| `ADMIN_EMAIL` | Correo del admin para el seed | `"admin@kenpaku.pe"` |
| `ADMIN_PASSWORD` | Contraseña del admin para el seed | Definir una propia, no reutilizar |

> Todas las claves van solo en `.env` (local) y en las variables de entorno de Render y Vercel. Nunca en el código.

---

## ☁️ Despliegue en Render (Free / Starter)

Este repositorio incluye los archivos `render.yaml` y `Dockerfile` listos para el despliegue automático.

### Método 1: Mediante `render.yaml` (Recomendado)
1. Conecta tu repositorio de GitHub a tu cuenta de Render.
2. Crea un nuevo **Blueprint** en Render y selecciona este repositorio.
3. Render detectará automáticamente `render.yaml`, configurará el servicio web Python y aplicará las migraciones y el seed durante el proceso de build.
4. Ingresa las variables secretas (`DATABASE_URL`, `GEMINI_API_KEY`, `ADMIN_PASSWORD`, `BREVO_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SUPABASE_URL`, `SUPABASE_KEY`, `CRON_SECRET`) en el panel de Render.

### Método 2: Mediante Dockerfile
1. Crea un nuevo **Web Service** en Render seleccionando el entorno **Docker**.
2. Render compilará la imagen de Docker utilizando el `Dockerfile` optimizado.

---

## ❄️ Nota sobre el Cold Start de Render (Free Tier) y Ping de Mantenimiento

> [!IMPORTANT]
> En el plan gratuito (Free Tier) de Render, el servidor entra en suspensión (sleep) después de **15 minutos de inactividad**. La primera solicitud posterior sufrirá un retraso de inicialización de aproximadamente **50 segundos (Cold Start)**.

### Solución recomendada para mantener el servicio activo (24/7):
Utiliza un servicio gratuito de monitoreo cron (como [UptimeRobot](https://uptimerobot.com) o [Cron-Job.org](https://cron-job.org)) configurado para realizar un **HTTP GET** cada **14 minutos** hacia el endpoint público de salud:

```http
GET https://tu-app-kenpaku.onrender.com/api/health
```

Esto evitará que Render suspenda la instancia, garantizando respuestas instantáneas al usuario final y al frontend en React.

---

## 💸 Servicios gratuitos utilizados

| Necesidad | Servicio | Límite a considerar |
| :--- | :--- | :--- |
| Frontend | Vercel | Plan personal |
| Backend | Render (free) | Se duerme tras 15 min sin tráfico |
| Base de datos y vouchers | Supabase | Pausa tras 7 días sin actividad |
| Correo al cliente | Brevo | 300 correos/día |
| Alertas al dueño | Bot de Telegram | Sin límite práctico |
| Tareas programadas | GitHub Actions | Ejecución aproximada cada hora |
| Asesor virtual | Gemini API | Límites por minuto y por día |

Los límites pueden cambiar: confirmar siempre en la página oficial de cada servicio.