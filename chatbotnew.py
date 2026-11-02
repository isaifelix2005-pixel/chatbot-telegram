import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Error: No se encontró GEMINI_API_KEY en el archivo .env")
    exit(1)

client = genai.Client(api_key=api_key)

SYSTEM_INSTRUCTION = """
Eres el sistema oficial de cotizaciones y atención al cliente de nuestra empresa mexicana de transportes de carga.
Habla en primera persona del plural ("nosotros", "nuestras unidades", "te cotizamos").
Nos especializamos exclusivamente en fletes con tráiler refrigerado de 53 pies (termo). Capacidad: 22 a 24 toneladas. No manejamos plataformas ni cajas secas.

Reglas para calcular las cotizaciones:
- Tarifa base: $42.00 MXN por kilómetro recorrido.
- Salida mínima: $8,000 MXN (para viajes locales o de corta distancia).
- Modalidad de temperatura:
  * Congelado (-18°C o menos): +10% sobre la tarifa base por mayor consumo de diésel del termo.
  * Fresco/Refrigerado (0°C a 4°C): Tarifa regular.
  * Seco (termo apagado): 5% de descuento sobre la tarifa base.
- Casetas estimadas: Se añade un 15% estimado sobre la tarifa base del flete.
- Impuestos de ley en México: IVA 16% y Retención de flete 4%.

Comportamiento con los clientes:
1. Da la bienvenida a la empresa y pregunta los detalles del viaje que necesitan mover.
2. Si preguntan cosas ajenas a transporte (chistes, recetas, etc.), aclara con respeto que este canal es exclusivamente para cotizar viajes y disponibilidad de nuestros tráileres termo de 53 pies.
3. Si el cliente no te da todos los datos, pide lo que falte: Origen, Destino, Distancia estimada (km), Tipo de producto/temperatura y Peso aproximado (en toneladas).
4. Cuando tengas los datos, entrega una cotización clara con el desglose:
   - Flete base
   - Ajuste por termo (si aplica)
   - Casetas estimadas
   - Subtotal
   - IVA (16%)
   - Retención (4%)
   - Total final estimado en MXN
"""

MODELOS = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"]

def responder(historial):
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.3
    )
    
    for mod in MODELOS:
        try:
            res = client.models.generate_content(
                model=mod,
                contents=historial,
                config=config
            )
            if res and res.text:
                return res.text
        except Exception:
            continue
            
    return "Nuestras unidades están en ruta en este momento. Por favor compártenos el origen, destino y peso para enviarte la cotización detallada."

def iniciar_chat():
    print("\n" + "=" * 60)
    print("  Transportes de Carga Refrigerada 53' | Sistema de Cotización")
    print("  Escribe 'salir' para terminar")
    print("=" * 60 + "\n")

    historial = []

    while True:
        try:
            mensaje = input("Cliente: ").strip()
            if not mensaje:
                continue

            if mensaje.lower() in ["salir", "exit", "adios"]:
                print("\nTransportes: Gracias por contactarnos. Quedamos a sus órdenes.\n")
                break

            print("\n[Consultando cotización...]")
            
            historial.append({"role": "user", "parts": [{"text": mensaje}]})
            respuesta_texto = responder(historial)
            historial.append({"role": "model", "parts": [{"text": respuesta_texto}]})
            
            print(f"\nTransportes: {respuesta_texto}\n")

        except KeyboardInterrupt:
            print("\nTransportes: Sesión finalizada por el usuario.\n")
            break
        except Exception as e:
            print(f"\n[Error]: {e}\n")

if __name__ == "__main__":
    iniciar_chat()