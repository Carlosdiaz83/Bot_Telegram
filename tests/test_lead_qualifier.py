"""
Tests unitarios — Lead Qualifier Service + Servired Rules.

Verifica la correcta extracción de intención, datos y flujo
de calificación comercial para SERVIRED.
"""

from __future__ import annotations

import pytest

from app.models.lead import (
    EstadoComercial,
    InteresDetectado,
    Lead,
    NecesidadPrincipal,
    PrioridadCliente,
    TipoAfiliacion,
)
from app.services.lead_qualifier import (
    LeadQualifierService,
    clasificar_intencion,
)
from app.services.servired_rules import clasificar_perfil


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def qualifier() -> LeadQualifierService:
    """Instancia del servicio de calificación."""
    return LeadQualifierService()


@pytest.fixture
def lead_nuevo() -> Lead:
    """Lead recién creado, sin información."""
    return Lead(lead_id="test_001")


# ─────────────────────────────────────────────
# Tests de intención
# ─────────────────────────────────────────────

class TestCaso1_Precio:
    """Caso 1: Cliente consulta precios."""

    def test_intencion_precio(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Hola quiero saber precios")

        assert resultado.lead.interes_detectado == InteresDetectado.PRECIOS
        assert resultado.estado == EstadoComercial.CALIFICANDO
        assert "interes_detectado" in resultado.datos_extraidos

    def test_precio_otras_variantes(self) -> None:
        assert clasificar_intencion("¿Cuánto cuesta?") == InteresDetectado.PRECIOS
        assert clasificar_intencion("¿Qué valor tiene?") == InteresDetectado.PRECIOS
        assert clasificar_intencion("¿Cuánto sale?") == InteresDetectado.PRECIOS


class TestCaso2_MonotributistaConFamilia:
    """Caso 2: Monotributista con esposa e hijos."""

    def test_monotributista_con_familia(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(
            lead_nuevo,
            "Soy monotributista y quiero cobertura para mi esposa y mis hijos",
        )

        assert resultado.lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO
        assert resultado.lead.grupo_familiar.conyuge is True
        assert resultado.lead.grupo_familiar.hijos is True
        assert resultado.lead.cantidad_hijos >= 1

    def test_monotributo_detectado(self) -> None:
        # MONOTRIBUTO se detecta como tipo_afiliacion, no como interés
        # El interés se clasifica según el contexto
        resultado = clasificar_intencion("Soy monotributista")
        assert resultado in (InteresDetectado.AFILIACION, InteresDetectado.INFORMACION_GENERAL)


class TestCaso3_CambioObraSocial:
    """Caso 3: Cliente quiere cambiarse de obra social."""

    def test_intencion_cambio(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Quiero cambiarme de obra social")

        assert resultado.lead.interes_detectado == InteresDetectado.CAMBIO_OBRA_SOCIAL
        assert resultado.estado == EstadoComercial.CALIFICANDO

    def test_cambio_variantes(self) -> None:
        assert clasificar_intencion("Me quiero cambiar de obra social") == InteresDetectado.CAMBIO_OBRA_SOCIAL
        assert clasificar_intencion("Busco otra obra social") == InteresDetectado.CAMBIO_OBRA_SOCIAL


class TestCaso4_Empresa:
    """Caso 4: Empresa que necesita cobertura para empleados."""

    def test_intencion_empresa(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(
            lead_nuevo,
            "Tengo una empresa y necesito cobertura para empleados",
        )

        assert resultado.lead.interes_detectado == InteresDetectado.EMPRESA
        assert resultado.lead.tipo_afiliacion == TipoAfiliacion.EMPRESA
        assert resultado.estado == EstadoComercial.CALIFICANDO

    def test_empresa_variantes(self) -> None:
        assert clasificar_intencion("Tengo un comercio") == InteresDetectado.EMPRESA
        assert clasificar_intencion("Necesito cobertura para mis empleados") == InteresDetectado.EMPRESA


# ─────────────────────────────────────────────
# Nuevos casos Sprint 3.5
# ─────────────────────────────────────────────

class TestCaso5_MonotributistaFamiliaDetectaGrupo:
    """
    Caso 5: Monotributista que necesita cobertura familiar.
    Mensaje: "Soy monotributista y necesito cobertura para mi esposa y dos hijos"
    Esperado: tipo_afiliacion=monotributo, grupo=familia
    """

    def test_detecta_tipo_y_grupo(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(
            lead_nuevo,
            "Soy monotributista y necesito cobertura para mi esposa y dos hijos",
        )

        assert resultado.lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO
        assert resultado.lead.grupo_familiar.conyuge is True
        assert resultado.lead.grupo_familiar.hijos is True
        assert resultado.lead.cantidad_hijos == 2

    def test_clasificacion_perfil(self) -> None:
        lead = Lead(
            lead_id="test_005",
            nombre="Carlos",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            cantidad_integrantes=4,
        )
        lead.actualizar_grupo_familiar(conyuge=True, hijos=True, cantidad_hijos=2)

        perfil = clasificar_perfil(lead)
        assert perfil.perfil == "familia"
        assert perfil.requiere_asesor is False


class TestCaso6_BuscaAlgoEconomico:
    """
    Caso 6: Cliente prioriza precio.
    Mensaje: "Busco algo económico"
    Esperado: prioridad=económico
    """

    def test_detecta_prioridad_economica(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Busco algo económico")

        assert resultado.lead.prioridad_cliente == PrioridadCliente.ECONOMICO
        assert "prioridad_cliente" in resultado.datos_extraidos

    def test_clasificacion_sensible_precio(self) -> None:
        lead = Lead(
            lead_id="test_006",
            nombre="María",
            prioridad_cliente=PrioridadCliente.ECONOMICO,
        )

        perfil = clasificar_perfil(lead)
        assert perfil.tipo_cliente == "sensible_precio"


class TestCaso7_QuiereSaberBeneficios:
    """
    Caso 7: Cliente quiere conocer beneficios.
    Mensaje: "Quiero saber beneficios"
    Esperado: interes=beneficios
    """

    def test_detecta_interes_beneficios(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Quiero saber beneficios")

        assert resultado.lead.interes_detectado == InteresDetectado.BENEFICIOS
        assert "interes_detectado" in resultado.datos_extraidos

    def test_beneficios_variantes(self) -> None:
        assert clasificar_intencion("¿Qué beneficios tiene?") == InteresDetectado.BENEFICIOS
        assert clasificar_intencion("¿Qué ventajas ofrece?") == InteresDetectado.BENEFICIOS


# ─────────────────────────────────────────────
# Tests de extracción de datos
# ─────────────────────────────────────────────

class TestExtraccionNombre:
    def test_me_llamo(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Me llamo Carlos")
        assert lead_nuevo.nombre == "Carlos"

    def test_soy(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Soy María García")
        assert lead_nuevo.nombre == "María García"

    def test_mi_nombre_es(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Mi nombre es Juan Pérez")
        assert lead_nuevo.nombre == "Juan Pérez"


class TestExtraccionEdad:
    def test_tengo_edad(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Tengo 35 años")
        assert lead_nuevo.edad == 35

    def test_edad_simple(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "30 años")
        assert lead_nuevo.edad == 30


class TestExtraccionLocalidad:
    def test_soy_de(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Soy de Córdoba")
        assert lead_nuevo.localidad == "Córdoba"

    def test_vivo_en(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Vivo en Buenos Aires")
        assert lead_nuevo.localidad == "Buenos Aires"


class TestGrupoFamiliar:
    def test_con_esposa(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Quiero cobertura para mi esposa")
        assert lead_nuevo.grupo_familiar.conyuge is True

    def test_con_hijos(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Tengo 3 hijos")
        assert lead_nuevo.grupo_familiar.hijos is True
        assert lead_nuevo.cantidad_hijos == 3

    def test_solo_titular(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Solo para mí")
        assert lead_nuevo.grupo_familiar.conyuge is False
        assert lead_nuevo.grupo_familiar.hijos is False


class TestNecesidadPrincipal:
    def test_precio(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Busco algo barato")
        assert lead_nuevo.necesidad_principal == NecesidadPrincipal.PRECIO

    def test_beneficios(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "¿Qué beneficios tiene?")
        assert lead_nuevo.necesidad_principal == NecesidadPrincipal.BENEFICIOS

    def test_cobertura_familiar(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Necesito cobertura para mi familia")
        assert lead_nuevo.necesidad_principal == NecesidadPrincipal.COBERTURA_FAMILIAR


class TestPrioridadCliente:
    def test_economico(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Algo económico")
        assert lead_nuevo.prioridad_cliente == PrioridadCliente.ECONOMICO

    def test_completo(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        qualifier.process_message(lead_nuevo, "Quiero lo mejor")
        assert lead_nuevo.prioridad_cliente == PrioridadCliente.COMPLETO


# ─────────────────────────────────────────────
# Tests de flujo completo
# ─────────────────────────────────────────────

class TestFlujoCompleto:
    def test_lead_nuevo_a_calificado(self, qualifier: LeadQualifierService) -> None:
        lead = Lead(lead_id="flow_001")

        # Paso 1: Intención — "familia" también detecta necesidad y prioridad
        r1 = qualifier.process_message(lead, "Quiero precios")
        assert r1.lead.interes_detectado == InteresDetectado.PRECIOS
        assert r1.proxima_pregunta == "nombre"

        # Paso 2: Nombre
        r2 = qualifier.process_message(lead, "Me llamo Ana")
        assert r2.lead.nombre == "Ana"
        assert r2.proxima_pregunta == "tipo_afiliacion"

        # Paso 3: Tipo de afiliación
        r3 = qualifier.process_message(lead, "Soy monotributista")
        assert r3.lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO
        assert r3.proxima_pregunta == "grupo_familiar"

        # Paso 4: Grupo familiar
        r4 = qualifier.process_message(lead, "Mi esposa y dos hijos")
        assert r4.lead.grupo_familiar.conyuge is True
        assert r4.lead.grupo_familiar.hijos is True
        assert r4.lead.cantidad_hijos == 2
        assert r4.proxima_pregunta == "localidad"

        # Paso 5: Localidad
        r5 = qualifier.process_message(lead, "Soy de Córdoba")
        assert r5.lead.localidad == "Córdoba"
        assert r5.proxima_pregunta == "edad"

        # Paso 6: Edad
        r6 = qualifier.process_message(lead, "Tengo 35 años")
        assert r6.lead.edad == 35
        assert r6.proxima_pregunta is None
        assert r6.listo_para_derivar is True
        assert r6.lead.estado_comercial == EstadoComercial.CALIFICADO

    def test_datos_no_se_sobreescriben(self, qualifier: LeadQualifierService) -> None:
        lead = Lead(lead_id="overwrite_001")
        qualifier.process_message(lead, "Me llamo Carlos")
        assert lead.nombre == "Carlos"

        qualifier.process_message(lead, "Me llámame Pedro")
        assert lead.nombre == "Carlos"


# ─────────────────────────────────────────────
# Tests de Servired Rules
# ─────────────────────────────────────────────

class TestServiredRules:
    def test_perfil_empresa_requiere_asesor(self) -> None:
        lead = Lead(
            lead_id="rules_001",
            nombre="Roberto",
            tipo_afiliacion=TipoAfiliacion.EMPRESA,
            cantidad_integrantes=10,
        )

        perfil = clasificar_perfil(lead)
        assert perfil.perfil == "empresa"
        assert perfil.requiere_asesor is True

    def test_perfil_solo(self) -> None:
        lead = Lead(
            lead_id="rules_002",
            nombre="Laura",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )

        perfil = clasificar_perfil(lead)
        assert perfil.perfil == "solo"
        assert perfil.requiere_asesor is False

    def test_perfil_familia_grande_requiere_asesor(self) -> None:
        lead = Lead(
            lead_id="rules_003",
            nombre="Pedro",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            cantidad_integrantes=5,
        )
        lead.actualizar_grupo_familiar(conyuge=True, hijos=True, cantidad_hijos=3)

        perfil = clasificar_perfil(lead)
        assert perfil.perfil == "familia"
        assert perfil.requiere_asesor is True  # más de 4 integrantes

    def test_cambio_obra_social_requiere_asesor(self) -> None:
        lead = Lead(
            lead_id="rules_004",
            nombre="Sofía",
            tipo_afiliacion=TipoAfiliacion.RELACION_DEPENDENCIA,
            interes_detectado=InteresDetectado.CAMBIO_OBRA_SOCIAL,
        )

        perfil = clasificar_perfil(lead)
        assert perfil.requiere_asesor is True
