"""Motor de cotizacion para trailers refrigerados de 53 pies."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
import unicodedata


TARIFA_POR_KM = Decimal("42.00")
FLETE_MINIMO = Decimal("8000.00")
PORCENTAJE_CASETAS = Decimal("0.15")
PORCENTAJE_IVA = Decimal("0.16")
PORCENTAJE_RETENCION = Decimal("0.04")
CAPACIDAD_MAXIMA_TONELADAS = Decimal("24")
CENTAVO = Decimal("0.01")


def _decimal_positivo(valor: Any, nombre: str) -> Decimal:
    """Convierte un valor numerico y exige que sea finito y mayor que cero."""
    if isinstance(valor, bool):
        raise ValueError(f"{nombre} debe ser un numero mayor que cero.")
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{nombre} debe ser un numero mayor que cero.") from None
    if not numero.is_finite() or numero <= 0:
        raise ValueError(f"{nombre} debe ser un numero mayor que cero.")
    return numero


def _normalizar(texto: str) -> str:
    """Normaliza texto para comparar opciones sin importar acentos o mayusculas."""
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(caracter for caracter in sin_acentos if not unicodedata.combining(caracter)).casefold()


def _resolver_temperatura(temperatura: str) -> tuple[str, Decimal]:
    """Devuelve el nombre de la modalidad y su ajuste porcentual."""
    opcion = _normalizar(temperatura.strip())
    modalidades = {
        "congelado": ("Congelado", Decimal("0.10")),
        "1": ("Congelado", Decimal("0.10")),
        "refrigerado": ("Refrigerado/Fresco", Decimal("0")),
        "fresco": ("Refrigerado/Fresco", Decimal("0")),
        "refrigerado/fresco": ("Refrigerado/Fresco", Decimal("0")),
        "2": ("Refrigerado/Fresco", Decimal("0")),
        "seco": ("Seco / Termo apagado", Decimal("-0.05")),
        "termo apagado": ("Seco / Termo apagado", Decimal("-0.05")),
        "seco / termo apagado": ("Seco / Termo apagado", Decimal("-0.05")),
        "3": ("Seco / Termo apagado", Decimal("-0.05")),
    }
    try:
        return modalidades[opcion]
    except KeyError:
        raise ValueError(
            "Temperatura no valida. Use Congelado, Refrigerado/Fresco o Seco / Termo apagado."
        ) from None


def cotizar_flete(
    origen: str,
    destino: str,
    distancia_km: Any,
    temperatura: str,
    peso_toneladas: Any,
) -> dict[str, Any]:
    """Calcula y devuelve el desglose de una cotizacion preliminar en MXN."""
    if not isinstance(origen, str) or not origen.strip():
        raise ValueError("La ciudad de origen es obligatoria.")
    if not isinstance(destino, str) or not destino.strip():
        raise ValueError("La ciudad de destino es obligatoria.")
    if not isinstance(temperatura, str):
        raise ValueError("Indique un tipo de temperatura valido.")

    distancia = _decimal_positivo(distancia_km, "La distancia")
    peso = _decimal_positivo(peso_toneladas, "El peso")
    if peso > CAPACIDAD_MAXIMA_TONELADAS:
        raise ValueError("La carga excede la capacidad maxima de 24 toneladas.")

    modalidad, porcentaje_ajuste = _resolver_temperatura(temperatura)
    flete_calculado = (distancia * TARIFA_POR_KM).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    flete_base = max(flete_calculado, FLETE_MINIMO)
    ajuste_temperatura = (flete_base * porcentaje_ajuste).quantize(
        CENTAVO, rounding=ROUND_HALF_UP
    )
    casetas = (flete_base * PORCENTAJE_CASETAS).quantize(
        CENTAVO, rounding=ROUND_HALF_UP
    )
    subtotal = flete_base + ajuste_temperatura + casetas
    iva = (subtotal * PORCENTAJE_IVA).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    retencion = (subtotal * PORCENTAJE_RETENCION).quantize(
        CENTAVO, rounding=ROUND_HALF_UP
    )
    total = subtotal + iva - retencion

    return {
        "origen": origen.strip(),
        "destino": destino.strip(),
        "distancia_km": distancia,
        "temperatura": modalidad,
        "peso_toneladas": peso,
        "flete_base": flete_base,
        "ajuste_temperatura": ajuste_temperatura,
        "casetas_estimadas": casetas,
        "subtotal": subtotal,
        "iva": iva,
        "retencion_flete": retencion,
        "total": total,
    }


def formatear_cotizacion(cotizacion: dict[str, Any]) -> str:
    """Presenta el desglose con formato legible para CLI y Telegram."""
    ajuste = cotizacion["ajuste_temperatura"]
    etiqueta_ajuste = "Diésel termo / ajuste"
    signo_ajuste = "+" if ajuste > 0 else "-" if ajuste < 0 else ""

    return "\n".join(
        [
            "📋 DESGLOSE DE COTIZACIÓN",
            f"Ruta: {cotizacion['origen']} → {cotizacion['destino']}",
            f"Distancia: {cotizacion['distancia_km']:,.2f} km",
            f"Temperatura: {cotizacion['temperatura']}",
            f"Peso: {cotizacion['peso_toneladas']:,.2f} toneladas",
            "",
            f"Flete base: ${cotizacion['flete_base']:,.2f} MXN",
            f"{etiqueta_ajuste}: {signo_ajuste}${abs(ajuste):,.2f} MXN",
            f"Casetas estimadas: ${cotizacion['casetas_estimadas']:,.2f} MXN",
            f"Subtotal: ${cotizacion['subtotal']:,.2f} MXN",
            f"IVA (16%): +${cotizacion['iva']:,.2f} MXN",
            f"Retención de flete (4%): -${cotizacion['retencion_flete']:,.2f} MXN",
            f"TOTAL ESTIMADO: ${cotizacion['total']:,.2f} MXN",
        ]
    )