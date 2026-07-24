# 🩺 Health Advisor AI

Asesor virtual inteligente de salud y nutrición para Telegram.

## Descripción

Un bot de Telegram que actúa como asesor personal de salud, ofreciendo:

- **Análisis nutricional** de alimentos e imágenes
- **Calculadoras** de IMC, TMB y macronutrientes
- **Recomendaciones** personalizadas según perfil del usuario
- **OCR** para etiquetas nutricionales y recetas médicas
- **Seguimiento** de hábitos y progreso del usuario

## Lead Qualifier (Sprint 3)

### ¿Qué es?

El **Lead Qualifier** es un sistema de calificación comercial que evalúa prospectos de clientes interesados en obras sociales/prepagas. Recolecta información estructurada del cliente a través de una conversación y determina cuándo está listo para ser derivado a un asesor humano.

### ¿Cómo funciona?

1. **Clasificación de intención**: Analiza el primer mensaje para detectar el interés (precio, cobertura, cambio, monotributo, empresa).
2. **Recolección de datos**: Pregunta secuencialmente por nombre, situación laboral, aportes, grupo familiar, localidad y edad.
3. **Actualización del perfil**: Cada respuesta actualiza el modelo `Lead` con los datos extraídos.
4. **Detección de listo**: Cuando tiene la información mínima necesaria, marca el lead como `CALIFICADO` y listo para derivar.

### Uso futuro con IA

El LeadQualifierService **no genera texto directamente**. Devuelve estados estructurados que la IA (futuro Sprint) interpretará para generar respuestas naturales al cliente.

```
Entrada IA:  "Quiero precios para mi familia"
Salida IA:   LeadQualifierService.process_message(lead, mensaje)
             → QualificationResult(estado=CALIFICANDO, proxima_pregunta="nombre")
             → IA genera: "¡Perfecto! ¿Cómo te llamás?"
```

### Flujo de calificación

```
Cliente dice intención → Detectar interés → Preguntar nombre
→ Preguntar tipo afiliación → Preguntar aportes → Preguntar grupo familiar
→ Calcular integrantes → Preguntar localidad → Preguntar edad
→ Marcar CALIFICADO → Derivar a asesor
```

### Ejemplo de flujo completo

| Paso | Mensaje del cliente | Datos extraídos | Siguiente pregunta |
|------|--------------------|-----------------|--------------------|
| 1 | "Quiero precios para mi familia" | interes: precio | nombre |
| 2 | "Me llamo Ana" | nombre: Ana | tipo_afiliacion |
| 3 | "Soy monotributista" | tipo: monotributo | grupo_familiar |
| 4 | "Mi esposa y 2 hijos" | conyuge: true, hijos: 2 | — (LISTO) |

### Archivos del módulo

| Archivo | Descripción |
|---------|-------------|
| `app/models/lead.py` | Modelo de dominio `Lead` con enums y GrupoFamiliar |
| `app/services/lead_qualifier.py` | Servicio de calificación con extracción de datos |
| `tests/test_lead_qualifier.py` | Tests unitarios de los 4 casos solicitados |

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
│   │   └── lead_qualifier.py  → Calificación comercial de leads
│   ├── models/        → Entidades de dominio (dataclasses/Pydantic)
│   │   └── lead.py            → Modelo Lead y enums comerciales
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
| Bot | python-telegram-bot v22 |
| IA | OpenAI API / LangChain (próximo) |
| DB | SQLAlchemy + SQLite (dev) / PostgreSQL (prod) |
| Validación | Pydantic v2 |
| OCR | Tesseract (próximo) |

## Requisitos

- Python 3.11+
- Token de bot de Telegram ([@BotFather](https://t.me/BotFather))
- API Key de OpenAI (próximo)

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
# Completar TELEGRAM_BOT_TOKEN en .env
```

## Ejecución

```bash
python -m app.main
```

## Tests

```bash
pytest -v
```

## Licencia

MIT
