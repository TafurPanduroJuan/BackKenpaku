# Comercial Kenpaku S.A.C. - Backend E-Commerce & Asesor Virtual IA (RAG)

API RESTful desarrollada desde cero para **Comercial Kenpaku S.A.C.**, MYPE peruana ubicada en Puente Piedra (Lima) especializada en la venta de tubos, perfiles, fierros y planchas de acero.

---

## 🛠️ Stack Tecnológico
- **Lenguaje / Framework**: Python 3.11+ / FastAPI
- **Configuración y Validación**: Pydantic v2 & `pydantic-settings`
- **ORM & Migraciones**: SQLAlchemy 2.0 & Alembic
- **Base de Datos & Búsqueda Vectorial**: PostgreSQL + Extensión `pgvector` (Supabase)
- **IA & Embeddings**: OpenAI API (`gpt-4o-mini` y `text-embedding-3-small` de 1536 dimensiones)
- **Seguridad & Autenticación**: JWT (`python-jose` / `PyJWT`) con contraseñas encriptadas con `bcrypt`
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
│   └── tests/             # Suite de 28 pruebas automatizadas
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
- Al registrar un pedido (`POST /api/orders`), se exige `acepto_privacidad == true` (de lo contrario HTTP 422) y se valida la disponibilidad de stock. Si no alcanza, responde HTTP 409 Conflict.
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
| `DATABASE_URL` | Cadena de conexión PostgreSQL | `"postgresql://postgres:[PASS]@db.[REF].supabase.co:5432/postgres"` |
| `OPENAI_API_KEY` | Clave API de OpenAI | `"sk-proj-your-key"` |
| `JWT_SECRET` | Clave secreta para firma de JWT | `"super-secret-jwt-key-min-32-chars"` |
| `JWT_EXPIRE_MINUTES` | Expiración de token JWT (minutos) | `120` |
| `CORS_ORIGINS` | Orígenes permitidos (separados por coma) | `"https://kenpaku.vercel.app,http://localhost:3000"` |
| `WHATSAPP_NUMBER` | Número telefónico para derivación | `"51987654321"` |
| `STOCK_LOW_THRESHOLD` | Umbral para marca 'pocas_unidades' | `10` |
| `RAG_MAX_DISTANCE` | Umbral máximo de distancia coseno RAG | `0.5` |
| `ADMIN_EMAIL` | Correo del admin para el seed | `"admin@kenpaku.pe"` |
| `ADMIN_PASSWORD` | Contraseña del admin para el seed | `"AdminKenpaku2026!"` |

---

## ☁️ Despliegue en Render (Free / Starter)

Este repositorio incluye los archivos `render.yaml` y `Dockerfile` listos para el despliegue automático.

### Método 1: Mediante `render.yaml` (Recomendado)
1. Conecta tu repositorio de GitHub a tu cuenta de Render.
2. Crea un nuevo **Blueprint** en Render y selecciona este repositorio.
3. Render detectará automáticamente `render.yaml`, configurará el servicio web Python y aplicará las migraciones y el seed durante el proceso de build.
4. Ingresa las variables secretas (`DATABASE_URL`, `OPENAI_API_KEY`, `ADMIN_PASSWORD`) en el panel de Render.

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
