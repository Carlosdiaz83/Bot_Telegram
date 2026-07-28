"""
Rutas del panel comercial SERVIRED.

Endpoints para dashboard, gestión de leads, detalle,
cambio de estados y evolución de Sofía.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.models import LeadDB, ConversationMessageDB, TrainingSessionDB
from app.database.repository import LeadRepository, ConversationRepository, TrainingRepository
from app.models.lead import EstadoComercial
from app.panel.dependencies import get_panel_db

router = APIRouter()
_templates_dir = str(Path(__file__).parent / "templates")
templates = Jinja2Templates(directory=_templates_dir)


ESTADOS_COMERCIALES = [e.value for e in EstadoComercial]


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_panel_db)) -> HTMLResponse:
    """Dashboard principal con estadísticas comerciales."""
    repo = LeadRepository(db)
    leads = repo.listar_leads(limit=5000)

    total = len(leads)
    por_estado = {}
    por_temperatura = {"frio": 0, "tibio": 0, "caliente": 0}

    for lead in leads:
        estado = lead.estado_comercial or "nuevo"
        por_estado[estado] = por_estado.get(estado, 0) + 1

        temp = lead.temperatura_lead or "frio"
        if temp in por_temperatura:
            por_temperatura[temp] += 1

    nuevos = por_estado.get("nuevo", 0)
    calificando = por_estado.get("calificando", 0)
    calificados = por_estado.get("calificado", 0)
    seguimiento = por_estado.get("seguimiento", 0)
    cierres = por_estado.get("vendido", 0)
    perdidas = por_estado.get("perdido", 0)

    # Estadísticas de entrenamiento
    training_repo = TrainingRepository(db)
    training_total = len(training_repo.historial(limit=10000))
    training_promedio = training_repo.score_promedio()
    training_mejor = training_repo.mejor_score()

    stats = {
        "total": total,
        "nuevos": nuevos,
        "calificando": calificando,
        "calificados": calificados,
        "seguimiento": seguimiento,
        "cierres": cierres,
        "perdidas": perdidas,
        "por_estado": por_estado,
        "por_temperatura": por_temperatura,
        "training_total": training_total,
        "training_promedio": round(training_promedio, 1),
        "training_mejor": training_mejor,
    }

    return templates.TemplateResponse(
        request,
        "index.html",
        {"stats": stats},
    )


@router.get("/leads", response_class=HTMLResponse)
def listar_leads(
    request: Request,
    estado: str | None = None,
    temperatura: str | None = None,
    q: str | None = None,
    orden: str | None = None,
    db: Session = Depends(get_panel_db),
) -> HTMLResponse:
    """Lista de leads con filtros, búsqueda y ordenamiento."""
    repo = LeadRepository(db)
    leads = repo.listar_leads(estado=estado, limit=500)

    if temperatura:
        leads = [l for l in leads if l.temperatura_lead == temperatura]

    if q:
        q_lower = q.lower()
        leads = [
            l for l in leads
            if (l.nombre and q_lower in l.nombre.lower())
            or (l.telegram_id and q_lower in str(l.telegram_id))
            or (l.localidad and q_lower in l.localidad.lower())
            or (l.telefono and q_lower in l.telefono)
        ]

    if orden == "score_desc":
        leads = sorted(leads, key=lambda l: l.score or 0, reverse=True)
    elif orden == "score_asc":
        leads = sorted(leads, key=lambda l: l.score or 0)
    elif orden == "reciente":
        leads = sorted(leads, key=lambda l: l.creado or "", reverse=True)

    return templates.TemplateResponse(
        request,
        "leads.html",
        {
            "leads": leads,
            "filtro_estado": estado,
            "filtro_temperatura": temperatura,
            "busqueda": q or "",
            "orden": orden or "",
            "estados": ESTADOS_COMERCIALES,
        },
    )


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail(
    request: Request,
    lead_id: int,
    db: Session = Depends(get_panel_db),
) -> HTMLResponse:
    """Detalle completo de un lead con historial de conversación y memoria comercial."""
    lead_db = db.get(LeadDB, lead_id)
    if lead_db is None:
        return RedirectResponse(url="/leads", status_code=303)

    conv_repo = ConversationRepository(db)
    historial = conv_repo.historial_lead(lead_db.id, limit=50)

    # Calcular score de forma segura
    score_val = lead_db.score if lead_db.score is not None else 0

    # Obtener memoria comercial del lead (Sprint 21.5)
    memory_context = None
    try:
        from app.services.commercial_memory import get_memory
        memory = get_memory()
        memory_context = memory.get_or_create(str(lead_db.id))
    except Exception:
        memory_context = None

    return templates.TemplateResponse(
        request,
        "lead_detail.html",
        {
            "lead": lead_db,
            "historial": historial,
            "score_pct": min(score_val, 100),
            "estados": ESTADOS_COMERCIALES,
            "memory_context": memory_context,
        },
    )


@router.post("/leads/{lead_id}/estado")
def cambiar_estado(
    lead_id: int,
    estado: str = Form(...),
    db: Session = Depends(get_panel_db),
) -> RedirectResponse:
    """Cambia el estado comercial de un lead."""
    lead_db = db.get(LeadDB, lead_id)
    if lead_db is None:
        return RedirectResponse(url="/leads", status_code=303)

    try:
        EstadoComercial(estado)
    except ValueError:
        return RedirectResponse(url=f"/leads/{lead_id}", status_code=303)

    lead_repo = LeadRepository(db)
    lead_db.estado_comercial = estado
    lead_repo.actualizar_lead(lead_db)

    return RedirectResponse(url=f"/leads/{lead_id}", status_code=303)


@router.get("/evolucion", response_class=HTMLResponse)
def evolucion_sofia(
    request: Request,
    db: Session = Depends(get_panel_db),
) -> HTMLResponse:
    """Página de evolución comercial de Sofía."""
    from app.services.commercial_evolution_service import CommercialEvolutionService

    evo_svc = CommercialEvolutionService(db)
    evolucion = evo_svc.obtener_evolucion()
    metricas = evo_svc.obtener_metricas()

    # Últimos 10 entrenamientos para la tabla
    training_repo = TrainingRepository(db)
    ultimos = training_repo.ultimos(10)

    return templates.TemplateResponse(
        request,
        "evolucion.html",
        {
            "evolucion": evolucion,
            "metricas": metricas,
            "ultimos_entrenamientos": ultimos,
        },
    )
