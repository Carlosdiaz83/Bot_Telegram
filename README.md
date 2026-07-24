# 🩺 Health Advisor AI

Asesor virtual inteligente de salud y nutrición para Telegram.

## Descripción

Un bot de Telegram que actúa como asesor personal de salud, ofreciendo:

- **Análisis nutricional** de alimentos e imágenes
- **Calculadoras** de IMC, TMB y macronutrientes
- **Recomendaciones** personalizadas según perfil del usuario
- **OCR** para etiquetas nutricionales y recetas médicas
- **Seguimiento** de hábitos y progreso del usuario

## Arquitectura

El proyecto sigue **Clean Architecture** y principios **SOLID**:

```
Bot_Telegram/
├── app/
│   ├── ai/            → Integración con modelos de LLM
│   ├── telegram/      → Handlers y conexión con Telegram API
│   ├── knowledge/     → Base de conocimiento estructurada
│   ├── calculator/    → Calculadoras nutricionales (IMC, TMB, macros)
│   ├── ocr/           → Reconocimiento de imágenes (etiquetas, recetas)
│   ├── crm/           → Gestión de usuarios y seguimiento
│   ├── config/        → Configuración centralizada (.env, settings)
│   ├── database/      → Persistencia: ORM, migraciones, repositorios
│   ├── services/      → Orquestación de lógica de negocio
│   ├── models/        → Entidades de dominio (dataclasses/Pydantic)
│   ├── prompts/       → Templates de prompts para IA
│   ├── utils/         → Helpers: fechas, validación, formato
│   └── main.py        → Entry point
├── docs/              → Documentación del proyecto
├── tests/             → Suite de tests unitarios y de integración
├── logs/              → Logs de ejecución (gitignored)
└── scripts/           → Scripts utilitarios (migraciones, seeds, etc.)
```

## Stack

| Capa | Tecnología |
|------|-----------|
| Bot | python-telegram-bot |
| IA | OpenAI API / LangChain |
| DB | SQLAlchemy + SQLite (dev) / PostgreSQL (prod) |
| Validación | Pydantic v2 |
| OCR | Tesseract |

## Requisitos

- Python 3.11+
- Token de bot de Telegram ([@BotFather](https://t.me/BotFather))
- API Key de OpenAI

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
# Completar TELEGRAM_BOT_TOKEN y OPENAI_API_KEY en .env
```

## Ejecución

```bash
python -m app.main
```

## Licencia

MIT
