from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import json

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ==========================================
# 🗄️ CONFIGURACIÓN DE BASE DE DATOS (NEON)
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL")

# Si por alguna razón local no está configurada, usa un SQLite de respaldo
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./test.db"
elif DATABASE_URL.startswith("postgres://"):
    # Render y SQLAlchemy a veces requieren este cambio de protocolo
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Modelo de tabla para guardar los datos de los jugadores
class Jugador(Base):
    __tablename__ = "jugadores"
    username = Column(String, primary_key=True, index=True)
    puntos = Column(Integer, default=100)  # Empiezan con 100 puntos de base

# Crear las tablas en Neon si no existen todavía
Base.metadata.create_all(bind=engine)

# ==========================================
# 🎮 GESTIÓN DE SALAS DE JUEGO
# ==========================================
# Estructura: { "codigo_sala": [websocket1, websocket2] }
salas: dict[str, list[WebSocket]] = {}

@app.get("/")
async def get_lobby(request: Request):
    # Solución definitiva para evitar el error de Jinja2 pasándole explícitamente el request
    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )

@app.get("/play/{codigo}/{username}")
async def get_game(request: Request, codigo: str, username: str):
    # Al entrar a jugar, registramos o buscamos al usuario en Neon para leer sus puntos
    db = SessionLocal()
    jugador = db.query(Jugador).filter(Jugador.username == username).first()
    if not jugador:
        jugador = Jugador(username=username, puntos=100)
        db.add(jugador)
        db.commit()
        db.refresh(jugador)
    puntos_actuales = jugador.puntos
    db.close()

    # Devolvemos la plantilla usando la sintaxis compatible más estricta
    return templates.TemplateResponse(
        request=request,
        name="game.html",
        context={
            "codigo": codigo,
            "username": username,
            "puntos": puntos_actuales
        }
    )

@app.websocket("/ws/{codigo}/{username}")
async def websocket_endpoint(websocket: WebSocket, codigo: str, username: str):
    await websocket.accept()
    
    # Aseguramos que el código de la sala esté registrado (usando el código que escribió el usuario)
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
    print(f"Jugador {username} conectado a la sala '{codigo}'")

    try:
        # Si ya se unieron los 2 jugadores, les mandamos la señal de inicio de partida
        if len(salas[codigo]) == 2:
            for index, ws in enumerate(salas[codigo]):
                es_creador = (index == 0)
                await ws.send_text(json.dumps({
                    "type": "start",
                    "rol": "creador" if es_creador else "invitado"
                }))

        # Escuchamos los movimientos del juego continuamente
        while True:
            data = await websocket.receive_text()
            mensaje = json.loads(data)
            
            # En caso de que se envíe una señal de fin de juego, sumamos los puntos en la DB
            if mensaje.get("type") == "victory":
                db = SessionLocal()
                jugador = db.query(Jugador).filter(Jugador.username == username).first()
                if jugador:
                    jugador.puntos += 25  # Sumamos 25 puntos por ganar
                    db.commit()
                db.close()

            # Reenviar el evento al rival
            for cliente in salas[codigo]:
                if cliente != websocket:
                    await cliente.send_text(data)

    except WebSocketDisconnect:
        # Manejamos la salida de un jugador de la sala
        if codigo in salas and websocket in salas[codigo]:
            salas[codigo].remove(websocket)
            for cliente in salas[codigo]:
                await cliente.send_text(json.dumps({
                    "type": "disconnection", 
                    "message": "Tu rival se ha desconectado de la partida."
                }))
            if not salas[codigo]:
                del salas[codigo]
        print(f"Jugador {username} abandonó la sala '{codigo}'")
