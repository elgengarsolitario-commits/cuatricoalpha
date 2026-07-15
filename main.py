import os
import random
import string
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Dict, List

app = FastAPI()

# Configuración de templates HTML
templates = Jinja2Templates(directory="templates")

# Estado global de las partidas activas
# Estructura: { "CÓDIGO": { "jugadores": [ws1, ws2], "nombres": [n1, n2], "turno": 0, "lineas": {} } }
partidas: Dict[str, dict] = {}

def generar_codigo_sala() -> str:
    """Genera un código único de 6 caracteres para el multijugador."""
    while True:
        codigo = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if codigo not in partidas:
            return codigo

# --- RUTAS DE NAVEGACIÓN CORREGIDAS ---

@app.get("/")
async def get_lobby(request: Request):
    # Pasamos el parámetro request explícitamente como argumento de la función
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )

@app.get("/play/{codigo}/{username}")
async def get_game(request: Request, codigo: str, username: str):
    # Pasamos request directamente y cualquier otra variable dentro del diccionario context
    return templates.TemplateResponse(
        request=request,
        name="game.html",
        context={
            "codigo": codigo,
            "username": username
        }
    )
# --- COMUNICACIÓN EN TIEMPO REAL (WEBSOCKET) ---

@app.websocket("/ws/{codigo}/{username}")
async def websocket_endpoint(websocket: WebSocket, codigo: str, username: str):
    await websocket.accept()
    
    if codigo not in partidas:
        await websocket.close(code=4001, reason="La sala no existe.")
        return
    
    sala = partidas[codigo]
    if len(sala["jugadores"]) >= 2:
        await websocket.close(code=4002, reason="La sala ya está llena.")
        return

    # Registrar jugador
    sala["jugadores"].append(websocket)
    sala["nombres"].append(username)
    id_jugador = len(sala["jugadores"]) - 1  # 0 o 1

    # Notificar que se unió un jugador
    for ws in sala["jugadores"]:
        await ws.send_json({
            "tipo": "SALA_ESTADO",
            "jugadores": sala["nombres"],
            "listo": len(sala["jugadores"]) == 2
        })

    try:
        while True:
            # Escuchar las jugadas del cliente (ej. cuando hace clic en una línea 3D)
            data = await websocket.receive_json()
            
            if data["tipo"] == "JUGADA":
                # Validar de quién es el turno
                if sala["turno_index"] != id_jugador:
                    continue  # Ignorar si no es su turno
                
                linea_id = data["linea_id"]
                color = "azul" if id_jugador == 0 else "rojo"
                
                # Registrar la línea pintada si estaba libre
                if linea_id not in sala["lineas"]:
                    sala["lineas"][linea_id] = color
                    
                    # Lógica simplificada: ¿Cerró un cuadro? 
                    # El cliente calcula si cerró cuadro y manda "puntos_ganados"
                    puntos_ganados = data.get("puntos_ganados", 0)
                    sala["puntos"][id_jugador] += puntos_ganados
                    
                    # Si ganó puntos, mantiene el turno. Si no, pasa el turno al rival.
                    if puntos_ganados == 0:
                        sala["turno_index"] = 1 - sala["turno_index"]

                    # Sincronizar tablero con ambos jugadores inmediatamente
                    for jugador_ws in sala["jugadores"]:
                        await jugador_ws.send_json({
                            "tipo": "TABLERO_ACTUALIZAR",
                            "linea_id": linea_id,
                            "color": color,
                            "puntos": sala["puntos"],
                            "turno_index": sala["turno_index"]
                        })

    except WebSocketDisconnect:
        if websocket in sala["jugadores"]:
            idx = sala["jugadores"].index(websocket)
            sala["jugadores"].remove(websocket)
            if idx < len(sala["nombres"]):
                sala["nombres"].pop(idx)
        
        # Si la sala se queda vacía, la borramos
        if not sala["jugadores"]:
            partidas.pop(codigo, None)

if __name__ == "__main__":
    import uvicorn
    # Render asigna dinámicamente un puerto en la variable de entorno PORT
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
