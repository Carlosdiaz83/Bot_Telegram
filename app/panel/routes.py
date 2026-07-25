"""
Rutas del panel comercial SERVIRED.

Endpoints para listar leads, ver detalles y gestionar
estados comerciales.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database.models import LeadDB, ConversationMessageDB
from app.database.repository import LeadRepository, ConversationRepository
from app.models.lead import EstadoComercial
from app.panel.dependencies import get_panel_db

router = APIRouter()
_templates_dir = str(Path(__file__).parent / "templates")
templates = Jinja2Templates(directory=_templates_dir)


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_panel_db)) -> HTMLResponse:
    """Dashboard principal con estadísticas."""
    repo = LeadRepository(db)
    leads = repo.listar_leads(limit=1000)

    total = len(leads)
    por_estado = {}
    por_temperatura = {"frio": 0, "tibio": 0, "caliente": 0}

    for lead in leads:
        estado = lead.estado_comercial or "nuevo"
        por_estado[estado] = por_estado.get(estado, 0) + 1

        temp = lead.temperatura_lead or "frio"
        if temp in por_temperatura:
            por_temperatura[temp] += 1

    stats = {
        "total": total,
        "por_estado": por_estado,
        "por_temperatura": por_temperatura,
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
    db: Session = Depends(get_panel_db),
) -> HTMLResponse:
    """Lista de leads con filtros."""
    repo = LeadRepository(db)
    leads = repo.listar_leads(estado=estado, limit=200)

    # Filtro por temperatura (post-query ya que es campo calculado)
    if temperatura:
        leads = [l for l in leads if l.temperatura_lead == temperatura]

    return templates.TemplateResponse(
        request,
        "leads.html",
        {"leads": leads, "filtro_estado": estado, "filtro_temperatura": temperatura},
    )


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detail(
    request: Request,
    lead_id: int,
    db: Session = Depends(get_panel_db),
) -> HTMLResponse:
    """Detalle de un lead con historial de conversación."""
    lead_db = db.get(LeadDB, lead_id)
    if lead_db is None:
        return RedirectResponse(url="/leads", status_code=303)

    conv_repo = ConversationRepository(db)
    historial = conv_repo.historial_lead(lead_db.id, limit=30)

    return templates.TemplateResponse(
        request,
        "lead_detail.html",
        {"lead": lead_db, "historial": historial},
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

    # Validar que el estado sea válido
    try:
        EstadoComercial(estado)
    except ValueError:
        return RedirectResponse(url=f"/leads/{lead_id}", status_code=303)

    lead_repo = LeadRepository(db)
    lead_db.estado_comercial = estado
    lead_repo.actualizar_lead(lead_db)

    return RedirectResponse(url=f"/leads/{lead_id}", status_code=303)
