"""
Aplicación FastAPI del panel comercial SERVIRED.

Ejecutar con:
    python -m app.panel.app

O desde el main.py con:
    from app.panel.app import create_panel_app
    app = create_panel_app()
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI

from app.panel.dependencies import init_panel_db
from app.panel.routes import router


def create_panel_app(database_url: str | None = None) -> FastAPI:
    """
    Crea la aplicación FastAPI del panel.

    Args:
        database_url: URL de la base de datos.
            Si no se provee, usa la del .env o SQLite default.

    Returns:
        FastAPI app lista para usar.
    """
    app = FastAPI(
        title="Panel Comercial SERVIRED",
        description="Mini CRM para gestión de leads",
        version="1.0.0",
    )

    # Configurar DB
    if database_url is None:
        try:
            from app.config.settings import BotConfig
            config = BotConfig.from_env()
            database_url = config.database_url
        except Exception:
            database_url = "sqlite:///./health_advisor.db"

    init_panel_db(database_url)

    # Registrar rutas
    app.include_router(router)

    return app


if __name__ == "__main__":
    import uvicorn
    app = create_panel_app()
    uvicorn.run(app, host="127.0.0.1", port=8000)
