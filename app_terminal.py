"""Interfaz de consola con conversacion libre asistida por Gemini."""

import asyncio
import os

from dotenv import load_dotenv

from asistente_ia import crear_cliente, procesar_mensaje


async def main() -> None:
    """Ejecuta el asesor en consola y conserva contexto durante la sesion."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Falta GEMINI_API_KEY. Configúrala en .env usando .env.example.")

    cliente = crear_cliente(api_key)
    datos_cotizacion: dict[str, str | None] = {}
    historial: list[dict[str, str]] = []
    print("¡Hola! Soy tu asesor de transporte refrigerado en tráiler termo de 53 pies.")
    print("Cuéntame qué necesitas. Escribe /reiniciar para limpiar la cotización o /salir para terminar.\n")

    try:
        while True:
            try:
                mensaje = input("Tú: ").strip()
            except EOFError:
                break
            if not mensaje:
                continue
            comando = mensaje.casefold()
            if comando == "/salir":
                print("Asesor: Gracias por comunicarte con nosotros. ¡Hasta pronto!")
                break
            if comando == "/reiniciar":
                datos_cotizacion.clear()
                historial.clear()
                print("Asesor: Listo, empecemos de nuevo. ¿Qué flete necesitas cotizar?")
                continue

            try:
                respuesta, datos_cotizacion, historial = await procesar_mensaje(
                    mensaje, datos_cotizacion, historial, cliente
                )
            except Exception as e:
                print(f"Error detallado: {e}")
                respuesta = "No pude procesar el mensaje. Inténtalo de nuevo."
            print(f"Asesor: {respuesta}\n")
    except KeyboardInterrupt:
        print("\nAsesor: Gracias por comunicarte con nosotros. ¡Hasta pronto!")
    finally:
        await asyncio.to_thread(cliente.close)


if __name__ == "__main__":
    asyncio.run(main())