# DEPLOY_RENDER.md — Sofía Comercial AI en Render

Guía paso a paso para desplegar Sofía en Render con PostgreSQL.

## Arquitectura en Render

```
Render
├── Web Service: sofia-comercial (Python)
│   ├── FastAPI (panel web + /health)
│   └── Telegram Bot (hilo de fondo)
│
└── PostgreSQL: sofia-db
    └── Base de datos: sofia_comercial
```

## Paso 1: Preparar el repositorio

### Asegurar que estos archivos existen:
- `app/server.py` — App unificada (FastAPI + Telegram)
- `render.yaml` — Blueprint de Render
- `requirements.txt` — Dependencias actualizadas
- `.env.example` — Variables de entorno

### Variables de entorno requeridas:
| Variable | Descripción | Dónde obtener |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot | @BotFather en Telegram |
| `GROQ_API_KEY` | API key de Groq | https://console.groq.com |
| `DATABASE_URL` | URL PostgreSQL | Render la genera automáticamente |

## Paso 2: Crear cuenta en Render

1. Ir a https://render.com
2. Crear cuenta (gratis)
3. Conectar cuenta de GitHub

## Paso 3: Crear base de datos PostgreSQL

1. En Render Dashboard, click **New +** → **PostgreSQL**
2. Configurar:
   - **Name**: `sofia-db`
   - **Database**: `sofia_comercial`
   - **Plan**: Free
3. Click **Create Database**
4. **Copiar la Internal Database URL** (la necesitás después)

## Paso 4: Crear el servicio Web

### Opción A: Deploy manual (recomendado para primera vez)

1. En Render Dashboard, click **New +** → **Web Service**
2. Conectar repositorio de GitHub
3. Configurar:
   - **Name**: `sofia-comercial`
   - **Runtime**: Python
   - **Plan**: Free
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.server:app --host 0.0.0.0 --port $PORT`
4. En **Environment Variables**, agregar:
   - `TELEGRAM_BOT_TOKEN` = tu token
   - `GROQ_API_KEY` = tu API key
   - `AI_MODEL` = `llama-3.3-70b-versatile`
   - `DATABASE_URL` = (pegar la URL de la BD de Render)
   - `APP_ENV` = `production`
   - `APP_DEBUG` = `false`
   - `LOG_LEVEL` = `INFO`
5. Click **Create Web Service**

### Opción B: Blueprint (automático)

1. En Render Dashboard, click **New +** → **Blueprint**
2. Conectar repositorio de GitHub
3. Render detecta `render.yaml` automáticamente
4. Configurar variables secretas en Dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `GROQ_API_KEY`
5. Click **Apply**

## Paso 5: Verificar el deploy

1. Esperar a que el build termine (~2-3 minutos)
2. Render asigna una URL: `https://sofia-comercial.onrender.com`
3. Probar:
   - `https://sofia-comercial.onrender.com/health` → `{"status": "ok", "service": "sofia"}`
   - `https://sofia-comercial.onrender.com/` → Panel web
4. Enviar `/start` al bot en Telegram

## Paso 6: Configurar el bot en Telegram

1. Abrir Telegram
2. Buscar tu bot
3. Enviar `/start`
4. Verificar que responda

## Troubleshooting

### El bot no responde en Telegram

1. Verificar logs en Render Dashboard → Logs
2. Buscar errores de `TELEGRAM_BOT_TOKEN`
3. Verificar que el token sea correcto

### Error de conexión a PostgreSQL

1. Verificar que `DATABASE_URL` sea correcta
2. Verificar que la BD `sofia-db` esté corriendo
3. Las tablas se crean automáticamente al iniciar

### Build falla

1. Verificar que `requirements.txt` tenga todas las dependencias
2. Buscar errores en los logs de build de Render
3. Verificar la versión de Python (3.12)

### El servicio se cae

1. Render free tier tiene limitaciones (15 min idle)
2. El health check en `/health` mantiene el servicio vivo
3. Verificar logs para errores de memoria

### Render free tier: servicio se duerme

El free tier de Render apaga servicios después de 15 min sin tráfico. Soluciones:
1. Usar un servicio externo que haga ping cada 10 min
2. Upgrade a un plan pago
3. Configurar un cron job externo:
```bash
# Ping cada 10 minutos
curl https://sofia-comercial.onrender.com/health
```

## Variables de entorno completas

| Variable | Valor | Secreta |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | tu_token | **Sí** |
| `GROQ_API_KEY` | tu_api_key | **Sí** |
| `AI_MODEL` | llama-3.3-70b-versatile | No |
| `DATABASE_URL` | postgresql://... | **Sí** |
| `APP_ENV` | production | No |
| `APP_DEBUG` | false | No |
| `LOG_LEVEL` | INFO | No |
| `PORT` | (asignado por Render) | No |

## Comandos útiles

```bash
# Ver logs en tiempo real (CLI de Render)
render logs --service sofia-comercial

# Deploy manual
render deploy --service sofia-comercial

# Verificar estado
render services list
```

## Migración de datos

Si tenés datos en SQLite que querés migrar:

```bash
# 1. Exportar de SQLite
sqlite3 health_advisor.db .dump > dump.sql

# 2. Importar a PostgreSQL
psql "postgresql://user:pass@host/sofia_comercial" < dump.sql
```
