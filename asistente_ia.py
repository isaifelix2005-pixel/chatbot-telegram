"""Conversacion comercial con extraccion estructurada mediante Gemini."""

import asyncio
import json
import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from google import genai
from google.genai import types

from cotizador import cotizar_flete, formatear_cotizacion


MODELO_GEMINI = "gemini-3.8-flash"
ESPERAS_REINTENTO = (1, 2)
DATOS_VACIOS = {
    "origen": None,
    "destino": None,
    "distancia_km": None,
    "temperatura": None,
    "peso_toneladas": None,
}
ESQUEMA_RESPUESTA = {
    "type": "OBJECT",
    "properties": {
        "intent": {
            "type": "STRING",
            "enum": ["quote", "greeting", "logistics_question", "out_of_scope", "other"],
        },
        "reply": {"type": "STRING"},
        "origen": {"type": ["STRING", "NULL"]},
        "destino": {"type": ["STRING", "NULL"]},
        "distancia_km": {"type": ["NUMBER", "NULL"]},
        "temperatura": {"type": ["STRING", "NULL"]},
        "peso_toneladas": {"type": ["NUMBER", "NULL"]},
    },
    "required": [
        "intent",
        "reply",
        "origen",
        "destino",
        "distancia_km",
        "temperatura",
        "peso_toneladas",
    ],
    "additionalProperties": False,
}
INSTRUCCIONES = """Eres un asesor comercial y logistico amable, profesional, conciso y con criterio de una empresa que solo ofrece trailers refrigerados tipo termo de 53 pies.

Tu servicio se limita a cotizar y responder preguntas relacionadas con fletes refrigerados, tarifas, rutas, temperatura y capacidad. No ayudes con chistes, recetas, temas personales ni solicitudes ajenas al transporte; clasificalas como out_of_scope y responde con naturalidad ofreciendo cotizar un termo de 53 pies o aclarar dudas logisticas.

Clasifica cada mensaje como quote (cotizar o aportar/corregir datos de una cotizacion activa), greeting (solo saludo), logistics_question, out_of_scope u other. Un saludo aislado nunca es una ciudad. Responde en espanol, con brevedad, sin mostrar razonamiento interno.

Extrae del mensaje actual y del historial los campos conocidos: origen, destino, distancia_km, temperatura y peso_toneladas. Conserva datos anteriores salvo que el usuario los corrija. Temperatura debe ser Congelado, Refrigerado/Fresco o Seco / Termo apagado cuando haya evidencia suficiente; si es ambigua, usa null. Interpreta carga y unidades cuando sea claro, pero no inventes ciudades, distancias, pesos ni condiciones. No estimes kilometros por tu cuenta: si faltan, se preguntan. Conserva pesos fuera de rango para explicar la limitacion, no los ocultes.

La capacidad operativa es de aproximadamente 22 a 24 toneladas, con 24 toneladas como limite maximo para cotizar, sujeto a volumen y caracteristicas de la carga. Solo se manejan trailers refrigerados de 53 pies; actualmente no se ofrecen plataformas ni otros equipos. Usa estos datos en respuestas logisticas. No calcules ni inventes precios: la aplicacion lo hace.

Si el usuario responde una pregunta pendiente con un dato, clasifica como quote. Si pregunta otra cosa logistica mientras hay una cotizacion en curso, clasifica como logistics_question y no cambies los datos a menos que corrija uno expresamente."""
PREGUNTAS_FALTANTES = {
    "origen": "¿En qué ciudad se recoge la carga?",
    "destino": "¿A qué ciudad se entrega?",
    "distancia_km": "¿Cuántos kilómetros aproximados tiene la ruta? No inventaré la distancia.",
    "temperatura": "¿La carga requiere congelado, refrigerado/fresco o termo apagado (seco)?",
    "peso_toneladas": "¿Cuál es el peso estimado de la carga en toneladas?",
}
RESPUESTA_FUERA_DE_TEMA = (
    "No puedo ayudarte con ese tema, pero con gusto puedo cotizarte un flete en termo de 53 pies, "
    "explicarte nuestras tarifas o resolver dudas sobre el manejo de temperatura de tu carga."
)


def crear_cliente(api_key: str) -> genai.Client:
    """Crea un cliente autenticado para Gemini."""
    return genai.Client(api_key=api_key)


def _normalizar_texto(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(caracter for caracter in descompuesto if not unicodedata.combining(caracter))


def _llamar_gemini(
    cliente: genai.Client,
    mensaje: str,
    datos: dict[str, Any],
    historial: list[dict[str, str]],
) -> dict[str, Any]:
    contexto = json.dumps(
        {"datos_cotizacion_actuales": datos, "historial_reciente": historial[-12:], "mensaje": mensaje},
        ensure_ascii=False,
    )
    configuracion = types.GenerateContentConfig(
        system_instruction=INSTRUCCIONES,
        response_mime_type="application/json",
        response_json_schema=ESQUEMA_RESPUESTA,
        temperature=0.2,
        max_output_tokens=500,
    )
    for intento in range(len(ESPERAS_REINTENTO) + 1):
        try:
            respuesta = cliente.models.generate_content(
                model=MODELO_GEMINI,
                contents=contexto,
                config=configuracion,
            )
            break
        except Exception as error:
            codigo = str(getattr(error, "code", ""))
            estado = str(getattr(error, "status", "")).upper()
            transitorio = codigo in {"429", "503"} or estado in {
                "RESOURCE_EXHAUSTED",
                "UNAVAILABLE",
            }
            if not transitorio or intento >= len(ESPERAS_REINTENTO):
                raise
            espera = ESPERAS_REINTENTO[intento]
            print(
                f"Gemini respondió con {codigo or estado}; reintento "
                f"{intento + 1}/{len(ESPERAS_REINTENTO)} en {espera} s."
            )
            time.sleep(espera)

    if not respuesta.text:
        raise ValueError("Gemini no devolvio contenido.")
    resultado = json.loads(respuesta.text)
    if not isinstance(resultado, dict):
        raise ValueError("La respuesta de Gemini no tiene el formato esperado.")
    return resultado


def _normalizar_numero(valor: Any) -> str | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = Decimal(str(valor).replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not numero.is_finite() or numero <= 0:
        return None
    return format(numero, "f")


def _normalizar_temperatura(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    opcion = _normalizar_texto(valor.strip())
    if opcion in {"congelado", "congelada", "congelados", "congeladas"}:
        return "Congelado"
    if opcion in {"fresco", "fresca", "refrigerado", "refrigerada", "refrigerado/fresco"}:
        return "Refrigerado/Fresco"
    if opcion in {"seco", "seca", "termo apagado", "seco / termo apagado"}:
        return "Seco / Termo apagado"
    return None


def _combinar_datos(actuales: dict[str, Any], extraidos: dict[str, Any]) -> dict[str, Any]:
    datos = {**DATOS_VACIOS, **actuales}
    for campo in ("origen", "destino"):
        valor = extraidos.get(campo)
        if isinstance(valor, str) and valor.strip():
            datos[campo] = valor.strip()
    for campo in ("distancia_km", "peso_toneladas"):
        valor = _normalizar_numero(extraidos.get(campo))
        if valor is not None:
            datos[campo] = valor
    temperatura = _normalizar_temperatura(extraidos.get("temperatura"))
    if temperatura is not None:
        datos["temperatura"] = temperatura
    return datos


def _respuesta_capacidad(mensaje: str, intent: str) -> str | None:
    texto = _normalizar_texto(mensaje)
    equipos_no_disponibles = (
        "plataforma", "caja seca", "rabon", "torton", "pipa", "lowboy", "cama baja"
    )
    if intent == "logistics_question" and any(equipo in texto for equipo in equipos_no_disponibles):
        return (
            "Por el momento solo manejamos tráileres refrigerados tipo termo de 53 pies; "
            "no contamos con plataformas ni otros equipos."
        )

    pesos_mencionados = re.findall(
        r"\b(\d+(?:[.,]\d+)?)\s*(?:ton(?:eladas?)?|tons?|t)\b", texto
    )
    if intent == "logistics_question":
        for peso in pesos_mencionados:
            try:
                excede_capacidad = Decimal(peso.replace(",", ".")) > 24
            except InvalidOperation:
                continue
            if excede_capacidad:
                return (
                    "Nuestro termo de 53 pies admite aproximadamente de 22 a 24 toneladas; "
                    "24 toneladas es el máximo para cotizar y depende del volumen y tipo de carga."
                )
        if any(termino in texto for termino in ("capacidad", "peso maximo", "cuanto peso", "cuántas toneladas")):
            return (
                "La capacidad es de aproximadamente 22 a 24 toneladas en tráiler termo de 53 pies; "
                "el máximo para cotizar es 24 toneladas, sujeto al volumen de la carga."
            )
    return None


async def procesar_mensaje(
    mensaje: str,
    datos_actuales: dict[str, Any],
    historial: list[dict[str, str]],
    cliente: genai.Client,
) -> tuple[str, dict[str, Any], list[dict[str, str]]]:
    """Interpreta un mensaje y devuelve respuesta, datos y contexto actualizados."""
    try:
        extraidos = await asyncio.to_thread(
            _llamar_gemini, cliente, mensaje, datos_actuales, historial
        )
    except Exception as e:
        print(f"Error detallado: {e}")
        respuesta = (
            "Ahora mismo no pude conectarme al asistente. Inténtalo de nuevo en un momento; "
            "conservaré los datos de tu cotización."
        )
        return respuesta, datos_actuales, _actualizar_historial(historial, mensaje, respuesta)

    intent = extraidos.get("intent", "other")
    if intent == "greeting":
        respuesta = (
            "¡Hola! Soy tu asesor de transporte refrigerado. Puedo cotizar un flete en termo de 53 pies "
            "o resolver tus dudas logísticas. ¿Qué necesitas?"
        )
        return respuesta, datos_actuales, _actualizar_historial(historial, mensaje, respuesta)
    if intent == "out_of_scope":
        return RESPUESTA_FUERA_DE_TEMA, datos_actuales, _actualizar_historial(
            historial, mensaje, RESPUESTA_FUERA_DE_TEMA
        )

    if intent == "logistics_question":
        respuesta = _respuesta_capacidad(mensaje, intent) or str(extraidos.get("reply", ""))
        if not respuesta.strip():
            respuesta = "Solo ofrecemos tráiler refrigerado tipo termo de 53 pies, con capacidad de hasta 24 toneladas."
        return respuesta, datos_actuales, _actualizar_historial(historial, mensaje, respuesta)

    if intent != "quote":
        respuesta = str(extraidos.get("reply", ""))
        if not respuesta.strip():
            respuesta = "Puedo ayudarte con cotizaciones y dudas sobre transporte refrigerado en tráiler termo de 53 pies."
        return respuesta, datos_actuales, _actualizar_historial(historial, mensaje, respuesta)

    datos = _combinar_datos(datos_actuales, extraidos)
    if datos["peso_toneladas"] is not None and Decimal(datos["peso_toneladas"]) > 24:
        respuesta = (
            "La capacidad máxima para cotizar es de 24 toneladas en un tráiler termo de 53 pies. "
            "¿Puedes confirmar si la carga puede ajustarse a ese límite?"
        )
        return respuesta, datos, _actualizar_historial(historial, mensaje, respuesta)

    faltantes = [campo for campo in DATOS_VACIOS if datos.get(campo) is None]
    if faltantes:
        respuesta = PREGUNTAS_FALTANTES[faltantes[0]]
        return respuesta, datos, _actualizar_historial(historial, mensaje, respuesta)

    try:
        cotizacion = cotizar_flete(
            datos["origen"],
            datos["destino"],
            datos["distancia_km"],
            datos["temperatura"],
            datos["peso_toneladas"],
        )
    except ValueError as error:
        respuesta = f"No puedo calcular esa cotización: {error}"
        return respuesta, datos, _actualizar_historial(historial, mensaje, respuesta)

    respuesta = (
        f"{formatear_cotizacion(cotizacion)}\n\n"
        "Cotización preliminar sujeta a disponibilidad de equipo y confirmación de casetas."
    )
    return respuesta, dict(DATOS_VACIOS), _actualizar_historial(historial, mensaje, respuesta)


def _actualizar_historial(
    historial: list[dict[str, str]], mensaje: str, respuesta: str
) -> list[dict[str, str]]:
    return [
        *historial[-10:],
        {"role": "user", "text": mensaje},
        {"role": "assistant", "text": respuesta},
    ]