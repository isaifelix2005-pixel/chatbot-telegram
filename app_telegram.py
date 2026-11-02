"""Bot de Telegram conversacional conectado a Gemini."""

import asyncio
import os

from dotenv import load_dotenv
from telegram import ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from asistente_ia import crear_cliente, procesar_mensaje


CHAT = 0


async def iniciar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Da la bienvenida y deja que el usuario converse libremente."""
    context.user_data.clear()
    await update.effective_message.reply_text(
        "¡Hola! Soy tu asesor comercial y logístico de transporte refrigerado en tráiler termo de 53 pies.\n"
        "Cuéntame qué necesitas; puedes describir tu cotización en un solo mensaje o paso a paso.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return CHAT


async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Interpreta mensajes naturales y devuelve la respuesta del asesor."""
    mensaje = update.effective_message.text.strip()
    cliente = context.application.bot_data["ai_client"]
    datos = context.user_data.get("cotizacion", {})
    historial = context.user_data.get("historial", [])

    respuesta, datos, historial = await procesar_mensaje(
        mensaje, datos, historial, cliente
    )
    context.user_data["cotizacion"] = datos
    context.user_data["historial"] = historial
    await update.effective_message.reply_text(respuesta)
    return CHAT


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Limpia los datos de la conversacion y la cierra."""
    context.user_data.clear()
    await update.effective_message.reply_text(
        "Conversación reiniciada. Cuando quieras, dime qué flete necesitas cotizar.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def cerrar_cliente(aplicacion: Application) -> None:
    """Cierra el cliente de Gemini al apagar el bot."""
    cliente = aplicacion.bot_data.get("ai_client")
    if cliente is not None:
        await asyncio.to_thread(cliente.close)


def main() -> None:
    """Configura el bot y ejecuta el polling de Telegram."""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    api_key = os.getenv("GEMINI_API_KEY")
    if not token:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN. Configúralo en .env.")
    if not api_key:
        raise SystemExit("Falta GEMINI_API_KEY. Configúrala en .env.")

    conversacion = ConversationHandler(
        entry_points=[
            CommandHandler("start", iniciar),
            MessageHandler(filters.TEXT & ~filters.COMMAND, responder),
        ],
        states={CHAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, responder)]},
        fallbacks=[CommandHandler("cancel", cancelar)],
        allow_reentry=True,
    )
    aplicacion = (
        Application.builder()
        .token(token)
        .post_shutdown(cerrar_cliente)
        .build()
    )
    aplicacion.bot_data["ai_client"] = crear_cliente(api_key)
    aplicacion.add_handler(conversacion)
    aplicacion.run_polling()


if __name__ == "__main__":
    main()