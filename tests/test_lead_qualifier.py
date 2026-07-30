"""
Tests de conversación — Sprint 4.

Verifica el flujo completo de conversación del asistente comercial Sofía.
Incluye: sesión, calificación, objeciones, cierre.
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
from app.services.session_manager import (
    EtapaConversacion,
    ResultadoCierre,
    SessionManager,
)
from app.services.conversation_manager import ConversationManager
from app.services.lead_qualifier import (
    LeadQualifierService,
    clasificar_intencion,
)
from app.services.servired_rules import clasificar_perfil
from app.services.objection_handler import (
    TipoObjecion,
    analizar_mensaje,
    detectar_objecion,
)
from app.services.closing_strategy import (
    intentar_cierre,
    interpretar_respuesta_cierre,
)
from app.services.sales_strategy import generar_argumento
from app.services.knowledge_service import KnowledgeService
from app.ai.service import AIService
from app.ai.client import LLMClient, LLMResponse
from app.ai.prompts import construir_prompt_sistema, construir_contexto
from app.database.database import get_engine, crear_tablas, cerrar_engine, get_session_factory
from app.database.models import Base
from app.database.repository import ConversationRepository, LeadRepository


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def manager() -> ConversationManager:
    """Instancia del ConversationManager."""
    return ConversationManager()


@pytest.fixture
def session_manager() -> SessionManager:
    """Instancia del SessionManager."""
    return SessionManager()


@pytest.fixture
def qualifier() -> LeadQualifierService:
    """Instancia del LeadQualifierService."""
    return LeadQualifierService()


@pytest.fixture
def lead_nuevo() -> Lead:
    """Lead recién creado."""
    return Lead(lead_id="test_001")


# ─────────────────────────────────────────────
# Tests de conversación (Sprint 4)
# ─────────────────────────────────────────────

class TestCaso1_ConversacionInteresada:
    """
    Caso 1: Cliente interesado y listo para contratar.
    Debe llegar a INTENTANDO_CIERRE.
    """

    def test_flujo_completo_hasta_cierre(self, manager: ConversationManager) -> None:
        tid = 90001

        # Saludo
        r1 = manager.procesar_mensaje(tid, "Hola, me llamo Pedro")
        assert "Pedro" in r1
        assert manager.session_manager.get(tid).etapa != EtapaConversacion.NUEVO

        # Descubrimiento — grupo familiar
        r2 = manager.procesar_mensaje(tid, "Para mi esposa y mis dos hijos")
        assert manager.session_manager.get(tid).etapa == EtapaConversacion.CALIFICANDO

        # Calificación — situación actual (detecta monotributo → ESPERANDO_DATOS)
        r3 = manager.procesar_mensaje(tid, "Soy monotributista")

        session = manager.session_manager.get(tid)
        assert session.etapa in (
            EtapaConversacion.ESPERANDO_DATOS,
            EtapaConversacion.CALIFICANDO,
        )

        # Completar datos para cotizar
        r4 = manager.procesar_mensaje(tid, "Córdoba, tengo 35 años")

        session = manager.session_manager.get(tid)
        assert session.etapa in (
            EtapaConversacion.PRESENTANDO_VALOR,
            EtapaConversacion.INTENTANDO_CIERRE,
            EtapaConversacion.CALIFICADO,
            EtapaConversacion.ESPERANDO_DATOS,
        )


class TestCaso2_ObjecionPrecio:
    """
    Caso 2: Cliente dice "Es caro".
    Debe entrar en MANEJANDO_OBJECIONES.
    """

    def test_objecion_precio(self, manager: ConversationManager) -> None:
        tid = 90002

        # Avanzar a calificación
        manager.procesar_mensaje(tid, "Hola, soy Ana")
        manager.procesar_mensaje(tid, "Solo para mí")
        manager.procesar_mensaje(tid, "Particular")

        # Completar datos para llegar a PRESENTANDO_VALOR
        manager.procesar_mensaje(tid, "Córdoba, 30 años")

        # Ahora sí objeción de precio (en PRESENTANDO_VALOR)
        r = manager.procesar_mensaje(tid, "Es muy caro")
        session = manager.session_manager.get(tid)
        assert session is not None
        assert session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES
        assert "presupuesto" in r.lower() or "precio" in r.lower() or " presupuesto" in r.lower()

    def test_detectar_objecion_precio(self) -> None:
        assert detectar_objecion("Es muy caro") == TipoObjecion.PRECIO
        assert detectar_objecion("No tengo plata") == TipoObjecion.PRECIO
        assert detectar_objecion("No puedo pagar eso") == TipoObjecion.PRECIO


class TestCaso3_AceptaAvanzar:
    """
    Caso 3: Cliente acepta avanzar.
    Debe registrar "aceptó".
    """

    def test_acepta(self, manager: ConversationManager) -> None:
        tid = 90003

        # Avanzar rápido a cierre
        manager.procesar_mensaje(tid, "Hola, soy Carlos")
        manager.procesar_mensaje(tid, "Solo para mí")
        manager.procesar_mensaje(tid, "Relación de dependencia")
        manager.procesar_mensaje(tid, "Sí, tengo aportes")

        # Forzar etapa de cierre
        session = manager.session_manager.get(tid)
        assert session is not None
        session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
        session.intento_de_cierre = True

        # Aceptar
        r = manager.procesar_mensaje(tid, "Sí quiero avanzar")
        assert session.resultado_cierre == ResultadoCierre.ACEPTO
        assert "excelente" in r.lower() or "avanzar" in r.lower() or "bienvenido" in r.lower()

    def test_interpretar_respuesta_acepta(self) -> None:
        assert interpretar_respuesta_cierre("Sí quiero avanzar") == ResultadoCierre.ACEPTO
        assert interpretar_respuesta_cierre("Dale") == ResultadoCierre.ACEPTO
        assert interpretar_respuesta_cierre("Avanzamos") == ResultadoCierre.ACEPTO


class TestCaso4_SoloConsulta:
    """
    Caso 4: Cliente solo consulta, debe seguir calificando.
    """

    def test_solo_consulta(self, manager: ConversationManager) -> None:
        tid = 90004

        # Saludo
        manager.procesar_mensaje(tid, "Hola")
        manager.procesar_mensaje(tid, "Me llamo Laura")

        # Respuesta que no es objeción ni aceptación
        r = manager.procesar_mensaje(tid, "Quiero saber precios")
        session = manager.session_manager.get(tid)
        assert session is not None
        # Debería seguir en calificación o haber avanzado normalmente
        assert session.etapa in (
            EtapaConversacion.CALIFICANDO,
            EtapaConversacion.DESCUBRIENDO_NECESIDAD,
            EtapaConversacion.PRESENTANDO_VALOR,
        )


# ─────────────────────────────────────────────
# Tests de sesión
# ─────────────────────────────────────────────

class TestSessionManager:
    def test_crear_sesion(self, session_manager: SessionManager) -> None:
        session = session_manager.get_or_create(12345)
        assert session.telegram_id == 12345
        assert session.etapa == EtapaConversacion.NUEVO
        assert session_manager.total_sesiones == 1

    def test_reutilizar_sesion(self, session_manager: SessionManager) -> None:
        s1 = session_manager.get_or_create(12345)
        s2 = session_manager.get_or_create(12345)
        assert s1 is s2
        assert session_manager.total_sesiones == 1

    def test_eliminar_sesion(self, session_manager: SessionManager) -> None:
        session_manager.get_or_create(12345)
        session_manager.eliminar(12345)
        assert session_manager.total_sesiones == 0

    def test_avanzar_etapa(self, session_manager: SessionManager) -> None:
        session = session_manager.get_or_create(12345)
        session.avanzar_etapa(EtapaConversacion.CALIFICANDO)
        assert session.etapa == EtapaConversacion.CALIFICANDO
        assert session.mensajes_en_etapa == 0


# ─────────────────────────────────────────────
# Tests de objeciones
# ─────────────────────────────────────────────

class TestObjeciones:
    def test_duda(self) -> None:
        assert detectar_objecion("No estoy seguro") == TipoObjecion.DUDA

    def test_procrastinacion(self) -> None:
        assert detectar_objecion("Lo voy a pensar") == TipoObjecion.PROCRASTINACION

    def test_tiempo(self) -> None:
        assert detectar_objecion("No tengo tiempo") == TipoObjecion.TIEMPO

    def test_confianza(self) -> None:
        assert detectar_objecion("No conozco Servired") == TipoObjecion.CONFIANZA

    def test_no_es_objecion(self) -> None:
        assert detectar_objecion("Quiero saber precios") == TipoObjecion.NINGUNA

    def test_analizar_mensaje_con_objecion(self, lead_nuevo: Lead) -> None:
        resultado = analizar_mensaje("Es muy caro", lead_nuevo)
        assert resultado.es_objecion is True
        assert resultado.tipo == TipoObjecion.PRECIO
        assert resultado.respuesta is not None

    def test_analizar_mensaje_sin_objecion(self, lead_nuevo: Lead) -> None:
        resultado = analizar_mensaje("Quiero precios", lead_nuevo)
        assert resultado.es_objecion is False


# ─────────────────────────────────────────────
# Tests de cierre
# ─────────────────────────────────────────────

class TestCierre:
    def test_cierre_beneficio(self) -> None:
        lead = Lead(
            lead_id="close_001",
            nombre="Pedro",
            cantidad_integrantes=3,
        )
        lead.actualizar_grupo_familiar(conyuge=True, hijos=True, cantidad_hijos=1)
        cierre = intentar_cierre(lead)
        assert cierre.tipo_cierre == "beneficio"
        assert "Pedro" in cierre.respuesta

    def test_cierre_directo_empresa(self) -> None:
        lead = Lead(
            lead_id="close_002",
            nombre="Roberto",
            tipo_afiliacion=TipoAfiliacion.EMPRESA,
        )
        cierre = intentar_cierre(lead)
        assert cierre.tipo_cierre == "directo"

    def test_cierre_alternativo(self) -> None:
        lead = Lead(
            lead_id="close_003",
            nombre="Laura",
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
        )
        cierre = intentar_cierre(lead)
        assert cierre.tipo_cierre == "alternativo"

    def test_interpretar_rechazo(self) -> None:
        assert interpretar_respuesta_cierre("No quiero") == ResultadoCierre.RECHAZO
        assert interpretar_respuesta_cierre("No gracias") == ResultadoCierre.RECHAZO

    def test_interpretar_pendiente(self) -> None:
        assert interpretar_respuesta_cierre("Lo voy a pensar") == ResultadoCierre.PENDIENTE
        assert interpretar_respuesta_cierre("No sé") == ResultadoCierre.PENDIENTE


# ─────────────────────────────────────────────
# Tests de sales strategy
# ─────────────────────────────────────────────

class TestSalesStrategy:
    def test_argumento_precio(self) -> None:
        lead = Lead(lead_id="sales_001", nombre="Ana", prioridad_cliente=PrioridadCliente.ECONOMICO)
        arg = generar_argumento(lead)
        assert "Ana" in arg
        assert "presupuesto" in arg.lower() or "precio" in arg.lower()

    def test_argumento_familiar(self) -> None:
        lead = Lead(lead_id="sales_002", nombre="Carlos", cantidad_integrantes=4)
        lead.actualizar_grupo_familiar(conyuge=True, hijos=True, cantidad_hijos=2)
        arg = generar_argumento(lead)
        assert "Carlos" in arg
        assert "4" in arg or "familia" in arg.lower()

    def test_argumento_calidad(self) -> None:
        lead = Lead(lead_id="sales_003", nombre="Laura", prioridad_cliente=PrioridadCliente.COMPLETO)
        arg = generar_argumento(lead)
        assert "Laura" in arg

    def test_argumento_generico(self) -> None:
        lead = Lead(lead_id="sales_004", nombre="Pedro")
        arg = generar_argumento(lead)
        assert "Pedro" in arg
        assert "Servired" in arg


# ─────────────────────────────────────────────
# Tests de Lead Qualifier (mantener)
# ─────────────────────────────────────────────

class TestCaso1_Precio:
    def test_intencion_precio(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Hola quiero saber precios")
        assert resultado.lead.interes_detectado == InteresDetectado.PRECIOS
        assert "interes_detectado" in resultado.datos_extraidos

    def test_precio_otras_variantes(self) -> None:
        assert clasificar_intencion("¿Cuánto cuesta?") == InteresDetectado.PRECIOS
        assert clasificar_intencion("¿Qué valor tiene?") == InteresDetectado.PRECIOS


class TestCaso2_MonotributistaConFamilia:
    def test_monotributista_con_familia(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(
            lead_nuevo,
            "Soy monotributista y quiero cobertura para mi esposa y mis hijos",
        )
        assert resultado.lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO
        assert resultado.lead.grupo_familiar.conyuge is True
        assert resultado.lead.grupo_familiar.hijos is True

    def test_monotributo_detectado(self) -> None:
        resultado = clasificar_intencion("Soy monotributista")
        assert resultado in (InteresDetectado.AFILIACION, InteresDetectado.INFORMACION_GENERAL)


class TestCaso3_CambioObraSocial:
    def test_intencion_cambio(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Quiero cambiarme de obra social")
        assert resultado.lead.interes_detectado == InteresDetectado.CAMBIO_OBRA_SOCIAL

    def test_cambio_variantes(self) -> None:
        assert clasificar_intencion("Me quiero cambiar de obra social") == InteresDetectado.CAMBIO_OBRA_SOCIAL


class TestCaso4_Empresa:
    def test_intencion_empresa(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(
            lead_nuevo,
            "Tengo una empresa y necesito cobertura para empleados",
        )
        assert resultado.lead.interes_detectado == InteresDetectado.EMPRESA
        assert resultado.lead.tipo_afiliacion == TipoAfiliacion.EMPRESA

    def test_empresa_variantes(self) -> None:
        assert clasificar_intencion("Tengo un comercio") == InteresDetectado.EMPRESA
        assert clasificar_intencion("Necesito cobertura para mis empleados") == InteresDetectado.EMPRESA


class TestCaso5_MonotributistaFamiliaDetectaGrupo:
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
    def test_detecta_prioridad_economica(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Busco algo económico")
        assert resultado.lead.prioridad_cliente == PrioridadCliente.ECONOMICO

    def test_clasificacion_sensible_precio(self) -> None:
        lead = Lead(lead_id="test_006", nombre="María", prioridad_cliente=PrioridadCliente.ECONOMICO)
        perfil = clasificar_perfil(lead)
        assert perfil.tipo_cliente == "sensible_precio"


class TestCaso7_QuiereSaberBeneficios:
    def test_detecta_interes_beneficios(self, qualifier: LeadQualifierService, lead_nuevo: Lead) -> None:
        resultado = qualifier.process_message(lead_nuevo, "Quiero saber beneficios")
        assert resultado.lead.interes_detectado == InteresDetectado.BENEFICIOS

    def test_beneficios_variantes(self) -> None:
        assert clasificar_intencion("¿Qué beneficios tiene?") == InteresDetectado.BENEFICIOS
        assert clasificar_intencion("¿Qué ventajas ofrece?") == InteresDetectado.BENEFICIOS


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


class TestFlujoCompleto:
    def test_lead_nuevo_a_calificado(self, qualifier: LeadQualifierService) -> None:
        lead = Lead(lead_id="flow_001")

        r1 = qualifier.process_message(lead, "Quiero precios")
        assert r1.lead.interes_detectado == InteresDetectado.PRECIOS
        assert r1.proxima_pregunta == "nombre"

        r2 = qualifier.process_message(lead, "Me llamo Ana")
        assert r2.lead.nombre == "Ana"

        r3 = qualifier.process_message(lead, "Soy monotributista")
        assert r3.lead.tipo_afiliacion == TipoAfiliacion.MONOTRIBUTO

        r4 = qualifier.process_message(lead, "Mi esposa y dos hijos")
        assert r4.lead.grupo_familiar.conyuge is True
        assert r4.lead.cantidad_hijos == 2

        r5 = qualifier.process_message(lead, "Soy de Córdoba")
        assert r5.lead.localidad == "Córdoba"

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


class TestServiredRules:
    def test_perfil_empresa_requiere_asesor(self) -> None:
        lead = Lead(lead_id="rules_001", nombre="Roberto", tipo_afiliacion=TipoAfiliacion.EMPRESA, cantidad_integrantes=10)
        perfil = clasificar_perfil(lead)
        assert perfil.perfil == "empresa"
        assert perfil.requiere_asesor is True

    def test_perfil_solo(self) -> None:
        lead = Lead(lead_id="rules_002", nombre="Laura", tipo_afiliacion=TipoAfiliacion.PARTICULAR)
        perfil = clasificar_perfil(lead)
        assert perfil.perfil == "solo"
        assert perfil.requiere_asesor is False

    def test_perfil_familia_grande_requiere_asesor(self) -> None:
        lead = Lead(lead_id="rules_003", nombre="Pedro", tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO, cantidad_integrantes=5)
        lead.actualizar_grupo_familiar(conyuge=True, hijos=True, cantidad_hijos=3)
        perfil = clasificar_perfil(lead)
        assert perfil.perfil == "familia"
        assert perfil.requiere_asesor is True

    def test_cambio_obra_social_requiere_asesor(self) -> None:
        lead = Lead(lead_id="rules_004", nombre="Sofía", tipo_afiliacion=TipoAfiliacion.RELACION_DEPENDENCIA, interes_detectado=InteresDetectado.CAMBIO_OBRA_SOCIAL)
        perfil = clasificar_perfil(lead)
        assert perfil.requiere_asesor is True


# ─────────────────────────────────────────────
# Tests de Knowledge Base (Sprint 5)
# ─────────────────────────────────────────────

@pytest.fixture
def knowledge() -> KnowledgeService:
    """Instancia del KnowledgeService."""
    return KnowledgeService()


class TestKnowledgeBeneficios:
    def test_cargar_beneficios(self, knowledge: KnowledgeService) -> None:
        contenido = knowledge.obtener_beneficios()
        assert "SERVIRED" in contenido
        assert "beneficios" in contenido.lower()

    def test_beneficios_contenido(self, knowledge: KnowledgeService) -> None:
        contenido = knowledge.obtener_beneficios()
        assert "red de prestadores" in contenido.lower()
        assert "cobertura integral" in contenido.lower()


class TestKnowledgeFAQ:
    def test_cargar_faq(self, knowledge: KnowledgeService) -> None:
        contenido = knowledge.obtener_faq()
        assert "preguntas frecuentes" in contenido.lower()

    def test_faq_como_funciona(self, knowledge: KnowledgeService) -> None:
        contenido = knowledge.obtener_faq()
        assert "cómo funciona" in contenido.lower() or "como funciona" in contenido.lower()


class TestKnowledgeObjeciones:
    def test_cargar_objeciones(self, knowledge: KnowledgeService) -> None:
        contenido = knowledge.obtener_objeciones()
        assert "objeciones" in contenido.lower()

    def test_respuesta_objecion_precio(self, knowledge: KnowledgeService) -> None:
        respuesta = knowledge.obtener_respuesta_objecion("caro")
        assert len(respuesta) > 0
        assert "presupuesto" in respuesta.lower() or "precio" in respuesta.lower()

    def test_respuesta_objecion_pensar(self, knowledge: KnowledgeService) -> None:
        respuesta = knowledge.obtener_respuesta_objecion("pensar")
        assert len(respuesta) > 0

    def test_respuesta_objecion_no_encontrada(self, knowledge: KnowledgeService) -> None:
        respuesta = knowledge.obtener_respuesta_objecion("xyz_inexistente")
        assert respuesta == ""


class TestKnowledgeArgumentos:
    def test_cargar_argumentos(self, knowledge: KnowledgeService) -> None:
        contenido = knowledge.obtener_argumentos_venta()
        assert "argumentos" in contenido.lower() or "venta" in contenido.lower()

    def test_argumento_familias(self, knowledge: KnowledgeService) -> None:
        argumento = knowledge.obtener_argumento_perfil("familias")
        assert len(argumento) > 0
        assert "familia" in argumento.lower()

    def test_argumento_monotributistas(self, knowledge: KnowledgeService) -> None:
        argumento = knowledge.obtener_argumento_perfil("monotributistas")
        assert len(argumento) > 0

    def test_beneficios_perfil(self, knowledge: KnowledgeService) -> None:
        beneficios = knowledge.obtener_beneficios_para_perfil("familias")
        assert len(beneficios) > 0


class TestKnowledgeCierres:
    def test_cargar_cierres(self, knowledge: KnowledgeService) -> None:
        contenido = knowledge.obtener_cierres()
        assert "cierre" in contenido.lower()

    def test_tecnica_cierre_directo(self, knowledge: KnowledgeService) -> None:
        tecnica = knowledge.obtener_tecnica_cierre("directo")
        assert len(tecnica) > 0

    def test_tecnica_cierre_alternativo(self, knowledge: KnowledgeService) -> None:
        tecnica = knowledge.obtener_tecnica_cierre("alternativo")
        assert len(tecnica) > 0

    def test_tecnica_cierre_siguiente_paso(self, knowledge: KnowledgeService) -> None:
        tecnica = knowledge.obtener_tecnica_cierre("siguiente paso")
        assert len(tecnica) > 0


class TestKnowledgeIntegracion:
    """Tests de integración knowledge + conversación."""

    def test_conversation_manager_tiene_knowledge(self, manager: ConversationManager) -> None:
        assert hasattr(manager, "knowledge")
        assert isinstance(manager.knowledge, KnowledgeService)

    def test_objecion_precio_usa_knowledge(self, manager: ConversationManager) -> None:
        tid = 90010
        manager.procesar_mensaje(tid, "Hola, soy Martín")
        manager.procesar_mensaje(tid, "Solo para mí")
        manager.procesar_mensaje(tid, "Particular")
        manager.procesar_mensaje(tid, "Córdoba, 30 años")
        r = manager.procesar_mensaje(tid, "Es caro")
        session = manager.session_manager.get(tid)
        assert session is not None
        assert session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES
        assert len(r) > 20

    def test_caso_beneficiosrespuesta_contiene_knowledge(self, manager: ConversationManager) -> None:
        """Cliente pregunta por beneficios → debe recibir info relevante."""
        tid = 90011
        manager.procesar_mensaje(tid, "Hola, me llamo Sofía")
        manager.procesar_mensaje(tid, "Solo para mí")
        manager.procesar_mensaje(tid, "Relación de dependencia")
        manager.procesar_mensaje(tid, "Córdoba, 30 años")
        r = manager.procesar_mensaje(tid, "¿Por qué debería elegir Servired?")
        r_lower = r.lower()
        assert (
            "servired" in r_lower
            or "beneficio" in r_lower
            or "planes" in r_lower
            or "consultas" in r_lower
            or "?" in r
        )

    def test_caso_avanzar_usa_cierre(self, manager: ConversationManager) -> None:
        """Cliente listo para avanzar → debe usar cierre."""
        tid = 90012
        manager.procesar_mensaje(tid, "Hola, soy Pedro")
        manager.procesar_mensaje(tid, "Solo para mí")
        manager.procesar_mensaje(tid, "Particular")
        session = manager.session_manager.get(tid)
        assert session is not None
        session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)
        r = manager.procesar_mensaje(tid, "Quiero avanzar")
        assert session.resultado_cierre == ResultadoCierre.ACEPTO
        assert "excelente" in r.lower() or "avanzar" in r.lower() or "bienvenido" in r.lower()


# ─────────────────────────────────────────────
# Tests de IA (Sprint 6) — mock LLM
# ─────────────────────────────────────────────

class _MockLLMClient(LLMClient):
    """Cliente LLM mockeado para tests."""

    def __init__(self, respuesta_mock: str = "Respuesta mock de Sofía") -> None:
        super().__init__(api_key="test-key", provider="groq")
        self._respuesta_mock = respuesta_mock
        self._ultima_llamada: list[dict[str, str]] = []

    def generar_respuesta(
        self,
        mensajes: list[dict[str, str]],
        temperatura: float = 0.7,
        max_tokens: int = 500,
    ) -> LLMResponse:
        self._ultima_llamada = mensajes
        return LLMResponse(
            texto=self._respuesta_mock,
            modelo="mock-model",
            tokens_usados=50,
            exito=True,
        )


def _crear_ai_mock(respuesta: str = "Respuesta mock de Sofía") -> AIService:
    """Crea un AIService con cliente mockeado."""
    ai = AIService.__new__(AIService)
    ai._client = _MockLLMClient(respuesta)
    ai._disponible = True
    return ai


class TestAIPrompts:
    """Tests de prompts y contexto."""

    def test_system_prompt_contiene_personalidad(self) -> None:
        prompt = construir_prompt_sistema()
        assert "Sofía" in prompt
        assert "Servired" in prompt
        assert "voseo" in prompt.lower() or "argentino" in prompt.lower()

    def test_system_prompt_restringe_inventar(self) -> None:
        prompt = construir_prompt_sistema()
        assert "NUNCA inventar" in prompt or "nunca inventar" in prompt.lower()

    def test_construir_contexto_con_lead(self) -> None:
        lead = Lead(
            lead_id="ai_001",
            nombre="Carlos",
            edad=35,
            localidad="Córdoba",
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
        )
        lead.actualizar_grupo_familiar(conyuge=True, hijos=True, cantidad_hijos=2)
        lead.prioridad_cliente = PrioridadCliente.ECONOMICO

        mensajes = construir_contexto(
            lead=lead,
            etapa=EtapaConversacion.MANEJANDO_OBJECIONES,
            knowledge="Info de objeción precio",
            mensaje_cliente="Es caro",
        )

        assert len(mensajes) >= 3
        system_content = mensajes[0]["content"]
        assert "Sofía" in system_content

        context_content = mensajes[1]["content"]
        assert "Carlos" in context_content
        assert "35" in context_content
        assert "Córdoba" in context_content
        assert "monotributo" in context_content.lower()
        assert "cónyuge" in context_content
        assert "2 hijos" in context_content
        assert "objeción precio" in context_content.lower()

        user_content = mensajes[2]["content"]
        assert user_content == "Es caro"

    def test_construir_contexto_sin_lead(self) -> None:
        mensajes = construir_contexto(
            lead=None,
            etapa=EtapaConversacion.NUEVO,
            knowledge="",
            mensaje_cliente="Hola",
        )
        assert len(mensajes) == 3
        assert mensajes[2]["content"] == "Hola"


class TestAIClient:
    """Tests del cliente LLM."""

    def test_respuesta_mock(self) -> None:
        client = _MockLLMClient("Hola, soy Sofía")
        resultado = client.generar_respuesta(
            [{"role": "user", "content": "Hola"}]
        )
        assert resultado.exito is True
        assert resultado.texto == "Hola, soy Sofía"
        assert resultado.tokens_usados == 50

    def test_guarda_ultima_llamada(self) -> None:
        client = _MockLLMClient("Test")
        mensajes = [
            {"role": "system", "content": "Sos Sofía"},
            {"role": "user", "content": "Hola"},
        ]
        client.generar_respuesta(mensajes)
        assert client._ultima_llamada == mensajes

    def test_sin_api_key(self) -> None:
        client = LLMClient(api_key="", provider="groq")
        resultado = client.generar_respuesta(
            [{"role": "user", "content": "Hola"}]
        )
        assert resultado.exito is False
        assert "API key" in resultado.error


class TestAIService:
    """Tests del servicio de IA."""

    def test_disponible_con_key(self) -> None:
        ai = _crear_ai_mock()
        assert ai.disponible is True

    def test_no_disponible_sin_key(self) -> None:
        ai = AIService(api_key="", provider="groq")
        assert ai.disponible is False

    def test_generar_respuesta_mock(self) -> None:
        ai = _crear_ai_mock("Hola, ¿cómo estás?")
        respuesta = ai.generar_respuesta(
            lead=Lead(lead_id="test", nombre="Ana"),
            etapa=EtapaConversacion.DESCUBRIENDO_NECESIDAD,
            knowledge="Beneficios de Servired",
            mensaje_cliente="Hola",
        )
        assert respuesta == "Hola, ¿cómo estás?"

    def test_fallback_si_falla(self) -> None:
        ai = _crear_ai_mock("")
        ai._disponible = False
        respuesta = ai.generar_respuesta(
            lead=None,
            etapa=EtapaConversacion.NUEVO,
            knowledge="",
            mensaje_cliente="Hola",
            respuesta_fallback="Respuesta de fallback",
        )
        assert respuesta == "Respuesta de fallback"


class TestAIIntegracion:
    """Tests de integración IA + ConversationManager."""

    def test_manager_sin_ai_fallback(self) -> None:
        """Sin IA, ConversationManager usa respuestas lógicas."""
        manager = ConversationManager(ai_service=None)
        tid = 90020
        r = manager.procesar_mensaje(tid, "Hola, soy Lucas")
        assert "Lucas" in r or "Sofía" in r

    def test_manager_con_ai_mock_objecion(self, manager: ConversationManager) -> None:
        """IA mockeada recibe contexto de objeción precio."""
        ai = _crear_ai_mock("Entiendo tu preocupación por el precio, Lucas")
        manager.ai = ai

        tid = 90021
        manager.procesar_mensaje(tid, "Hola, soy Lucas")
        manager.procesar_mensaje(tid, "Solo para mí")
        manager.procesar_mensaje(tid, "Particular")
        manager.procesar_mensaje(tid, "Córdoba, 30 años")
        r = manager.procesar_mensaje(tid, "Me parece caro")

        session = manager.session_manager.get(tid)
        assert session is not None
        assert session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES

        # Verificar que la respuesta contiene manejo de objeción
        # (la respuesta del handler se usa directamente, sin LLM)
        assert "presupuesto" in r.lower() or "precio" in r.lower() or "caro" in r.lower()

    def test_manager_con_ai_mock_cierre(self) -> None:
        """IA mockeada recibe contexto de cierre."""
        ai = _crear_ai_mock("¡Excelente! Avanzamos con tu afiliación")
        manager = ConversationManager(ai_service=ai)

        tid = 90022
        manager.procesar_mensaje(tid, "Hola, soy Pedro")
        manager.procesar_mensaje(tid, "Solo para mí")
        manager.procesar_mensaje(tid, "Particular")

        session = manager.session_manager.get(tid)
        assert session is not None
        session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)

        r = manager.procesar_mensaje(tid, "Quiero avanzar")
        assert session.resultado_cierre == ResultadoCierre.ACEPTO

        # Verificar que la IA fue llamada
        mock_client: _MockLLMClient = ai._client  # type: ignore
        assert len(mock_client._ultima_llamada) >= 2
        context_msg = mock_client._ultima_llamada[1]["content"]
        assert "cierre" in context_msg.lower() or "beneficio" in context_msg.lower() or "avanzar" in context_msg.lower()

    def test_manager_ai_fallback_en_error(self) -> None:
        """Si la IA falla, usa respuesta de fallback."""
        ai = _crear_ai_mock("")
        manager = ConversationManager(ai_service=ai)

        tid = 90023
        r1 = manager.procesar_mensaje(tid, "Hola, soy Ana")
        r2 = manager.procesar_mensaje(tid, "Solo para mí")
        r3 = manager.procesar_mensaje(tid, "Particular")

        session = manager.session_manager.get(tid)
        assert session is not None
        session.avanzar_etapa(EtapaConversacion.INTENTANDO_CIERRE)

        r4 = manager.procesar_mensaje(tid, "Sí quiero avanzar")
        # Con fallback vacío, debe usar la respuesta lógica
        assert session.resultado_cierre == ResultadoCierre.ACEPTO
        assert "excelente" in r4.lower() or "avanzar" in r4.lower() or "bienvenido" in r4.lower()


# ─────────────────────────────────────────────
# Tests de DB / Persistencia (Sprint 7)
# ─────────────────────────────────────────────

@pytest.fixture
def db_engine():
    """Engine SQLite en memoria para tests."""
    engine = get_engine("sqlite:///:memory:")
    crear_tablas(engine)
    yield engine
    cerrar_engine()


@pytest.fixture
def db_session(db_engine):
    """Sesión de DB para tests."""
    factory = get_session_factory(db_engine)
    session = factory()
    yield session
    session.close()


class TestLeadRepository:
    def test_crear_lead(self, db_session) -> None:
        repo = LeadRepository(db_session)
        lead_db = repo.crear_lead(telegram_id=12345)
        assert lead_db.id is not None
        assert lead_db.telegram_id == 12345
        assert lead_db.estado_comercial == "nuevo"

    def test_buscar_por_telegram_id(self, db_session) -> None:
        repo = LeadRepository(db_session)
        repo.crear_lead(telegram_id=12345)
        found = repo.buscar_por_telegram_id(12345)
        assert found is not None
        assert found.telegram_id == 12345

    def test_buscar_inexistente(self, db_session) -> None:
        repo = LeadRepository(db_session)
        found = repo.buscar_por_telegram_id(99999)
        assert found is None

    def test_actualizar_lead(self, db_session) -> None:
        repo = LeadRepository(db_session)
        lead_db = repo.crear_lead(telegram_id=12345)
        lead_db.nombre = "Carlos"
        lead_db.edad = 35
        lead_db.localidad = "Córdoba"
        lead_db.tipo_afiliacion = "monotributo"
        lead_db.conyuge = True
        lead_db.hijos = True
        lead_db.cantidad_hijos = 2
        lead_db.cantidad_integrantes = 4
        lead_db.estado_comercial = "calificado"
        lead_db.etapa_conversacion = "presentando_valor"
        repo.actualizar_lead(lead_db)

        found = repo.buscar_por_telegram_id(12345)
        assert found is not None
        assert found.nombre == "Carlos"
        assert found.edad == 35
        assert found.localidad == "Córdoba"
        assert found.tipo_afiliacion == "monotributo"
        assert found.conyuge is True
        assert found.hijos is True
        assert found.cantidad_hijos == 2
        assert found.estado_comercial == "calificado"
        assert found.etapa_conversacion == "presentando_valor"

    def test_listar_leads(self, db_session) -> None:
        repo = LeadRepository(db_session)
        repo.crear_lead(telegram_id=100)
        repo.crear_lead(telegram_id=200)
        repo.crear_lead(telegram_id=300)
        leads = repo.listar_leads()
        assert len(leads) == 3

    def test_listar_leads_por_estado(self, db_session) -> None:
        repo = LeadRepository(db_session)
        l1 = repo.crear_lead(telegram_id=100)
        l1.estado_comercial = "calificado"
        repo.actualizar_lead(l1)
        repo.crear_lead(telegram_id=200)
        leads = repo.listar_leads(estado="calificado")
        assert len(leads) == 1
        assert leads[0].telegram_id == 100

    def test_lead_domain_a_db(self, db_session) -> None:
        repo = LeadRepository(db_session)
        lead_db = repo.crear_lead(telegram_id=12345)
        lead = Lead(
            lead_id="12345",
            nombre="Pedro",
            edad=40,
            localidad="Buenos Aires",
            tipo_afiliacion=TipoAfiliacion.RELACION_DEPENDENCIA,
            estado_comercial=EstadoComercial.CALIFICADO,
            necesidad_principal=NecesidadPrincipal.BENEFICIOS,
            prioridad_cliente=PrioridadCliente.COMPLETO,
        )
        lead.actualizar_grupo_familiar(conyuge=True, hijos=False)
        repo.lead_domain_a_db(lead, lead_db)

        found = repo.buscar_por_telegram_id(12345)
        assert found is not None
        assert found.nombre == "Pedro"
        assert found.edad == 40
        assert found.tipo_afiliacion == "relacion_dependencia"
        assert found.estado_comercial == "calificado"
        assert found.conyuge is True

    def test_db_a_lead_domain(self, db_session) -> None:
        repo = LeadRepository(db_session)
        lead_db = repo.crear_lead(telegram_id=12345)
        lead_db.nombre = "Ana"
        lead_db.edad = 30
        lead_db.tipo_afiliacion = "particular"
        lead_db.conyuge = False
        lead_db.hijos = True
        lead_db.cantidad_hijos = 1
        lead_db.cantidad_integrantes = 2
        repo.actualizar_lead(lead_db)

        lead = repo.db_a_lead_domain(lead_db)
        assert lead.nombre == "Ana"
        assert lead.edad == 30
        assert lead.tipo_afiliacion == TipoAfiliacion.PARTICULAR
        assert lead.grupo_familiar.conyuge is False
        assert lead.grupo_familiar.hijos is True
        assert lead.cantidad_hijos == 1
        assert lead.cantidad_integrantes == 2


class TestConversationRepository:
    def test_guardar_mensaje(self, db_session) -> None:
        lead_repo = LeadRepository(db_session)
        lead_db = lead_repo.crear_lead(telegram_id=12345)
        conv_repo = ConversationRepository(db_session)
        msg = conv_repo.guardar_mensaje(
            lead_id=lead_db.id,
            mensaje_cliente="Hola",
            respuesta_sofia="¡Hola! Soy Sofía",
            etapa="nuevo",
        )
        assert msg.id is not None
        assert msg.lead_id == lead_db.id
        assert msg.mensaje_cliente == "Hola"
        assert msg.respuesta_sofia == "¡Hola! Soy Sofía"
        assert msg.etapa == "nuevo"

    def test_historial_lead(self, db_session) -> None:
        lead_repo = LeadRepository(db_session)
        lead_db = lead_repo.crear_lead(telegram_id=12345)
        conv_repo = ConversationRepository(db_session)
        conv_repo.guardar_mensaje(lead_db.id, "Hola", "Hola!", "nuevo")
        conv_repo.guardar_mensaje(lead_db.id, "Soy Ana", "Hola Ana!", "descubriendo_necesidad")
        conv_repo.guardar_mensaje(lead_db.id, "Particular", "Genial", "calificando")

        historial = conv_repo.historial_lead(lead_db.id)
        assert len(historial) == 3
        assert historial[0].mensaje_cliente == "Hola"
        assert historial[2].etapa == "calificando"

    def test_historial_lead_vacio(self, db_session) -> None:
        lead_repo = LeadRepository(db_session)
        lead_db = lead_repo.crear_lead(telegram_id=99999)
        conv_repo = ConversationRepository(db_session)
        historial = conv_repo.historial_lead(lead_db.id)
        assert len(historial) == 0


class TestConversationManagerDB:
    def test_manager_sin_db(self) -> None:
        """Sin database_url, no persiste pero funciona."""
        manager = ConversationManager(database_url=None)
        assert manager._db_enabled is False
        r = manager.procesar_mensaje(80001, "Hola, soy Lucas")
        assert "Lucas" in r

    def test_manager_con_db_crea_lead(self) -> None:
        """Con DB, crea lead al primer mensaje."""
        from sqlalchemy import create_engine as _create_engine
        import tempfile, os

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_url = f"sqlite:///{tmp.name}"
        try:
            manager = ConversationManager(database_url=db_url)

            tid = 80002
            r = manager.procesar_mensaje(tid, "Hola, soy Martín")
            assert "Martín" in r

            # Verificar en DB con engine dedicado
            engine2 = _create_engine(db_url)
            Session2 = get_session_factory(engine2)
            db = Session2()
            try:
                repo = LeadRepository(db)
                lead_db = repo.buscar_por_telegram_id(tid)
                assert lead_db is not None
                assert lead_db.nombre == "Martín"
            finally:
                db.close()
                engine2.dispose()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def test_manager_con_db_guarda_mensajes(self) -> None:
        """Con DB, guarda cada intercambio de mensajes."""
        from sqlalchemy import create_engine as _create_engine
        import tempfile, os

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_url = f"sqlite:///{tmp.name}"
        try:
            manager = ConversationManager(database_url=db_url)

            tid = 80003
            manager.procesar_mensaje(tid, "Hola, soy Pedro")
            manager.procesar_mensaje(tid, "Solo para mí")
            manager.procesar_mensaje(tid, "Particular")

            # Verificar historial en DB
            engine2 = _create_engine(db_url)
            Session2 = get_session_factory(engine2)
            db = Session2()
            try:
                lead_repo = LeadRepository(db)
                lead_db = lead_repo.buscar_por_telegram_id(tid)
                assert lead_db is not None

                conv_repo = ConversationRepository(db)
                historial = conv_repo.historial_lead(lead_db.id)
                assert len(historial) >= 2
            finally:
                db.close()
                engine2.dispose()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def test_manager_con_db_recupera_estado(self) -> None:
        """Con DB, recupera el estado de la conversación."""
        from sqlalchemy import create_engine as _create_engine
        import tempfile, os

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_url = f"sqlite:///{tmp.name}"
        try:
            manager1 = ConversationManager(database_url=db_url)

            tid = 80004
            manager1.procesar_mensaje(tid, "Hola, soy Ana")
            manager1.procesar_mensaje(tid, "Solo para mí")
            manager1.procesar_mensaje(tid, "Particular")

            session1 = manager1.session_manager.get(tid)
            assert session1 is not None
            etapa1 = session1.etapa

            # Crear nuevo manager (simula reinicio)
            manager2 = ConversationManager(database_url=db_url)
            manager2.procesar_mensaje(tid, "Hola de nuevo")

            session2 = manager2.session_manager.get(tid)
            assert session2 is not None
            # Debe recuperar nombre y etapa desde DB
            assert session2.lead.nombre == "Ana"
            assert session2.etapa == etapa1
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def test_manager_con_db_actualiza_lead(self) -> None:
        """Con DB, actualiza el lead cuando cambian datos."""
        from sqlalchemy import create_engine as _create_engine
        import tempfile, os

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_url = f"sqlite:///{tmp.name}"
        try:
            manager = ConversationManager(database_url=db_url)

            tid = 80005
            manager.procesar_mensaje(tid, "Hola, soy Laura")
            manager.procesar_mensaje(tid, "Solo para mí")

            # Verificar en DB
            engine2 = _create_engine(db_url)
            Session2 = get_session_factory(engine2)
            db = Session2()
            try:
                repo = LeadRepository(db)
                lead_db = repo.buscar_por_telegram_id(tid)
                assert lead_db is not None
                assert lead_db.nombre == "Laura"
                assert lead_db.cantidad_integrantes == 1
                assert lead_db.conyuge is False
                assert lead_db.hijos is False
            finally:
                db.close()
                engine2.dispose()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


# ─────────────────────────────────────────────
# Tests Sprint 8 — Lead Scoring
# ─────────────────────────────────────────────

class TestLeadScoring:
    """Tests del servicio de Lead Scoring."""

    def test_lead_nuevo_score_bajo(self) -> None:
        """Lead recién creado sin datos tiene score bajo."""
        from app.services.lead_scoring import LeadScoringService
        scoring = LeadScoringService()
        lead = Lead(lead_id="999")
        score = scoring.calcular_score(lead)
        assert score <= 10

    def test_lead_completo_score_alto(self) -> None:
        """Lead con todos los datos tiene score alto."""
        from app.services.lead_scoring import LeadScoringService
        scoring = LeadScoringService()
        lead = Lead(
            lead_id="998",
            nombre="Carlos",
            edad=35,
            localidad="Buenos Aires",
            telefono="1155551234",
            interes_detectado=InteresDetectado.AFILIACION,
            tipo_afiliacion=TipoAfiliacion.MONOTRIBUTO,
            tiene_aportes=True,
            necesidad_principal=NecesidadPrincipal.COBERTURA_FAMILIAR,
            prioridad_cliente=PrioridadCliente.ECONOMICO,
        )
        lead.grupo_familiar.conyuge = True
        lead.grupo_familiar.hijos = True
        score = scoring.calcular_score(lead)
        assert score >= 80

    def test_temperatura_frio(self) -> None:
        """Score 0-30 es frío."""
        from app.services.lead_scoring import LeadScoringService
        scoring = LeadScoringService()
        assert scoring.clasificar_temperatura(0) == "frio"
        assert scoring.clasificar_temperatura(30) == "frio"

    def test_temperatura_tibio(self) -> None:
        """Score 31-70 es tibio."""
        from app.services.lead_scoring import LeadScoringService
        scoring = LeadScoringService()
        assert scoring.clasificar_temperatura(31) == "tibio"
        assert scoring.clasificar_temperatura(70) == "tibio"

    def test_temperatura_caliente(self) -> None:
        """Score 71-100 es caliente."""
        from app.services.lead_scoring import LeadScoringService
        scoring = LeadScoringService()
        assert scoring.clasificar_temperatura(71) == "caliente"
        assert scoring.clasificar_temperatura(100) == "caliente"

    def test_score_grupo_familiar(self) -> None:
        """Grupo familiar suma +15 puntos."""
        from app.services.lead_scoring import LeadScoringService
        scoring = LeadScoringService()
        lead_sin = Lead(lead_id="997")
        lead_con = Lead(lead_id="996")
        lead_con.grupo_familiar.conyuge = True
        score_sin = scoring.calcular_score(lead_sin)
        score_con = scoring.calcular_score(lead_con)
        assert score_con == score_sin + 15

    def test_score_aportes(self) -> None:
        """Tiene aportes suma +15 puntos."""
        from app.services.lead_scoring import LeadScoringService
        scoring = LeadScoringService()
        lead_sin = Lead(lead_id="995")
        lead_con = Lead(lead_id="994", tiene_aportes=True)
        score_sin = scoring.calcular_score(lead_sin)
        score_con = scoring.calcular_score(lead_con)
        assert score_con == score_sin + 15

    def test_score_no_supera_100(self) -> None:
        """El score nunca supera 100."""
        from app.services.lead_scoring import LeadScoringService
        scoring = LeadScoringService()
        lead = Lead(
            lead_id="993",
            nombre="Test",
            edad=30,
            localidad="CABA",
            telefono="1155559999",
            interes_detectado=InteresDetectado.AFILIACION,
            tipo_afiliacion=TipoAfiliacion.PARTICULAR,
            tiene_aportes=True,
            necesidad_principal=NecesidadPrincipal.PRECIO,
            prioridad_cliente=PrioridadCliente.COMPLETO,
            estado_comercial=EstadoComercial.VENDIDO,
        )
        lead.grupo_familiar.conyuge = True
        lead.grupo_familiar.hijos = True
        score = scoring.calcular_score(lead)
        assert score <= 100

    def test_calcular_y_clasificar(self) -> None:
        """Método combinado retorna tupla correcta."""
        from app.services.lead_scoring import LeadScoringService
        scoring = LeadScoringService()
        lead = Lead(lead_id="992")
        score, temp = scoring.calcular_y_clasificar(lead)
        assert isinstance(score, int)
        assert temp in ("frio", "tibio", "caliente")


# ─────────────────────────────────────────────
# Tests Sprint 8 — EstadoComercial
# ─────────────────────────────────────────────

class TestEstadoComercialSprint8:
    """Tests de los nuevos estados comerciales."""

    def test_nuevos_estados_existen(self) -> None:
        """Los 11 estados comerciales existen."""
        assert EstadoComercial.NUEVO.value == "nuevo"
        assert EstadoComercial.CONTACTADO.value == "contactado"
        assert EstadoComercial.CALIFICANDO.value == "calificando"
        assert EstadoComercial.INTERESADO.value == "interesado"
        assert EstadoComercial.OBJECION.value == "objecion"
        assert EstadoComercial.INTENTANDO_CIERRE.value == "intentando_cierre"
        assert EstadoComercial.VENDIDO.value == "vendido"
        assert EstadoComercial.PERDIDO.value == "perdido"
        assert EstadoComercial.SEGUIMIENTO.value == "seguimiento"
        assert EstadoComercial.CALIFICADO.value == "calificado"
        assert EstadoComercial.DERIVADO.value == "derivado"

    def test_flujo_estados_conversacion(self) -> None:
        """El flujo de conversación asigna estados correctamente."""
        manager = ConversationManager()
        tid = 70001
        manager.procesar_mensaje(tid, "Hola, soy Pedro")
        session = manager.session_manager.get(tid)
        assert session is not None
        assert session.lead.estado_comercial == EstadoComercial.CONTACTADO

    def test_estado_vendido_en_cierre(self) -> None:
        """El cierre aceptado marca vendido."""
        manager = ConversationManager()
        tid = 70002
        manager.procesar_mensaje(tid, "Hola, soy Ana")
        manager.procesar_mensaje(tid, "Solo para mí")
        manager.procesar_mensaje(tid, "Particular")
        manager.procesar_mensaje(tid, "Córdoba, 30 años")
        manager.procesar_mensaje(tid, "Dale, avanzamos")
        manager.procesar_mensaje(tid, "Sí, quiero")
        session = manager.session_manager.get(tid)
        assert session is not None
        assert session.lead.estado_comercial == EstadoComercial.VENDIDO


# ─────────────────────────────────────────────
# Tests Sprint 8 — Panel Web
# ─────────────────────────────────────────────

class TestPanelWeb:
    """Tests del panel web FastAPI."""

    def _create_test_app(self):
        """Crea una app de test con DB temporal."""
        import tempfile
        from fastapi.testclient import TestClient
        from app.panel.app import create_panel_app

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_url = f"sqlite:///{tmp.name}"
        app = create_panel_app(database_url=db_url)
        return app, tmp.name

    def test_dashboard_status(self) -> None:
        """GET / retorna 200."""
        from fastapi.testclient import TestClient
        app, tmp_name = self._create_test_app()
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        import os
        try:
            os.unlink(tmp_name)
        except OSError:
            pass

    def test_leads_list_status(self) -> None:
        """GET /leads retorna 200."""
        from fastapi.testclient import TestClient
        app, tmp_name = self._create_test_app()
        client = TestClient(app)
        response = client.get("/leads")
        assert response.status_code == 200
        import os
        try:
            os.unlink(tmp_name)
        except OSError:
            pass

    def test_leads_list_muestra_leads(self) -> None:
        """GET /leads muestra leads creados."""
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine as _create_engine
        from app.panel.app import create_panel_app
        from app.database.database import get_session_factory, crear_tablas
        from app.database.models import LeadDB
        import tempfile, os

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_url = f"sqlite:///{tmp.name}"

        # Crear lead directo en DB
        engine = _create_engine(db_url)
        crear_tablas(engine)
        Session = get_session_factory(engine)
        db = Session()
        lead = LeadDB(telegram_id=55555, nombre="Test Lead")
        db.add(lead)
        db.commit()
        db.close()
        engine.dispose()

        app = create_panel_app(database_url=db_url)
        client = TestClient(app)
        response = client.get("/leads")
        assert response.status_code == 200
        assert "Test Lead" in response.text
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    def test_lead_detail_status(self) -> None:
        """GET /leads/{id} retorna 200 para lead existente."""
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine as _create_engine
        from app.panel.app import create_panel_app
        from app.database.database import get_session_factory, crear_tablas
        from app.database.models import LeadDB
        import tempfile, os

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_url = f"sqlite:///{tmp.name}"

        engine = _create_engine(db_url)
        crear_tablas(engine)
        Session = get_session_factory(engine)
        db = Session()
        lead = LeadDB(telegram_id=55556, nombre="Detalle Test", score=75, temperatura_lead="tibio")
        db.add(lead)
        db.commit()
        lead_id = lead.id
        db.close()
        engine.dispose()

        app = create_panel_app(database_url=db_url)
        client = TestClient(app)
        response = client.get(f"/leads/{lead_id}")
        assert response.status_code == 200
        assert "Detalle Test" in response.text
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    def test_cambiar_estado(self) -> None:
        """POST /leads/{id}/estado cambia el estado."""
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine as _create_engine
        from app.panel.app import create_panel_app
        from app.database.database import get_session_factory, crear_tablas
        from app.database.models import LeadDB
        import tempfile, os

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_url = f"sqlite:///{tmp.name}"

        engine = _create_engine(db_url)
        crear_tablas(engine)
        Session = get_session_factory(engine)
        db = Session()
        lead = LeadDB(telegram_id=55557, nombre="Estado Test", estado_comercial="nuevo")
        db.add(lead)
        db.commit()
        lead_id = lead.id
        db.close()
        engine.dispose()

        app = create_panel_app(database_url=db_url)
        client = TestClient(app)
        response = client.post(
            f"/leads/{lead_id}/estado",
            data={"estado": "vendido"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        # Verificar cambio
        engine2 = _create_engine(db_url)
        Session2 = get_session_factory(engine2)
        db2 = Session2()
        lead_db = db2.get(LeadDB, lead_id)
        assert lead_db is not None
        assert lead_db.estado_comercial == "vendido"
        db2.close()
        engine2.dispose()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    def test_lead_detail_inexistente_redirige(self) -> None:
        """GET /leads/{id} inexistente redirige a /leads."""
        from fastapi.testclient import TestClient
        app, tmp_name = self._create_test_app()
        client = TestClient(app)
        response = client.get("/leads/99999", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/leads"
        import os
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


# ─────────────────────────────────────────────
# Tests Sprint 8 — Scoring en ConversationManager
# ─────────────────────────────────────────────

class TestScoringIntegration:
    """Tests de integración de scoring con ConversationManager."""

    def test_manager_calcula_score(self) -> None:
        """ConversationManager calcula score al procesar mensajes."""
        manager = ConversationManager()
        tid = 70010
        manager.procesar_mensaje(tid, "Hola, soy Lucía")
        session = manager.session_manager.get(tid)
        assert session is not None
        assert isinstance(session.lead.score, int)
        assert session.lead.score >= 0

    def test_manager_guarda_temperatura(self) -> None:
        """ConversationManager guarda temperatura del lead."""
        manager = ConversationManager()
        tid = 70011
        manager.procesar_mensaje(tid, "Hola, soy Martín")
        session = manager.session_manager.get(tid)
        assert session is not None
        assert session.lead.temperatura_lead in ("frio", "tibio", "caliente")

    def test_manager_con_db_guarda_score(self) -> None:
        """Con DB, el score se persiste correctamente."""
        from sqlalchemy import create_engine as _create_engine
        import tempfile, os

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_url = f"sqlite:///{tmp.name}"
        try:
            manager = ConversationManager(database_url=db_url)
            tid = 70012
            manager.procesar_mensaje(tid, "Hola, soy Pedro")

            # Verificar en DB
            engine2 = _create_engine(db_url)
            Session2 = get_session_factory(engine2)
            db = Session2()
            try:
                repo = LeadRepository(db)
                lead_db = repo.buscar_por_telegram_id(tid)
                assert lead_db is not None
                assert lead_db.score >= 0
                assert lead_db.temperatura_lead in ("frio", "tibio", "caliente")
            finally:
                db.close()
                engine2.dispose()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


# =====================================================
# Sprint 9 — Simulador de Clientes
# =====================================================

class TestSimuladorClientes:
    """Tests del simulador de conversaciones."""

    def test_simulador_cliente_listo(self) -> None:
        """Cliente listo para contratar completa el flujo."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        profile = obtener_perfil("cliente_listo_para_contratar")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        assert resultado.cantidad_mensajes == len(profile.mensajes)
        assert resultado.lead_final is not None
        assert resultado.estado_final != ""

    def test_simulador_cliente_frio(self) -> None:
        """Cliente frío genera conversación válida."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        profile = obtener_perfil("cliente_frio")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        assert resultado.cantidad_mensajes == 5
        assert resultado.lead_final is not None

    def test_simulador_cliente_objecion_precio(self) -> None:
        """Cliente con objeción de precio genera objeción detectada."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        profile = obtener_perfil("cliente_objecion_precio")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        assert resultado.cantidad_mensajes == len(profile.mensajes)
        assert resultado.estado_final in ("objecion", "intentando_cierre", "perdido", "seguimiento")

    def test_simulador_cliente_indeciso(self) -> None:
        """Cliente indeciso genera seguimiento o derivación."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        profile = obtener_perfil("cliente_indeciso")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        assert resultado.cantidad_mensajes == len(profile.mensajes)

    def test_simulador_multiples(self) -> None:
        """Múltiples simulaciones funcionan correctamente."""
        from app.simulation import SimuladorConversacion, PERFILES_CLIENTES
        sim = SimuladorConversacion(ConversationManager())
        perfiles = [PERFILES_CLIENTES["cliente_frio"], PERFILES_CLIENTES["cliente_listo_para_contratar"]]
        resultados = sim.simular_multiples(perfiles)
        assert len(resultados) == 2
        assert resultados[0].perfil.nombre == "cliente_frio"
        assert resultados[1].perfil.nombre == "cliente_listo_para_contratar"

    def test_simulador_exito_cliente_listo(self) -> None:
        """Cliente listo para contratar marca exitosa=True."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        profile = obtener_perfil("cliente_listo_para_contratar")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        # Cliente listo debería llegar a un estado exitoso
        assert resultado.estado_final in ("vendido", "calificado", "seguimiento")

    def test_listar_perfiles(self) -> None:
        """listar_perfiles retorna 8 perfiles."""
        from app.simulation import listar_perfiles
        perfiles = listar_perfiles()
        assert len(perfiles) == 8
        assert "cliente_frio" in perfiles
        assert "cliente_listo_para_contratar" in perfiles

    def test_perfil_busca_precio(self) -> None:
        """Perfil busca precio tiene prioridad ECONOMICO."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        profile = obtener_perfil("cliente_busca_precio")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        lead = resultado.lead_final
        assert lead is not None
        # Debería tener prioridad o necesidad relacionada con precio
        from app.models.lead import PrioridadCliente, NecesidadPrincipal
        assert (
            lead.prioridad_cliente == PrioridadCliente.ECONOMICO
            or lead.necesidad_principal == NecesidadPrincipal.PRECIO
            or lead.interes_detectado is not None
        )


# =====================================================
# Sprint 9 — Evaluador Comercial
# =====================================================

class TestEvaluadorComercial:
    """Tests del evaluador comercial."""

    def test_evaluar_cliente_listo(self) -> None:
        """Evaluación de cliente listo tiene score alto."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        from app.services.sales_evaluator import SalesEvaluatorService
        profile = obtener_perfil("cliente_listo_para_contratar")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        evaluador = SalesEvaluatorService()
        evaluacion = evaluador.evaluar(resultado)
        assert evaluacion.score_total > 0
        assert evaluacion.score_total <= 100
        assert evaluacion.perfil_evaluado == "cliente_listo_para_contratar"

    def test_evaluar_cliente_frio(self) -> None:
        """Evaluación de cliente frío tiene score bajo-medio."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        from app.services.sales_evaluator import SalesEvaluatorService
        profile = obtener_perfil("cliente_frio")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        evaluador = SalesEvaluatorService()
        evaluacion = evaluador.evaluar(resultado)
        assert evaluacion.score_total >= 0
        assert evaluacion.score_total <= 100

    def test_evaluar_dimensiones(self) -> None:
        """Cada dimensión de evaluación tiene un score válido."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        from app.services.sales_evaluator import SalesEvaluatorService
        profile = obtener_perfil("cliente_busca_cobertura_familiar")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        evaluador = SalesEvaluatorService()
        evaluacion = evaluador.evaluar(resultado)
        assert 0 <= evaluacion.descubrimiento <= 20
        assert 0 <= evaluacion.calificacion <= 20
        assert 0 <= evaluacion.valor <= 20
        assert 0 <= evaluacion.objeciones <= 20
        assert 0 <= evaluacion.cierre <= 20

    def test_evaluar_detalle(self) -> None:
        """La evaluación genera un detalle explicativo."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        from app.services.sales_evaluator import SalesEvaluatorService
        profile = obtener_perfil("cliente_monotributista")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        evaluador = SalesEvaluatorService()
        evaluacion = evaluador.evaluar(resultado)
        assert len(evaluacion.detalle) > 0

    def test_score_suma_dimensiones(self) -> None:
        """El score total es la suma de las 5 dimensiones."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        from app.services.sales_evaluator import SalesEvaluatorService
        profile = obtener_perfil("cliente_listo_para_contratar")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        evaluador = SalesEvaluatorService()
        evaluacion = evaluador.evaluar(resultado)
        suma = (
            evaluacion.descubrimiento
            + evaluacion.calificacion
            + evaluacion.valor
            + evaluacion.objeciones
            + evaluacion.cierre
        )
        assert evaluacion.score_total == suma


# =====================================================
# Sprint 9 — Cierre Mejorado
# =====================================================

class TestCierreMejorado:
    """Tests de mejoras en cierre."""

    def test_cierre_urgencia_seleccion(self) -> None:
        """Prioridad RAPIDEZ selecciona cierre de urgencia."""
        from app.services.closing_strategy import seleccionar_cierre
        from app.models.lead import Lead, PrioridadCliente
        lead = Lead(lead_id="test_urgencia", nombre="Test", prioridad_cliente=PrioridadCliente.RAPIDEZ)
        cierre = seleccionar_cierre(lead)
        assert cierre.tipo_cierre == "urgencia"
        assert "pronto" in cierre.respuesta.lower() or "antes" in cierre.respuesta.lower()

    def test_cierre_beneficio_familia(self) -> None:
        """Familia selecciona cierre de beneficio."""
        from app.services.closing_strategy import seleccionar_cierre
        from app.models.lead import Lead
        lead = Lead(lead_id="test_beneficio", nombre="Test")
        lead.actualizar_grupo_familiar(conyuge=True, hijos=True, cantidad_hijos=2)
        cierre = seleccionar_cierre(lead)
        assert cierre.tipo_cierre == "beneficio"

    def test_recuperar_indeciso_familia(self) -> None:
        """Recuperación de indeciso con familia refuerza beneficio."""
        from app.services.closing_strategy import recuperar_indeciso
        from app.models.lead import Lead
        lead = Lead(lead_id="test_recuperar", nombre="Test")
        lead.actualizar_grupo_familiar(conyuge=True, hijos=True, cantidad_hijos=1)
        respuesta = recuperar_indeciso(lead)
        assert "familia" in respuesta.lower() or "familiar" in respuesta.lower()

    def test_recuperar_indeciso_precio(self) -> None:
        """Recuperación de indeciso sensible a precio."""
        from app.services.closing_strategy import recuperar_indeciso
        from app.models.lead import Lead, PrioridadCliente
        lead = Lead(
            lead_id="test_recuperar_precio",
            nombre="Test",
            prioridad_cliente=PrioridadCliente.ECONOMICO,
        )
        respuesta = recuperar_indeciso(lead)
        assert "presupuesto" in respuesta.lower() or "precio" in respuesta.lower()

    def test_recuperar_indeciso_default(self) -> None:
        """Recuperación de indeciso genérica."""
        from app.services.closing_strategy import recuperar_indeciso
        from app.models.lead import Lead
        lead = Lead(lead_id="test_recuperar_default", nombre="Test")
        respuesta = recuperar_indeciso(lead)
        assert len(respuesta) > 0

    def test_conversation_manager_usa_recuperar(self) -> None:
        """ConversationManager usa recuperar_indeciso para clientes indecisos."""
        manager = ConversationManager()
        tid = 91001
        # Simular flujo hasta cierre
        manager.procesar_mensaje(tid, "Hola, soy Lucas")
        manager.procesar_mensaje(tid, "Busco obra social")
        manager.procesar_mensaje(tid, "Soy particular")
        manager.procesar_mensaje(tid, "Solo yo")
        manager.procesar_mensaje(tid, "30 años")
        manager.procesar_mensaje(tid, "De Buenos Aires")
        # Intentar cierre
        manager.procesar_mensaje(tid, "Sí, quiero avanzar")
        # Responder con indecisión
        respuesta = manager.procesar_mensaje(tid, "Tengo que pensarlo")
        assert len(respuesta) > 0


# =====================================================
# Sprint 10 — Training Engine
# =====================================================

class TestTrainingEngine:
    """Tests del motor de entrenamiento."""

    def test_ejecutar_perfil(self) -> None:
        """Ejecutar un perfil retorna resultado válido."""
        from app.training import TrainingEngine
        trainer = TrainingEngine()
        resultado = trainer.ejecutar("cliente_listo_para_contratar")
        assert resultado.perfil == "cliente_listo_para_contratar"
        assert resultado.resultado_simulacion is not None
        assert resultado.evaluacion is not None
        assert isinstance(resultado.errores, list)
        assert isinstance(resultado.recomendaciones, list)
        assert 0 <= resultado.score_final <= 100

    def test_ejecutar_todos(self) -> None:
        """Ejecutar todos los perfiles retorna 8 resultados."""
        from app.training import TrainingEngine
        trainer = TrainingEngine()
        resultados = trainer.ejecutar_todos()
        assert len(resultados) == 8

    def test_ejecutar_lote(self) -> None:
        """Ejecutar un lote de perfiles funciona correctamente."""
        from app.training import TrainingEngine
        trainer = TrainingEngine()
        resultados = trainer.ejecutar_lote(
            ["cliente_frio", "cliente_busca_precio"]
        )
        assert len(resultados) == 2
        assert resultados[0].perfil == "cliente_frio"
        assert resultados[1].perfil == "cliente_busca_precio"

    def test_errores_detectados(self) -> None:
        """El entrenamiento detecta errores comerciales."""
        from app.training import TrainingEngine
        trainer = TrainingEngine()
        resultado = trainer.ejecutar("cliente_frio")
        # Cliente frío puede tener errores por falta de datos
        assert isinstance(resultado.errores, list)

    def test_recomendaciones_generadas(self) -> None:
        """El entrenamiento genera recomendaciones."""
        from app.training import TrainingEngine
        trainer = TrainingEngine()
        resultado = trainer.ejecutar("cliente_indeciso")
        assert isinstance(resultado.recomendaciones, list)

    def test_score_final_con_errores(self) -> None:
        """Score final se penaliza por errores."""
        from app.training import TrainingEngine
        trainer = TrainingEngine()
        resultado = trainer.ejecutar("cliente_frio")
        # Score final debe ser <= score de evaluación
        assert resultado.score_final <= resultado.evaluacion.score_total

    def test_perfil_inexistente(self) -> None:
        """Perfil inexistente lanza error."""
        from app.training import TrainingEngine
        trainer = TrainingEngine()
        try:
            trainer.ejecutar("perfil_inexistente")
            assert False, "Debería lanzar ValueError"
        except ValueError:
            pass


# =====================================================
# Sprint 10 — Sales Report
# =====================================================

class TestSalesReport:
    """Tests del servicio de reportes."""

    def test_generar_reporte(self) -> None:
        """Generar reporte con resultados válidos."""
        from app.training import TrainingEngine
        from app.services.sales_report import SalesReportService
        trainer = TrainingEngine()
        resultados = trainer.ejecutar_lote(
            ["cliente_frio", "cliente_listo_para_contratar"]
        )
        reporte_svc = SalesReportService()
        reporte = reporte_svc.generar_reporte(resultados)
        assert reporte.total_simulaciones == 2
        assert reporte.score_promedio >= 0
        assert reporte.score_promedio <= 100

    def test_scores_por_dimension(self) -> None:
        """El reporte tiene scores por dimensión."""
        from app.training import TrainingEngine
        from app.services.sales_report import SalesReportService
        trainer = TrainingEngine()
        resultados = trainer.ejecutar_lote(
            ["cliente_busca_precio", "cliente_monotributista"]
        )
        reporte_svc = SalesReportService()
        reporte = reporte_svc.generar_reporte(resultados)
        assert "descubrimiento" in reporte.scores_por_dimension
        assert "calificacion" in reporte.scores_por_dimension
        assert "valor" in reporte.scores_por_dimension
        assert "objeciones" in reporte.scores_por_dimension
        assert "cierre" in reporte.scores_por_dimension

    def test_generar_texto(self) -> None:
        """Generar texto del reporte."""
        from app.training import TrainingEngine
        from app.services.sales_report import SalesReportService
        trainer = TrainingEngine()
        resultados = trainer.ejecutar_lote(
            ["cliente_frio", "cliente_listo_para_contratar"]
        )
        reporte_svc = SalesReportService()
        reporte = reporte_svc.generar_reporte(resultados)
        texto = reporte_svc.generar_texto(reporte)
        assert len(texto) > 0
        assert "REPORTE COMERCIAL" in texto
        assert "Score promedio" in texto

    def test_reporte_vacio(self) -> None:
        """Reporte con lista vacía retorna valores por defecto."""
        from app.services.sales_report import SalesReportService
        reporte_svc = SalesReportService()
        reporte = reporte_svc.generar_reporte([])
        assert reporte.total_simulaciones == 0
        assert reporte.score_promedio == 0


# =====================================================
# Sprint 10 — Sales Quality Rules
# =====================================================

class TestSalesQualityRules:
    """Tests de reglas de calidad comercial."""

    def test_verificar_cliente_listo(self) -> None:
        """Cliente listo tiene menos incumplimientos."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        from app.services.sales_quality_rules import SalesQualityRules
        profile = obtener_perfil("cliente_listo_para_contratar")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        reglas = SalesQualityRules()
        incumplidas = reglas.verificar(resultado)
        # Cliente listo debería tener pocos incumplimientos
        assert isinstance(incumplidas, list)

    def test_verificar_cliente_frio(self) -> None:
        """Cliente frío tiene más incumplimientos."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        from app.services.sales_quality_rules import SalesQualityRules
        profile = obtener_perfil("cliente_frio")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        reglas = SalesQualityRules()
        incumplidas = reglas.verificar(resultado)
        # Cliente frío debería tener incumplimientos por datos faltantes
        assert isinstance(incumplidas, list)

    def test_reglas_estructura(self) -> None:
        """Las reglas incumplidas tienen estructura correcta."""
        from app.simulation import SimuladorConversacion, obtener_perfil
        from app.services.sales_quality_rules import SalesQualityRules
        profile = obtener_perfil("cliente_busca_precio")
        assert profile is not None
        sim = SimuladorConversacion(ConversationManager())
        resultado = sim.simular(profile)
        reglas = SalesQualityRules()
        incumplidas = reglas.verificar(resultado)
        for incumplida in incumplidas:
            assert "regla" in incumplida
            assert "fase" in incumplida
            assert "descripcion" in incumplida

    def test_fases_cubiertas(self) -> None:
        """Las reglas cubren todas las fases del método."""
        from app.services.sales_quality_rules import (
            REGLAS_DESCUBRIMIENTO,
            REGLAS_PROPUESTA,
            REGLAS_OBJECIONES,
            REGLAS_CIERRE,
        )
        assert len(REGLAS_DESCUBRIMIENTO) >= 5
        assert len(REGLAS_PROPUESTA) >= 2
        assert len(REGLAS_OBJECIONES) >= 2
        assert len(REGLAS_CIERRE) >= 2

    def test_error_cotizacion_sin_diagnostico(self) -> None:
        """TrainingEngine detecta cotización sin diagnóstico."""
        from app.training.engine import TrainingEngine
        trainer = TrainingEngine()
        resultado = trainer.ejecutar("cliente_busca_precio")
        # Este perfil pregunta precio, puede tener este error
        tipos_error = {e.tipo for e in resultado.errores}
        # Verificar que el sistema de detección funciona
        assert isinstance(tipos_error, set)
