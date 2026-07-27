"""
Calculadora comercial SERVIRED.

Calcula aportes de obra social, valor de planes y valor final a pagar.
Los precios se obtienen de la base de conocimiento (KnowledgeRepository).

Uso:
    from app.services.servired_calculator import ServiredCalculator
    calc = ServiredCalculator(knowledge_engine)
    resultado = calc.cotizar(lead, conceptos_obra_social, zona="cordoba")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.database.repository import KnowledgeRepository, PriceRepository
from app.models.lead import Lead

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────

# Fórmula de aportes obra social:
#   conceptos_obra_social * 33.33 * 7 / 100
FACTOR_APORTES = 33.33 * 7 / 100  # ≈ 2.3331

# Edad máxima para Plan Joven
EDAD_MAXIMA_PLAN_JOVEN = 30

# Planes conocidos SERVIRED (keywords para buscar en knowledge)
PLANES_CONOCIDOS = [
    "medimax co",
    "medimax",
    "medimax gold",
    "gold",
]


# ─────────────────────────────────────────
# Resultado de cotización
# ─────────────────────────────────────────

@dataclass
class IntegranteCotizacion:
    """Datos de un integrante para cotización."""
    nombre: str
    edad: int
    es_titular: bool = False


@dataclass
class CotizacionResult:
    """
    Resultado completo de una cotización SERVIRED.

    Attributes:
        plan: Nombre del plan cotizado.
        zona: "cordoba" o "interior".
        integrantes: Lista de integrantes cotizados.
        valor_plan_total: Valor total del plan para todos los integrantes.
        aportes_calculados: Aportes de obra social calculados.
        valor_a_pagar: Valor final a pagar (plan - aportes).
        plan_joven_disponible: Si el Plan Joven está disponible.
        plan_joven_rechazado: Si se rechazó Plan Joven por edad.
        desglose_por_integrante: Valor por integrante.
        observaciones: Notas adicionales.
    """
    plan: str
    zona: str
    integrantes: list[IntegranteCotizacion]
    valor_plan_total: float
    aportes_calculados: float
    valor_a_pagar: float
    plan_joven_disponible: bool
    plan_joven_rechazado: bool = False
    desglose_por_integrante: list[dict] = field(default_factory=list)
    observaciones: list[str] = field(default_factory=list)


# ─────────────────────────────────────────
# Calculadora
# ─────────────────────────────────────────

class ServiredCalculator:
    """
    Motor de cálculo comercial SERVIRED.

    Calcula aportes, valor de planes y valor final a pagar.
    Los precios se obtienen de la base de conocimiento.
    """

    def __init__(self, db: Session, price_repository: PriceRepository | None = None) -> None:
        """
        Args:
            db: Sesión de base de datos.
            price_repository: Repositorio de precios estructurados (opcional).
                              Si se provee, se usa como fuente principal de precios.
        """
        self._repo = KnowledgeRepository(db)
        self._price_repo = price_repository

    # ─────────────────────────────────────────
    # Cálculo de aportes
    # ─────────────────────────────────────────

    def calcular_aportes(self, conceptos_obra_social: list[float]) -> float:
        """
        Calcula los aportes de obra social a partir de conceptos del recibo.

        Fórmula:
            total_conceptos * 33.33 * 7 / 100

        Args:
            conceptos_obra_social: Lista de montos de conceptos de obra social
                                   detectados en el recibo de sueldo.

        Returns:
            Monto total de aportes calculados.
        """
        if not conceptos_obra_social:
            return 0.0

        total_conceptos = sum(conceptos_obra_social)
        aportes = total_conceptos * FACTOR_APORTES

        logger.info(
            "[CALCULATOR] Aportes: conceptos=%s, total=%.2f, aportes=%.2f",
            conceptos_obra_social, total_conceptos, aportes,
        )
        return round(aportes, 2)

    # ─────────────────────────────────────────
    # Detección de Plan Joven
    # ─────────────────────────────────────────

    def verificar_plan_joven(self, edades: list[int]) -> tuple[bool, bool]:
        """
        Verifica si el Plan Joven está disponible.

        Regla: TODOS los integrantes deben tener ≤30 años.

        Args:
            edades: Lista de edades de todos los integrantes.

        Returns:
            Tuple (disponible, rechazado):
                disponible: True si todos tienen ≤30.
                rechazado: True si alguno tiene >30.
        """
        if not edades:
            return False, False

        todos_jovenes = all(edad <= EDAD_MAXIMA_PLAN_JOVEN for edad in edades)
        alguno_no_joven = any(edad > EDAD_MAXIMA_PLAN_JOVEN for edad in edades)

        if todos_jovenes:
            logger.info(
                "[CALCULATOR] Plan Joven disponible: edades=%s",
                edades,
            )
            return True, False

        if alguno_no_joven:
            logger.info(
                "[CALCULATOR] Plan Joven NO disponible (edad > %d): edades=%s",
                EDAD_MAXIMA_PLAN_JOVEN, edades,
            )
            return False, True

        return False, False

    # ─────────────────────────────────────────
    # Obtención de precios desde knowledge
    # ─────────────────────────────────────────

    def _obtener_precio_tabla(
        self,
        tipo_afiliacion: str,
        nombre_plan: str,
        zona: str,
        edad: int | None = None,
    ) -> float | None:
        """
        Busca precio en la tabla estructurada ServiredPriceDB.

        Método principal de obtención de precios cuando se tiene
        PriceRepository disponible.

        Args:
            tipo_afiliacion: particular|monotributo|relacion_dependencia
            nombre_plan: Nombre normalizado del plan
            zona: cordoba|interior
            edad: Edad del integrante (opcional)

        Returns:
            Precio encontrado, o None.
        """
        if self._price_repo is None:
            return None

        precio_db = self._price_repo.buscar_precio(
            tipo_afiliacion=tipo_afiliacion,
            plan=nombre_plan,
            zona=zona,
            edad=edad,
        )

        if precio_db:
            logger.debug(
                "[CALCULATOR] Precio desde tabla: tipo=%s, plan=%s, zona=%s, "
                "edad=%s -> $%.2f",
                tipo_afiliacion, nombre_plan, zona, edad, precio_db.precio,
            )
            return precio_db.precio

        return None

    def _obtener_precios_plan(
        self, nombre_plan: str, zona: str
    ) -> dict[str, float] | None:
        """
        Busca precios de un plan en la base de conocimiento.

        Busca en categoría "precios" y "planes" registros que contengan
        el nombre del plan y parsea los valores encontrados.

        Args:
            nombre_plan: Nombre del plan (ej: "medimax", "gold").
            zona: "cordoba" o "interior".

        Returns:
            Dict con precios por zona, o None si no se encontraron.
        """
        nombre_lower = nombre_plan.lower().strip()

        # Buscar en categoría precios
        items_precios = self._repo.buscar_por_categoria("precios")
        for item in items_precios:
            precios = self._parsear_precios(item.contenido, nombre_lower, zona)
            if precios:
                return precios

        # Buscar en categoría planes
        items_planes = self._repo.buscar_por_categoria("planes")
        for item in items_planes:
            precios = self._parsear_precios(item.contenido, nombre_lower, zona)
            if precios:
                return precios

        # Búsqueda por tags
        tags = [nombre_lower.replace(" ", "_"), nombre_lower.replace(" ", "-")]
        items_tags = self._repo.buscar_por_tags(tags, limite=5)
        for item in items_tags:
            precios = self._parsear_precios(item.contenido, nombre_lower, zona)
            if precios:
                return precios

        # Búsqueda por texto
        items_texto = self._repo.buscar_por_texto(nombre_plan, limite=5)
        for item in items_texto:
            precios = self._parsear_precios(item.contenido, nombre_lower, zona)
            if precios:
                return precios

        logger.warning(
            "[CALCULATOR] No se encontraron precios para plan '%s' en zona '%s'",
            nombre_plan, zona,
        )
        return None

    def _parsear_precios(
        self, contenido: str, nombre_plan: str, zona_buscada: str
    ) -> dict[str, float] | None:
        """
        Parsea precios de un contenido de knowledge.

        Busca patrones como:
            - "Medimax: $15.000 (Córdoba), $13.000 (Interior)"
            - "Plan Gold desde $25.000"
            - "Medimax Gold: Cordoba $30000 Interior $28000"

        Returns:
            Dict con precios por zona, o None.
        """
        contenido_lower = contenido.lower()

        # Verificar que el contenido mencione el plan
        if nombre_plan not in contenido_lower:
            return None

        precios: dict[str, float] = {}
        lineas = contenido.split("\n")

        # Buscar la línea exacta que describe este plan
        # Ignorar líneas que son de otros planes (ej: "medimax gold" cuando buscamos "medimax")
        linea_plan_idx = -1
        for i, linea in enumerate(lineas):
            linea_lower = linea.lower().strip()
            # Verificar que la línea menciona el plan
            if nombre_plan in linea_lower:
                # Excluir líneas de otros planes que contengan nuestro nombre como subcadena
                es_linea_otro_plan = False
                for otro_plan in PLANES_CONOCIDOS:
                    if otro_plan == nombre_plan:
                        continue
                    if otro_plan not in linea_lower:
                        continue
                    # No excluir si nuestro plan empieza con el otro plan
                    # (ej: "medimax gold" empieza con "medimax")
                    if nombre_plan.startswith(otro_plan):
                        continue
                    # Excluir solo si la línea empieza con el otro plan
                    # (ej: línea "medimax co: ..." es de otro plan)
                    linea_limpia = linea_lower.lstrip("- ").strip()
                    if linea_limpia.startswith(otro_plan):
                        es_linea_otro_plan = True
                        break
                if not es_linea_otro_plan:
                    linea_plan_idx = i
                    break

        if linea_plan_idx == -1:
            return None

        # Extraer precios de la línea del plan y las siguientes 2-3 líneas
        precios_encontrados: dict[str, list[float]] = {"cordoba": [], "interior": []}

        for j in range(0, min(4, len(lineas) - linea_plan_idx)):
            linea = lineas[linea_plan_idx + j]
            linea_lower = linea.lower()

            # Patrón especial: "$XX.XXX (Zona), $YY.YYY (Zona2)"
            patron_zona = re.findall(
                r'\$([\d.,]+)\s*\(\s*(c[oó]rdoba|interior)\s*\)',
                linea_lower,
            )
            if patron_zona:
                for monto_str, zona in patron_zona:
                    monto_limpio = monto_str.replace(".", "").replace(",", ".")
                    try:
                        monto = float(monto_limpio)
                        if monto >= 1000:
                            zona_lower = zona.lower().replace("ó", "o")
                            zona_normalizada = "cordoba" if "cordoba" in zona_lower else "interior"
                            precios_encontrados[zona_normalizada].append(monto)
                    except ValueError:
                        continue
                continue

            # Patrón genérico: "$XX.XXX" sin zona explícita
            montos = re.findall(r'\$([\d.,]+)', linea)
            for monto_str in montos:
                monto_limpio = monto_str.replace(".", "").replace(",", ".")
                try:
                    monto = float(monto_limpio)
                    if monto < 1000:
                        continue

                    if "cordoba" in linea_lower:
                        precios_encontrados["cordoba"].append(monto)
                    elif "interior" in linea_lower:
                        precios_encontrados["interior"].append(monto)
                    else:
                        precios_encontrados["cordoba"].append(monto)
                        precios_encontrados["interior"].append(monto)
                except ValueError:
                    continue

        # Tomar el primer precio de cada zona
        if precios_encontrados["cordoba"]:
            precios["cordoba"] = precios_encontrados["cordoba"][0]
        if precios_encontrados["interior"]:
            precios["interior"] = precios_encontrados["interior"][0]

        return precios if precios else None

    # ─────────────────────────────────────────
    # Cálculo de valor del plan
    # ─────────────────────────────────────────

    def calcular_valor_plan(
        self,
        nombre_plan: str,
        zona: str,
        edades: list[int],
        tipo_afiliacion: str = "particular",
    ) -> float | None:
        """
        Calcula el valor total del plan para un grupo de integrantes.

        Usa PriceRepository si está disponible, fallback a KnowledgeRepository.

        Args:
            nombre_plan: Nombre del plan (ej: "medimax").
            zona: "cordoba" o "interior".
            edades: Lista de edades de los integrantes.
            tipo_afiliacion: particular|monotributo|relacion_dependencia

        Returns:
            Valor total del plan, o None si no se encontraron precios.
        """
        precio_total = 0.0
        integrantes_con_precio = 0

        # Intentar con PriceRepository (precio por integrante)
        if self._price_repo is not None:
            for edad in edades:
                precio = self._obtener_precio_tabla(
                    tipo_afiliacion=tipo_afiliacion,
                    nombre_plan=nombre_plan,
                    zona=zona,
                    edad=edad,
                )
                if precio is not None:
                    precio_total += precio
                    integrantes_con_precio += 1

            if integrantes_con_precio > 0:
                logger.info(
                    "[CALCULATOR] Valor plan (tabla): plan='%s', zona='%s', "
                    "tipo=%s, integrantes=%d/%d, total=%.2f",
                    nombre_plan, zona, tipo_afiliacion,
                    integrantes_con_precio, len(edades), precio_total,
                )
                return precio_total if precio_total > 0 else None

        # Fallback: KnowledgeRepository (precio base * cantidad)
        precios = self._obtener_precios_plan(nombre_plan, zona)
        if precios is None:
            return None

        zona_lower = zona.lower().strip()
        precio_base = precios.get(zona_lower)

        if precio_base is None:
            precio_base = next(iter(precios.values()), None)

        if precio_base is None:
            return None

        cantidad = len(edades) if edades else 1
        valor_total = precio_base * cantidad

        logger.info(
            "[CALCULATOR] Valor plan (knowledge): plan='%s', zona='%s', "
            "precio_base=%.2f, integrantes=%d, total=%.2f",
            nombre_plan, zona, precio_base, cantidad, valor_total,
        )
        return valor_total

    # ─────────────────────────────────────────
    # Cotización completa
    # ─────────────────────────────────────────

    def cotizar(
        self,
        lead: Lead,
        conceptos_obra_social: list[float] | None = None,
        zona: str = "cordoba",
        nombre_plan: str = "medimax",
    ) -> CotizacionResult:
        """
        Genera una cotización completa para un lead.

        Args:
            lead: Lead con datos del cliente.
            conceptos_obra_social: Conceptos del recibo de sueldo (opcional).
            zona: "cordoba" o "interior".
            nombre_plan: Nombre del plan a cotizar.

        Returns:
            CotizacionResult con el desglose completo.
        """
        # Construir lista de integrantes
        integrantes = self._construir_integrantes(lead)
        edades = [i.edad for i in integrantes]

        # Detectar tipo de afiliación
        tipo_afiliacion = "particular"
        if lead.tipo_afiliacion:
            tipo_afiliacion = lead.tipo_afiliacion.value

        # Verificar Plan Joven
        plan_joven_disponible, plan_joven_rechazado = self.verificar_plan_joven(edades)

        # Calcular aportes
        aportes = self.calcular_aportes(
            conceptos_obra_social if conceptos_obra_social else []
        )

        # Calcular valor del plan
        valor_plan = self.calcular_valor_plan(
            nombre_plan, zona, edades, tipo_afiliacion,
        )
        if valor_plan is None:
            valor_plan = 0.0
            observaciones = [
                "No se encontraron precios en la base de conocimiento. "
                "Se requiere carga de precios para cotizar."
            ]
        else:
            observaciones = []

        # Calcular valor a pagar
        valor_a_pagar = max(0.0, valor_plan - aportes)

        # Desglose por integrante
        desglose = []
        if valor_plan > 0 and integrantes:
            if self._price_repo is not None:
                # Usar precios individuales de la tabla
                for integrante in integrantes:
                    precio_individual = self._obtener_precio_tabla(
                        tipo_afiliacion=tipo_afiliacion,
                        nombre_plan=nombre_plan,
                        zona=zona,
                        edad=integrante.edad,
                    )
                    desglose.append({
                        "nombre": integrante.nombre,
                        "edad": integrante.edad,
                        "valor": round(precio_individual or 0.0, 2),
                        "es_titular": integrante.es_titular,
                    })
            else:
                # Fallback: dividir el total entre integrantes
                precio_por_integrante = valor_plan / len(integrantes)
                for integrante in integrantes:
                    desglose.append({
                        "nombre": integrante.nombre,
                        "edad": integrante.edad,
                        "valor": round(precio_por_integrante, 2),
                        "es_titular": integrante.es_titular,
                    })

        # Observaciones
        if aportes > valor_plan and valor_plan > 0:
            observaciones.append(
                f"Los aportes (${aportes:,.2f}) superan el valor del plan "
                f"(${valor_plan:,.2f}). El valor a pagar es $0."
            )

        resultado = CotizacionResult(
            plan=nombre_plan,
            zona=zona,
            integrantes=integrantes,
            valor_plan_total=round(valor_plan, 2),
            aportes_calculados=round(aportes, 2),
            valor_a_pagar=round(valor_a_pagar, 2),
            plan_joven_disponible=plan_joven_disponible,
            plan_joven_rechazado=plan_joven_rechazado,
            desglose_por_integrante=desglose,
            observaciones=observaciones,
        )

        logger.info(
            "[CALCULATOR] Cotización: plan='%s', zona='%s', integrantes=%d, "
            "valor_plan=%.2f, aportes=%.2f, a_pagar=%.2f, joven=%s",
            nombre_plan, zona, len(integrantes),
            valor_plan, aportes, valor_a_pagar, plan_joven_disponible,
        )

        return resultado

    # ─────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────

    def _construir_integrantes(self, lead: Lead) -> list[IntegranteCotizacion]:
        """
        Construye la lista de integrantes del grupo familiar del lead.

        Args:
            lead: Lead con datos del grupo familiar.

        Returns:
            Lista de IntegranteCotizacion.
        """
        integrantes: list[IntegranteCotizacion] = []

        # Titular siempre presente
        integrantes.append(
            IntegranteCotizacion(
                nombre=lead.nombre or "Titular",
                edad=lead.edad or 0,
                es_titular=True,
            )
        )

        # Cónyuge
        if lead.grupo_familiar.conyuge:
            integrantes.append(
                IntegranteCotizacion(
                    nombre="Cónyuge",
                    edad=0,  # Edad no disponible aún
                    es_titular=False,
                )
            )

        # Hijos
        if lead.grupo_familiar.hijos and lead.cantidad_hijos > 0:
            for i in range(lead.cantidad_hijos):
                integrantes.append(
                    IntegranteCotizacion(
                        nombre=f"Hijo {i + 1}",
                        edad=0,  # Edad no disponible aún
                        es_titular=False,
                    )
                )

        return integrantes

    def generar_propuesta_texto(self, resultado: CotizacionResult) -> str:
        """
        Genera un texto de propuesta comercial a partir de una cotización.

        Args:
            resultado: CotizacionResult con la cotización.

        Returns:
            Texto formateado para enviar al cliente.
        """
        lineas: list[str] = []

        lineas.append(
            f"📋 *Cotización SERVIRED — Plan {resultado.plan.title()}*"
        )
        lineas.append(f"📍 Zona: {resultado.zona.title()}")
        lineas.append("")

        # Integrantes
        if len(resultado.integrantes) == 1:
            lineas.append("👤 *Titular:* {} ({} años)".format(
                resultado.integrantes[0].nombre,
                resultado.integrantes[0].edad,
            ))
        else:
            lineas.append(f"👥 *Grupo familiar:* {len(resultado.integrantes)} personas")
            for intg in resultado.integrantes:
                edad_str = f" — {intg.edad} años" if intg.edad > 0 else ""
                rol = " (titular)" if intg.es_titular else ""
                lineas.append(f"  • {intg.nombre}{rol}{edad_str}")

        lineas.append("")

        # Valores
        lineas.append(
            f"💰 *Valor del plan:* ${resultado.valor_plan_total:,.2f}/mes"
        )

        if resultado.aportes_calculados > 0:
            lineas.append(
                f"🏥 *Aportes obra social:* -${resultado.aportes_calculados:,.2f}"
            )

        lineas.append(
            f"✅ *Valor a pagar:* ${resultado.valor_a_pagar:,.2f}/mes"
        )

        # Plan Joven
        if resultado.plan_joven_disponible:
            lineas.append("")
            lineas.append("🎉 *¡Plan Joven disponible!* Todos los integrantes tienen 30 años o menos.")

        if resultado.plan_joven_rechazado:
            lineas.append("")
            lineas.append(
                "ℹ️ *Plan Joven no disponible:* Para acceder, todos los "
                "integrantes deben tener 30 años o menos."
            )

        # Observaciones
        if resultado.observaciones:
            lineas.append("")
            for obs in resultado.observaciones:
                lineas.append(f"ℹ️ {obs}")

        return "\n".join(lineas)
