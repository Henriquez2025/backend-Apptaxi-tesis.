import os
import urllib.parse
import random
import json
import base64
from datetime import date, datetime, timedelta
from typing import Optional, List

import uvicorn
import httpx
from fastapi import FastAPI, Depends, HTTPException, Form, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, ForeignKey, text, Date, DateTime, Boolean
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from sqladmin import Admin, ModelView
from geoalchemy2 import Geometry

# --- CONFIGURACIï¿½N DE BASE DE DATOS ---
PROJECT_ID = os.getenv("SUPABASE_PROJECT_ID") or os.getenv("PROJECT_ID")
SUPABASE_USER = os.getenv("SUPABASE_DB_USER") or os.getenv("DB_USER")
SUPABASE_HOST = os.getenv("SUPABASE_DB_HOST") or os.getenv("DB_HOST") or "aws-1-sa-east-1.pooler.supabase.com"
SUPABASE_PORT = os.getenv("SUPABASE_DB_PORT") or os.getenv("DB_PORT") or "6543"
SUPABASE_DB = os.getenv("SUPABASE_DB_NAME") or os.getenv("DB_NAME") or "postgres"
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD") or os.getenv("DB_PASSWORD")

if not SUPABASE_USER and PROJECT_ID:
    SUPABASE_USER = f"postgres.{PROJECT_ID}"

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    if not SUPABASE_USER or not DB_PASSWORD:
        raise RuntimeError("Falta configuraciï¿½n de base de datos (DATABASE_URL o SUPABASE_DB_USER/DB_USER y SUPABASE_DB_PASSWORD/DB_PASSWORD).")
    encoded_pass = urllib.parse.quote_plus(DB_PASSWORD)
    DATABASE_URL = (
        f"postgresql+asyncpg://{SUPABASE_USER}:{encoded_pass}"
        f"@{SUPABASE_HOST}:{SUPABASE_PORT}/{SUPABASE_DB}"
        "?ssl=require&prepared_statement_cache_size=0"
    )
# Inicializaciï¿½n del Motor
engine = None
try:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {"jit": "off"},
            "command_timeout": 60,
            "statement_cache_size": 0,
        }
    )
except Exception as e:
    print(f"FATAL: Error inicializando engine DB: {e}")

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

PALABRAS_CLAVE = ["SOL", "LUNA", "MAR", "RIO", "LUZ", "PAZ", "ORO", "AZUL", "ROJO", "TIGRE", "LEON", "AGUA", "FUEGO", "AIRE", "JAZZ", "ROCK", "MENTA", "COCO", "LIMA"]

# --- CONFIGURACIï¿½N SUPABASE AUTH ---
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("SUPABASE_SERVICE_KEY")
DEFAULT_USER_PASSWORD = os.getenv("DEFAULT_USER_PASSWORD")
BASE_PUBLIC_URL = (os.getenv("PUBLIC_BASE_URL") or "https://backend-apptaxi-tesis.onrender.com").rstrip("/")

def _build_public_url(path: str):
    return f"{BASE_PUBLIC_URL}{path}"

def _require_default_password() -> str:
    if not DEFAULT_USER_PASSWORD:
        raise HTTPException(status_code=500, detail="DEFAULT_USER_PASSWORD no configurado")
    return DEFAULT_USER_PASSWORD

async def _supabase_admin_create_user(email: str, password: str, role: str):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return {"error": "Supabase Auth no configurado (SUPABASE_URL/SUPABASE_SERVICE_ROLE)"}
    url = f"{SUPABASE_URL}/auth/v1/admin/users"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"role": role},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        try:
            body = resp.json()
            msg = body.get("msg") or body.get("message") or body.get("error") or str(body)
        except Exception:
            msg = resp.text or f"HTTP {resp.status_code}"
        return {"error": msg}
    return resp.json()

async def _supabase_admin_delete_user(user_id: str):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return
    url = f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        await client.delete(url, headers=headers)


_sos_connections = set()

async def _broadcast_sos(payload: dict):
    if not _sos_connections:
        return
    for ws in list(_sos_connections):
        try:
            await ws.send_json(payload)
        except Exception:
            _sos_connections.discard(ws)
async def _file_to_b64(file: Optional[UploadFile]) -> Optional[str]:
    if not file:
        return None
    data = await file.read()
    return base64.b64encode(data).decode("ascii")


def _b64_to_bytes(value: Optional[str]) -> Optional[bytes]:
    if not value:
        return None
    if "," in value:
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value)
    except Exception:
        return None

def _guess_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return "application/octet-stream"# -----------------------------------------------------------------------------
# MODELOS ORM
# -----------------------------------------------------------------------------
class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    password_hash = Column(String) 
    role = Column(String)
    perfil_cliente = relationship("Cliente", back_populates="usuario", uselist=False)
    perfil_conductor = relationship("Conductor", back_populates="usuario", uselist=False)
    perfil_admin = relationship("Administrador", back_populates="usuario", uselist=False)

class Cliente(Base):
    __tablename__ = "clientes"
    id_cliente = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    nom_apell = Column(String)
    pais = Column(String)
    ciudad = Column(String)
    telefono = Column(String)
    fecha_nacimiento = Column(Date)
    usuario = relationship("Usuario", back_populates="perfil_cliente")

class Vehiculo(Base):
    __tablename__ = "vehiculos"
    id = Column(Integer, primary_key=True)
    marca = Column(String)
    modelo = Column(String)
    placa = Column(String, unique=True)
    color = Column(String, nullable=True)
    anio = Column(String, nullable=True)

class Conductor(Base):
    __tablename__ = "conductores"
    id_conductor = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"))
    nom_apell = Column(String)
    telefono = Column(String)
    fecha_nacimiento = Column(Date)
    ubicacion = Column(Geometry('POINT', srid=4326), nullable=True)
    activo = Column(Boolean, default=False)
    cedula = Column(String, nullable=True) 
    usuario = relationship("Usuario", back_populates="perfil_conductor")
    vehiculo = relationship("Vehiculo")

class Administrador(Base):
    __tablename__ = "administradores"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    nom_apell = Column(String)
    cargo = Column(String)
    telefono = Column(String)
    usuario = relationship("Usuario", back_populates="perfil_admin")

class Emergencia(Base):
    __tablename__ = "emergencia"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    nombre_contacto = Column(String)
    numero_whatsapp = Column(String)
    fecha_registro = Column(DateTime(timezone=True), server_default=func.now())
    usuario = relationship("Usuario")

class Alerta(Base):
    __tablename__ = "alertas"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    ubicacion = Column(String)
    mensaje_extra = Column(String)
    fecha = Column(DateTime(timezone=True), server_default=func.now())
    usuario = relationship("Usuario")

class Viaje(Base):
    __tablename__ = "viajes"
    id = Column(Integer, primary_key=True)
    cliente_id = Column(Integer, ForeignKey("usuarios.id"))
    conductor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    origen = Column(String)
    destino = Column(String)
    estado = Column(String, default='pendiente')
    tarifa = Column(Float)
    origen_lat = Column(Float, nullable=True)
    origen_lng = Column(Float, nullable=True)
    destino_lat = Column(Float, nullable=True)
    destino_lng = Column(Float, nullable=True)
    origen_geom = Column(Geometry('POINT', srid=4326), nullable=True)
    destino_geom = Column(Geometry('POINT', srid=4326), nullable=True)
    clave_seguridad = Column(String, nullable=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    cliente_usuario = relationship("Usuario", foreign_keys=[cliente_id])
    conductor_usuario = relationship("Usuario", foreign_keys=[conductor_id])

# -----------------------------------------------------------------------------
# DTOs
# -----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str; password: str
    
class AuthSyncRequest(BaseModel):
    email: str
    supabase_uid: str
    access_token: Optional[str] = None

class ViajeRequest(BaseModel):
    usuario_id: int; origen: str; destino: str; tarifa: float
    origen_lat: Optional[float] = None; origen_lng: Optional[float] = None
    destino_lat: Optional[float] = None; destino_lng: Optional[float] = None

class AceptarViajeRequest(BaseModel):
    viaje_id: int; conductor_id: int

class UsuarioRegistroRequest(BaseModel):
    nombre: str; email: str; password: str; role: str = "cliente"
    telefono: Optional[str] = None; fecha_nacimiento: Optional[str] = None
    pais: Optional[str] = None; ciudad: Optional[str] = None
    tipo_documento: str | None = None
    numero_documento: str | None = None

class RegistroConductorRequest(BaseModel):
    nombre: str; email: str; password: str; telefono: str; fecha_nacimiento: str
    role: str = "conductor"; vehiculo_marca: str; vehiculo_modelo: str; vehiculo_placa: str
    vehiculo_color: Optional[str] = None; vehiculo_anio: Optional[str] = None; cedula: Optional[str] = None; horario_trabajo: Optional[str] = None

class ContactoRequest(BaseModel):
    usuario_id: int; nombre_contacto: str; numero_whatsapp: str

class ContactoEditRequest(BaseModel):
    nombre_contacto: str; numero_whatsapp: str

class AlertaRequest(BaseModel):
    usuario_id: int; ubicacion: str; mensaje: str

class SosConductorRequest(BaseModel):
    usuario_id: int
    lat: float
    lng: float
    mensaje: Optional[str] = None

class SosConductorCloseRequest(BaseModel):
    usuario_id: int
class UbicacionConductorRequest(BaseModel):
    usuario_id: int; latitud: float; longitud: float

class EstadoConductorRequest(BaseModel):
    usuario_id: int; activo: bool

class EstadoViajeRequest(BaseModel):
    viaje_id: int; nuevo_estado: str

class CancelarViajeRequest(BaseModel):
    viaje_id: int; motivo: str = "Cancelado por usuario/conductor"

class IniciarViajeRequest(BaseModel):
    viaje_id: int; clave_ingresada: str

class EstadoConductorPut(BaseModel):
    activo: bool

# -----------------------------------------------------------------------------
# CONFIGURACIï¿½N APP & ADMIN
# -----------------------------------------------------------------------------
app = FastAPI(title="Taxi App API", description="API REST")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

if engine:
    admin = Admin(app, engine, title="Taxi Admin")
    class UsuarioAdmin(ModelView, model=Usuario): column_list = [Usuario.id, Usuario.email, Usuario.role]
    class ClienteAdmin(ModelView, model=Cliente): column_list = [Cliente.id_cliente, Cliente.nom_apell, Cliente.ciudad]
    class ConductorAdmin(ModelView, model=Conductor): column_list = [Conductor.id_conductor, Conductor.nom_apell, Conductor.activo]
    class VehiculoAdmin(ModelView, model=Vehiculo): column_list = [Vehiculo.id, Vehiculo.placa, Vehiculo.modelo]
    class ViajeAdmin(ModelView, model=Viaje): column_list = [Viaje.id, Viaje.estado, Viaje.tarifa, Viaje.origen]
    class EmergenciaAdmin(ModelView, model=Emergencia): column_list = [Emergencia.id, Emergencia.nombre_contacto]
    class AlertaAdmin(ModelView, model=Alerta): column_list = [Alerta.id, Alerta.ubicacion, Alerta.fecha]
    class AdministradorAdmin(ModelView, model=Administrador): column_list = [Administrador.id, Administrador.nom_apell]

    admin.add_view(UsuarioAdmin); admin.add_view(ClienteAdmin); admin.add_view(ConductorAdmin)
    admin.add_view(VehiculoAdmin); admin.add_view(ViajeAdmin); admin.add_view(EmergenciaAdmin)
    admin.add_view(AlertaAdmin); admin.add_view(AdministradorAdmin)

async def get_db():
    if not engine: raise HTTPException(status_code=500, detail="Error DB: Engine no inicializado")
    async with async_session() as session: yield session

# =============================================================================
# ENDPOINTS API
# =============================================================================

@app.get("/")
def leer_raiz(): return {"mensaje": "API Taxi Running (v29.0 - Con Registro Flota)."}

# ---------------------------------------------------------------------------
# REPORTES (ADMIN)
# ---------------------------------------------------------------------------

@app.get("/reportes/viajes/conductores")
async def reportes_viajes_conductores(db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT v.id, v.origen, v.destino, v.estado, v.tarifa, v.fecha_creacion,
                   c.nom_apell as conductor_nombre,
                   cli.nom_apell as cliente_nombre
            FROM viajes v
            LEFT JOIN conductores c ON v.conductor_id = c.usuario_id
            LEFT JOIN clientes cli ON v.cliente_id = cli.usuario_id
            WHERE v.conductor_id IS NOT NULL
            ORDER BY v.fecha_creacion DESC
        """)
        res = await db.execute(query)
        return [{
            "id": r.id,
            "origen": r.origen,
            "destino": r.destino,
            "estado": r.estado,
            "tarifa": r.tarifa,
            "fecha": r.fecha_creacion.isoformat() if r.fecha_creacion else None,
            "conductor": r.conductor_nombre or "Conductor",
            "pasajero": r.cliente_nombre or "Cliente",
        } for r in res.fetchall()]
    except Exception as e:
        return {"error": str(e)}


@app.get("/reportes/viajes/clientes")
async def reportes_viajes_clientes(db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT v.id, v.origen, v.destino, v.estado, v.tarifa, v.fecha_creacion,
                   c.nom_apell as conductor_nombre,
                   cli.nom_apell as cliente_nombre
            FROM viajes v
            LEFT JOIN conductores c ON v.conductor_id = c.usuario_id
            LEFT JOIN clientes cli ON v.cliente_id = cli.usuario_id
            ORDER BY v.fecha_creacion DESC
        """)
        res = await db.execute(query)
        return [{
            "id": r.id,
            "origen": r.origen,
            "destino": r.destino,
            "estado": r.estado,
            "tarifa": r.tarifa,
            "fecha": r.fecha_creacion.isoformat() if r.fecha_creacion else None,
            "conductor": r.conductor_nombre or "Conductor",
            "pasajero": r.cliente_nombre or "Cliente",
        } for r in res.fetchall()]
    except Exception as e:
        return {"error": str(e)}


@app.get("/reportes/sos/conductores")
async def reportes_sos_conductores(db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT a.id, a.ubicacion, a.mensaje_extra, a.fecha,
                   c.nom_apell as nombre, u.email
            FROM alertas a
            JOIN usuarios u ON a.usuario_id = u.id
            LEFT JOIN conductores c ON a.usuario_id = c.usuario_id
            WHERE u.role = 'conductor'
            ORDER BY a.fecha DESC
        """)
        res = await db.execute(query)
        return [{
            "id": r.id,
            "ubicacion": r.ubicacion,
            "mensaje": r.mensaje_extra,
            "fecha": r.fecha.isoformat() if r.fecha else None,
            "nombre": r.nombre or "Conductor",
            "email": r.email,
        } for r in res.fetchall()]
    except Exception as e:
        return {"error": str(e)}


@app.get("/reportes/sos/clientes")
async def reportes_sos_clientes(db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT a.id, a.ubicacion, a.mensaje_extra, a.fecha,
                   c.nom_apell as nombre, u.email
            FROM alertas a
            JOIN usuarios u ON a.usuario_id = u.id
            LEFT JOIN clientes c ON a.usuario_id = c.usuario_id
            WHERE u.role = 'cliente'
            ORDER BY a.fecha DESC
        """)
        res = await db.execute(query)
        return [{
            "id": r.id,
            "ubicacion": r.ubicacion,
            "mensaje": r.mensaje_extra,
            "fecha": r.fecha.isoformat() if r.fecha else None,
            "nombre": r.nombre or "Cliente",
            "email": r.email,
        } for r in res.fetchall()]
    except Exception as e:
        return {"error": str(e)}

# --- LOGIN Y REGISTROS Bï¿½SICOS ---

@app.post("/login")
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        res = await db.execute(text("SELECT id, email, password_hash, role, must_change_password FROM usuarios WHERE email = :email"), {"email": datos.email})
        user = res.fetchone()
        
        if not user: return {"error": "Usuario no encontrado"}
        if user.password_hash != datos.password: return {"error": "Contraseï¿½a incorrecta"}

        nombre_real = "Usuario"
        try:
            if user.role == 'cliente':
                res_cli = (await db.execute(text("SELECT nom_apell FROM clientes WHERE usuario_id = :uid"), {"uid": user.id})).fetchone()
                if res_cli: nombre_real = res_cli.nom_apell
            elif user.role == 'conductor':
                res_cond = (await db.execute(text("SELECT nom_apell FROM conductores WHERE usuario_id = :uid"), {"uid": user.id})).fetchone()
                if res_cond: nombre_real = res_cond.nom_apell
        except Exception: pass

        return dict(mensaje='Login OK', usuario=dict(id=user.id, nombre=nombre_real, role=user.role, must_change_password=bool(user.must_change_password)))
    except Exception as e:
        return {"error": f"Error interno: {str(e)}"}


@app.get("/debug/supabase")
async def debug_supabase():
    url = SUPABASE_URL
    key = SUPABASE_SERVICE_ROLE or ""
    return {
        "supabase_url": url,
        "service_role_len": len(key),
        "service_role_prefix": key[:6] if key else "",
        "service_role_suffix": key[-6:] if key else "",
    }
@app.post("/auth/sync")
async def auth_sync(datos: AuthSyncRequest, db: AsyncSession = Depends(get_db)):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return {"error": "Supabase Auth no configurado (SUPABASE_URL/SUPABASE_SERVICE_ROLE)"}

    auth_user = None
    admin_error = None
    token_error = None

    try:
        url = f"{SUPABASE_URL}/auth/v1/admin/users/{datos.supabase_uid}"
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 200:
            auth_user = resp.json()
        else:
            try:
                body = resp.json()
                admin_error = body.get("msg") or body.get("message") or body.get("error") or str(body)
            except Exception:
                admin_error = resp.text or f"HTTP {resp.status_code}"
    except Exception as e:
        admin_error = f"Error validando Supabase (admin): {str(e)}"

    if not auth_user and datos.access_token:
        try:
            url = f"{SUPABASE_URL}/auth/v1/user"
            headers = {
                "apikey": SUPABASE_SERVICE_ROLE,
                "Authorization": f"Bearer {datos.access_token}",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                auth_user = resp.json()
            else:
                try:
                    body = resp.json()
                    token_error = body.get("msg") or body.get("message") or body.get("error") or str(body)
                except Exception:
                    token_error = resp.text or f"HTTP {resp.status_code}"
        except Exception as e:
            token_error = f"Error validando Supabase (token): {str(e)}"

    if not auth_user:
        return {"error": admin_error or token_error or "No se pudo validar usuario en Supabase"}

    email_auth = (auth_user.get("email") or "").lower()
    if email_auth and email_auth != datos.email.lower():
        return {"error": "Email no coincide con el uid de Supabase"}

    auth_id = auth_user.get("id")
    if auth_id and auth_id != datos.supabase_uid:
        return {"error": "UID no coincide con Supabase"}
    try:
        res = await db.execute(
            text("SELECT id, email, role, must_change_password FROM usuarios WHERE email = :email"),
            {"email": datos.email},
        )
        user = res.fetchone()
        if not user:
            return {"error": "Usuario no encontrado en backend"}

        nombre_real = "Usuario"
        try:
            if user.role == "cliente":
                res_cli = (await db.execute(
                    text("SELECT nom_apell FROM clientes WHERE usuario_id = :uid"),
                    {"uid": user.id},
                )).fetchone()
                if res_cli:
                    nombre_real = res_cli.nom_apell
            elif user.role == "conductor":
                res_cond = (await db.execute(
                    text("SELECT nom_apell FROM conductores WHERE usuario_id = :uid"),
                    {"uid": user.id},
                )).fetchone()
                if res_cond:
                    nombre_real = res_cond.nom_apell
            elif user.role == "admin":
                res_admin = (await db.execute(
                    text("SELECT nom_apell FROM administradores WHERE usuario_id = :uid"),
                    {"uid": user.id},
                )).fetchone()
                if res_admin:
                    nombre_real = res_admin.nom_apell
        except Exception:
            pass

        return {
            "usuario": {
                "id": user.id,
                "nombre": nombre_real,
                "role": user.role,
                "roles_disponibles": [user.role],
                 'must_change_password': bool(user.must_change_password),
            }
        }
    except Exception as e:
        return {"error": f"Error interno: {str(e)}"}
@app.post("/registrar_usuario")
async def registrar_usuario(datos: UsuarioRegistroRequest, db: AsyncSession = Depends(get_db)):
    try:
        existing_id = (await db.execute(
            text("SELECT id FROM usuarios WHERE email = :e"),
            {"e": datos.email},
        )).scalar()

        f_nac = None
        if datos.fecha_nacimiento:
            try:
                f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date()
            except Exception:
                f_nac = None

        if existing_id:
            try:
                exists_cli = (await db.execute(
                    text("SELECT 1 FROM clientes WHERE usuario_id = :u"),
                    {"u": existing_id},
                )).scalar()

                if not exists_cli:
                    await db.execute(
                        text(
                            "INSERT INTO clientes (usuario_id, nom_apell, pais, ciudad, telefono, fecha_nacimiento, tipo_documento, numero_documento) "
                            "VALUES (:u, :n, :p, :c, :t, :f, :td, :nd)"
                        ),
                        {
                            "u": existing_id,
                            "n": datos.nombre,
                            "p": datos.pais,
                            "c": datos.ciudad,
                            "t": datos.telefono,
                            "f": f_nac,
                            "td": datos.tipo_documento,
                            "nd": datos.numero_documento,
                        },
                    )
                else:
                    await db.execute(
                        text(
                            "UPDATE clientes SET "
                            "nom_apell = COALESCE(NULLIF(nom_apell, ''), :n), "
                            "pais = COALESCE(NULLIF(pais, ''), :p), "
                            "ciudad = COALESCE(NULLIF(ciudad, ''), :c), "
                            "telefono = COALESCE(NULLIF(telefono, ''), :t), "
                            "fecha_nacimiento = COALESCE(fecha_nacimiento, :f), "
                            "tipo_documento = COALESCE(tipo_documento, :td), "
                            "numero_documento = COALESCE(numero_documento, :nd) "
                            "WHERE usuario_id = :u"
                        ),
                        {
                            "u": existing_id,
                            "n": datos.nombre,
                            "p": datos.pais,
                            "c": datos.ciudad,
                            "t": datos.telefono,
                            "f": f_nac,
                            "td": datos.tipo_documento,
                            "nd": datos.numero_documento,
                        },
                    )
                await db.commit()
                return {"mensaje": "Perfil actualizado", "id": existing_id}
            except Exception:
                await db.rollback()
                return {"error": "No se pudo actualizar perfil"}

        uid = (await db.execute(
            text("INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"),
            {"e": datos.email, "p": datos.password, "r": "cliente"},
        )).scalar()

        try:
            await db.execute(
                text(
                    "INSERT INTO clientes (usuario_id, nom_apell, pais, ciudad, telefono, fecha_nacimiento, tipo_documento, numero_documento) "
                    "VALUES (:u, :n, :p, :c, :t, :f, :td, :nd)"
                ),
                {
                    "u": uid,
                    "n": datos.nombre,
                    "p": datos.pais,
                    "c": datos.ciudad,
                    "t": datos.telefono,
                    "f": f_nac,
                    "td": datos.tipo_documento,
                    "nd": datos.numero_documento,
                },
            )
        except Exception:
            pass

        await db.commit()
        return {"mensaje": "Registrado", "id": uid}
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}


@app.post("/registrar_usuario_fotos")
async def registrar_usuario_fotos(
    nombre: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("cliente"),
    telefono: Optional[str] = Form(None),
    fecha_nacimiento: Optional[str] = Form(None),
    pais: Optional[str] = Form(None),
    ciudad: Optional[str] = Form(None),
    tipo_documento: Optional[str] = Form(None),
    numero_documento: Optional[str] = Form(None),
    foto_cedulafrente: UploadFile = File(None),
    foto_cedulaposterior: UploadFile = File(None),
    foto_selfieci: UploadFile = File(None),
    foto_pasaporte: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        f_nac = None
        if fecha_nacimiento:
            try:
                f_nac = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
            except Exception:
                f_nac = None

        foto_frente = await _file_to_b64(foto_cedulafrente)
        foto_atras = await _file_to_b64(foto_cedulaposterior)
        foto_selfie = await _file_to_b64(foto_selfieci)
        foto_pass = await _file_to_b64(foto_pasaporte)

        existing_id = (await db.execute(
            text("SELECT id FROM usuarios WHERE email = :e"),
            {"e": email},
        )).scalar()

        role_db = (role or "cliente").lower()

        if not existing_id:
            existing_id = (await db.execute(
                text("INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"),
                {"e": email, "p": password, "r": role_db},
            )).scalar()

        exists_cli = (await db.execute(
            text("SELECT 1 FROM clientes WHERE usuario_id = :u"),
            {"u": existing_id},
        )).scalar()

        foto_frente_url = _build_public_url(f"/clientes/{existing_id}/foto_cedula_frente") if foto_frente else None
        foto_atras_url = _build_public_url(f"/clientes/{existing_id}/foto_cedula_posterior") if foto_atras else None
        foto_selfie_url = _build_public_url(f"/clientes/{existing_id}/foto_selfie") if foto_selfie else None
        foto_pass_url = _build_public_url(f"/clientes/{existing_id}/foto_pasaporte") if foto_pass else None

        if not exists_cli:
            await db.execute(
                text(
                    "INSERT INTO clientes (usuario_id, nom_apell, pais, ciudad, telefono, fecha_nacimiento, tipo_documento, numero_documento, "
                    "foto_cedulafrente, foto_cedulaposterior, foto_selfieci, foto_pasaporte, "
                    "foto_cedulafrente_url, foto_cedulaposterior_url, foto_selfieci_url, foto_pasaporte_url) "
                    "VALUES (:u, :n, :p, :c, :t, :f, :td, :nd, :ff, :fa, :fs, :fp, :ffu, :fau, :fsu, :fpu)"
                ),
                {
                    "u": existing_id,
                    "n": nombre,
                    "p": pais,
                    "c": ciudad,
                    "t": telefono,
                    "f": f_nac,
                    "td": tipo_documento,
                    "nd": numero_documento,
                    "ff": foto_frente,
                    "fa": foto_atras,
                    "fs": foto_selfie,
                    "fp": foto_pass,
                    "ffu": foto_frente_url,
                    "fau": foto_atras_url,
                    "fsu": foto_selfie_url,
                    "fpu": foto_pass_url,
                },
            )
        else:
            await db.execute(
                text(
                    "UPDATE clientes SET "
                    "nom_apell = COALESCE(NULLIF(nom_apell, ''), :n), "
                    "pais = COALESCE(NULLIF(pais, ''), :p), "
                    "ciudad = COALESCE(NULLIF(ciudad, ''), :c), "
                    "telefono = COALESCE(NULLIF(telefono, ''), :t), "
                    "fecha_nacimiento = COALESCE(fecha_nacimiento, :f), "
                    "tipo_documento = COALESCE(tipo_documento, :td), "
                    "numero_documento = COALESCE(numero_documento, :nd), "
                    "foto_cedulafrente = COALESCE(:ff, foto_cedulafrente), "
                    "foto_cedulaposterior = COALESCE(:fa, foto_cedulaposterior), "
                    "foto_selfieci = COALESCE(:fs, foto_selfieci), "
                    "foto_pasaporte = COALESCE(:fp, foto_pasaporte), "
                    "foto_cedulafrente_url = COALESCE(:ffu, foto_cedulafrente_url), "
                    "foto_cedulaposterior_url = COALESCE(:fau, foto_cedulaposterior_url), "
                    "foto_selfieci_url = COALESCE(:fsu, foto_selfieci_url), "
                    "foto_pasaporte_url = COALESCE(:fpu, foto_pasaporte_url) "
                    "WHERE usuario_id = :u"
                ),
                {
                    "u": existing_id,
                    "n": nombre,
                    "p": pais,
                    "c": ciudad,
                    "t": telefono,
                    "f": f_nac,
                    "td": tipo_documento,
                    "nd": numero_documento,
                    "ff": foto_frente,
                    "fa": foto_atras,
                    "fs": foto_selfie,
                    "fp": foto_pass,
                    "ffu": foto_frente_url,
                    "fau": foto_atras_url,
                    "fsu": foto_selfie_url,
                    "fpu": foto_pass_url,
                },
            )

        await db.commit()
        return {"mensaje": "Registrado", "id": existing_id}
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}
@app.post("/api/admin/registrar_conductor_auth")
async def registrar_conductor_auth(datos: RegistroConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        existing_id = (await db.execute(
            text("SELECT id FROM usuarios WHERE email = :e"),
            {"e": datos.email},
        )).scalar()
        if existing_id:
            return {"error": "El correo ya estï¿½ registrado"}

        if not datos.cedula:
            return {"error": "Cedula requerida para clave inicial"}
        supa_res = await _supabase_admin_create_user(datos.email, datos.cedula, "conductor")
        if isinstance(supa_res, dict) and supa_res.get("error"):
            return {"error": supa_res["error"]}

        vehiculo_id = (await db.execute(
            text("SELECT id FROM vehiculos WHERE placa = :p"),
            {"p": datos.vehiculo_placa},
        )).scalar()

        if not vehiculo_id:
            vehiculo_id = (await db.execute(
                text(
                    "INSERT INTO vehiculos (marca, modelo, placa, color, anio) "
                    "VALUES (:m, :mo, :p, :c, :a) RETURNING id"
                ),
                {
                    "m": datos.vehiculo_marca,
                    "mo": datos.vehiculo_modelo,
                    "p": datos.vehiculo_placa,
                    "c": datos.vehiculo_color,
                    "a": datos.vehiculo_anio,
                },
            )).scalar()

        uid = (await db.execute(
            text(
                "INSERT INTO usuarios (email, password_hash, role, must_change_password) "
                "VALUES (:e, :p, :r, true) RETURNING id"
            ),
            {"e": datos.email, "p": datos.cedula, "r": "conductor"},
        )).scalar()

        await db.execute(
            text(
                "INSERT INTO conductores (usuario_id, vehiculo_id, nom_apell, telefono, fecha_nacimiento, cedula, activo) "
                "VALUES (:uid, :vid, :nom, :tel, :fn, :ced, true)"
            ),
            {
                "uid": uid,
                "vid": vehiculo_id,
                "nom": datos.nombre,
                "tel": datos.telefono,
                "fn": datos.fecha_nacimiento,
                "ced": datos.cedula,
            },
        )

        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}

@app.get("/vehiculos/placas")
async def obtener_lista_placas(db: AsyncSession = Depends(get_db)):
    # Retorna lista simple: ["GCA-123", "PBA-456"]
    try:
        result = await db.execute(text("SELECT placa FROM vehiculos ORDER BY placa ASC"))
        return [row.placa for row in result.fetchall()]
    except Exception as e:
        print(f"Error obteniendo placas: {e}")
        return []

@app.get("/vehiculos/{placa}")
async def obtener_vehiculo_por_placa(placa: str, db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT v.marca, v.modelo, v.color, c.nom_apell 
            FROM vehiculos v 
            JOIN conductores c ON c.vehiculo_id = v.id 
            WHERE v.placa = :placa 
            LIMIT 1
        """)
        result = await db.execute(query, {"placa": placa})
        row = result.fetchone()
        
        if row:
            return {
                "marca": f"{row.marca} {row.modelo}", 
                "color": row.color,
                "dueno": row.nom_apell
            }
        else:
            return None 
    except Exception as e:
        print(f"Error buscando placa: {e}")
        return None


@app.get("/vehiculos/{vehiculo_id}/foto")
async def ver_foto_vehiculo(vehiculo_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("SELECT foto_vehiculo FROM vehiculos WHERE id = :id"),
        {"id": vehiculo_id},
    )).fetchone()
    data = _b64_to_bytes(row.foto_vehiculo if row else None)
    if not data:
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))

@app.get("/conductores/{usuario_id}/foto_perfil")
async def ver_foto_conductor(usuario_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("SELECT foto_perfil FROM conductores WHERE usuario_id = :uid"),
        {"uid": usuario_id},
    )).fetchone()
    data = _b64_to_bytes(row.foto_perfil if row else None)
    if not data:
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))

@app.get("/conductores/{usuario_id}/cedula_front")
async def ver_cedula_front_conductor(usuario_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("SELECT cedula_front FROM conductores WHERE usuario_id = :uid"),
        {"uid": usuario_id},
    )).fetchone()
    data = _b64_to_bytes(row.cedula_front if row else None)
    if not data:
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))

@app.get("/conductores/{usuario_id}/cedula_back")
async def ver_cedula_back_conductor(usuario_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("SELECT cedula_back FROM conductores WHERE usuario_id = :uid"),
        {"uid": usuario_id},
    )).fetchone()
    data = _b64_to_bytes(row.cedula_back if row else None)
    if not data:
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))

@app.get("/clientes/{usuario_id}/foto_cedula_frente")
async def ver_cedula_frente_cliente(usuario_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("SELECT foto_cedulafrente FROM clientes WHERE usuario_id = :uid"),
        {"uid": usuario_id},
    )).fetchone()
    data = _b64_to_bytes(row.foto_cedulafrente if row else None)
    if not data:
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))

@app.get("/clientes/{usuario_id}/foto_cedula_posterior")
async def ver_cedula_posterior_cliente(usuario_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("SELECT foto_cedulaposterior FROM clientes WHERE usuario_id = :uid"),
        {"uid": usuario_id},
    )).fetchone()
    data = _b64_to_bytes(row.foto_cedulaposterior if row else None)
    if not data:
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))

@app.get("/clientes/{usuario_id}/foto_selfie")
async def ver_selfie_cliente(usuario_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("SELECT foto_selfieci FROM clientes WHERE usuario_id = :uid"),
        {"uid": usuario_id},
    )).fetchone()
    data = _b64_to_bytes(row.foto_selfieci if row else None)
    if not data:
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))

@app.get("/clientes/{usuario_id}/foto_pasaporte")
async def ver_pasaporte_cliente(usuario_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("SELECT foto_pasaporte FROM clientes WHERE usuario_id = :uid"),
        {"uid": usuario_id},
    )).fetchone()
    data = _b64_to_bytes(row.foto_pasaporte if row else None)
    if not data:
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))
@app.post("/registrar_conductor_existente")
async def registrar_conductor_existente(
    placa_vinculada: str = Form(...),
    nombre: str = Form(...),
    apellido: str = Form(...),
    cedula: str = Form(...),
    email: str = Form(...),
    telefono: str = Form(...),
    fecha_nacimiento: str = Form(...),
    role: str = Form(...),
    cedula_front: UploadFile = File(None),
    cedula_back: UploadFile = File(None),
    foto_perfil: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
):
    try:
        # A. Verificar Auto
        q_vehiculo = text("SELECT id FROM vehiculos WHERE placa = :placa")
        res_v = await db.execute(q_vehiculo, {"placa": placa_vinculada})
        vehiculo_id = res_v.scalar()

        if not vehiculo_id:
            raise HTTPException(status_code=404, detail="El vehï¿½culo no existe")

        # B. Crear Usuario
        # Usamos el email que viene del form, o generamos uno si no viene
        email_final = email if email else f"{cedula}@taxis.com"
        # Evitar duplicados
        exists_email = (await db.execute(
            text("SELECT 1 FROM usuarios WHERE email = :e"),
            {"e": email_final},
        )).scalar()
        if exists_email:
            return JSONResponse(status_code=400, content={"error": "El correo ya existe"})
        supa_res = await _supabase_admin_create_user(email_final, cedula, role)
        if isinstance(supa_res, dict) and supa_res.get('error'):
            return JSONResponse(status_code=400, content=dict(error=supa_res['error']))

        
        q_user = text
        q_user = text("""
            INSERT INTO usuarios (email, password_hash, role, must_change_password)
            VALUES (:email, :pwd, :role, true)
            RETURNING id
        """)
        try:
            res_u = await db.execute(q_user, {
                "email": email_final,
                "pwd": cedula,
                "role": role
            })
            new_user_id = res_u.scalar()
        except IntegrityError:
            await db.rollback()
            return JSONResponse(status_code=400, content={"error": "El correo ya existe"})
        # C. Crear Conductor vinculado
        q_conductor = text("""
            INSERT INTO conductores (usuario_id, nom_apell, telefono, cedula, activo, vehiculo_id)
            VALUES (:uid, :nombre, :telf, :ced, true, :vid)
        """)
        await db.execute(q_conductor, {
            "uid": new_user_id,
            "nombre": f"{nombre} {apellido}",
            "telf": telefono,
            "ced": cedula,
            "vid": vehiculo_id
        })

        foto_front = await _file_to_b64(cedula_front)
        foto_back = await _file_to_b64(cedula_back)
        foto_perfil_b64 = await _file_to_b64(foto_perfil)
        foto_front_url = _build_public_url(f"/conductores/{new_user_id}/cedula_front") if foto_front else None
        foto_back_url = _build_public_url(f"/conductores/{new_user_id}/cedula_back") if foto_back else None
        foto_perfil_url = _build_public_url(f"/conductores/{new_user_id}/foto_perfil") if foto_perfil_b64 else None
        await db.execute(
            text("UPDATE conductores SET cedula_front=:f1, cedula_back=:f2, foto_perfil=:fp, cedula_front_url=:f1u, cedula_back_url=:f2u, foto_perfil_url=:fpu WHERE usuario_id=:uid"),
            {"f1": foto_front, "f2": foto_back, "fp": foto_perfil_b64, "f1u": foto_front_url, "f2u": foto_back_url, "fpu": foto_perfil_url, "uid": new_user_id},
        )

        await db.commit()
        return {"mensaje": "Conductor registrado y vinculado exitosamente"}

    except Exception as e:
        await db.rollback()
        print(f"Error en registro: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/registrar_flota_completo")
async def registrar_flota_completo(
    # Recibimos los campos de texto
    vehiculo_marca: str = Form(...),
    vehiculo_modelo: str = Form(...),
    vehiculo_placa: str = Form(...),
    vehiculo_color: str = Form(...),
    
    owner_nombre: str = Form(...),
    owner_apellido: str = Form(...),
    owner_cedula: str = Form(...),
    owner_fecha_nac: str = Form(...),
    owner_telefono: str = Form(...),
    
    # La lista de conductores extra llega como texto JSON
    conductores_extra: str = Form(default="[]"), 

    # Recibimos los archivos (pueden ser opcionales con None)
    cedula_front: UploadFile = File(None),
    cedula_back: UploadFile = File(None),
    foto_perfil: UploadFile = File(None),
    foto_vehiculo: UploadFile = File(None),
    
    db: AsyncSession = Depends(get_db)
):
    try:
        # 1. Crear el Usuario (Dueño)
        owner_email = f"{owner_cedula}@taxis.com"
        owner_row = (await db.execute(
            text("SELECT id, role FROM usuarios WHERE email = :e"),
            {"e": owner_email},
        )).fetchone()
        if owner_row:
            if owner_row.role != "conductor":
                return JSONResponse(status_code=400, content={"error": "Email ya existe con otro rol"})
            owner_user_id = owner_row.id
        else:
            supa_res = await _supabase_admin_create_user(owner_email, owner_cedula, "conductor")
            if isinstance(supa_res, dict) and supa_res.get("error"):
                return JSONResponse(status_code=400, content={"error": supa_res["error"]})
            owner_user_id = (await db.execute(
                text("INSERT INTO usuarios (email, password_hash, role, must_change_password) VALUES (:e, :p, :r, true) RETURNING id"),
                {"e": owner_email, "p": owner_cedula, "r": "conductor"},
            )).scalar()

        # 2. Registrar Vehï¿½culo
        nuevo_auto = Vehiculo(
            placa=vehiculo_placa,
            marca=vehiculo_marca,
            modelo=vehiculo_modelo,
            color=vehiculo_color,
            anio="2025" 
        )
        db.add(nuevo_auto)
        await db.commit()
        await db.refresh(nuevo_auto)

        foto_auto = await _file_to_b64(foto_vehiculo)
        foto_auto_url = _build_public_url(f"/vehiculos/{nuevo_auto.id}/foto") if foto_auto else None
        await db.execute(
            text("UPDATE vehiculos SET foto_vehiculo=:fv, foto_vehiculo_url=:fvu WHERE id=:vid"),
            {"fv": foto_auto, "fvu": foto_auto_url, "vid": nuevo_auto.id},
        )
        await db.commit()

        # 3. Registrar al Dueño en tabla Conductores
        exists_owner_cond = (await db.execute(
            text("SELECT 1 FROM conductores WHERE usuario_id = :u"),
            {"u": owner_user_id},
        )).scalar()
        if exists_owner_cond:
            return JSONResponse(status_code=400, content={"error": "El conductor ya existe"})

        nuevo_conductor = Conductor(
            usuario_id=owner_user_id,
            nom_apell=f"{owner_nombre} {owner_apellido}",
            telefono=owner_telefono,
            cedula=owner_cedula, 
            activo=True,
            vehiculo_id=nuevo_auto.id
        )
        db.add(nuevo_conductor)
        await db.commit()

        foto_front = await _file_to_b64(cedula_front)
        foto_back = await _file_to_b64(cedula_back)
        foto_perfil_b64 = await _file_to_b64(foto_perfil)
        foto_front_url = _build_public_url(f"/conductores/{owner_user_id}/cedula_front") if foto_front else None
        foto_back_url = _build_public_url(f"/conductores/{owner_user_id}/cedula_back") if foto_back else None
        foto_perfil_url = _build_public_url(f"/conductores/{owner_user_id}/foto_perfil") if foto_perfil_b64 else None
        await db.execute(
            text("UPDATE conductores SET cedula_front=:f1, cedula_back=:f2, foto_perfil=:fp, cedula_front_url=:f1u, cedula_back_url=:f2u, foto_perfil_url=:fpu WHERE usuario_id=:uid"),
            {"f1": foto_front, "f2": foto_back, "fp": foto_perfil_b64, "f1u": foto_front_url, "f2u": foto_back_url, "fpu": foto_perfil_url, "uid": owner_user_id},
        )
        await db.commit()

        # 4. Registrar Conductores Extra
        lista_conductores = json.loads(conductores_extra) 
        
        for extra in lista_conductores:
            # Crear usuario para el chofer extra
            # Generar email ï¿½nico si no viene
            email_extra = f"{extra['cedula']}@chofer.com"
            
            chofer_row = (await db.execute(
                text("SELECT id, role FROM usuarios WHERE email = :e"),
                {"e": email_extra},
            )).fetchone()
            if chofer_row:
                if chofer_row.role != "conductor":
                    return JSONResponse(status_code=400, content={"error": f"Email ya existe con otro rol: {email_extra}"})
                chofer_user_id = chofer_row.id
            else:
                supa_res = await _supabase_admin_create_user(email_extra, extra["cedula"], "conductor")
                if isinstance(supa_res, dict) and supa_res.get("error"):
                    return JSONResponse(status_code=400, content={"error": supa_res["error"]})
                chofer_user_id = (await db.execute(
                    text("INSERT INTO usuarios (email, password_hash, role, must_change_password) VALUES (:e, :p, :r, true) RETURNING id"),
                    {"e": email_extra, "p": extra["cedula"], "r": "conductor"},
                )).scalar()

            chofer = Conductor(
                usuario_id=chofer_user_id,
                nom_apell=f"{extra['nombre']} {extra['apellido']}",
                telefono=extra.get('telefono', '0000000000'),
                activo=True,
                vehiculo_id=nuevo_auto.id,
                cedula=extra['cedula']
            )
            db.add(chofer)
        
        await db.commit()
        return {"mensaje": "Flota registrada correctamente"}

    except Exception as e:
        print(f"Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/viajes/solicitar")
async def solicitar(v: ViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        clave = random.choice(PALABRAS_CLAVE)
        geo_ori = f"ST_GeomFromText('POINT({v.origen_lng} {v.origen_lat})', 4326)" if v.origen_lng else "NULL"
        geo_des = f"ST_GeomFromText('POINT({v.destino_lng} {v.destino_lat})', 4326)" if v.destino_lng else "NULL"
        
        query = text(f"INSERT INTO viajes (cliente_id, origen, destino, tarifa, estado, origen_lat, origen_lng, destino_lat, destino_lng, origen_geom, destino_geom, clave_seguridad, fecha_creacion) VALUES (:cid, :ori, :des, :tar, 'pendiente', :olat, :olng, :dlat, :dlng, {geo_ori}, {geo_des}, :clave, NOW()) RETURNING id")
        res = await db.execute(query, {"cid": v.usuario_id, "ori": v.origen, "des": v.destino, "tar": v.tarifa, "olat": v.origen_lat, "olng": v.origen_lng, "dlat": v.destino_lat, "dlng": v.destino_lng, "clave": clave})
        vid = res.scalar()
        
        await db.commit()
        return {"mensaje": "Viaje solicitado", "id_viaje": vid, "clave": clave}
    except Exception as e: 
        await db.rollback()
        return {"error": str(e)}

@app.get("/viajes/pendientes")
async def ver_pendientes(db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT v.id, v.origen, v.destino, v.tarifa, v.estado, 
                   v.origen_lat, v.origen_lng, v.destino_lat, v.destino_lng, 
                   c.nom_apell, v.fecha_creacion
            FROM viajes v
            LEFT JOIN clientes c ON v.cliente_id = c.usuario_id
            WHERE v.estado='pendiente' 
            ORDER BY v.fecha_creacion DESC
            LIMIT 50
        """)
        res = await db.execute(query)
        return [{"id": r.id, "origen": r.origen, "destino": r.destino, "tarifa": r.tarifa, 
                 "estado": r.estado, "cliente": r.nom_apell or "Cliente", 
                 "origen_lat": r.origen_lat, "origen_lng": r.origen_lng, 
                 "destino_lat": r.destino_lat, "destino_lng": r.destino_lng,
                 "creado_en": r.fecha_creacion.isoformat() if r.fecha_creacion else None} for r in res.fetchall()]
    except: return []

@app.post("/viajes/aceptar")
async def aceptar(d: AceptarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        st = (await db.execute(text("SELECT estado FROM viajes WHERE id=:vid"), {"vid": d.viaje_id})).scalar()
        if st != 'pendiente': return {"error": "Viaje no disponible"}
        
        await db.execute(text("UPDATE viajes SET conductor_id=:cid, estado='aceptado' WHERE id=:vid"), {"cid": d.conductor_id, "vid": d.viaje_id})
        await db.commit()
        return {"mensaje": "Viaje aceptado"}
    except Exception as e: 
        await db.rollback()
        return {"error": str(e)}

@app.post("/viajes/validar_inicio")
async def validar_inicio_viaje(d: IniciarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        real = (await db.execute(text("SELECT clave_seguridad FROM viajes WHERE id=:vid"), {"vid": d.viaje_id})).scalar()
        if not real: return {"error": "Datos no encontrados", "exito": False}
        
        if d.clave_ingresada.upper().strip() == real.upper().strip():
            await db.execute(text("UPDATE viajes SET estado='en_curso' WHERE id=:vid"), {"vid": d.viaje_id})
            await db.commit()
            return {"mensaje": "OK", "exito": True}
        else: return {"error": "Clave incorrecta", "exito": False}
    except Exception as e: 
        await db.rollback()
        return {"error": str(e), "exito": False}

@app.post("/viajes/actualizar_estado")
async def actualizar_estado_viaje(d: EstadoViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("UPDATE viajes SET estado=:st WHERE id=:vid"), {"st": d.nuevo_estado, "vid": d.viaje_id})
        await db.commit()
        return {"mensaje": "Estado actualizado"}
    except Exception as e: 
        await db.rollback()
        return {"error": str(e)}

@app.post("/viajes/cancelar")
async def cancelar_viaje(d: CancelarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        st = (await db.execute(text("SELECT estado FROM viajes WHERE id=:vid"), {"vid": d.viaje_id})).scalar()
        if not st: return {"error": "Viaje no encontrado"}
        if st == 'cancelado': return {"mensaje": "Ya cancelado"}
        if st == 'finalizado': return {"error": "No se puede cancelar un viaje finalizado."}

        await db.execute(text("UPDATE viajes SET estado='cancelado' WHERE id=:vid"), {"vid": d.viaje_id})
        await db.commit()
        return {"mensaje": "Viaje cancelado correctamente"}
    except Exception as e: 
        await db.rollback()
        return {"error": f"Error interno: {str(e)}"}

@app.get("/viajes/{viaje_id}")
async def obtener_viaje(viaje_id: int, db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT v.estado, v.conductor_id, v.clave_seguridad, 
                   v.origen_lat, v.origen_lng, v.destino_lat, v.destino_lng,
                   c.nom_apell as nombre_conductor, ve.placa, ve.modelo, ve.color,
                   c.telefono,
                   ST_X(c.ubicacion::geometry) as conductor_lng, 
                   ST_Y(c.ubicacion::geometry) as conductor_lat
            FROM viajes v
            LEFT JOIN conductores c ON v.conductor_id = c.usuario_id
            LEFT JOIN vehiculos ve ON c.vehiculo_id = ve.id
            WHERE v.id = :vid
        """)
        v = (await db.execute(query, {"vid": viaje_id})).fetchone()
        if v:
            return {
                "estado": v.estado,
                "clave_seguridad": v.clave_seguridad,
                "origen": {"lat": v.origen_lat, "lng": v.origen_lng},
                "destino": {"lat": v.destino_lat, "lng": v.destino_lng},
                "conductor": {
                    "nombre": v.nombre_conductor,
                    "placa": v.placa,
                    "modelo": v.modelo,
                    "color": v.color,
                    "telefono": v.telefono,
                    "lat": v.conductor_lat,
                    "lng": v.conductor_lng
                } if v.conductor_id else None
            }
        return {"error": "No encontrado"}
    except Exception as e: return {"error": str(e)}


@app.get("/public/viajes/{viaje_id}")
async def public_viaje(viaje_id: int, db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT v.estado,
                   ST_X(c.ubicacion::geometry) as conductor_lng,
                   ST_Y(c.ubicacion::geometry) as conductor_lat
            FROM viajes v
            LEFT JOIN conductores c ON v.conductor_id = c.usuario_id
            WHERE v.id = :vid
        """)
        v = (await db.execute(query, {"vid": viaje_id})).fetchone()
        if not v:
            return {"error": "No encontrado"}
        return {
            "estado": v.estado,
            "conductor": {
                "lat": v.conductor_lat,
                "lng": v.conductor_lng,
            } if v.conductor_lat is not None and v.conductor_lng is not None else None,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/share/viaje/{viaje_id}", response_class=HTMLResponse)
async def share_viaje(viaje_id: int):
    return HTMLResponse(f"""
<!doctype html>
<html lang=\"es\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Seguimiento de viaje</title>
  <link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\" />
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    .banner {{ position: absolute; top: 12px; left: 12px; right: 12px; z-index: 999; background: #fff; padding: 10px 12px; border-radius: 10px; box-shadow: 0 6px 18px rgba(0,0,0,.15); font-family: Arial, sans-serif; }}
    .state {{ font-size: 12px; color: #666; }}
  </style>
</head>
<body>
  <div class=\"banner\">Seguimiento en tiempo real<br><span class=\"state\" id=\"state\">Cargando...</span></div>
  <div id=\"map\"></div>
  <script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script>
  <script>
    const map = L.map('map').setView([0, 0], 15);
   L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 19 }}).addTo(map);
    const marker = L.marker([0,0]).addTo(map);
    let hasFix = false;

    async function tick() {{
      try {{
        const r = await fetch(`/public/viajes/{viaje_id}`);
        const data = await r.json();
        if (data.error) {{
          document.getElementById('state').textContent = data.error;
          return;
        }}
        document.getElementById('state').textContent = data.estado || '';
        if (data.conductor && data.conductor.lat && data.conductor.lng) {{
          const lat = data.conductor.lat;
          const lng = data.conductor.lng;
          marker.setLatLng([lat, lng]);
          if (!hasFix) {{
            map.setView([lat, lng], 16);
            hasFix = true;
          }}
        }}
      }} catch (e) {{
        document.getElementById('state').textContent = 'Sin conexion';
      }}
    }}

    tick();
    setInterval(tick, 3000);
  </script>
</body>
</html>
""")

@app.post("/contactos/agregar")
async def agregar_contacto(d: ContactoRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("INSERT INTO emergencia (usuario_id, nombre_contacto, numero_whatsapp) VALUES (:uid, :nom, :num)"), {"uid": d.usuario_id, "nom": d.nombre_contacto, "num": d.numero_whatsapp})
        await db.commit()
        return {"mensaje": "Guardado"}
    except Exception as e: 
        await db.rollback()
        return {"error": str(e)}

@app.get("/contactos/listar/{uid}")
async def listar_contactos(uid: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("SELECT id, nombre_contacto, numero_whatsapp FROM emergencia WHERE usuario_id = :uid"), {"uid": uid})
    return [{"id": c.id, "nombre": c.nombre_contacto, "numero": c.numero_whatsapp} for c in res.fetchall()]

@app.put("/contactos/editar/{cid}")
async def editar_contacto(cid: int, datos: ContactoEditRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("UPDATE emergencia SET nombre_contacto=:nom, numero_whatsapp=:num WHERE id=:id"), {"nom": datos.nombre_contacto, "num": datos.numero_whatsapp, "id": cid})
        await db.commit()
        return {"mensaje": "Actualizado"}
    except: return {"error": "Error"}

@app.delete("/contactos/eliminar/{cid}")
async def eliminar_contacto(cid: int, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("DELETE FROM emergencia WHERE id=:id"), {"id": cid})
        await db.commit()
        return {"mensaje": "Eliminado"}
    except: return {"error": "Error"}

@app.post("/sos/activar")
async def activar_sos(d: AlertaRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("INSERT INTO alertas (usuario_id, ubicacion, mensaje_extra) VALUES (:uid, :ubi, :msg)"), {"uid": d.usuario_id, "ubi": d.ubicacion, "msg": d.mensaje})
        await db.commit()
        return {"mensaje": "Alerta registrada"}
    except: return {"error": "Error"}


@app.post("/sos/activar_conductor")
async def activar_sos_conductor(d: SosConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(
            text("INSERT INTO alertas (usuario_id, ubicacion, mensaje_extra) VALUES (:uid, :ubi, :msg)"),
            {"uid": d.usuario_id, "ubi": f"{d.lat},{d.lng}", "msg": d.mensaje or "SOS Conductor"},
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}

    res = await db.execute(
        text("""
            SELECT c.nom_apell, v.marca, v.modelo, v.placa, v.color
            FROM conductores c
            LEFT JOIN vehiculos v ON c.vehiculo_id = v.id
            WHERE c.usuario_id = :uid
        """),
        {"uid": d.usuario_id},
    )
    row = res.fetchone()

    payload = {
        "type": "sos",
        "usuario_id": d.usuario_id,
        "conductor": row.nom_apell if row and row.nom_apell else "Conductor",
        "vehiculo": {
            "marca": row.marca if row else None,
            "modelo": row.modelo if row else None,
            "placa": row.placa if row else None,
            "color": row.color if row else None,
        },
        "lat": d.lat,
        "lng": d.lng,
        "mensaje": d.mensaje,
        "ts": datetime.utcnow().isoformat(),
    }
    await _broadcast_sos(payload)
    return {"mensaje": "Alerta SOS enviada"}

@app.post("/sos/actualizar_conductor")
async def actualizar_sos_conductor(d: SosConductorRequest):
    payload = {
        "type": "sos_update",
        "usuario_id": d.usuario_id,
        "lat": d.lat,
        "lng": d.lng,
        "mensaje": d.mensaje,
        "ts": datetime.utcnow().isoformat(),
    }
    await _broadcast_sos(payload)
    return {"mensaje": "Actualizada"}

@app.post("/sos/cerrar_conductor")
async def cerrar_sos_conductor(d: SosConductorCloseRequest):
    payload = {
        "type": "sos_end",
        "usuario_id": d.usuario_id,
        "ts": datetime.utcnow().isoformat(),
    }
    await _broadcast_sos(payload)
    return {"mensaje": "SOS cerrado"}
@app.post("/conductores/ubicacion")
async def actualizar_ubicacion(datos: UbicacionConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("UPDATE conductores SET ubicacion = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) WHERE usuario_id = :uid"), {"uid": datos.usuario_id, "lat": datos.latitud, "lng": datos.longitud})
        await db.commit()
        return {"mensaje": "Ubicaciï¿½n OK"}
    except: return {"error": "Error"}

@app.post("/conductores/estado")
async def cambiar_estado(datos: EstadoConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("UPDATE conductores SET activo = :st WHERE usuario_id = :uid"), {"uid": datos.usuario_id, "st": datos.activo})
        await db.commit()
        return {"mensaje": "Estado OK"}
    except: return {"error": "Error"}

@app.get("/conductores/cercanos")
async def obtener_conductores_cercanos(lat: float, lng: float, radio_km: float = 2.0, db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT c.id_conductor, c.nom_apell, v.placa, v.modelo,
                   ST_X(c.ubicacion::geometry) as lng, 
                   ST_Y(c.ubicacion::geometry) as lat
            FROM conductores c
            JOIN vehiculos v ON c.vehiculo_id = v.id
            WHERE c.ubicacion IS NOT NULL
            AND c.activo = TRUE 
            AND ST_DWithin(c.ubicacion, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :metros)
        """)
        res = await db.execute(query, {"lat": lat, "lng": lng, "metros": radio_km * 1000})
        return [{"id": c.id_conductor, "nombre": c.nom_apell, "placa": c.placa, "modelo": c.modelo, "lat": c.lat, "lng": c.lng} for c in res.fetchall()]
    except: return []

@app.get("/conductores")
async def listar_conductores_todos(db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT c.id_conductor, c.nom_apell, c.telefono, c.activo, v.placa, u.id as usuario_id
            FROM conductores c
            JOIN vehiculos v ON c.vehiculo_id = v.id
            JOIN usuarios u ON c.usuario_id = u.id
        """)
        res = await db.execute(query)
        return [{
            "id": r.usuario_id,         
            "id_conductor": r.id_conductor, 
            "nom_apell": r.nom_apell, 
            "nombre": r.nom_apell,      
            "telefono": r.telefono, 
            "activo": r.activo,
            "placa": r.placa
        } for r in res.fetchall()]
    except Exception as e: return []

@app.get("/usuarios")
async def listar_usuarios_todos(db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT u.id, u.email, COALESCE(c.nom_apell, 'Sin Nombre') as nombre, c.telefono
            FROM usuarios u
            LEFT JOIN clientes c ON u.id = c.usuario_id
            WHERE u.role = 'cliente'
        """)
        res = await db.execute(query)
        return [{
            "id": r.id, 
            "email": r.email, 
            "nombre": r.nombre,
            "telefono": r.telefono 
        } for r in res.fetchall()]
    except Exception as e:
        print(f"Error usuarios: {e}")
        return []
    
@app.get("/vehiculos")
async def listar_vehiculos_todos(db: AsyncSession = Depends(get_db)):
    try:
        query = text("SELECT id, marca, modelo, placa, color, anio FROM vehiculos")
        res = await db.execute(query)
        return [{
            "id": r.id, 
            "marca": r.marca, 
            "modelo": r.modelo, 
            "placa": r.placa, 
            "color": r.color,
            "anio": r.anio
        } for r in res.fetchall()]
    except Exception as e:
        print(f"Error vehiculos: {e}")
        return []
    
@app.put("/conductores/{id_conductor}")
async def modificar_estado_conductor(id_conductor: int, datos: EstadoConductorPut, db: AsyncSession = Depends(get_db)):
    uid = (await db.execute(text("SELECT usuario_id FROM conductores WHERE id_conductor=:id"), {"id": id_conductor})).scalar()
    if uid:
        await db.execute(text("UPDATE conductores SET activo = :st WHERE usuario_id = :uid"), {"uid": uid, "st": datos.activo})
        await db.commit()
        return {"mensaje": "Estado actualizado"}
    return {"error": "Conductor no encontrado"}


@app.websocket("/ws/sos")
async def ws_sos(websocket: WebSocket):
    await websocket.accept()
    _sos_connections.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _sos_connections.discard(websocket)
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


@app.post('/usuarios/clear_password_flag')
async def clear_password_flag(d: dict, db: AsyncSession = Depends(get_db)):
    try:
        uid = d.get('usuario_id')
        if not uid:
            return dict(error='usuario_id requerido')
        await db.execute(text('UPDATE usuarios SET must_change_password = false WHERE id = :uid'), dict(uid=uid))
        await db.commit()
        return dict(mensaje='OK')
    except Exception as e:
        await db.rollback()
        return dict(error=str(e))


