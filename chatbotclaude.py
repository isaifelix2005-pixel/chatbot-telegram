"""
Chatbot de transportes - caja refrigerada / seca de 53 pies
-----------------------------------------------------------
- Sin dependencias de pago ni creditos: todo corre local (no usa IA externa).
- Memoria de conversaciones en SQLite (archivo chatbot.db).
- Tolera errores ortograficos (difflib + normalizacion de texto).
- API REST con FastAPI.

Instalacion:
    pip install fastapi uvicorn

Uso por consola:
    python chatbot_transportes.py

Uso como API:
    python chatbot_transportes.py api
    (o: uvicorn chatbot_transportes:app --host 0.0.0.0 --port 8000)

    POST /chat   {"session_id": "cliente1", "mensaje": "hola"}
    GET  /historial/{session_id}
    DELETE /sesion/{session_id}
    GET  /docs   (documentacion interactiva)
"""

import difflib
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime

# ----------------------------------------------------------------------
# CONFIGURACION (ajusta aqui)
# ----------------------------------------------------------------------
PESO_MAX_TON = 24.0          # limite de carga por unidad
UNIDADES_DISPONIBLES = 2     # numero de unidades de la empresa
DB_PATH = "chatbot.db"
UMBRAL_FUZZY = 0.72          # 0-1, que tan parecido debe ser para "entender" una palabra

# Rango de temperatura que puede manejar el termo (ajusta a tu equipo)
TEMP_MIN_C = -25
TEMP_MAX_C = 25

CIUDADES = [
    "Tijuana", "Tecate", "Mexicali", "San Luis Rio Colorado", "Ensenada",
    "Caborca", "Santa Ana", "Hermosillo", "Guaymas", "Empalme", "Ciudad Obregon",
    "Navojoa", "Los Mochis", "Guasave", "Guamuchil", "Culiacan", "Mazatlan",
    "Tepic", "Guadalajara", "Zapopan", "Tlaquepaque", "Tonala", "Tlajomulco",
    "Nogales", "Magdalena", "Sonoyta", "Puerto Penasco",
]

# Abreviaturas y apodos comunes
ALIAS_CIUDADES = {
    "gdl": "Guadalajara", "tj": "Tijuana", "tij": "Tijuana", "hmo": "Hermosillo",
    "cul": "Culiacan", "obregon": "Ciudad Obregon", "cd obregon": "Ciudad Obregon",
    "slrc": "San Luis Rio Colorado", "mochis": "Los Mochis",
}

TIPOS_CARGA = {
    "refrigerada": ["refrigerada", "refrigerado", "frio", "fria", "congelada",
                    "congelado", "perecedero", "perecederos", "termo", "reefer"],
    "seca": ["seca", "seco", "caja seca", "sin termo", "sin refrigeracion", "abarrotes"],
}

# ----------------------------------------------------------------------
# UTILIDADES DE TEXTO
# ----------------------------------------------------------------------
def normalizar(texto: str) -> str:
    """minusculas, sin acentos, sin signos raros."""
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9\s\.,\-]", " ", texto)
    return re.sub(r"\s+", " ", texto)


CIUDADES_NORM = {normalizar(c): c for c in CIUDADES}


def mejor_parecido(palabra: str, opciones, umbral=UMBRAL_FUZZY):
    r = difflib.get_close_matches(palabra, list(opciones), n=1, cutoff=umbral)
    return r[0] if r else None


def buscar_ciudad(texto: str):
    """Busca una ciudad en el texto, tolerando errores de ortografia."""
    t = normalizar(texto)
    # 0) abreviaturas / apodos
    for alias, real in sorted(ALIAS_CIUDADES.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(alias)}\b", t):
            return real
    # 1) coincidencia exacta dentro del texto
    for norm, real in sorted(CIUDADES_NORM.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(norm)}\b", t):
            return real
    # 2) fuzzy: ventanas de 1 a 4 palabras
    palabras = t.split()
    mejor, mejor_score = None, 0
    for n in range(1, 5):
        for i in range(len(palabras) - n + 1):
            ventana = " ".join(palabras[i:i + n])
            if len(ventana) < 4:
                continue
            for norm, real in CIUDADES_NORM.items():
                s = difflib.SequenceMatcher(None, ventana, norm).ratio()
                if s > mejor_score and s >= UMBRAL_FUZZY:
                    mejor, mejor_score = real, s
    return mejor


def buscar_tipo_carga(texto: str):
    t = normalizar(texto)
    # "sin termo" / "sin refrigeracion" siempre es carga seca
    if re.search(r"\bsin\s+(termo|refriger\w*|frio)", t):
        return "seca"
    palabras = t.split()
    for tipo, sinonimos in TIPOS_CARGA.items():
        for sin in sinonimos:
            if sin in t:
                return tipo
        for p in palabras:
            if len(p) >= 4 and mejor_parecido(p, [normalizar(s) for s in sinonimos], 0.78):
                return tipo
    return None


def extraer_numero(texto: str):
    t = normalizar(texto).replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group()) if m else None


def extraer_peso_ton(texto: str):
    """Devuelve el peso en toneladas. Entiende 'kg', 'kilos', 'ton', 'toneladas'."""
    t = normalizar(texto).replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kgs|kilo|kilos|kilogramos)", t)
    if m:
        return float(m.group(1)) / 1000.0
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    return float(m.group(1)) if m else None


def extraer_temperatura(texto: str):
    t = normalizar(texto).replace(",", ".")
    m = re.search(r"(-?\d+(?:\.\d+)?)", t)
    if not m:
        return None
    valor = float(m.group(1))
    # "menos 18" / "bajo cero 18" => negativo
    if re.search(r"\b(menos|bajo cero|negativ\w*)\b", t) and valor > 0:
        valor = -valor
    return valor


def es_si(texto: str):
    t = normalizar(texto)
    for p in t.split():
        if p in ("si", "sip", "claro", "ok", "dale", "correcto", "confirmo", "va", "simon", "afirmativo"):
            return True
        if mejor_parecido(p, ["si", "claro", "correcto", "confirmo", "afirmativo"], 0.8):
            return True
    return False


def es_no(texto: str):
    t = normalizar(texto)
    for p in t.split():
        if p in ("no", "nop", "nel", "cancelar", "cancela", "negativo"):
            return True
        if mejor_parecido(p, ["cancelar", "negativo"], 0.8):
            return True
    return False


# ----------------------------------------------------------------------
# MEMORIA (SQLite)
# ----------------------------------------------------------------------
class Memoria:
    def __init__(self, path=DB_PATH):
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.execute("""CREATE TABLE IF NOT EXISTS mensajes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, rol TEXT, texto TEXT, fecha TEXT)""")
        self.con.execute("""CREATE TABLE IF NOT EXISTS sesiones(
            session_id TEXT PRIMARY KEY, estado TEXT, datos TEXT)""")
        self.con.execute("""CREATE TABLE IF NOT EXISTS solicitudes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, fecha TEXT, datos TEXT)""")
        self.con.commit()

    def guardar_mensaje(self, sid, rol, texto):
        self.con.execute("INSERT INTO mensajes(session_id,rol,texto,fecha) VALUES(?,?,?,?)",
                         (sid, rol, texto, datetime.now().isoformat(timespec="seconds")))
        self.con.commit()

    def historial(self, sid, limite=200):
        cur = self.con.execute(
            "SELECT rol,texto,fecha FROM mensajes WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (sid, limite))
        return [{"rol": r, "texto": t, "fecha": f} for r, t, f in reversed(cur.fetchall())]

    def cargar_sesion(self, sid):
        cur = self.con.execute("SELECT estado,datos FROM sesiones WHERE session_id=?", (sid,))
        fila = cur.fetchone()
        if fila:
            return fila[0], json.loads(fila[1])
        return "inicio", {}

    def guardar_sesion(self, sid, estado, datos):
        self.con.execute("INSERT OR REPLACE INTO sesiones(session_id,estado,datos) VALUES(?,?,?)",
                         (sid, estado, json.dumps(datos, ensure_ascii=False)))
        self.con.commit()

    def guardar_solicitud(self, sid, datos):
        self.con.execute("INSERT INTO solicitudes(session_id,fecha,datos) VALUES(?,?,?)",
                         (sid, datetime.now().isoformat(timespec="seconds"),
                          json.dumps(datos, ensure_ascii=False)))
        self.con.commit()

    def borrar_sesion(self, sid):
        self.con.execute("DELETE FROM mensajes WHERE session_id=?", (sid,))
        self.con.execute("DELETE FROM sesiones WHERE session_id=?", (sid,))
        self.con.commit()


# ----------------------------------------------------------------------
# LOGICA DEL CHATBOT (maquina de estados)
# ----------------------------------------------------------------------
class ChatbotTransportes:
    def __init__(self, memoria: Memoria):
        self.mem = memoria

    # --- helpers de mensajes ---
    def _resumen(self, d):
        if d["tipo_carga"] == "refrigerada":
            temp = f"Refrigerada a {d['temperatura']:g} °C (termo encendido)"
        else:
            temp = "Seca (termo apagado)"
        return (
            "Resumen de tu solicitud:\n"
            f"- Origen: {d['origen']}\n"
            f"- Destino: {d['destino']}\n"
            f"- Carga: {d['descripcion']}\n"
            f"- Peso: {d['peso_ton']:g} ton\n"
            f"- Tipo: {temp}\n"
            "¿Los datos son correctos? (si / no)"
        )

    def _intermedias(self, texto):
        """Detecta paradas intermedias mencionadas ('con paradas en ...')."""
        t = normalizar(texto)
        m = re.search(r"(?:parada|paradas|pasando por|pasa por|entre)\s+(.*)", t)
        if not m:
            return []
        paradas = []
        for trozo in re.split(r",| y | e ", m.group(1)):
            c = buscar_ciudad(trozo)
            if c and c not in paradas:
                paradas.append(c)
        return paradas

    # --- punto de entrada ---
    def responder(self, sid: str, mensaje: str) -> str:
        estado, datos = self.mem.cargar_sesion(sid)
        self.mem.guardar_mensaje(sid, "usuario", mensaje)
        t = normalizar(mensaje)

        # comandos globales
        if t in ("reiniciar", "reset", "empezar de nuevo", "nuevo") or \
                mejor_parecido(t, ["reiniciar", "empezar de nuevo"], 0.85):
            estado, datos = "inicio", {}
            resp = "Listo, empecemos de nuevo. ¿Desde qué ciudad sale la carga?"
            estado = "origen"
            return self._cerrar(sid, estado, datos, resp)

        if estado == "inicio":
            resp, estado, datos = self._inicio(mensaje, datos)
        elif estado == "origen":
            resp, estado, datos = self._origen(mensaje, datos)
        elif estado == "destino":
            resp, estado, datos = self._destino(mensaje, datos)
        elif estado == "descripcion":
            resp, estado, datos = self._descripcion(mensaje, datos)
        elif estado == "peso":
            resp, estado, datos = self._peso(mensaje, datos)
        elif estado == "tipo":
            resp, estado, datos = self._tipo(mensaje, datos)
        elif estado == "temperatura":
            resp, estado, datos = self._temperatura(mensaje, datos)
        elif estado == "confirmar":
            resp, estado, datos = self._confirmar(sid, mensaje, datos)
        else:  # "finalizado" u otro
            resp, estado, datos = self._inicio(mensaje, {})
        return self._cerrar(sid, estado, datos, resp)

    def _cerrar(self, sid, estado, datos, resp):
        self.mem.guardar_sesion(sid, estado, datos)
        self.mem.guardar_mensaje(sid, "bot", resp)
        return resp

    # --- estados ---
    def _inicio(self, msg, datos):
        t = normalizar(msg)
        saludo = "¡Hola! Soy el asistente de transportes con caja de 53 pies (refrigerada o seca). "
        # si ya trae datos en el primer mensaje, los aprovechamos
        origen = buscar_ciudad(msg)
        if origen and re.search(r"\b(de|desde|salgo de|sale de)\b", normalizar(msg)):
            datos["origen"] = origen
            return (saludo + f"Tomé {origen} como origen. ¿A qué ciudad va la carga?",
                    "destino", datos)
        return (saludo + "Te ayudo a solicitar un viaje. ¿Desde qué ciudad sale la carga?",
                "origen", datos)

    def _origen(self, msg, datos):
        c = buscar_ciudad(msg)
        if not c:
            return ("No reconocí la ciudad. Atendemos la ruta Tijuana–Guadalajara y ciudades "
                    "intermedias. ¿Desde qué ciudad sale la carga?", "origen", datos)
        datos["origen"] = c
        return (f"Origen: {c}. ¿A qué ciudad va la carga?", "destino", datos)

    def _destino(self, msg, datos):
        # el destino es lo que viene ANTES de "con paradas en ..." / "pasando por ..."
        cabeza = re.split(r"\b(?:con\s+)?(?:paradas?|pasando por|pasa por)\b", normalizar(msg))[0]
        c = buscar_ciudad(cabeza) or buscar_ciudad(msg)
        if not c:
            return ("No reconocí el destino. ¿A qué ciudad va la carga?", "destino", datos)
        if c == datos.get("origen"):
            return ("El destino no puede ser igual al origen. ¿A qué ciudad va?", "destino", datos)
        datos["destino"] = c
        datos["paradas"] = self._intermedias(msg)
        extra = f" (paradas: {', '.join(datos['paradas'])})" if datos["paradas"] else ""
        return (f"Destino: {c}{extra}. ¿Qué tipo de mercancía vas a transportar? "
                "(ej. frutas, lácteos, abarrotes, congelados)", "descripcion", datos)

    def _descripcion(self, msg, datos):
        datos["descripcion"] = msg.strip()
        # si en la descripcion ya viene el tipo, lo sugerimos
        tipo = buscar_tipo_carga(msg)
        if tipo:
            datos["tipo_sugerido"] = tipo
        return (f"Anotado: {datos['descripcion']}. ¿Cuánto pesa la carga? "
                f"(en toneladas, máximo {PESO_MAX_TON:g} ton)", "peso", datos)

    def _peso(self, msg, datos):
        p = extraer_peso_ton(msg)
        if p is None or p <= 0:
            return ("No entendí el peso. Dímelo en toneladas, por ejemplo: 18 ton.", "peso", datos)
        if p > PESO_MAX_TON:
            return (f"Lo siento, el límite de carga por unidad es de {PESO_MAX_TON:g} toneladas y "
                    f"tu carga es de {p:g} ton. Puedes dividirla en dos viajes/unidades "
                    f"(tenemos {UNIDADES_DISPONIBLES} unidades). ¿Cuál es el peso que sí quieres "
                    "enviar en esta unidad?", "peso", datos)
        datos["peso_ton"] = p
        return ("Peso aceptado. ¿La carga es refrigerada (con termo encendido) o seca (sin termo)?",
                "tipo", datos)

    def _tipo(self, msg, datos):
        tipo = buscar_tipo_carga(msg)
        if not tipo:
            return ("No te entendí. Responde 'refrigerada' (termo encendido) o 'seca' "
                    "(sin termo).", "tipo", datos)
        datos["tipo_carga"] = tipo
        if tipo == "seca":
            datos["temperatura"] = None
            return (self._resumen(datos), "confirmar", datos)
        return (f"¿A qué temperatura se va a manejar la carga? (en °C, el termo opera entre "
                f"{TEMP_MIN_C} y {TEMP_MAX_C} °C. Ej: 4, o -18 para congelado)",
                "temperatura", datos)

    def _temperatura(self, msg, datos):
        v = extraer_temperatura(msg)
        if v is None:
            return ("No entendí la temperatura. Dime un número en °C, por ejemplo 4 o -18.",
                    "temperatura", datos)
        if not (TEMP_MIN_C <= v <= TEMP_MAX_C):
            return (f"Esa temperatura queda fuera del rango del termo ({TEMP_MIN_C} a "
                    f"{TEMP_MAX_C} °C). ¿Qué temperatura necesitas?", "temperatura", datos)
        datos["temperatura"] = v
        return (self._resumen(datos), "confirmar", datos)

    def _confirmar(self, sid, msg, datos):
        if es_no(msg) and not es_si(msg):
            return ("Sin problema. Escribe 'reiniciar' para capturar la solicitud de nuevo.",
                    "confirmar", datos)
        if es_si(msg):
            self.mem.guardar_solicitud(sid, datos)
            return ("¡Solicitud registrada! Un asesor te contactará para confirmar tarifa y "
                    "fecha de salida. Si quieres otra cotización, escribe 'nuevo'.",
                    "finalizado", {})
        return ("¿Confirmas los datos? Responde 'si' o 'no'.", "confirmar", datos)


# ----------------------------------------------------------------------
# API (FastAPI)
# ----------------------------------------------------------------------
memoria = Memoria()
bot = ChatbotTransportes(memoria)

try:
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(title="Chatbot Transportes 53 pies")

    class EntradaChat(BaseModel):
        session_id: str
        mensaje: str

    @app.post("/chat")
    def chat(e: EntradaChat):
        return {"session_id": e.session_id, "respuesta": bot.responder(e.session_id, e.mensaje)}

    @app.get("/historial/{session_id}")
    def historial(session_id: str):
        return {"session_id": session_id, "mensajes": memoria.historial(session_id)}

    @app.delete("/sesion/{session_id}")
    def borrar(session_id: str):
        memoria.borrar_sesion(session_id)
        return {"ok": True}

    @app.get("/")
    def raiz():
        return {"estado": "ok", "peso_max_ton": PESO_MAX_TON}
except ImportError:
    app = None


# ----------------------------------------------------------------------
# MODO CONSOLA / ARRANQUE DE API
# ----------------------------------------------------------------------
def consola():
    print("=== Chatbot de transportes (escribe 'salir' para terminar) ===")
    sid = input("ID de cliente (ej. su telefono o nombre): ").strip() or "consola"
    hist = memoria.historial(sid, 1)
    if hist:
        print("(Retomando tu conversación anterior. Escribe 'reiniciar' para empezar de cero.)")
    print("Bot:", bot.responder(sid, "hola") if not hist else "¿Seguimos donde nos quedamos?")
    while True:
        try:
            msg = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if normalizar(msg) in ("salir", "exit", "quit"):
            break
        if msg:
            print("Bot:", bot.responder(sid, msg))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "api":
        if app is None:
            print("Falta instalar: pip install fastapi uvicorn")
        else:
            import uvicorn
            uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        consola()