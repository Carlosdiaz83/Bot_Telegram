# 🤖 Sofía Comercial AI

Asistente comercial inteligente para ventas SERVIRED en Telegram.

## Descripción

Sofía es un asistente comercial basado en inteligencia artificial que conversa con potenciales clientes, entiende sus necesidades, presenta valor, maneja objeciones y acompaña el proceso de contratación de SERVIRED (obra social/prepaga).

### ¿Qué es SERVIRED?

SERVIRED es una obra social/prepaga que ofrece cobertura de salud para:

- Titulares
- Cónyuges/parejas
- Hijos menores

## Funcionalidades

### 🤖 Asistente Conversacional

- Bot de Telegram con respuestas naturales
- Personalidad de asesora comercial (voseo argentino)
- Manejo de conversaciones多-turno
- Memoria de conversaciones anteriores

### 📋 Lead Qualification

- Calificación automática de prospectos
- Extracción de datos del cliente (nombre, edad, localidad, etc.)
- Detección de necesidades principales
- Clasificación de prioridades (económico, cobertura, calidad)

### 📊 Lead Scoring

- Sistema de puntuación automático (0-100)
- Clasificación de temperatura: frío, tibio, caliente
- Bonus por datos completos y etapas avanzadas
- Persistencia en base de datos

### 🏢 SERVIRED Rules

- Validación de perfiles (titular, cónyuge, hijos)
- Detección de casos especiales (empresas, monotributistas)
- Reglas de cobertura y aportes

### 📚 Knowledge Base Comercial

- Beneficios de SERVIRED por perfil de cliente
- Preguntas frecuentes (FAQ)
- Manejo de objeciones comunes
- Argumentos de venta personalizados
- Estrategias de cierre

### 💼 Sales Strategy

- Generación de argumentos según perfil
- Personalización por necesidad y prioridad
- Manejo de objeciones (precio, tiempo, confianza)

### ✅ Closing Strategy

- Técnicas de cierre directo e indirecto
- Interpretación de respuestas
- Próximos pasos claros

### 🗄️ Persistencia de Leads

- SQLite (preparado para PostgreSQL)
- Historial completo de conversaciones
- Estados comerciales (11 valores)
- Timestamps de creación y actualización

### 🖥️ Panel Web Comercial

- Dashboard con estadísticas
- Lista de leads con filtros
- Detalle de lead con historial
- Acciones comerciales (cambiar estado)

## Arquitectura

```
Cliente Telegram
       ↓
   Sofía IA (Groq)
       ↓
Conversation Manager
       ↓
Lead Qualifier
       ↓
Sales Strategy
       ↓
Knowledge Servired
       ↓
    Database (SQLite)
```

### Estructura del Proyecto

```
Bot_Telegram/
├── app/
│   ├── ai/                → Integración con Groq (llama-3.3-70b-versatile)
│   ├── config/            → Configuración centralizada (.env, settings)
│   ├── crm/               → Gestión de usuarios y seguimiento
│   ├── database/          → ORM SQLAlchemy, repositorios, migraciones
│   ├── knowledge/         → Base de conocimiento estructurada
│   │   └── servired/      → Docs: beneficios, FAQ, objeciones, cierres
│   ├── models/            → Entidades de dominio (Lead, enums)
│   ├── panel/             → Panel web FastAPI
│   ├── prompts/           → Templates de prompts para IA
│   ├── services/          → Lógica de negocio
│   │   ├── conversation_manager.py  → Orquestador principal
│   │   ├── lead_qualifier.py        → Calificación de leads
│   │   ├── lead_scoring.py          → Scoring y temperatura
│   │   ├── sales_strategy.py        → Argumentos de venta
│   │   ├── objection_handler.py     → Manejo de objeciones
│   │   ├── closing_strategy.py      → Técnicas de cierre
│   │   ├── session_manager.py       → Sesiones de usuario
│   │   └── knowledge_service.py     → Servicio de knowledge base
│   ├── telegram/          → Bot y handlers de Telegram
│   └── main.py            → Entry point
├── docs/                  → Documentación
├── tests/                 → Suite de tests (133 tests)
└── requirements.txt
```

## Stack

| Capa | Tecnología |
|------|-----------|
| Bot | python-telegram-bot v22 |
| IA | Groq API (llama-3.3-70b-versatile) + OpenAI |
| DB | SQLAlchemy + SQLite (dev) / PostgreSQL (prod) |
| Validación | Pydantic v2 |
| Panel Web | FastAPI + Jinja2 |
| Arquitectura | Clean Architecture + SOLID |

## Instalación

```bash
# Clonar
git clone https://github.com/Carlosdiaz83/Bot_Telegram.git
cd Bot_Telegram

# Entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# Dependencias
pip install -r requirements.txt

# Configurar entorno
copy .env.example .env        # Windows
# cp .env.example .env        # Linux/Mac
# Completar variables en .env:
#   TELEGRAM_BOT_TOKEN
#   GROQ_API_KEY
#   OPENAI_API_KEY (opcional)
```

## Ejecución

```bash
# Bot de Telegram
python -m app.main

# Panel Web
python -m app.panel.app
# Abrir http://127.0.0.1:8000
```

## Tests

```bash
pytest -v
```

**133 tests** cubriendo:
- Lead Qualifier
- Lead Scoring
- Sales Strategy
- Objection Handler
- Closing Strategy
- Knowledge Base
- AI Integration
- Panel Web
- Persistencia

## Flujo de Conversación

```
1. Cliente escribe → Sofia detecta necesidad
2. Calificación → Nombre, edad, localidad, tipo afiliación
3. Lead Scoring → Score + temperatura
4. Presentación valor → Beneficios personalizados
5. Manejo objeciones → Respuestas knowledge base
6. Cierre → Técnica según perfil
7. Estado → VENDIDO/PERDIDO/SEGUIMIENTO
```

## Estados Comerciales

```
NUEVO → CONTACTADO → CALIFICANDO → INTERESADO → OBJECION →
INTENTANDO_CIERRE → VENDIDO / PERDIDO / SEGUIMIENTO
```

## Licencia

MIT
