import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from groq import Groq

# 1. Cargar las credenciales desde el archivo .env
load_dotenv()

# 2. Asignar las variables de entorno
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CLAVE_GROQ = os.getenv("CLAVE_GROQ")

# 3. Inicializar el cliente de Groq
cliente_ia = Groq(api_key=CLAVE_GROQ)

INSTRUCCION_SISTEMA = (
    "Eres el despachador y encargado de atención de 'Transportes del Pacífico', "
    "empresa de autotransporte de carga pesada en el corredor del Pacífico "
    "(rutas entre Sonora, Sinaloa, Jalisco y Baja California: Tijuana, Hermosillo, Navojoa, Guadalajara). "
    "Manejas tractocamiones con cajas de 53 pies (cajas secas y refrigeradas/termo). "
    "Reglas de conversación: "
    "1. Recuerda en todo momento los datos que el cliente ya te dijo a lo largo de la plática. "
    "2. Trata al cliente de forma profesional, amable y directa. "
    "3. Si el producto es perecedero (fruta, verdura, carne), sugiere termo; si son secos o abarrotes, caja seca. "
    "4. Solo pide los datos que falten para cotizar."
)

historiales_chat = {}

# ==================== MANEJADORES ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    historiales_chat[chat_id] = [
        {"role": "system", "content": INSTRUCCION_SISTEMA}
    ]
    saludo = (
        "🚛 *Bienvenido a Transportes del Pacífico*\n\n"
        "Atención y logística de carga pesada en el corredor del Pacífico (cajas de 53 ft secas y refrigeradas).\n"
        "¿Qué movimiento de carga o ruta deseas cotizar hoy?"
    )
    await update.message.reply_text(saludo, parse_mode="Markdown")

async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    mensaje_cliente = update.message.text

    if chat_id not in historiales_chat:
        historiales_chat[chat_id] = [
            {"role": "system", "content": INSTRUCCION_SISTEMA}
        ]

    historiales_chat[chat_id].append({"role": "user", "content": mensaje_cliente})

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        chat_completion = cliente_ia.chat.completions.create(
            messages=historiales_chat[chat_id],
            model="openai/gpt-oss-20b",
            temperature=0.6,
        )
        respuesta_texto = chat_completion.choices[0].message.content

        historiales_chat[chat_id].append({"role": "assistant", "content": respuesta_texto})
        await update.message.reply_text(respuesta_texto)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        await update.message.reply_text("Ocurrió un detalle al procesar el mensaje. Reintenta en un momento.")

# ==================== ARRANQUE DEL BOT ====================

if __name__ == "__main__":
    print("Iniciando servicio de Telegram...")
    app = ApplicationBuilder().token(TOKEN_TELEGRAM).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), responder))

    print("✅ Bot activo con Groq. Abre Telegram y pruébalo.")
    app.run_polling(drop_pending_updates=True)