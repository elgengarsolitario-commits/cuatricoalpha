import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import json

app = FastAPI()
templates = Jinja2Templates(directory="templates")

class SalaTimiriche:
    def __init__(self, codigo: str):
        self.codigo = codigo
        # Tamaño del tablero: 4x4 cuadrados (requiere una malla de 5x5 puntos)
        self.filas_puntos = 5
        self.columnas_puntos = 5
        
        # Estado de las líneas: True si está colocada, False si no
        # Líneas horizontales: matriz de 5 x 4
        self.horizontales = [[False for _ in range(4)] for _ in range(5)]
        # Líneas verticales: matriz de 4 x 5
        self.verticales = [[False for _ in range(5)] for _ in range(4)]
        
        # Estado de los cuadrados completados: 0 si libre, 1 si es de P1, 2 si es de P2
        self.cuadrados = [[0 for _ in range(4)] for _ in range(4)]
        
        # Puntuaciones
        self.puntos_p1 = 0
        self.puntos_p2 = 0
        
        self.turno_actual = 1  # Comienza P1
        self.websocket_p1 = None
        self.websocket_p2 = None
        self.nombre_p1 = None
        self.nombre_p2 = None

    async def broadcast(self, payload: dict):
        mensaje = json.dumps(payload)
        if self.websocket_p1:
            try: await self.websocket_p1.send_text(mensaje)
            except Exception: pass
        if self.websocket_p2:
            try: await self.websocket_p2.send_text(mensaje)
            except Exception: pass

    def colocar_linea(self, tipo: str, r: int, c: int, jugador_id: int) -> bool:
        """Intenta colocar un palito. Retorna True si se cerró al menos un cuadrado (turno extra)."""
        if self.turno_actual != jugador_id:
            return False

        linea_nueva = False
        if tipo == "H":
            if 0 <= r < 5 and 0 <= c < 4 and not self.horizontales[r][c]:
                self.horizontales[r][c] = True
                linea_nueva = True
        elif tipo == "V":
            if 0 <= r < 4 and 0 <= c < 5 and not self.verticales[r][c]:
                self.verticales[r][c] = True
                linea_nueva = True

        if not linea_nueva:
            return False

        # Verificar si esta nueva línea completó algún cuadrado
        cuadrados_completados_ahora = 0
        
        # Recorremos la grilla de 4x4 cuadrados
        for i in range(4):
            for j in range(4):
                # Si el cuadrado ya estaba conquistado, lo saltamos
                if self.cuadrados[i][j] != 0:
                    continue
                
                # Un cuadrado (i, j) está delimitado por:
                # Arriba: H[i][j], Abajo: H[i+1][j], Izquierda: V[i][j], Derecha: V[i][j+1]
                arriba = self.horizontales[i][j]
                abajo = self.horizontales[i+1][j]
                izquierda = self.verticales[i][j]
                derecha = self.verticales[i][j+1]
                
                if arriba and abajo and izquierda and derecha:
                    self.cuadrados[i][j] = jugador_id
                    cuadrados_completados_ahora += 1
                    if jugador_id == 1:
                        self.puntos_p1 += 1
                    else:
                        self.puntos_p2 += 1

        if cuadrados_completados_ahora > 0:
            # Gana turno extra: no cambiamos de turno
            return True
        else:
            # No completó nada: pasa el turno al oponente
            self.turno_actual = 2 if jugador_id == 1 else 1
            return False

    def juego_terminado(self) -> bool:
        # El juego termina cuando todos los 16 cuadrados (4x4) estén conquistados
        for r in range(4):
            for c in range(4):
                if self.cuadrados[r][c] == 0:
                    return False
        return True

    def obtener_ganador(self) -> int:
        if self.puntos_p1 > self.puntos_p2:
            return 1
        elif self.puntos_p2 > self.puntos_p1:
            return 2
        return 0 # Empate

salas_activas = {}

@app.get("/")
async def get_lobby(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/play/{codigo}/{username}")
async def get_game(request: Request, codigo: str, username: str):
    return templates.TemplateResponse("game.html", {
        "request": request,
        "codigo": codigo.upper(),
        "username": username
    })

@app.websocket("/ws/{codigo}/{username}")
async def websocket_endpoint(websocket: WebSocket, codigo: str, username: str):
    await websocket.accept()
    codigo_sala = codigo.upper()

    if codigo_sala not in salas_activas:
        salas_activas[codigo_sala] = SalaTimiriche(codigo_sala)
        sala = salas_activas[codigo_sala]
        sala.websocket_p1 = websocket
        sala.nombre_p1 = username
        jugador_id = 1
    else:
        sala = salas_activas[codigo_sala]
        if sala.websocket_p2 is None:
            sala.websocket_p2 = websocket
            sala.nombre_p2 = username
            jugador_id = 2
        else:
            await websocket.close(code=4001, reason="Sala llena")
            return

    await websocket.send_text(json.dumps({
        "type": "init",
        "player_id": jugador_id
    }))

    await sala.broadcast({
        "type": "update",
        "horizontales": sala.horizontales,
        "verticales": sala.verticales,
        "cuadrados": sala.cuadrados,
        "puntos_p1": sala.puntos_p1,
        "puntos_p2": sala.puntos_p2,
        "turn": sala.turno_actual,
        "player1_name": sala.nombre_p1,
        "player2_name": sala.nombre_p2
    })

    try:
        while True:
            data = await websocket.receive_text()
            event = json.loads(data)

            if event.get("action") == "colocar_linea":
                tipo = event.get("tipo") # "H" o "V"
                r = event.get("r")
                c = event.get("c")
                p_id = event.get("player")
                
                # Ejecutar movimiento
                sala.colocar_linea(tipo, r, c, p_id)
                
                if sala.juego_terminado():
                    await sala.broadcast({
                        "type": "game_over",
                        "horizontales": sala.horizontales,
                        "verticales": sala.verticales,
                        "cuadrados": sala.cuadrados,
                        "puntos_p1": sala.puntos_p1,
                        "puntos_p2": sala.puntos_p2,
                        "winner": sala.obtener_ganador(),
                        "player1_name": sala.nombre_p1,
                        "player2_name": sala.nombre_p2
                    })
                else:
                    await sala.broadcast({
                        "type": "update",
                        "horizontales": sala.horizontales,
                        "verticales": sala.verticales,
                        "cuadrados": sala.cuadrados,
                        "puntos_p1": sala.puntos_p1,
                        "puntos_p2": sala.puntos_p2,
                        "turn": sala.turno_actual,
                        "player1_name": sala.nombre_p1,
                        "player2_name": sala.nombre_p2
                    })
                        
    except WebSocketDisconnect:
        if jugador_id == 1:
            sala.websocket_p1 = None
            sala.nombre_p1 = None
        else:
            sala.websocket_p2 = None
            sala.nombre_p2 = None

        await sala.broadcast({"type": "opponent_left"})

        if sala.websocket_p1 is None and sala.websocket_p2 is None:
            if codigo_sala in salas_activas:
                del salas_activas[codigo_sala]
