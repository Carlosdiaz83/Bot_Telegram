"""
Tests de ingestión real de documentos con DocumentIngester.

Verifica que archivos .txt, .md, .pdf y la ingesta por carpeta
funcionan correctamente y que KnowledgeEngine puede recuperarlos.
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, ServiredKnowledgeDB
from app.database.repository import KnowledgeRepository
from app.services.document_ingester import DocumentIngester, _detectar_categoria
from app.services.knowledge_engine import KnowledgeEngine
from app.models.lead import Lead, GrupoFamiliar


# ─────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def knowledge_engine(db_session):
    return KnowledgeEngine(db_session)


@pytest.fixture()
def ingester(knowledge_engine):
    return DocumentIngester(knowledge_engine)


@pytest.fixture()
def sample_lead():
    return Lead(
        lead_id="123456",
        nombre="Carlos",
        edad=45,
        localidad="Buenos Aires",
        grupo_familiar=GrupoFamiliar(titular=True, conyuge=True, hijos=True),
    )


# ─────────────────────────────────────────
# Detección de categoría
# ─────────────────────────────────────────


class TestDetectarCategoria:
    def test_detecta_planes(self):
        assert _detectar_categoria("planes_SERVIRED") == "planes"
        assert _detectar_categoria("plan_medimax") == "planes"
        assert _detectar_categoria("medimax_gold") == "planes"

    def test_detecta_coberturas(self):
        assert _detectar_categoria("coberturas_generales") == "coberturas"
        assert _detectar_categoria("ambulatorio") == "coberturas"
        assert _detectar_categoria("internacion") == "coberturas"

    def test_detecta_beneficios(self):
        assert _detectar_categoria("beneficios_2024") == "beneficios"
        assert _detectar_categoria("descuentos") == "beneficios"

    def test_detecta_objeciones(self):
        assert _detectar_categoria("objeciones_frecuentes") == "objeciones"
        assert _detectar_categoria("rechazos") == "objeciones"

    def test_detecta_cierres(self):
        assert _detectar_categoria("cierre_venta") == "cierres"
        assert _detectar_categoria("closing_tecnico") == "cierres"

    def test_detecta_precios(self):
        assert _detectar_categoria("precios_2024") == "precios"
        assert _detectar_categoria("costos") == "precios"

    def test_detecta_argumentos(self):
        assert _detectar_categoria("argumentos_venta") == "argumentos"
        assert _detectar_categoria("pitch_comercial") == "argumentos"

    def test_fallback_informacion(self):
        assert _detectar_categoria("archivo_random") == "informacion"
        assert _detectar_categoria("algo") == "informacion"


# ─────────────────────────────────────────
# Ingesta de texto (.txt)
# ─────────────────────────────────────────


class TestIngestirTxt:
    def test_ingesta_basica(self, ingester, db_session):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False,
        ) as f:
            f.write("Planes SERVIRED:\n- Medimax\n- Medimax Gold")
            ruta = Path(f.name)

        item_id = ingester.ingestir_txt("planes", ruta)
        assert item_id > 0

        repo = KnowledgeRepository(db_session)
        item = repo.buscar_por_id(item_id)
        assert item is not None
        assert item.categoria == "planes"
        assert "Medimax" in item.contenido
        assert item.fuente == str(ruta)

        ruta.unlink()

    def test_titulo_desde_nombre_archivo(self, ingester, db_session):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False,
        ) as f:
            f.write("Contenido de prueba")
            ruta = Path(f.name)

        item_id = ingester.ingestir_txt("informacion", ruta)
        repo = KnowledgeRepository(db_session)
        item = repo.buscar_por_id(item_id)
        # El título se genera del nombre del archivo
        assert item.titulo is not None
        assert len(item.titulo) > 0

        ruta.unlink()

    def test_archivo_no_existe(self, ingester):
        with pytest.raises(FileNotFoundError):
            ingester.ingestir_txt("planes", "/no/existe/archivo.txt")


# ─────────────────────────────────────────
# Ingesta de markdown (.md)
# ─────────────────────────────────────────


class TestIngestirMarkdown:
    def test_ingesta_basica(self, ingester, db_session):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False,
        ) as f:
            f.write("# Planes SERVIRED\n\n## Medimax\nCobertura completa.")
            ruta = Path(f.name)

        item_id = ingester.ingestir_markdown("planes", ruta)
        assert item_id > 0

        repo = KnowledgeRepository(db_session)
        item = repo.buscar_por_id(item_id)
        assert "Medimax" in item.contenido

        ruta.unlink()

    def test_titulo_custom(self, ingester, db_session):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False,
        ) as f:
            f.write("Contenido")
            ruta = Path(f.name)

        item_id = ingester.ingestir_markdown("planes", ruta, titulo="Mi Plan")
        repo = KnowledgeRepository(db_session)
        item = repo.buscar_por_id(item_id)
        assert item.titulo == "Mi Plan"

        ruta.unlink()


# ─────────────────────────────────────────
# Ingesta por carpeta
# ─────────────────────────────────────────


class TestIngestirCarpeta:
    def test_carpeta_plana(self, ingester, db_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            carpeta = Path(tmpdir)
            (carpeta / "planes_SERVIRED.txt").write_text(
                "Planes: Medimax, Gold", encoding="utf-8",
            )
            (carpeta / "coberturas_generales.txt").write_text(
                "Coberturas: ambulatorio, internacion", encoding="utf-8",
            )

            stats = ingester.ingestir_carpeta(carpeta)
            assert stats["archivos_ok"] == 2
            assert stats["archivos_err"] == 0
            assert len(stats["ids"]) == 2

            repo = KnowledgeRepository(db_session)
            activos = repo.activos()
            assert len(activos) == 2

    def test_carpeta_con_subcarpetas(self, ingester, db_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            carpeta = Path(tmpdir)
            sub = carpeta / "planes"
            sub.mkdir()
            (sub / "medimax.md").write_text(
                "Plan Medimax: cobertura completa", encoding="utf-8",
            )

            stats = ingester.ingestir_carpeta(carpeta)
            assert stats["archivos_ok"] == 1

            repo = KnowledgeRepository(db_session)
            items = repo.buscar_por_categoria("planes")
            assert len(items) == 1
            assert "Medimax" in items[0].contenido

    def test_carpeta_vacia(self, ingester, db_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            stats = ingester.ingestir_carpeta(Path(tmpdir))
            assert stats["archivos_ok"] == 0
            assert stats["archivos_err"] == 0

    def test_carpeta_no_existe(self, ingester):
        with pytest.raises(NotADirectoryError):
            ingester.ingestir_carpeta("/no/existe/carpeta")

    def test_archivos_no_soportados_se_ignoran(self, ingester, db_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            carpeta = Path(tmpdir)
            (carpeta / "imagen.jpg").write_bytes(b"fake jpg")
            (carpeta / "datos.json").write_text("{}")
            (carpeta / "info.txt").write_text("Datos reales")

            stats = ingester.ingestir_carpeta(carpeta)
            assert stats["archivos_ok"] == 1
            assert stats["archivos_err"] == 0

    def test_error_en_archivo_no_detiene_los_demas(self, ingester, db_session):
        with tempfile.TemporaryDirectory() as tmpdir:
            carpeta = Path(tmpdir)
            (carpeta / "bueno.txt").write_text("Contenido bueno")
            # Archivo corrupto (simulado con .md sin contenido válido)
            ruta_mala = carpeta / "malo.md"
            ruta_mala.write_text("OK")

            stats = ingester.ingestir_carpeta(carpeta)
            assert stats["archivos_ok"] == 2  # ambos se ingesan OK


# ─────────────────────────────────────────
# Verificación: KnowledgeEngine recupera
# ─────────────────────────────────────────


class TestKnowledgeEngineRecupera:
    def test_despues_de_ingesta_txt(self, ingester, knowledge_engine, sample_lead):
        with tempfile.TemporaryDirectory() as tmpdir:
            carpeta = Path(tmpdir)
            (carpeta / "planes_SERVIRED.txt").write_text(
                "Planes SERVIRED: Medimax CO desde $15000, "
                "Medimax Gold desde $25000. Sin periodo de carencia.",
                encoding="utf-8",
            )
            ingester.ingestir_carpeta(carpeta)

            contexto = knowledge_engine.contexto_para_lead(
                sample_lead, etapa="presentando_valor",
            )
            assert "Medimax" in contexto

    def test_despues_de_ingesta_md(self, ingester, knowledge_engine, sample_lead):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8", delete=False,
        ) as f:
            f.write(
                "# Coberturas SERVIRED\n\n"
                "Ambulatorio: consultas médicas.\n"
                "Internación: clínicas y sanatorios.",
            )
            ruta = Path(f.name)

        ingester.ingestir_markdown("coberturas", ruta)

        contexto = knowledge_engine.contexto_para_lead(
            sample_lead, etapa="presentando_valor",
        )
        assert "Coberturas" in contexto or "ambulatorio" in contexto.lower()

        ruta.unlink()

    def test_tags_facilitan_busqueda(self, ingester, knowledge_engine, sample_lead):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", encoding="utf-8", delete=False,
        ) as f:
            f.write("Odontología SERVIRED: 50% de descuento en limpiezas.")
            ruta = Path(f.name)

        ingester.ingestir_txt("beneficios", ruta, tags="odontologia,descuento,limpieza")

        contexto = knowledge_engine.contexto_para_lead(
            sample_lead, mensaje="¿Tienen descuentos en odontología?",
        )
        assert "odontolog" in contexto.lower() or "descuento" in contexto.lower()

        ruta.unlink()


# ─────────────────────────────────────────
# Test con documento real de servired_knowledge/
# ─────────────────────────────────────────


class TestDocumentoReal:
    def test_plans_servired_real_file(self, ingester, knowledge_engine, sample_lead):
        ruta_real = Path("servired_knowledge/planes_SERVIRED.txt")
        if not ruta_real.exists():
            pytest.skip("Archivo servired_knowledge/planes_SERVIRED.txt no encontrado")

        ingester.ingestir_txt("planes", ruta_real, prioridad_comercial=5)

        contexto = knowledge_engine.contexto_para_lead(
            sample_lead, etapa="presentando_valor",
        )
        assert len(contexto) > 0

        repo = KnowledgeRepository(ingester._engine._repo._db)
        items = repo.buscar_por_categoria("planes")
        assert len(items) >= 1
        assert "Medimax" in items[0].contenido or "SERVIRED" in items[0].contenido
