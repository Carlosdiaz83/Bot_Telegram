"""
Sistema de Lead Scoring para el funnel comercial SERVIRED.

Calcula un puntaje (0-100) basado en los datos del lead y lo clasifica
en temperaturas: frío, tibio o caliente.

Uso:
    from app.services.lead_scoring import LeadScoringService
    scoring = LeadScoringService()
    score = scoring.calcular_score(lead)
    temp = scoring.clasificar_temperatura(score)
"""

from __future__ import annotations

from app.models.lead import (
    EstadoComercial,
    InteresDetectado,
    Lead,
    TipoAfiliacion,
)


class LeadScoringService:
    """
    Servicio de scoring comercial.

    Evalúa la probabilidad de conversión de un lead basándose en:
    - Intención de afiliación
    - Composición del grupo familiar
    - Situación laboral (aportes)
    - Datos completos del perfil
    - Etapa del funnel
    """

    def calcular_score(self, lead: Lead) -> int:
        """
        Calcula el puntaje del lead (0-100).

        Args:
            lead: Lead de dominio con datos recopilados.

        Returns:
            Puntaje numérico entre 0 y 100.
        """
        score = 0

        # +20: Intención de afiliación directa
        if lead.interes_detectado == InteresDetectado.AFILIACION:
            score += 20

        # +15: Tiene grupo familiar (cónyuge o hijos)
        if lead.grupo_familiar.conyuge or lead.grupo_familiar.hijos:
            score += 15

        # +15: Tiene aportes previos
        if lead.tiene_aportes is True:
            score += 15

        # +10: Necesidad principal definida
        if lead.necesidad_principal is not None:
            score += 10

        # +10: Prioridad definida
        if lead.prioridad_cliente is not None:
            score += 10

        # +10: Tipo de afiliación definido
        if lead.tipo_afiliacion is not None:
            score += 10

        # +5: Edad conocida
        if lead.edad is not None:
            score += 5

        # +5: Localidad conocida
        if lead.localidad is not None:
            score += 5

        # +10: Teléfono disponible (listo para contacto)
        if lead.telefono is not None:
            score += 10

        # Bonificación por etapa del funnel
        score += self._bonus_por_estado(lead.estado_comercial)

        return min(score, 100)

    def clasificar_temperatura(self, score: int) -> str:
        """
        Clasifica el puntaje en una temperatura comercial.

        Args:
            score: Puntaje calculado (0-100).

        Returns:
            "frío", "tibio" o "caliente".
        """
        if score <= 30:
            return "frio"
        if score <= 70:
            return "tibio"
        return "caliente"

    def _bonus_por_estado(self, estado: EstadoComercial) -> int:
        """
        Bonificación adicional según la etapa del funnel.

        Leads en etapas avanzadas tienen mayor probabilidad
        de conversión.
        """
        bonificaciones = {
            EstadoComercial.NUEVO: 0,
            EstadoComercial.CONTACTADO: 0,
            EstadoComercial.CALIFICANDO: 5,
            EstadoComercial.INTERESADO: 10,
            EstadoComercial.OBJECION: 5,
            EstadoComercial.INTENTANDO_CIERRE: 15,
            EstadoComercial.VENDIDO: 20,
            EstadoComercial.SEGUIMIENTO: 5,
            EstadoComercial.CALIFICADO: 10,
            EstadoComercial.DERIVADO: 10,
            EstadoComercial.CERRADO: 20,
        }
        return bonificaciones.get(estado, 0)

    def calcular_y_clasificar(self, lead: Lead) -> tuple[int, str]:
        """
        Calcula score y temperatura en una sola llamada.

        Args:
            lead: Lead de dominio.

        Returns:
            Tupla (score, temperatura).
        """
        score = self.calcular_score(lead)
        temperatura = self.clasificar_temperatura(score)
        return score, temperatura
