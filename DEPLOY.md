# DEPLOY.md — Sofía Comercial AI

Guía completa de instalación, configuración y ejecución.

## Requisitos

- Python 3.11+ (o Docker)
- Token de Telegram (@BotFather)
- API key de Groq (https://console.groq.com)

## Instalación local

### 1. Clonar el repositorio

```bash
git clone https://github.com/Carlosdiaz83/Bot_Telegram.git
cd Bot_Telegram
```

### 2. Crear entorno virtual

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno

```bash
cp .env.example .env
```

Editar `.env` con tus valores reales:

```ini
TELEGRAM_BOT_TOKEN=tu_token_aqui
GROQ_API_KEY=tu_api_key_aqui
DATABASE_URL=sqlite:///./health_advisor.db
APP_ENV=development
APP_DEBUG=true
LOG_LEVEL=INFO
```

### 5. Ejecutar

```bash
python -m app.main
```

El bot iniciará y comenzará a recibir mensajes en Telegram.

### 6. Panel web (opcional)

```bash
python -m app.panel.app
```

Abrir http://localhost:8000 en el navegador.

## Instalación con Docker

### 1. Clonar y configurar

```bash
git clone https://github.com/Carlosdiaz83/Bot_Telegram.git
cd Bot_Telegram
cp .env.example .env
```

Editar `.env` con tus valores.

### 2. Construir y ejecutar

```bash
# Construir imagen
docker compose build

# Ejecutar en segundo plano
docker compose up -d

# Ver logs
docker compose logs -f sofia-bot

# Detener
docker compose down
```

### 3. Verificar

```bash
# Estado del contenedor
docker compose ps

# Logs recientes
docker compose logs --tail=20 sofia-bot
```

## Variables de entorno

| Variable | Requerida | Default | Descripción |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **Sí** | - | Token de @BotFather |
| `GROQ_API_KEY` | No | `""` | API key de Groq |
| `AI_MODEL` | No | `llama-3.3-70b-versatile` | Modelo de LLM |
| `DATABASE_URL` | No | `sqlite:///./health_advisor.db` | URL de base de datos |
| `APP_ENV` | No | `development` | `development` o `production` |
| `APP_DEBUG` | No | `false` | Logging detallado |
| `LOG_LEVEL` | No | `INFO` | Nivel de logging |

## Estructura de datos

```
Bot_Telegram/
├── data/                   # Base de datos SQLite (Docker)
│   └── health_advisor.db
├── logs/                   # Archivos de log
│   └── health_advisor.log
├── app/
│   ├── knowledge/servired/ # Base de conocimiento
│   └── ...
└── .env                    # Variables de entorno (no commitear)
```

## Troubleshooting

### El bot no inicia

```
Error de configuración: TELEGRAM_BOT_TOKEN no está definido.
```

**Solución:** Verificar que `.env` exista y tenga el token correcto.

### Error de conexión a Telegram

```
telegram.error.TimedOut
```

**Solución:** Verificar conexión a internet. El bot reconecta automáticamente.

### Error de base de datos

```
sqlalchemy.exc.OperationalError
```

**Solución:** Verificar que `DATABASE_URL` sea correcta. Para SQLite, verificar que el directorio exista.

### Error de Groq API

```
groq.APIError
```

**Solución:** Verificar `GROQ_API_KEY` en https://console.groq.com.

### Docker: permisos de volumen

```bash
# Linux: verificar permisos
sudo chown -R $USER:$USER ./data ./logs
```

### Docker: contenedor se reinicia

```bash
# Ver logs del contenedor
docker compose logs sofia-bot

# Verificar estado
docker compose ps
```

## Comandos útiles

```bash
# Desarrollo: ejecutar con logs detallados
APP_DEBUG=true LOG_LEVEL=DEBUG python -m app.main

# Producción: ejecutar con Docker
docker compose --env-file .env up -d

# Ver logs en tiempo real
docker compose logs -f

# Reiniciar después de cambios
docker compose restart

# Rebuild después de cambios en código
docker compose up -d --build

# Ejecutar tests
python -m pytest tests/ -v

# Backup de base de datos
cp health_advisor.db backups/backup_$(date +%Y%m%d).db
```

## Seguridad

- **NUNCA** commitear `.env` al repositorio
- **NUNCA** exponer tokens o API keys
- Usar `.env.example` como plantilla
- En producción: usar variables de entorno del sistema o Docker secrets
- Rotar tokens periódicamente
