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

        # Calificación — situación actual
        r3 = manager.procesar_mensaje(tid, "Soy monotributista")
        assert "monotributo" in r3.lower() or "monotribut" in r3.lower() or "¿" in r3

        # Calificación — seguir respondiendo
        r4 = manager.procesar_mensaje(tid, "Sí, tengo aportes")
        r5 = manager.procesar_mensaje(tid, "Soy de Córdoba")
        r6 = manager.procesar_mensaje(tid, "Tengo 35 años")

        session = manager.session_manager.get(tid)
        assert session is not None
        # Debería estar en valor o cierre
        assert session.etapa in (
            EtapaConversacion.PRESENTANDO_VALOR,
            EtapaConversacion.INTENTANDO_CIERRE,
            EtapaConversacion.CALIFICADO,
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

        # Objeción de precio
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
        r = manager.procesar_mensaje(tid, "¿Por qué debería elegir Servired?")
        assert "servired" in r.lower() or "beneficio" in r.lower() or "?" in r

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
        r = manager.procesar_mensaje(tid, "Me parece caro")

        session = manager.session_manager.get(tid)
        assert session is not None
        assert session.etapa == EtapaConversacion.MANEJANDO_OBJECIONES

        # Verificar que la IA fue llamada
        mock_client: _MockLLMClient = ai._client  # type: ignore
        assert len(mock_client._ultima_llamada) >= 2
        context_msg = mock_client._ultima_llamada[1]["content"]
        assert "objeción" in context_msg.lower() or "precio" in context_msg.lower()

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
