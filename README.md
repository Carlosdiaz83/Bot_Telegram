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

**168 tests** cubriendo:
- Lead Qualifier
- Lead Scoring
- Sales Strategy
- Objection Handler
- Closing Strategy
- Knowledge Base
- AI Integration
- Panel Web
- Persistencia
- Simulador de Clientes
- Evaluador Comercial
- Training Engine
- Sales Report
- Quality Rules

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

## Entrenamiento Comercial

Sofía cuenta con un laboratorio de entrenamiento para evaluar y mejorar su capacidad comercial antes de producción.

### Simulador de Clientes

8 perfiles predefinidos que simulan diferentes tipos de clientes:

| Perfil | Comportamiento |
|---|---|
| `cliente_frio` | Respuestas cortas, no da datos |
| `cliente_busca_precio` | Busca lo más barato |
| `cliente_busca_cobertura_familiar` | Esposa + hijos |
| `cliente_monotributista` | Monotributista buscando opciones |
| `cliente_relacion_dependencia` | Empleado con recibo de sueldo |
| `cliente_objecion_precio` | Acepta pero objeta por precio |
| `cliente_indeciso` | Nunca se decide |
| `cliente_listo_para_contratar` | Da todo y acepta avanzar |

### Evaluador Comercial

5 dimensiones de evaluación (0-20 cada una = 0-100 total):

- **Descubrimiento**: ¿detectó necesidades?
- **Calificación**: ¿obtuvo datos importantes?
- **Valor**: ¿explicó beneficios?
- **Objeciones**: ¿respondió correctamente?
- **Cierre**: ¿intentó avanzar?

### Training Engine

```python
from app.training import TrainingEngine

trainer = TrainingEngine()

# Ejecutar un perfil
resultado = trainer.ejecutar("cliente_busca_precio")
print(resultado.score_final)
print(resultado.errores)
print(resultado.recomendaciones)

# Ejecutar todos los perfiles
resultados = trainer.ejecutar_todos()

# Generar reporte
from app.services.sales_report import SalesReportService
reporte_svc = SalesReportService()
reporte = reporte_svc.generar_reporte(resultados)
print(reporte_svc.generar_texto(reporte))
```

### Detección de Errores

El sistema detecta errores comerciales automáticamente:

| Error | Gravedad | Descripción |
|---|---|---|
| `cotizacion_sin_diagnostico` | alta | Cotiza sin diagnosticar necesidades |
| `falta_avance` | alta | No avanza cuando hay interés |
| `descuento_inmediato` | alta | Ofrece descuento sin investigar valor |
| `sin_personalizacion` | media | Respuestas genéricas |
| `cierre_prematuro` | media | Cierra antes de calificar |

### Reglas de Calidad

Basadas en el método de venta consultivo:

1. **Antes de ofrecer**: nombre, grupo familiar, edades, localidad, situación laboral, aportes, necesidad
2. **En propuesta**: explicar valor, personalizar, no vender solo precio
3. **En objeciones**: validar, preguntar motivo real, resolver
4. **En cierre**: detectar intención, pedir avance, solicitar documentación

### Evolución Comercial

Cada entrenamiento se guarda automáticamente en SQLite (si se proporciona `database_url`), permitiendo analizar la mejora continua de Sofía:

```python
# Entrenamiento con persistencia
trainer = TrainingEngine(database_url="sqlite:///data/training.db")
resultado = trainer.ejecutar("cliente_busca_precio")

# Analizar evolución
from app.services.commercial_evolution_service import CommercialEvolutionService
evo_svc = CommercialEvolutionService(db_session)

# Evolución general
evolucion = evo_svc.obtener_evolucion()
print(f"Mejora: {evolucion.mejora:+d} puntos")
print(f"Debilidades: {evolucion.debilidades_principales}")
print(f"Fortalezas: {evolucion.fortalezas}")

# Métricas consolidadas
metricas = evo_svc.obtener_metricas()
print(f"Score promedio: {metricas.score_promedio}")
print(f"Errores frecuentes: {metricas.errores_frecuentes}")
```

El sistema analiza:
- **Evolución**: diferencia entre primer y último entrenamiento
- **Debilidades**: dimensiones con score promedio < 10
- **Fortalezas**: dimensiones con score promedio >= 15
- **Errores frecuentes**: tipos de error más repetidos
- **Evolución por dimensión**: tendencia temporal de cada área

## Licencia

MIT

## Cómo actualizar precios SERVIRED

El bot carga precios automáticamente desde un archivo Excel al deploy en Render. Para actualizar:

1. Colocá el nuevo archivo `.xls` o `.xlsx` en `servired_knowledge/precios/`
2. Si el nombre cambió, actualizá el `preDeployCommand` en `render.yaml`
3. Hacé push a GitHub — Render ejecutará el importador automáticamente

### Uso local

```bash
# Importar precios (requiere DATABASE_URL apuntando a una DB)
export DATABASE_URL="sqlite:///./sofia.db"
python -m app.services.price_importer servired_knowledge/precios/archivo.xlsx
```

### Formato del Excel

| Hoja | tipo_afiliacion |
|------|----------------|
| PARTICULARES | particular |
| MONOTRIBUTOS | monotributo |
| RELACION DE DEPENDENCIA | relacion_dependencia |

Cada hoja debe tener:
- Columna con nombre del plan
- Columnas de precio por zona (Córdoba / Interior)
- Columnas con rango de edad

El importador es **idempotente**: re-ejecutarlo no duplica registros, solo actualiza precios que cambiaron.
