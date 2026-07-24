"""
Tests unitarios — Lead Qualifier Service.

Verifica la correcta extracción de intención, datos y flujo
de calificación comercial sin dependencias externas.
"""

from __future__ import annotations

import pytest

from app.models.lead import (
    EstadoComercial,
    InteresDetectado,
    Lead,
    TipoAfiliacion,
)
from app.services.lead_qualifier import (
    LeadQualifierService,
    clasificar_intencion,
)


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
# Fase 5 — Tests de casos solicitados
# ─────────────────────────────────────────────

class TestCaso1_Precio:
    """
    Caso 1: Cliente consulta precios.

    Mensaje: "Hola quiero saber precios"
    Resultado esperado: interes = precio
    """

    def test_intencion_precio(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Hola quiero saber precios")

        assert resultado.lead.interes_detectado == InteresDetectado.PRECIO
        assert resultado.estado == EstadoComercial.CALIFICANDO
        assert resultado.datos_extraidos == ["interes_detectado"]

    def test_precio_otras_variantes(self) -> None:
        assert clasificar_intencion("¿Cuánto cuesta?") == InteresDetectado.PRECIO
        assert clasificar_intencion("¿Qué valor tiene?") == InteresDetectado.PRECIO
        assert clasificar_intencion("¿Cuánto sale?") == InteresDetectado.PRECIO


class TestCaso2_MonotributistaConFamilia:
    """
    Caso 2: Monotributista con esposa e hijos.

    Mensaje: "Soy monotributista y quiero cobertura para mi esposa y mis hijos"
    Resultado esperado:
        tipo_afiliacion = monotributo
        conyuge = true
        hijos = true
    """

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
        assert clasificar_intencion("Soy monotributista") == InteresDetectado.MONOTRIBUTO
        assert clasificar_intencion("Tengo monotributo") == InteresDetectado.MONOTRIBUTO


class TestCaso3_CambioObraSocial:
    """
    Caso 3: Cliente quiere cambiarse de obra social.

    Mensaje: "Quiero cambiarme de obra social"
    Resultado esperado: interes = cambio_obra_social
    """

    def test_intencion_cambio(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Quiero cambiarme de obra social")

        assert resultado.lead.interes_detectado == InteresDetectado.CAMBIO_OBRA_SOCIAL
        assert resultado.estado == EstadoComercial.CALIFICANDO

    def test_cambio_variantes(self) -> None:
        assert clasificar_intencion("Me quiero cambiar de obra social") == InteresDetectado.CAMBIO_OBRA_SOCIAL
        assert clasificar_intencion("Busco otra obra social") == InteresDetectado.CAMBIO_OBRA_SOCIAL


class TestCaso4_Empresa:
    """
    Caso 4: Empresa que necesita cobertura para empleados.

    Mensaje: "Tengo una empresa y necesito cobertura para empleados"
    Resultado esperado: interes = empresa
    """

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


# ─────────────────────────────────────────────
# Tests de flujo completo
# ─────────────────────────────────────────────

class TestFlujoCompleto:
    def test_lead_nuevo_a_calificado(self, qualifier: LeadQualifierService) -> None:
        lead = Lead(lead_id="flow_001")

        # Paso 1: Intención
        r1 = qualifier.process_message(lead, "Quiero precios para mi familia")
        assert r1.lead.interes_detectado == InteresDetectado.PRECIO
        assert r1.proxima_pregunta == "nombre"

        # Paso 2: Nombre
        r2 = qualifier.process_message(lead, "Me llamo Ana")
        assert r2.lead.nombre == "Ana"
        assert r2.proxima_pregunta == "tipo_afiliacion"

        # Paso 3: Tipo de afiliación
        r3 = qualifier.process_message(lead, "Soy monotributista")
        assert r3.lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO
        assert r3.proxima_pregunta == "tiene_aportes"

        # Paso 4: Aportes
        r4 = qualifier.process_message(lead, "Sí, tengo aportes")
        assert r4.lead.tiene_aportes is True
        assert r4.proxima_pregunta == "grupo_familiar"

        # Paso 5: Grupo familiar
        r5 = qualifier.process_message(lead, "Mi esposa y 2 hijos")
        assert r5.lead.grupo_familiar.conyuge is True
        assert r5.lead.grupo_familiar.hijos is True
        assert r5.lead.cantidad_hijos == 2
        assert r5.proxima_pregunta == "localidad"

        # Paso 6: Localidad
        r6 = qualifier.process_message(lead, "Soy de Córdoba")
        assert r6.lead.localidad == "Córdoba"
        assert r6.proxima_pregunta == "edad"

        # Paso 7: Edad
        r7 = qualifier.process_message(lead, "Tengo 35 años")
        assert r7.lead.edad == 35
        assert r7.proxima_pregunta is None
        assert r7.listo_para_derivar is True
        assert r7.lead.estado_comercial == EstadoComercial.CALIFICADO

    def test_datos_no_se_sobreescriben(self, qualifier: LeadQualifierService) -> None:
        lead = Lead(lead_id="overwrite_001")
        qualifier.process_message(lead, "Me llamo Carlos")
        assert lead.nombre == "Carlos"

        qualifier.process_message(lead, "Me llámame Pedro")
        # El nombre no se sobreescribe porque ya existe
        assert lead.nombre == "Carlos"
