¡Claro que sí! Vamos a hacerlo súper sencillo. Te voy a dar los dos archivos completos de inicio a fin para que solo tengas que copiar, pegar y reemplazar todo el contenido en tu GitHub.

🐍 1. Archivo main.py completo
Reemplaza todo el contenido de tu archivo main.py actual con este código:

Python
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import json

app = FastAPI()

# Configuramos la carpeta de plantillas (Jinja2)
templates = Jinja2Templates(directory="templates")

# Diccionario global para manejar las salas de juego
# Estructura: { "codigo_sala": [websocket1, websocket2] }
salas: dict[str, list[WebSocket]] = {}

@app.get("/")
async def get_lobby(request: Request):
    # Carga la pantalla de inicio (Lobby)
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )

@app.get("/play/{codigo}/{username}")
async def get_game(request: Request, codigo: str, username: str):
    # Carga la pantalla de juego 3D con las variables de la sala
    return templates.TemplateResponse(
        request=request,
        name="game.html",
        context={
            "codigo": codigo,
            "username": username
        }
    )

@app.websocket("/ws/{codigo}/{username}")
async def websocket_endpoint(websocket: WebSocket, codigo: str, username: str):
    await websocket.accept()
    
    # Aseguramos que el código de la sala esté registrado
    if codigo not in salas:
        salas[codigo] = []
    
    # Validamos que no entren más de 2 personas a la misma sala
    if len(salas[codigo]) >= 2:
        await websocket.send_text(json.dumps({
            "type": "error", 
            "message": "La sala ya está llena. Intenta con otro código."
        }))
        await websocket.close()
        return

    # Añadimos la conexión del jugador a la sala
    salas[codigo].append(websocket)
    print(f"Jugador {username} se unió a la sala '{codigo}'. Total: {len(salas[codigo])}")

    try:
        # Si ya se unieron los 2 jugadores, les mandamos la señal de inicio de partida
        if len(salas[codigo]) == 2:
            # Mandamos mensaje a ambos para sincronizar el comienzo
            for index, ws in enumerate(salas[codigo]):
                # El primero que entró es el creador (ficha roja), el segundo es el invitado (azul)
                es_creador = (index == 0)
                await ws.send_text(json.dumps({
                    "type": "start",
                    "rol": "creador" if es_creador else "invitado"
                }))

        # Escuchamos los movimientos del juego continuamente
        while True:
            data = await websocket.receive_text()
            # Reenviamos el movimiento recibido al rival de la sala
            for cliente in salas[codigo]:
                if cliente != websocket:
                    await cliente.send_text(data)

    except WebSocketDisconnect:
        # Manejamos la salida de un jugador de la sala
        if codigo in salas and websocket in salas[codigo]:
            salas[codigo].remove(websocket)
            # Avisamos al rival que se quedó solo
            for cliente in salas[codigo]:
                await cliente.send_text(json.dumps({
                    "type": "disconnection", 
                    "message": "Tu rival se ha desconectado de la partida."
                }))
            # Si la sala quedó vacía, la eliminamos para liberar memoria
            if not salas[codigo]:
                del salas[codigo]
        print(f"Jugador {username} se desconectó de la sala '{codigo}'")
