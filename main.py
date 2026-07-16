import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import json

app = FastAPI()

# Configuración de plantillas Jinja2 (asegúrate de tener la carpeta 'templates')
templates = Jinja2Templates(directory="templates")

# Estructura para representar una Sala de Juego
class SalaJuego:
    def __init__(self, codigo: str):
        self.codigo = codigo
        self.tablero = [[0 for _ in range(7)] for _ in range(6)]  # Tablero de 6x7
        self.turno_actual = 1  # Empieza el Jugador 1 (Creador)
        
        # Conexiones activas de WebSockets
        self.websocket_p1 = None
        self.websocket_p2 = None
        
        # Nombres de usuario
        self.nombre_p1 = None
        self.nombre_p2 = None

    async def broadcast(self, payload: dict):
        """Envía un mensaje JSON a ambos jugadores conectados"""
        mensaje = json.dumps(payload)
        if self.websocket_p1:
            try:
                await self.websocket_p1.send_text(mensaje)
            except Exception:
                pass
        if self.websocket_p2:
            try:
                await self.websocket_p2.send_text(mensaje)
            except Exception:
                pass

    def realizar_movimiento(self, columna: int, jugador_id: int) -> bool:
        """Intenta colocar una ficha en la columna indicada (gravedad hacia abajo)"""
        if self.turno_actual != jugador_id:
            return False  # No es su turno
        
        # Buscar la primera celda vacía desde abajo en la columna seleccionada
        for fila in range(5, -1, -1):
            if self.tablero[fila][columna] == 0:
                self.tablero[fila][columna] = jugador_id
                # Alternar turno
                self.turno_actual = 2 if jugador_id == 1 else 1
                return True
        return False  # Columna llena

    def verificar_ganador(self) -> int:
        """
        Verifica si hay un ganador en el tablero (4 en línea).
        Retorna: 1 o 2 si hay un ganador, 0 si hay empate (tablero lleno), -1 si el juego continúa.
        """
        # 1. Sentido Horizontal
        for f in range(6):
            for c in range(4):
                if self.tablero[f][c] != 0 and self.tablero[f][c] == self.tablero[f][c+1] == self.tablero[f][c+2] == self.tablero[f][c+3]:
                    return self.tablero[f][c]

        # 2. Sentido Vertical
        for f in range(3):
            for c in range(7):
                if self.tablero[f][c] != 0 and self.tablero[f][c] == self.tablero[f+1][c] == self.tablero[f+2][c] == self.tablero[f+3][c]:
                    return self.tablero[f][c]

        # 3. Diagonal descendente (\)
        for f in range(3):
            for c in range(4):
                if self.tablero[f][c] != 0 and self.tablero[f][c] == self.tablero[f+1][c+1] == self.tablero[f+2][c+2] == self.tablero[f+3][c+3]:
                    return self.tablero[f][c]

        # 4. Diagonal ascendente (/)
        for f in range(3, 6):
            for c in range(4):
                if self.tablero[f][c] != 0 and self.tablero[f][c] == self.tablero[f-1][c+1] == self.tablero[f-2][c+2] == self.tablero[f-3][c+3]:
                    return self.tablero[f][c]

        # 5. Verificar si queda espacio libre (Empate)
        for f in range(6):
            for c in range(7):
                if self.tablero[f][c] == 0:
                    return -1  # El juego sigue
                    
        return 0  # Empate

# Almacén global de salas activas {codigo: SalaJuego}
salas_activas = {}

@app.get("/")
async def get_lobby(request: Request):
    """Ruta para cargar la pantalla de inicio o Lobby"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/play/{codigo}/{username}")
async def get_game(request: Request, codigo: str, username: str):
    """Ruta que renderiza la interfaz del tablero"""
    return templates.TemplateResponse("game.html", {
        "request": request,
        "codigo": codigo.upper(),
        "username": username
    })

@app.websocket("/ws/{codigo}/{username}")
async def websocket_endpoint(websocket: WebSocket, codigo: str, username: str):
    await websocket.accept()
    codigo_sala = codigo.upper()

    # Si la sala no existe, la creamos y este usuario se registra como Jugador 1
    if codigo_sala not in salas_activas:
        salas_activas[codigo_sala] = SalaJuego(codigo_sala)
        sala = salas_activas[codigo_sala]
        sala.websocket_p1 = websocket
        sala.nombre_p1 = username
        jugador_id = 1
    else:
        sala = salas_activas[codigo_sala]
        # Si el Jugador 1 ya está pero no el Jugador 2, se registra como Jugador 2
        if sala.websocket_p2 is None:
            sala.websocket_p2 = websocket
            sala.nombre_p2 = username
            jugador_id = 2
        else:
            # Sala llena: rechazar conexión extra
            await websocket.close(code=4001, reason="La sala ya está llena")
            return

    # 1. Notificar al cliente su número de jugador asignado
    await websocket.send_text(json.dumps({
        "type": "init",
        "player_id": jugador_id
    }))

    # Enviar estado actual (sirve para pintar el nombre si se conecta el segundo jugador)
    await sala.broadcast({
        "type": "update",
        "board": sala.tablero,
        "turn": sala.turno_actual,
        "player1_name": sala.nombre_p1,
        "player2_name": sala.nombre_p2
    })

    try:
        while True:
            # Esperar instrucciones del cliente en tiempo real
            data = await websocket.receive_text()
            event = json.loads(data)

            if event.get("action") == "move":
                col = event.get("col")
                p_id = event.get("player")
                
                # Intentar registrar el tiro en el tablero interno
                if sala.realizar_movimiento(col, p_id):
                    # Verificar si este tiro genera un final de partida
                    resultado = sala.verificar_ganador()
                    
                    if resultado == 1 or resultado == 2:
                        await sala.broadcast({
                            "type": "game_over",
                            "board": sala.tablero,
                            "winner": resultado,
                            "player1_name": sala.nombre_p1,
                            "player2_name": sala.nombre_p2
                        })
                    elif resultado == 0:
                        await sala.broadcast({
                            "type": "game_over",
                            "board": sala.tablero,
                            "winner": 0,
                            "player1_name": sala.nombre_p1,
                            "player2_name": sala.nombre_p2
                        })
                    else:
                        # Si no hay fin del juego, simplemente enviamos el tablero actualizado
                        await sala.broadcast({
                            "type": "update",
                            "board": sala.tablero,
                            "turn": sala.turno_actual,
                            "player1_name": sala.nombre_p1,
                            "player2_name": sala.nombre_p2
                        })
                        
    except WebSocketDisconnect:
        # Remover el WebSocket correspondiente si se cae la conexión
        if jugador_id == 1:
            sala.websocket_p1 = None
            sala.nombre_p1 = None
        else:
            sala.websocket_p2 = None
            sala.nombre_p2 = None

        # Avisar al jugador que queda conectado de la salida del oponente
        await sala.broadcast({
            "type": "opponent_left"
        })

        # Si la sala queda completamente vacía, la eliminamos de la memoria ram
        if sala.websocket_p1 is None and sala.websocket_p2 is None:
            if codigo_sala in salas_activas:
                del salas_activas[codigo_sala]
