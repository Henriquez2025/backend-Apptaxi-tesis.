import os
import urllib.parse
import random
import json
import base64
from datetime import date, datetime, timedelta
from typing import Optional, List
from passlib.context import CryptContext
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(".") / ".env"
load_dotenv()

import uvicorn
import httpx
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Form,
    File,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, HTMLResponse, Response, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    text,
    Date,
    DateTime,
    Boolean,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from sqladmin import Admin, ModelView
from geoalchemy2 import Geometry

# CONFIGURACIÓN DE BASE DE DATOS Y SUPABASE
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE")
DATABASE_URL = os.getenv("DATABASE_URL")

# Validación simple de seguridad
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE or not DATABASE_URL:
    raise RuntimeError(
        "Faltan variables de entorno (Revisa el .env en local o el Dashboard en Render)"
    )

# Variables para compatibilidad
PROJECT_ID = "manual"
SUPABASE_USER = "manual"
DB_PASSWORD = "manual"

# CONEXIÓN ASÍNCRONA CON LA BASE DE DATOS
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
        },
    )
except Exception as e:
    print(f"ERROR CRÍTICO: No se pudo conectar con la base de datos: {e}")

# crea las sesiones de trabajo para cada petición de las Apps
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

# SEGURIDAD
PALABRAS_CLAVE = [
    "SOL",
    "LUNA",
    "MAR",
    "RIO",
    "LUZ",
    "PAZ",
    "ORO",
    "AZUL",
    "ROJO",
    "TIGRE",
    "LEON",
    "AGUA",
    "FUEGO",
    "AIRE",
    "JAZZ",
    "ROCK",
    "MENTA",
    "COCO",
    "LIMA",
]

# SEGURIDAD
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def obtener_hash_password(password: str) -> str:
    return pwd_context.hash(
        password
    )  # Cifra la contraseña antes de guardarla en Render


def verificar_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(
        plain_password, hashed_password
    )  # Compara una contraseña escrita con la cifrada en la base de datos


# FUNCIONES ADMINISTRATIVAS DE SUPABASE AUTH
# Estas funciones permiten gestionar usuarios (Crear, Actualizar, Eliminar)
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv(
    "SUPABASE_SERVICE_KEY"
)
DEFAULT_USER_PASSWORD = os.getenv("DEFAULT_USER_PASSWORD")
BASE_PUBLIC_URL = (
    os.getenv("PUBLIC_BASE_URL") or "https://backend-apptaxi-tesis.onrender.com"
).rstrip("/")


def _build_public_url(path: str):
    return f"{BASE_PUBLIC_URL}{path}"


def _require_default_password() -> str:
    if not DEFAULT_USER_PASSWORD:
        raise HTTPException(
            status_code=500, detail="DEFAULT_USER_PASSWORD no configurado"
        )
    return DEFAULT_USER_PASSWORD


async def _supabase_admin_create_user(email: str, password: str, role: str):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return {
            "error": "Supabase Auth no configurado (SUPABASE_URL/SUPABASE_SERVICE_ROLE)"
        }
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
            msg = (
                body.get("msg") or body.get("message") or body.get("error") or str(body)
            )
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


async def _supabase_admin_update_user(user_id: str, payload: dict):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return {
            "error": "Supabase Auth no configurado (SUPABASE_URL/SUPABASE_SERVICE_ROLE)"
        }
    url = f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(url, headers=headers, json=payload)
    if resp.status_code not in (200, 201):
        try:
            body = resp.json()
            msg = (
                body.get("msg") or body.get("message") or body.get("error") or str(body)
            )
        except Exception:
            msg = resp.text or f"HTTP {resp.status_code}"
        return {"error": msg}
    return resp.json()


def _is_supabase_user_exists_error(msg: str) -> bool:
    """Detecta si un error de Supabase es porque el usuario ya está registrado."""
    if not msg:
        return False
    m = msg.lower()
    return any(x in m for x in ["already", "exists", "registered", "duplicate"])


async def _supabase_admin_get_user_by_email(email: str) -> Optional[dict]:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return None
    url = f"{SUPABASE_URL}/auth/v1/admin/users"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
    }
    params = {"email": email}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict) and data.get("id"):
        return data
    return None


# GESTIÓN DE EMERGENCIAS (SOS) EN TIEMPO REAL
_sos_connections = set()


async def _broadcast_sos(payload: dict):
    if not _sos_connections:
        return
    for ws in list(_sos_connections):
        try:
            await ws.send_json(payload)
        except Exception:
            _sos_connections.discard(ws)


# UTILIDADES PARA PROCESAMIENTO DE IMÁGENES
# Convierte un archivo subido a formato Base64 (Texto)
async def _file_to_b64(file: Optional[UploadFile]) -> Optional[str]:
    if not file:
        return None
    data = await file.read()
    return base64.b64encode(data).decode("ascii")


# Convierte un texto Base64 de vuelta a bytes para guardarlo
def _b64_to_bytes(value: Optional[str]) -> Optional[bytes]:
    if not value:
        return None
    if "," in value:
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value)
    except Exception:
        return None


# Detecta automáticamente si la imagen es JPEG o PNG
def _guess_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return "application/octet-stream"


# CONFIGURACIÓN DE ALMACENAMIENTO (SUPABASE STORAGE)
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET") or "taxi-media"
_STORAGE_READY = False


async def _ensure_storage_bucket():
    """
    Asegura que el bucket 'taxi-media' exista en Supabase.
    Si no existe (Error 404), lo crea automáticamente como un bucket público.
    """
    global _STORAGE_READY
    if _STORAGE_READY:
        return
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        # Verificamos si el bucket ya existe
        resp = await client.get(
            f"{SUPABASE_URL}/storage/v1/bucket/{SUPABASE_STORAGE_BUCKET}",
            headers=headers,
        )
        # Si no existe, procedemos a crearlo
        if resp.status_code == 404:
            payload = {
                "id": SUPABASE_STORAGE_BUCKET,
                "name": SUPABASE_STORAGE_BUCKET,
                "public": True,  # Las imágenes podrán ser vistas mediante URL pública
            }
            await client.post(
                f"{SUPABASE_URL}/storage/v1/bucket",
                headers=headers,
                json=payload,
            )
        elif resp.status_code not in (200, 201):
            return
    _STORAGE_READY = True


async def _storage_upload(path: str, file: Optional[UploadFile]) -> bool:
    """
    Sube un archivo físico al Storage de Supabase.
    path: La ruta interna (ej. 'vehiculos/1/foto_auto')
    file: El archivo binario proveniente del formulario.
    """
    if not file:
        return False
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return False
    await _ensure_storage_bucket()
    data = await file.read()
    if not data:
        return False
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
        "Content-Type": file.content_type or "application/octet-stream",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        # PUT con upsert=true es para sobrescribir el archivo si ya existe
        resp = await client.put(
            f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{path}",
            headers=headers,
            params={"upsert": "true"},
            content=data,
        )
    return resp.status_code in (200, 201)


async def _storage_download(path: str) -> Optional[bytes]:
    """
    Descarga los bytes de una imagen desde el Storage para mostrarla en la App.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return None
    await _ensure_storage_bucket()
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE}",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{path}",
            headers=headers,
        )
    if resp.status_code != 200:
        return None
    return resp.content


async def _get_media_url(
    db: AsyncSession, table: str, column: str, key_col: str, key_val: int
) -> Optional[str]:
    """
    Busca en la base de datos si existe una URL externa directa para el archivo,
    en caso de que no se use el almacenamiento local de Supabase.
    """
    try:
        q = text(f"SELECT {column} as url FROM {table} WHERE {key_col} = :id")
        row = (await db.execute(q, {"id": key_val})).fetchone()
        if row and row.url:
            return row.url
    except Exception:
        return None
    return None


# MODELOS ORM (TABLAS DE BASE DE DATOS)
class Usuario(Base):
    """
    Tabla maestra de credenciales. Almacena el acceso principal
    y vincula con los perfiles específicos mediante relaciones uno-a-uno.
    """

    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    password_hash = Column(String)
    role = Column(String)
    must_change_password = Column(
        Boolean, default=False
    )  # Para usuarios creados por Admin
    supabase_uid = Column(String, nullable=True)  # ID único de la nube de Supabase

    # Relaciones con las demás tablas de perfiles
    perfil_cliente = relationship("Cliente", back_populates="usuario", uselist=False)
    perfil_conductor = relationship(
        "Conductor", back_populates="usuario", uselist=False
    )
    perfil_admin = relationship(
        "Administrador", back_populates="usuario", uselist=False
    )
    perfil_propietario = relationship(
        "Propietario", back_populates="usuario", uselist=False
    )


# Información personal de los usuarios que solicitan taxis
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


# Datos técnicos de los vehículos registrados en la flota
class Vehiculo(Base):
    __tablename__ = "vehiculos"
    id = Column(Integer, primary_key=True)
    marca = Column(String)
    modelo = Column(String)
    placa = Column(String, unique=True)
    color = Column(String, nullable=True)
    anio = Column(String, nullable=True)
    foto_vehiculo = Column(String, nullable=True)


# Perfil para dueños de vehículos
class Propietario(Base):
    __tablename__ = "propietarios"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    nom_apell = Column(String)
    telefono = Column(String)
    cedula = Column(String)
    fecha_nacimiento = Column(Date, nullable=True)
    usuario = relationship("Usuario", back_populates="perfil_propietario")


# Perfil operativo para los choferes
class Conductor(Base):
    __tablename__ = "conductores"
    id_conductor = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"))
    nom_apell = Column(String)
    telefono = Column(String)
    fecha_nacimiento = Column(Date)
    # Punto geográfico para el mapa de Flutter
    ubicacion = Column(Geometry("POINT", srid=4326), nullable=True)
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


# Registro de transacciones de servicio entre Clientes y Conductores
class Viaje(Base):
    __tablename__ = "viajes"
    id = Column(Integer, primary_key=True)
    cliente_id = Column(Integer, ForeignKey("usuarios.id"))
    conductor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    origen = Column(String)
    destino = Column(String)
    estado = Column(String, default="pendiente")
    tarifa = Column(Float)
    origen_lat = Column(Float, nullable=True)
    origen_lng = Column(Float, nullable=True)
    destino_lat = Column(Float, nullable=True)
    destino_lng = Column(Float, nullable=True)
    origen_geom = Column(Geometry("POINT", srid=4326), nullable=True)
    destino_geom = Column(Geometry("POINT", srid=4326), nullable=True)
    clave_seguridad = Column(String, nullable=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    cliente_usuario = relationship("Usuario", foreign_keys=[cliente_id])
    conductor_usuario = relationship("Usuario", foreign_keys=[conductor_id])


# DTOs (DATA TRANSFER OBJECTS) - ESQUEMAS DE VALIDACIÓN PYDANTIC
# Estos modelos definen la estructura exacta de los datos que el Backend espera recibir.
# Pydantic se encarga de validar que los tipos de datos (str, int, float) sean correctos
# antes de procesarlos en la lógica de negocio.


class LoginRequest(BaseModel):
    """Esquema para la autenticación de usuarios."""

    email: str
    password: str


class AuthSyncRequest(BaseModel):
    """
    Sincronización entre Supabase Auth y la Base de Datos local.
    Se usa cuando un usuario se registra o loguea por primera vez.
    """

    email: str
    supabase_uid: str
    access_token: Optional[str] = None
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    fecha_nacimiento: Optional[str] = None
    pais: Optional[str] = None
    ciudad: Optional[str] = None
    tipo_documento: Optional[str] = None
    numero_documento: Optional[str] = None


class ViajeRequest(BaseModel):
    """
    Datos necesarios para solicitar un nuevo viaje.
    """

    usuario_id: int
    origen: str
    destino: str
    tarifa: float
    origen_lat: Optional[float] = None
    origen_lng: Optional[float] = None
    destino_lat: Optional[float] = None
    destino_lng: Optional[float] = None


class AceptarViajeRequest(BaseModel):
    """Datos enviados por el conductor al aceptar una carrera."""

    viaje_id: int
    conductor_id: int


class UsuarioRegistroRequest(BaseModel):
    """Registro estándar de nuevos clientes."""

    nombre: str
    email: str
    password: str
    role: str = "cliente"
    telefono: Optional[str] = None
    fecha_nacimiento: Optional[str] = None
    pais: Optional[str] = None
    ciudad: Optional[str] = None
    tipo_documento: Optional[str] = None
    numero_documento: Optional[str] = None


class ConductorExtra(BaseModel):
    nombre: str
    apellido: str
    email: str
    cedula: str
    telefono: str
    fecha_nacimiento: str


class RegistroFlotaCompletoRequest(BaseModel):
    owner_email: str
    owner_cedula: str
    owner_nombre: str
    owner_apellido: str
    owner_telefono: str
    owner_fecha_nac: str
    vehiculo_marca: str
    vehiculo_modelo: str
    vehiculo_placa: str
    vehiculo_color: str
    conductores_extra: Optional[str] = None

    @classmethod
    def as_form(
        cls,
        owner_email: str = Form(...),
        owner_cedula: str = Form(...),
        owner_nombre: str = Form(...),
        owner_apellido: str = Form(...),
        owner_telefono: str = Form(...),
        owner_fecha_nac: str = Form(...),
        vehiculo_marca: str = Form(...),
        vehiculo_modelo: str = Form(...),
        vehiculo_placa: str = Form(...),
        vehiculo_color: str = Form(...),
        conductores_extra: str = Form(None),
    ):
        return cls(
            owner_email=owner_email,
            owner_cedula=owner_cedula,
            owner_nombre=owner_nombre,
            owner_apellido=owner_apellido,
            owner_telefono=owner_telefono,
            owner_fecha_nac=owner_fecha_nac,
            vehiculo_marca=vehiculo_marca,
            vehiculo_modelo=vehiculo_modelo,
            vehiculo_placa=vehiculo_placa,
            vehiculo_color=vehiculo_color,
            conductores_extra=conductores_extra,
        )


class RegistroConductorRequest(BaseModel):
    """
    Registro administrativo de conductores.
    """

    nombre: str
    email: str
    password: str
    telefono: str
    fecha_nacimiento: str
    role: str = "conductor"
    vehiculo_marca: str
    vehiculo_modelo: str
    vehiculo_placa: str
    vehiculo_color: Optional[str] = None
    vehiculo_anio: Optional[str] = None
    cedula: Optional[str] = None
    horario_trabajo: Optional[str] = None


class ContactoRequest(BaseModel):
    """Agregar un contacto de emergencia."""

    usuario_id: int
    nombre_contacto: str
    numero_whatsapp: str


class ContactoEditRequest(BaseModel):
    """Edición de contacto de emergencia."""

    nombre_contacto: str
    numero_whatsapp: str


class AlertaRequest(BaseModel):
    """Alerta de pánico genérica - SOS"""

    usuario_id: int
    ubicacion: str
    mensaje: str


class SosConductorRequest(BaseModel):
    """
    Alerta de pánico específica para conductores.
    """

    usuario_id: int
    lat: float
    lng: float
    mensaje: Optional[str] = None


class SosConductorCloseRequest(BaseModel):
    """Para marcar una alerta SOS como atendida/cerrada."""

    usuario_id: int


class UbicacionConductorRequest(BaseModel):
    """Actualización periódica del GPS del conductor."""

    usuario_id: int
    latitud: float
    longitud: float


class EstadoConductorRequest(BaseModel):
    """Switch de Disponible / ocupado."""

    usuario_id: int
    activo: bool


class EstadoViajeRequest(BaseModel):
    """Cambio de flujo del viaje."""

    viaje_id: int
    nuevo_estado: str


class CancelarViajeRequest(BaseModel):
    """Cancelación de viaje con motivo opcional."""

    viaje_id: int
    motivo: str = "Cancelado por usuario/conductor"


class IniciarViajeRequest(BaseModel):
    """Validación de la clave de seguridad para iniciar la carrera."""

    viaje_id: int
    clave_ingresada: str


class EstadoConductorPut(BaseModel):
    """DTO simple para actualizaciones de estado - vía PUT."""

    activo: bool


class AdminConductorUpdateRequest(BaseModel):
    """
    Edición de perfil de conductor por parte de un Administrador.
    """

    usuario_id: int
    email: Optional[str] = None
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    fecha_nacimiento: Optional[str] = None
    cedula: Optional[str] = None
    activo: Optional[bool] = None
    vehiculo_placa: Optional[str] = None
    password: Optional[str] = None


# CONFIGURACIÓN DEL SERVIDOR Y PANEL ADMINISTRATIVO
app = FastAPI(title="Taxi App API", description="API REST")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "https://backend-apptaxi-tesis.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración del Panel de Administración
if engine:
    admin = Admin(app, engine, title="Taxi Admin")

    class UsuarioAdmin(ModelView, model=Usuario):
        column_list = [Usuario.id, Usuario.email, Usuario.role]
        name = "Usuario"
        name_plural = "Usuarios"

    class ClienteAdmin(ModelView, model=Cliente):
        column_list = [Cliente.id_cliente, Cliente.nom_apell, Cliente.ciudad]
        name = "Cliente"
        name_plural = "Clientes"

    class ConductorAdmin(ModelView, model=Conductor):
        column_list = [Conductor.id_conductor, Conductor.nom_apell, Conductor.activo]
        name = "Conductor"
        name_plural = "Conductores"

    class PropietarioAdmin(ModelView, model=Propietario):
        column_list = [Propietario.id, Propietario.nom_apell, Propietario.cedula]
        name = "Propietario"
        name_plural = "Propietarios"

    class VehiculoAdmin(ModelView, model=Vehiculo):
        column_list = [Vehiculo.id, Vehiculo.placa, Vehiculo.modelo]
        name = "Vehículo"
        name_plural = "Vehículos"

    class ViajeAdmin(ModelView, model=Viaje):
        column_list = [Viaje.id, Viaje.estado, Viaje.tarifa, Viaje.origen]
        name = "Viaje"
        name_plural = "Viajes"

    class EmergenciaAdmin(ModelView, model=Emergencia):
        column_list = [Emergencia.id, Emergencia.nombre_contacto]
        name = "Contacto SOS"
        name_plural = "Contactos SOS"

    class AlertaAdmin(ModelView, model=Alerta):
        column_list = [Alerta.id, Alerta.ubicacion, Alerta.fecha]
        name = "Alerta Pánico"
        name_plural = "Alertas Pánico"

    class AdministradorAdmin(ModelView, model=Administrador):
        column_list = [Administrador.id, Administrador.nom_apell]
        name = "Administrador"
        name_plural = "Administradores"

    # Registrar las vistas en el panel
    admin.add_view(UsuarioAdmin)
    admin.add_view(ClienteAdmin)
    admin.add_view(ConductorAdmin)
    admin.add_view(PropietarioAdmin)
    admin.add_view(VehiculoAdmin)
    admin.add_view(ViajeAdmin)
    admin.add_view(EmergenciaAdmin)
    admin.add_view(AlertaAdmin)
    admin.add_view(AdministradorAdmin)


# Dependencia para obtener la sesión de base de datos en cada petición
async def get_db():
    if not engine:
        raise HTTPException(
            status_code=500,
            detail="Error Crítico: El motor de base de datos no se inició.",
        )
    async with async_session() as session:
        yield session


# ENDPOINTS API - RUTA RAÍZ
@app.get("/")
def leer_raiz():
    """
    Endpoint para verificar rápidamente si el servidor está respondiendo.
    """
    return {"mensaje": "API Taxi Running (v29.0 - Con Registro Flota)."}

# ---------------------------------------------------------------------------
# REPORTES (ADMIN)
# ---------------------------------------------------------------------------

@app.get("/reportes")
async def reportes_general(db: AsyncSession = Depends(get_db)):
    try:
        viajes_q = text(
            """
            SELECT v.id, v.origen, v.destino, v.estado, v.tarifa, v.fecha_creacion,
                   c.nom_apell as conductor_nombre,
                   cli.nom_apell as cliente_nombre
            FROM viajes v
            LEFT JOIN conductores c ON v.conductor_id = c.usuario_id
            LEFT JOIN clientes cli ON v.cliente_id = cli.usuario_id
            ORDER BY v.fecha_creacion DESC
            LIMIT 200
        """
        )
        alertas_q = text(
            """
            SELECT a.id, a.ubicacion, a.mensaje_extra, a.fecha, u.role, u.email,
                   COALESCE(c.nom_apell, cli.nom_apell, 'Usuario') as nombre
            FROM alertas a
            JOIN usuarios u ON a.usuario_id = u.id
            LEFT JOIN conductores c ON a.usuario_id = c.usuario_id
            LEFT JOIN clientes cli ON a.usuario_id = cli.usuario_id
            ORDER BY a.fecha DESC
            LIMIT 200
        """
        )
        viajes_res = await db.execute(viajes_q)
        alertas_res = await db.execute(alertas_q)
        viajes = [
            {
                "id": r.id,
                "origen": r.origen,
                "destino": r.destino,
                "estado": r.estado,
                "tarifa": r.tarifa,
                "fecha": r.fecha_creacion.isoformat() if r.fecha_creacion else None,
                "conductor": r.conductor_nombre or "Conductor",
                "pasajero": r.cliente_nombre or "Cliente",
            }
            for r in viajes_res.fetchall()
        ]
        alertas = [
            {
                "id": r.id,
                "ubicacion": r.ubicacion,
                "mensaje": r.mensaje_extra,
                "fecha": r.fecha.isoformat() if r.fecha else None,
                "rol": r.role,
                "nombre": r.nombre or "Usuario",
                "email": r.email,
            }
            for r in alertas_res.fetchall()
        ]
        return {"viajes": viajes, "alertas": alertas}
    except Exception as e:
        return {"viajes": [], "alertas": [], "error": str(e)}


# REPORTES (ADMINISTRADOR)
@app.get("/reportes/viajes/conductores")
async def reportes_viajes_conductores(db: AsyncSession = Depends(get_db)):
    """
    Obtiene el historial de viajes que fueron asignados a un conductor.
    """
    try:
        query = text(
            """
            SELECT v.id, v.origen, v.destino, v.estado, v.tarifa, v.fecha_creacion,
                   c.nom_apell as conductor_nombre,
                   cli.nom_apell as cliente_nombre
            FROM viajes v
            LEFT JOIN conductores c ON v.conductor_id = c.usuario_id
            LEFT JOIN clientes cli ON v.cliente_id = cli.usuario_id
            WHERE v.conductor_id IS NOT NULL
            ORDER BY v.fecha_creacion DESC
        """
        )
        res = await db.execute(query)
        return [
            {
                "id": r.id,
                "origen": r.origen,
                "destino": r.destino,
                "estado": r.estado,
                "tarifa": r.tarifa,
                "fecha": r.fecha_creacion.isoformat() if r.fecha_creacion else None,
                "conductor": r.conductor_nombre or "Conductor",
                "pasajero": r.cliente_nombre or "Cliente",
            }
            for r in res.fetchall()
        ]
    except Exception as e:
        return {"error": str(e)}


@app.get("/reportes/viajes/clientes")
async def reportes_viajes_clientes(db: AsyncSession = Depends(get_db)):
    try:
        query = text(
            """
            SELECT v.id, v.origen, v.destino, v.estado, v.tarifa, v.fecha_creacion,
                   c.nom_apell as conductor_nombre,
                   cli.nom_apell as cliente_nombre
            FROM viajes v
            LEFT JOIN conductores c ON v.conductor_id = c.usuario_id
            LEFT JOIN clientes cli ON v.cliente_id = cli.usuario_id
            ORDER BY v.fecha_creacion DESC
        """
        )
        res = await db.execute(query)
        return [
            {
                "id": r.id,
                "origen": r.origen,
                "destino": r.destino,
                "estado": r.estado,
                "tarifa": r.tarifa,
                "fecha": r.fecha_creacion.isoformat() if r.fecha_creacion else None,
                "conductor": r.conductor_nombre or "Conductor",
                "pasajero": r.cliente_nombre or "Cliente",
            }
            for r in res.fetchall()
        ]
    except Exception as e:
        return {"error": str(e)}


@app.get("/reportes/sos/conductores")
async def reportes_sos_conductores(db: AsyncSession = Depends(get_db)):
    try:
        query = text(
            """
            SELECT a.id, a.ubicacion, a.mensaje_extra, a.fecha,
                   c.nom_apell as nombre, u.email
            FROM alertas a
            JOIN usuarios u ON a.usuario_id = u.id
            LEFT JOIN conductores c ON a.usuario_id = c.usuario_id
            WHERE u.role = 'conductor'
            ORDER BY a.fecha DESC
        """
        )
        res = await db.execute(query)
        return [
            {
                "id": r.id,
                "ubicacion": r.ubicacion,
                "mensaje": r.mensaje_extra,
                "fecha": r.fecha.isoformat() if r.fecha else None,
                "nombre": r.nombre or "Conductor",
                "email": r.email,
            }
            for r in res.fetchall()
        ]
    except Exception as e:
        return {"error": str(e)}


@app.get("/reportes/sos/clientes")
async def reportes_sos_clientes(db: AsyncSession = Depends(get_db)):
    try:
        query = text(
            """
            SELECT a.id, a.ubicacion, a.mensaje_extra, a.fecha,
                   c.nom_apell as nombre, u.email
            FROM alertas a
            JOIN usuarios u ON a.usuario_id = u.id
            LEFT JOIN clientes c ON a.usuario_id = c.usuario_id
            WHERE u.role = 'cliente'
            ORDER BY a.fecha DESC
        """
        )
        res = await db.execute(query)
        return [
            {
                "id": r.id,
                "ubicacion": r.ubicacion,
                "mensaje": r.mensaje_extra,
                "fecha": r.fecha.isoformat() if r.fecha else None,
                "nombre": r.nombre or "Cliente",
                "email": r.email,
            }
            for r in res.fetchall()
        ]
    except Exception as e:
        return {"error": str(e)}


# ENDPOINT: INICIO DE SESIÓN (LOGIN)
@app.post("/login")
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Verifica credenciales y determina los permisos del usuario.
    """
    try:
        # Buscar usuario por email
        res = await db.execute(
            text(
                "SELECT id, email, password_hash, role, must_change_password FROM usuarios WHERE email = :email"
            ),
            {"email": datos.email},
        )
        user = res.fetchone()

        # Validaciones básicas
        if not user:
            return {"error": "Usuario no encontrado"}
        if not verificar_password(datos.password, user.password_hash):
            if user.password_hash == datos.password:
                # Migración suave: si la clave estaba en texto plano, se cifra y se guarda
                try:
                    nuevo_hash = obtener_hash_password(datos.password)
                    await db.execute(
                        text("UPDATE usuarios SET password_hash = :p WHERE id = :uid"),
                        {"p": nuevo_hash, "uid": user.id},
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
            else:
                return {"error": "Contraseña incorrecta"}

        # Obtener nombre real y determinar roles secundarios
        nombre_real = "Usuario"
        es_conductor_tambien = False
        try:
            if user.role == "cliente":
                res_cli = (
                    await db.execute(
                        text("SELECT nom_apell FROM clientes WHERE usuario_id = :uid"),
                        {"uid": user.id},
                    )
                ).fetchone()
                if res_cli:
                    nombre_real = res_cli.nom_apell

            elif user.role == "conductor":
                res_cond = (
                    await db.execute(
                        text(
                            "SELECT nom_apell FROM conductores WHERE usuario_id = :uid"
                        ),
                        {"uid": user.id},
                    )
                ).fetchone()
                if res_cond:
                    nombre_real = res_cond.nom_apell
                es_conductor_tambien = True

            elif user.role == "propietario":
                res_prop = (
                    await db.execute(
                        text(
                            "SELECT nom_apell FROM propietarios WHERE usuario_id = :uid"
                        ),
                        {"uid": user.id},
                    )
                ).fetchone()
                if res_prop:
                    nombre_real = res_prop.nom_apell

                # VERIFICAMOS SI EL DUEÑO TAMBIÉN ES CONDUCTOR
                check_cond = (
                    await db.execute(
                        text("SELECT 1 FROM conductores WHERE usuario_id = :u"),
                        {"u": user.id},
                    )
                ).scalar()
                if check_cond:
                    es_conductor_tambien = True

        except Exception:
            pass
        # Respuesta final al Frontend
        return {
            "mensaje": "Login OK",
            "usuario": {
                "id": user.id,
                "nombre": nombre_real,
                "role": user.role,
                "es_conductor": es_conductor_tambien,
                "must_change_password": bool(user.must_change_password),
            },
        }
    except Exception as e:
        return {"error": f"Error interno: {str(e)}"}


# ENDPOINT: SINCRONIZACIÓN DE AUTENTICACIÓN
@app.post("/auth/sync")
async def auth_sync(datos: AuthSyncRequest, db: AsyncSession = Depends(get_db)):
    """
    Valida el token recibido desde Supabase (Google/etc) y
    sincroniza el usuario con la base de datos local.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        return {
            "error": "Supabase Auth no configurado (SUPABASE_URL/SUPABASE_SERVICE_ROLE)"
        }

    # Valida el Token contra la API de Supabase
    auth_user = None
    admin_error = None
    token_error = None

    try:
        # Intento 1: Consultar como Admin
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
                admin_error = (
                    body.get("msg")
                    or body.get("message")
                    or body.get("error")
                    or str(body)
                )
            except Exception:
                admin_error = resp.text or f"HTTP {resp.status_code}"
    except Exception as e:
        admin_error = f"Error validando Supabase (admin): {str(e)}"

    # Intento 2: Consultar como Usuario
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
                    token_error = (
                        body.get("msg")
                        or body.get("message")
                        or body.get("error")
                        or str(body)
                    )
                except Exception:
                    token_error = resp.text or f"HTTP {resp.status_code}"
        except Exception as e:
            token_error = f"Error validando Supabase (token): {str(e)}"

    if not auth_user:
        return {
            "error": admin_error
            or token_error
            or "No se pudo validar usuario en Supabase"
        }
    # Validaciones de Seguridad
    email_auth = (auth_user.get("email") or "").lower()
    if email_auth and email_auth != datos.email.lower():
        return {"error": "Email no coincide con el uid de Supabase"}

    auth_id = auth_user.get("id")
    if auth_id and auth_id != datos.supabase_uid:
        return {"error": "UID no coincide con Supabase"}
    try:
        f_nac = None
        if datos.fecha_nacimiento:
            try:
                f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date()
            except Exception:
                f_nac = None
        # Busca usuario en Base de Datos Local
        res = await db.execute(
            text(
                "SELECT id, email, role, must_change_password FROM usuarios WHERE email = :email"
            ),
            {"email": datos.email},
        )
        user = res.fetchone()

        if not user:
            return {"error": "Usuario no encontrado en backend"}
        # Sincroniza datos del perfil CLIENTE si aplica
        if user.role == "cliente":
            try:
                exists_cli = (
                    await db.execute(
                        text("SELECT 1 FROM clientes WHERE usuario_id = :u"),
                        {"u": user.id},
                    )
                ).scalar()
                if not exists_cli:
                    meta = auth_user.get("user_metadata") or {}
                    nombre_meta = (
                        datos.nombre
                        or meta.get("nombre")
                        or meta.get("name")
                        or "Cliente"
                    )
                    await db.execute(
                        text(
                            "INSERT INTO clientes (usuario_id, nom_apell, pais, ciudad, telefono, fecha_nacimiento, tipo_documento, numero_documento) "
                            "VALUES (:u, :n, :p, :c, :t, :f, :td, :nd)"
                        ),
                        {
                            "u": user.id,
                            "n": nombre_meta,
                            "p": datos.pais,
                            "c": datos.ciudad,
                            "t": datos.telefono,
                            "f": f_nac,
                            "td": datos.tipo_documento,
                            "nd": datos.numero_documento,
                        },
                    )
                    await db.commit()
                else:
                    if any(
                        [
                            datos.nombre,
                            datos.pais,
                            datos.ciudad,
                            datos.telefono,
                            datos.fecha_nacimiento,
                            datos.tipo_documento,
                            datos.numero_documento,
                        ]
                    ):
                        await db.execute(
                            text(
                                "UPDATE clientes SET "
                                "nom_apell = COALESCE(NULLIF(:n, ''), nom_apell), "
                                "pais = COALESCE(NULLIF(:p, ''), pais), "
                                "ciudad = COALESCE(NULLIF(:c, ''), ciudad), "
                                "telefono = COALESCE(NULLIF(:t, ''), telefono), "
                                "fecha_nacimiento = COALESCE(:f, fecha_nacimiento), "
                                "tipo_documento = COALESCE(NULLIF(:td, ''), tipo_documento), "
                                "numero_documento = COALESCE(NULLIF(:nd, ''), numero_documento) "
                                "WHERE usuario_id = :u"
                            ),
                            {
                                "u": user.id,
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
            except Exception:
                await db.rollback()

        # Obtiene nombre real y roles
        nombre_real = "Usuario"
        es_conductor_tambien = False
        try:
            # ES CLIENTE
            if user.role == "cliente":
                res_cli = (
                    await db.execute(
                        text("SELECT nom_apell FROM clientes WHERE usuario_id = :uid"),
                        {"uid": user.id},
                    )
                ).fetchone()
                if res_cli:
                    nombre_real = res_cli.nom_apell
            # ES CONDUCTOR
            elif user.role == "conductor":
                res_cond = (
                    await db.execute(
                        text(
                            "SELECT nom_apell FROM conductores WHERE usuario_id = :uid"
                        ),
                        {"uid": user.id},
                    )
                ).fetchone()
                if res_cond:
                    nombre_real = res_cond.nom_apell
                es_conductor_tambien = True
            # ES PROPIETARIO
            elif user.role == "propietario":
                res_prop = (
                    await db.execute(
                        text(
                            "SELECT nom_apell FROM propietarios WHERE usuario_id = :uid"
                        ),
                        {"uid": user.id},
                    )
                ).fetchone()
                # ES PROPIETARIO Y CONDUCTOR
                if res_prop:
                    nombre_real = res_prop.nom_apell
                check_cond = (
                    await db.execute(
                        text("SELECT 1 FROM conductores WHERE usuario_id = :u"),
                        {"u": user.id},
                    )
                ).scalar()

                if check_cond:
                    es_conductor_tambien = True
            # ES ADMIN
            elif user.role == "admin":
                res_admin = (
                    await db.execute(
                        text(
                            "SELECT nom_apell FROM administradores WHERE usuario_id = :uid"
                        ),
                        {"uid": user.id},
                    )
                ).fetchone()
                if res_admin:
                    nombre_real = res_admin.nom_apell

        except Exception:
            pass

        lista_roles = [user.role]
        if es_conductor_tambien and user.role != "conductor":
            lista_roles.append("conductor")

        # Respuesta Final (JSON)
        return {
            "usuario": {
                "id": user.id,
                "nombre": nombre_real,
                "role": user.role,
                "es_conductor": es_conductor_tambien,
                "roles_disponibles": lista_roles,
                "must_change_password": bool(user.must_change_password),
            }
        }
    except Exception as e:
        return {"error": f"Error interno: {str(e)}"}


# ENDPOINT: REGISTRO DE USUARIOS (CLIENTES / PASAJEROS)
@app.post("/registrar_usuario")
async def registrar_usuario(
    datos: UsuarioRegistroRequest, db: AsyncSession = Depends(get_db)
):
    try:
        existing_id = (
            await db.execute(
                text("SELECT id FROM usuarios WHERE email = :e"),
                {"e": datos.email},
            )
        ).scalar()

        f_nac = None
        if datos.fecha_nacimiento:
            try:
                f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date()
            except Exception:
                f_nac = None

        if existing_id:
            try:
                exists_cli = (
                    await db.execute(
                        text("SELECT 1 FROM clientes WHERE usuario_id = :u"),
                        {"u": existing_id},
                    )
                ).scalar()

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
                return {"error": f"No se pudo actualizar perfil: {str(e)}"}

        password_segura = obtener_hash_password(datos.password)
        # Insertar en tabla Usuarios y obtener ID
        uid = (
            await db.execute(
                text(
                    "INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"
                ),
                {"e": datos.email, "p": password_segura, "r": "cliente"},
            )
        ).scalar()

        # Insertar en tabla Clientes
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
            await db.commit()
            return {"mensaje": "Usuario registrado exitosamente", "id": uid}

        except Exception as e:
            await db.rollback()
            return {"error": f"Error creando perfil de cliente: {str(e)}"}
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}


# ENDPOINT: REGISTRO DE CLIENTE CON FOTOS
@app.post("/registrar_usuario_fotos")
async def registrar_usuario_fotos(
    nombre: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
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

        existing_id = (
            await db.execute(
                text("SELECT id FROM usuarios WHERE email = :e"),
                {"e": email},
            )
        ).scalar()

        if not existing_id:
            password_segura = obtener_hash_password(password)
            existing_id = (
                await db.execute(
                    text(
                        "INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"
                    ),
                    {"e": email, "p": password_segura, "r": "cliente"},
                )
            ).scalar()

        exists_cli = (
            await db.execute(
                text("SELECT 1 FROM clientes WHERE usuario_id = :u"),
                {"u": existing_id},
            )
        ).scalar()

        if not exists_cli:
            await db.execute(
                text(
                    "INSERT INTO clientes (usuario_id, nom_apell, pais, ciudad, telefono, fecha_nacimiento, tipo_documento, numero_documento) "
                    "VALUES (:u, :n, :p, :c, :t, :f, :td, :nd)"
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
                    "n": nombre,
                    "p": pais,
                    "c": ciudad,
                    "t": telefono,
                    "f": f_nac,
                    "td": tipo_documento,
                    "nd": numero_documento,
                },
            )

        await db.commit()

        # SubE fotos al storage
        ok_frente = await _storage_upload(
            f"clientes/{existing_id}/foto_cedula_frente",
            foto_cedulafrente,
        )
        ok_posterior = await _storage_upload(
            f"clientes/{existing_id}/foto_cedula_posterior",
            foto_cedulaposterior,
        )
        ok_selfie = await _storage_upload(
            f"clientes/{existing_id}/foto_selfie",
            foto_selfieci,
        )
        ok_pasaporte = await _storage_upload(
            f"clientes/{existing_id}/foto_pasaporte",
            foto_pasaporte,
        )

        updates = []
        params = {"uid": existing_id}
        if ok_frente:
            updates.append("foto_cedulafrente = :ff")
            updates.append("foto_cedulafrente_url = NULL")
            params["ff"] = "OK"

        if ok_posterior:
            updates.append("foto_cedulaposterior = :fa")
            updates.append("foto_cedulaposterior_url = NULL")
            params["fa"] = "OK"

        if ok_selfie:
            updates.append("foto_selfieci = :fs")
            updates.append("foto_selfieci_url = NULL")
            params["fs"] = "OK"

        if ok_pasaporte:
            updates.append("foto_pasaporte = :fp")
            updates.append("foto_pasaporte_url = NULL")
            params["fp"] = "OK"

        if updates:
            await db.execute(
                text(
                    "UPDATE clientes SET "
                    + ", ".join(updates)
                    + " WHERE usuario_id = :uid"
                ),
                params,
            )
            await db.commit()

        return {"mensaje": "Registrado", "id": existing_id}
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}


# ENDPOINT: REGISTRO ADMINISTRATIVO (CONDUCTORES Y PROPIETARIOS)
@app.post("/registrar_flota_completo")
async def registrar_vehiculo_completo(
    datos: RegistroFlotaCompletoRequest = Depends(RegistroFlotaCompletoRequest.as_form),
    cedula_front: UploadFile = File(None),
    cedula_back: UploadFile = File(None),
    foto_perfil: UploadFile = File(None),
    foto_vehiculo: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        if cedula_front:
            print(f"Archivo recibido: {cedula_front.filename}")
        owner_email = (datos.owner_email or "").strip().lower()
        if not owner_email:
            return JSONResponse(status_code=400, content={"error": "Email requerido"})

        owner_f_nac = None
        if datos.owner_fecha_nac:
            try:
                owner_f_nac = datetime.strptime(
                    datos.owner_fecha_nac, "%Y-%m-%d"
                ).date()
            except Exception:
                owner_f_nac = None

        # Crea o actualiza el Vehículo
        vehiculo_id = (
            await db.execute(
                text("SELECT id FROM vehiculos WHERE placa = :p"),
                {"p": datos.vehiculo_placa},
            )
        ).scalar()

        if not vehiculo_id:
            vehiculo_id = (
                await db.execute(
                    text(
                        """INSERT INTO vehiculos (marca, modelo, placa, color) 
                        VALUES (:m, :mo, :p, :c) RETURNING id"""
                    ),
                    {
                        "m": datos.vehiculo_marca,
                        "mo": datos.vehiculo_modelo,
                        "p": datos.vehiculo_placa,
                        "c": datos.vehiculo_color,
                    },
                )
            ).scalar()

        # Verifica/Crea Usuario para el Dueño
        user_row = (
            await db.execute(
                text("SELECT id, role FROM usuarios WHERE email = :e"),
                {"e": owner_email},
            )
        ).fetchone()

        supa_user = None
        if user_row:
            if (user_row.role or "").lower() != "propietario":
                return JSONResponse(
                    status_code=400, content={"error": "Email ya existe con otro rol"}
                )
            user_id = user_row.id
        else:
            # Crea en Supabase Auth y luego en tabla local
            supa_res = await _supabase_admin_create_user(
                owner_email, datos.owner_cedula, "propietario"
            )
            if isinstance(supa_res, dict) and supa_res.get("error"):
                err_msg = str(supa_res.get("error"))
                if _is_supabase_user_exists_error(err_msg):
                    supa_user = await _supabase_admin_get_user_by_email(owner_email)
                else:
                    return JSONResponse(
                        status_code=400, content={"error": supa_res["error"]}
                    )
            else:
                supa_user = supa_res

            user_id = (
                await db.execute(
                    text(
                        """INSERT INTO usuarios (email, password_hash, role, must_change_password) 
                        VALUES (:e, :p, 'propietario', true) RETURNING id"""
                    ),
                    {
                        "e": owner_email,
                        "p": obtener_hash_password(datos.owner_cedula),
                    },
                )
            ).scalar()

            try:
                if isinstance(supa_user, dict) and supa_user.get("id"):
                    await db.execute(
                        text("UPDATE usuarios SET supabase_uid = :suid WHERE id = :uid"),
                        {"suid": supa_user.get("id"), "uid": user_id},
                    )
            except Exception:
                pass

        # Crea Perfil de Propietario
        exists_prop = (
            await db.execute(
                text("SELECT 1 FROM propietarios WHERE usuario_id = :u"), {"u": user_id}
            )
        ).scalar()

        if not exists_prop:
            await db.execute(
                text(
                    """INSERT INTO propietarios (usuario_id, nom_apell, cedula, telefono, fecha_nacimiento) 
                        VALUES (:u, :n, :c, :t, :f)"""
                ),
                {
                    "u": user_id,
                    "n": f"{datos.owner_nombre} {datos.owner_apellido}",
                    "c": datos.owner_cedula,
                    "t": datos.owner_telefono,
                    "f": owner_f_nac,
                },
            )

        # Crea Conductor para el dueño si no existe
        exists_owner_cond = (
            await db.execute(
                text("SELECT 1 FROM conductores WHERE usuario_id = :u"),
                {"u": user_id},
            )
        ).scalar()
        if not exists_owner_cond:
            await db.execute(
                text(
                    """INSERT INTO conductores (usuario_id, nom_apell, telefono, fecha_nacimiento, cedula, activo, vehiculo_id)
                    VALUES (:uid, :nom, :tel, :fn, :ced, true, :vid)"""
                ),
                {
                    "uid": user_id,
                    "nom": f"{datos.owner_nombre} {datos.owner_apellido}",
                    "tel": datos.owner_telefono,
                    "fn": owner_f_nac,
                    "ced": datos.owner_cedula,
                    "vid": vehiculo_id,
                },
            )

        # Subir fotos del vehículo y del dueño (si vienen)
        ok_auto = await _storage_upload(
            f"vehiculos/{vehiculo_id}/foto_vehiculo",
            foto_vehiculo,
        )
        if ok_auto:
            try:
                await db.execute(
                    text(
                        "UPDATE vehiculos SET foto_vehiculo = :fv, foto_vehiculo_url = NULL WHERE id = :vid"
                    ),
                    {"fv": "OK", "vid": vehiculo_id},
                )
            except Exception:
                pass

        ok_front = await _storage_upload(
            f"conductores/{user_id}/cedula_front",
            cedula_front,
        )
        ok_back = await _storage_upload(
            f"conductores/{user_id}/cedula_back",
            cedula_back,
        )
        ok_perfil = await _storage_upload(
            f"conductores/{user_id}/foto_perfil",
            foto_perfil,
        )
        updates = []
        params = {"uid": user_id}
        if ok_front:
            updates.append("cedula_front = :cf")
            updates.append("cedula_front_url = NULL")
            params["cf"] = "OK"
        if ok_back:
            updates.append("cedula_back = :cb")
            updates.append("cedula_back_url = NULL")
            params["cb"] = "OK"
        if ok_perfil:
            updates.append("foto_perfil = :fp")
            updates.append("foto_perfil_url = NULL")
            params["fp"] = "OK"
        if updates:
            try:
                await db.execute(
                    text(
                        "UPDATE conductores SET "
                        + ", ".join(updates)
                        + " WHERE usuario_id = :uid"
                    ),
                    params,
                )
            except Exception:
                pass

        # Procesa Conductores Extra
        if datos.conductores_extra:
            try:
                extras = json.loads(datos.conductores_extra)
            except Exception:
                extras = []
            if isinstance(extras, list):
                for c in extras:
                    try:
                        extra_cedula = c.get("cedula") or ""
                        extra_email = (c.get("email") or f"{extra_cedula}@chofer.com").strip().lower()
                        extra_nombre = f"{c.get('nombre', '').strip()} {c.get('apellido', '').strip()}".strip()
                        extra_tel = c.get("telefono") or ""
                        extra_fecha = c.get("fecha_nacimiento")
                        extra_f_nac = None
                        if extra_fecha:
                            try:
                                extra_f_nac = datetime.strptime(extra_fecha, "%Y-%m-%d").date()
                            except Exception:
                                extra_f_nac = None

                        row = (
                            await db.execute(
                                text("SELECT id, role FROM usuarios WHERE email = :e"),
                                {"e": extra_email},
                            )
                        ).fetchone()

                        supa_extra = None
                        if row:
                            if (row.role or "").lower() != "conductor":
                                return JSONResponse(
                                    status_code=400,
                                    content={"error": f"Email ya existe con otro rol: {extra_email}"},
                                )
                            extra_uid = row.id
                        else:
                            supa_res = await _supabase_admin_create_user(
                                extra_email, extra_cedula, "conductor"
                            )
                            if isinstance(supa_res, dict) and supa_res.get("error"):
                                err_msg = str(supa_res.get("error"))
                                if _is_supabase_user_exists_error(err_msg):
                                    supa_extra = await _supabase_admin_get_user_by_email(extra_email)
                                else:
                                    return JSONResponse(
                                        status_code=400, content={"error": supa_res["error"]}
                                    )
                            else:
                                supa_extra = supa_res

                            extra_uid = (
                                await db.execute(
                                    text(
                                        """INSERT INTO usuarios (email, password_hash, role, must_change_password)
                                        VALUES (:e, :p, 'conductor', true) RETURNING id"""
                                    ),
                                    {
                                        "e": extra_email,
                                        "p": obtener_hash_password(extra_cedula),
                                    },
                                )
                            ).scalar()

                            try:
                                if isinstance(supa_extra, dict) and supa_extra.get("id"):
                                    await db.execute(
                                        text(
                                            "UPDATE usuarios SET supabase_uid = :suid WHERE id = :uid"
                                        ),
                                        {"suid": supa_extra.get("id"), "uid": extra_uid},
                                    )
                            except Exception:
                                pass

                        exists_extra_cond = (
                            await db.execute(
                                text("SELECT 1 FROM conductores WHERE usuario_id = :u"),
                                {"u": extra_uid},
                            )
                        ).scalar()
                        if not exists_extra_cond:
                            await db.execute(
                                text(
                                    """INSERT INTO conductores (usuario_id, nom_apell, telefono, fecha_nacimiento, cedula, activo, vehiculo_id)
                                    VALUES (:uid, :nom, :tel, :fn, :ced, true, :vid)"""
                                ),
                                {
                                    "uid": extra_uid,
                                    "nom": extra_nombre or "Conductor",
                                    "tel": extra_tel,
                                    "fn": extra_f_nac,
                                    "ced": extra_cedula,
                                    "vid": vehiculo_id,
                                },
                            )
                    except Exception:
                        continue

        await db.commit()
        return {"ok": True, "mensaje": "Flota registrada exitosamente"}

    except Exception as e:
        await db.rollback()
        print(f"Error en registro completo: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# CONSULTAS AUXILIARES Y REGISTRO DE CONDUCTORES
@app.get("/vehiculos/placas")
async def obtener_lista_placas(db: AsyncSession = Depends(get_db)):
    # Retorna lista simple: ["GCA-123", "PBA-456"]
    try:
        result = await db.execute(
            text("SELECT placa FROM vehiculos ORDER BY placa ASC")
        )
        return [row.placa for row in result.fetchall()]
    except Exception as e:
        print(f"Error obteniendo placas: {e}")
        return []


# PARA BUSCAR VEHICULO X PLACA EN REGISTRO CONDUCTOR
@app.get("/vehiculos/{placa}")
async def obtener_vehiculo_por_placa(placa: str, db: AsyncSession = Depends(get_db)):
    try:
        query = text(
            """
            SELECT v.id, v.marca, v.modelo, v.color,
                   COALESCE(p.nom_apell, c.nom_apell) as nom_apell
            FROM vehiculos v 
            LEFT JOIN conductores c ON c.vehiculo_id = v.id 
            LEFT JOIN propietarios p ON p.usuario_id = c.usuario_id
            WHERE v.placa = :placa 
            ORDER BY (p.nom_apell IS NOT NULL) DESC, c.id_conductor ASC
            LIMIT 1
        """
        )
        result = await db.execute(query, {"placa": placa})
        row = result.fetchone()

        if row:
            return {
                "id": row.id,
                "marca": f"{row.marca} {row.modelo}",
                "color": row.color,
                "dueno": row.nom_apell,
            }
        else:
            return None
    except Exception as e:
        print(f"Error buscando placa: {e}")
        return None


# ENDPOINTS: VISUALIZACIÓN DE IMÁGENES Y DOCUMENTOS
@app.get("/vehiculos/{vehiculo_id}/foto")
async def ver_foto_vehiculo(vehiculo_id: int, db: AsyncSession = Depends(get_db)):
    data = await _storage_download(f"vehiculos/{vehiculo_id}/foto_vehiculo")
    if not data:
        url = await _get_media_url(
            db, "vehiculos", "foto_vehiculo_url", "id", vehiculo_id
        )
        if url:
            return RedirectResponse(url)
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))


@app.get("/conductores/{usuario_id}/foto_perfil")
async def ver_foto_conductor(usuario_id: int, db: AsyncSession = Depends(get_db)):
    data = await _storage_download(f"conductores/{usuario_id}/foto_perfil")
    if not data:
        url = await _get_media_url(
            db, "conductores", "foto_perfil_url", "usuario_id", usuario_id
        )
        if url:
            return RedirectResponse(url)
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))


@app.get("/conductores/{usuario_id}/cedula_front")
async def ver_cedula_front_conductor(
    usuario_id: int, db: AsyncSession = Depends(get_db)
):
    data = await _storage_download(f"conductores/{usuario_id}/cedula_front")
    if not data:
        url = await _get_media_url(
            db, "conductores", "cedula_front_url", "usuario_id", usuario_id
        )
        if url:
            return RedirectResponse(url)
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))


@app.get("/conductores/{usuario_id}/cedula_back")
async def ver_cedula_back_conductor(
    usuario_id: int, db: AsyncSession = Depends(get_db)
):
    data = await _storage_download(f"conductores/{usuario_id}/cedula_back")
    if not data:
        url = await _get_media_url(
            db, "conductores", "cedula_back_url", "usuario_id", usuario_id
        )
        if url:
            return RedirectResponse(url)
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))


@app.get("/clientes/{usuario_id}/foto_cedula_frente")
async def ver_cedula_frente_cliente(
    usuario_id: int, db: AsyncSession = Depends(get_db)
):
    data = await _storage_download(f"clientes/{usuario_id}/foto_cedula_frente")
    if not data:
        url = await _get_media_url(
            db, "clientes", "foto_cedulafrente_url", "usuario_id", usuario_id
        )
        if url:
            return RedirectResponse(url)
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))


@app.get("/clientes/{usuario_id}/foto_cedula_posterior")
async def ver_cedula_posterior_cliente(
    usuario_id: int, db: AsyncSession = Depends(get_db)
):
    data = await _storage_download(f"clientes/{usuario_id}/foto_cedula_posterior")
    if not data:
        url = await _get_media_url(
            db, "clientes", "foto_cedulaposterior_url", "usuario_id", usuario_id
        )
        if url:
            return RedirectResponse(url)
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))


@app.get("/clientes/{usuario_id}/foto_selfie")
async def ver_selfie_cliente(usuario_id: int, db: AsyncSession = Depends(get_db)):
    data = await _storage_download(f"clientes/{usuario_id}/foto_selfie")
    if not data:
        url = await _get_media_url(
            db, "clientes", "foto_selfieci_url", "usuario_id", usuario_id
        )
        if url:
            return RedirectResponse(url)
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))


@app.get("/clientes/{usuario_id}/foto_pasaporte")
async def ver_pasaporte_cliente(usuario_id: int, db: AsyncSession = Depends(get_db)):
    data = await _storage_download(f"clientes/{usuario_id}/foto_pasaporte")
    if not data:
        url = await _get_media_url(
            db, "clientes", "foto_pasaporte_url", "usuario_id", usuario_id
        )
        if url:
            return RedirectResponse(url)
        return JSONResponse(status_code=404, content={"error": "No encontrada"})
    return Response(content=data, media_type=_guess_mime(data))


# ENDPOINT: REGISTRO DE CONDUCTOR
# Permite que un conductor nuevo se registre seleccionando un vehículo
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
    db: AsyncSession = Depends(get_db),
):
    try:
        role_db = (role or "conductor").lower()
        # Verifica Auto
        q_vehiculo = text("SELECT id FROM vehiculos WHERE placa = :placa")
        res_v = await db.execute(q_vehiculo, {"placa": placa_vinculada})
        vehiculo_id = res_v.scalar()

        if not vehiculo_id:
            raise HTTPException(status_code=404, detail="El vehï¿½culo no existe")

        f_nac = None
        if fecha_nacimiento:
            try:
                f_nac = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
            except Exception:
                f_nac = None

        # Crea Usuario
        email_final = (email or f"{cedula}@taxis.com").strip().lower()
        existing_row = (
            await db.execute(
                text("SELECT id, role FROM usuarios WHERE email = :e"),
                {"e": email_final},
            )
        ).fetchone()

        if existing_row:
            if (existing_row.role or "").lower() != "conductor":
                return JSONResponse(
                    status_code=400, content={"error": "El correo ya existe"}
                )
            new_user_id = existing_row.id
        else:
            supa_user = None
            supa_res = await _supabase_admin_create_user(email_final, cedula, role_db)
            if isinstance(supa_res, dict) and supa_res.get("error"):
                err_msg = str(supa_res.get("error"))
                if _is_supabase_user_exists_error(err_msg):
                    supa_user = await _supabase_admin_get_user_by_email(email_final)
                else:
                    return JSONResponse(
                        status_code=400, content=dict(error=supa_res["error"])
                    )
            else:
                supa_user = supa_res

            q_user = text(
                """
                INSERT INTO usuarios (email, password_hash, role, must_change_password)
                VALUES (:email, :pwd, :role, true)
                RETURNING id
            """
            )
            try:
                pwd_hash = obtener_hash_password(cedula)
                res_u = await db.execute(
                    q_user, {"email": email_final, "pwd": pwd_hash, "role": role_db}
                )
                new_user_id = res_u.scalar()
            except IntegrityError:
                await db.rollback()
                existing_dup = (
                    await db.execute(
                        text("SELECT id, role FROM usuarios WHERE email = :e"),
                        {"e": email_final},
                    )
                ).fetchone()
                if not existing_dup:
                    return JSONResponse(
                        status_code=400, content={"error": "El correo ya existe"}
                    )
                if (existing_dup.role or "").lower() != "conductor":
                    return JSONResponse(
                        status_code=400,
                        content={"error": "El correo ya existe con otro rol"},
                    )
                new_user_id = existing_dup.id
            try:
                if isinstance(supa_user, dict) and supa_user.get("id"):
                    await db.execute(
                        text(
                            "UPDATE usuarios SET supabase_uid = :suid WHERE id = :uid"
                        ),
                        {"suid": supa_user.get("id"), "uid": new_user_id},
                    )
            except Exception:
                pass

        # Crea Conductor vinculado
        exists_cond = (
            await db.execute(
                text("SELECT 1 FROM conductores WHERE usuario_id = :u"),
                {"u": new_user_id},
            )
        ).scalar()
        if not exists_cond:
            q_conductor = text(
                """
                INSERT INTO conductores (usuario_id, nom_apell, telefono, fecha_nacimiento, cedula, activo, vehiculo_id)
                VALUES (:uid, :nombre, :telf, :fn, :ced, true, :vid)
            """
            )
            await db.execute(
                q_conductor,
                {
                    "uid": new_user_id,
                    "nombre": f"{nombre} {apellido}",
                    "telf": telefono,
                    "fn": f_nac,
                    "ced": cedula,
                    "vid": vehiculo_id,
                },
            )
        else:
            await db.execute(
                text(
                    "UPDATE conductores SET "
                    "nom_apell = COALESCE(NULLIF(nom_apell, ''), :nombre), "
                    "telefono = COALESCE(NULLIF(telefono, ''), :telf), "
                    "fecha_nacimiento = COALESCE(fecha_nacimiento, :fn), "
                    "cedula = COALESCE(NULLIF(cedula, ''), :ced), "
                    "vehiculo_id = COALESCE(vehiculo_id, :vid) "
                    "WHERE usuario_id = :uid"
                ),
                {
                    "uid": new_user_id,
                    "nombre": f"{nombre} {apellido}",
                    "telf": telefono,
                    "fn": f_nac,
                    "ced": cedula,
                    "vid": vehiculo_id,
                },
            )

        ok_front = await _storage_upload(
            f"conductores/{new_user_id}/cedula_front",
            cedula_front,
        )
        ok_back = await _storage_upload(
            f"conductores/{new_user_id}/cedula_back",
            cedula_back,
        )
        ok_perfil = await _storage_upload(
            f"conductores/{new_user_id}/foto_perfil",
            foto_perfil,
        )

        updates = []
        params = {"uid": new_user_id}
        if ok_front:
            updates.append("cedula_front = :cf")
            params["cf"] = "OK"
        if ok_back:
            updates.append("cedula_back = :cb")
            params["cb"] = "OK"
        if ok_perfil:
            updates.append("foto_perfil = :fp")
            params["fp"] = "OK"
        if updates:
            updates.append("cedula_front_url = NULL")
            updates.append("cedula_back_url = NULL")
            updates.append("foto_perfil_url = NULL")
            await db.execute(
                text(
                    "UPDATE conductores SET "
                    + ", ".join(updates)
                    + " WHERE usuario_id = :uid"
                ),
                params,
            )

        await db.commit()
        return {"mensaje": "Conductor registrado y vinculado exitosamente"}

    except Exception as e:
        await db.rollback()
        print(f"Error en registro: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# GESTION DE VIAJES
@app.post("/viajes/solicitar")
async def solicitar(v: ViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        clave = random.choice(PALABRAS_CLAVE)
        geo_ori = (
            f"ST_GeomFromText('POINT({v.origen_lng} {v.origen_lat})', 4326)"
            if v.origen_lng
            else "NULL"
        )
        geo_des = (
            f"ST_GeomFromText('POINT({v.destino_lng} {v.destino_lat})', 4326)"
            if v.destino_lng
            else "NULL"
        )

        query = text(
            f"INSERT INTO viajes (cliente_id, origen, destino, tarifa, estado, origen_lat, origen_lng, destino_lat, destino_lng, origen_geom, destino_geom, clave_seguridad, fecha_creacion) VALUES (:cid, :ori, :des, :tar, 'pendiente', :olat, :olng, :dlat, :dlng, {geo_ori}, {geo_des}, :clave, NOW()) RETURNING id"
        )
        res = await db.execute(
            query,
            {
                "cid": v.usuario_id,
                "ori": v.origen,
                "des": v.destino,
                "tar": v.tarifa,
                "olat": v.origen_lat,
                "olng": v.origen_lng,
                "dlat": v.destino_lat,
                "dlng": v.destino_lng,
                "clave": clave,
            },
        )
        vid = res.scalar()

        await db.commit()
        return {"mensaje": "Viaje solicitado", "id_viaje": vid, "clave": clave}
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}


@app.get("/viajes/pendientes")
async def ver_pendientes(db: AsyncSession = Depends(get_db)):
    try:
        query = text(
            """
            SELECT v.id, v.origen, v.destino, v.tarifa, v.estado, 
                   v.origen_lat, v.origen_lng, v.destino_lat, v.destino_lng, 
                   c.nom_apell, v.fecha_creacion
            FROM viajes v
            LEFT JOIN clientes c ON v.cliente_id = c.usuario_id
            WHERE v.estado='pendiente' 
            ORDER BY v.fecha_creacion DESC
            LIMIT 50
        """
        )
        res = await db.execute(query)
        return [
            {
                "id": r.id,
                "origen": r.origen,
                "destino": r.destino,
                "tarifa": r.tarifa,
                "estado": r.estado,
                "cliente": r.nom_apell or "Cliente",
                "origen_lat": r.origen_lat,
                "origen_lng": r.origen_lng,
                "destino_lat": r.destino_lat,
                "destino_lng": r.destino_lng,
                "creado_en": r.fecha_creacion.isoformat() if r.fecha_creacion else None,
            }
            for r in res.fetchall()
        ]
    except:
        return []


@app.post("/viajes/aceptar")
async def aceptar(d: AceptarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        st = (
            await db.execute(
                text("SELECT estado FROM viajes WHERE id=:vid"), {"vid": d.viaje_id}
            )
        ).scalar()
        if st != "pendiente":
            return {"error": "Viaje no disponible"}

        await db.execute(
            text(
                "UPDATE viajes SET conductor_id=:cid, estado='aceptado' WHERE id=:vid"
            ),
            {"cid": d.conductor_id, "vid": d.viaje_id},
        )
        await db.commit()
        return {"mensaje": "Viaje aceptado"}
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}


@app.post("/viajes/validar_inicio")
async def validar_inicio_viaje(
    d: IniciarViajeRequest, db: AsyncSession = Depends(get_db)
):
    try:
        real = (
            await db.execute(
                text("SELECT clave_seguridad FROM viajes WHERE id=:vid"),
                {"vid": d.viaje_id},
            )
        ).scalar()
        if not real:
            return {"error": "Datos no encontrados", "exito": False}

        if d.clave_ingresada.upper().strip() == real.upper().strip():
            await db.execute(
                text("UPDATE viajes SET estado='en_curso' WHERE id=:vid"),
                {"vid": d.viaje_id},
            )
            await db.commit()
            return {"mensaje": "OK", "exito": True}
        else:
            return {"error": "Clave incorrecta", "exito": False}
    except Exception as e:
        await db.rollback()
        return {"error": str(e), "exito": False}


@app.post("/viajes/actualizar_estado")
async def actualizar_estado_viaje(
    d: EstadoViajeRequest, db: AsyncSession = Depends(get_db)
):
    try:
        await db.execute(
            text("UPDATE viajes SET estado=:st WHERE id=:vid"),
            {"st": d.nuevo_estado, "vid": d.viaje_id},
        )
        await db.commit()
        return {"mensaje": "Estado actualizado"}
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}


@app.post("/viajes/cancelar")
async def cancelar_viaje(d: CancelarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        st = (
            await db.execute(
                text("SELECT estado FROM viajes WHERE id=:vid"), {"vid": d.viaje_id}
            )
        ).scalar()
        if not st:
            return {"error": "Viaje no encontrado"}
        if st == "cancelado":
            return {"mensaje": "Ya cancelado"}
        if st == "finalizado":
            return {"error": "No se puede cancelar un viaje finalizado."}

        await db.execute(
            text("UPDATE viajes SET estado='cancelado' WHERE id=:vid"),
            {"vid": d.viaje_id},
        )
        await db.commit()
        return {"mensaje": "Viaje cancelado correctamente"}
    except Exception as e:
        await db.rollback()
        return {"error": f"Error interno: {str(e)}"}


@app.get("/viajes/{viaje_id}")
async def obtener_viaje(viaje_id: int, db: AsyncSession = Depends(get_db)):
    try:
        query = text(
            """
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
        """
        )
        v = (await db.execute(query, {"vid": viaje_id})).fetchone()
        if v:
            return {
                "estado": v.estado,
                "clave_seguridad": v.clave_seguridad,
                "origen": {"lat": v.origen_lat, "lng": v.origen_lng},
                "destino": {"lat": v.destino_lat, "lng": v.destino_lng},
                "conductor": (
                    {
                        "nombre": v.nombre_conductor,
                        "placa": v.placa,
                        "modelo": v.modelo,
                        "color": v.color,
                        "telefono": v.telefono,
                        "lat": v.conductor_lat,
                        "lng": v.conductor_lng,
                    }
                    if v.conductor_id
                    else None
                ),
            }
        return {"error": "No encontrado"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/public/viajes/{viaje_id}")
async def public_viaje(viaje_id: int, db: AsyncSession = Depends(get_db)):
    try:
        query = text(
            """
            SELECT v.estado,
                   ST_X(c.ubicacion::geometry) as conductor_lng,
                   ST_Y(c.ubicacion::geometry) as conductor_lat
            FROM viajes v
            LEFT JOIN conductores c ON v.conductor_id = c.usuario_id
            WHERE v.id = :vid
        """
        )
        v = (await db.execute(query, {"vid": viaje_id})).fetchone()
        if not v:
            return {"error": "No encontrado"}
        return {
            "estado": v.estado,
            "conductor": (
                {
                    "lat": v.conductor_lat,
                    "lng": v.conductor_lng,
                }
                if v.conductor_lat is not None and v.conductor_lng is not None
                else None
            ),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/share/viaje/{viaje_id}", response_class=HTMLResponse)
async def share_viaje(viaje_id: int):
    return HTMLResponse(
        f"""
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
"""
    )


@app.post("/contactos/agregar")
async def agregar_contacto(d: ContactoRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(
            text(
                "INSERT INTO emergencia (usuario_id, nombre_contacto, numero_whatsapp) VALUES (:uid, :nom, :num)"
            ),
            {"uid": d.usuario_id, "nom": d.nombre_contacto, "num": d.numero_whatsapp},
        )
        await db.commit()
        return {"mensaje": "Guardado"}
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}


@app.get("/contactos/listar/{uid}")
async def listar_contactos(uid: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        text(
            "SELECT id, nombre_contacto, numero_whatsapp FROM emergencia WHERE usuario_id = :uid"
        ),
        {"uid": uid},
    )
    return [
        {"id": c.id, "nombre": c.nombre_contacto, "numero": c.numero_whatsapp}
        for c in res.fetchall()
    ]


@app.put("/contactos/editar/{cid}")
async def editar_contacto(
    cid: int, datos: ContactoEditRequest, db: AsyncSession = Depends(get_db)
):
    try:
        await db.execute(
            text(
                "UPDATE emergencia SET nombre_contacto=:nom, numero_whatsapp=:num WHERE id=:id"
            ),
            {"nom": datos.nombre_contacto, "num": datos.numero_whatsapp, "id": cid},
        )
        await db.commit()
        return {"mensaje": "Actualizado"}
    except:
        return {"error": "Error"}


@app.delete("/contactos/eliminar/{cid}")
async def eliminar_contacto(cid: int, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("DELETE FROM emergencia WHERE id=:id"), {"id": cid})
        await db.commit()
        return {"mensaje": "Eliminado"}
    except:
        return {"error": "Error"}


# SEGURIDAD Y SOS
@app.post("/sos/activar")
async def activar_sos(d: AlertaRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(
            text(
                "INSERT INTO alertas (usuario_id, ubicacion, mensaje_extra) VALUES (:uid, :ubi, :msg)"
            ),
            {"uid": d.usuario_id, "ubi": d.ubicacion, "msg": d.mensaje},
        )
        await db.commit()
        return {"mensaje": "Alerta registrada"}
    except:
        return {"error": "Error"}


@app.post("/sos/activar_conductor")
async def activar_sos_conductor(
    d: SosConductorRequest, db: AsyncSession = Depends(get_db)
):
    try:
        await db.execute(
            text(
                "INSERT INTO alertas (usuario_id, ubicacion, mensaje_extra) VALUES (:uid, :ubi, :msg)"
            ),
            {
                "uid": d.usuario_id,
                "ubi": f"{d.lat},{d.lng}",
                "msg": d.mensaje or "SOS Conductor",
            },
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        return {"error": str(e)}

    res = await db.execute(
        text(
            """
            SELECT c.nom_apell, v.marca, v.modelo, v.placa, v.color
            FROM conductores c
            LEFT JOIN vehiculos v ON c.vehiculo_id = v.id
            WHERE c.usuario_id = :uid
        """
        ),
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
async def actualizar_ubicacion(
    datos: UbicacionConductorRequest, db: AsyncSession = Depends(get_db)
):
    try:
        await db.execute(
            text(
                "UPDATE conductores SET ubicacion = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) WHERE usuario_id = :uid"
            ),
            {"uid": datos.usuario_id, "lat": datos.latitud, "lng": datos.longitud},
        )
        await db.commit()
        return {"mensaje": "Ubicaciï¿½n OK"}
    except:
        return {"error": "Error"}


@app.post("/conductores/estado")
async def cambiar_estado(
    datos: EstadoConductorRequest, db: AsyncSession = Depends(get_db)
):
    try:
        await db.execute(
            text("UPDATE conductores SET activo = :st WHERE usuario_id = :uid"),
            {"uid": datos.usuario_id, "st": datos.activo},
        )
        await db.commit()
        return {"mensaje": "Estado OK"}
    except:
        return {"error": "Error"}


@app.get("/conductores/cercanos")
async def obtener_conductores_cercanos(
    lat: float, lng: float, radio_km: float = 2.0, db: AsyncSession = Depends(get_db)
):
    try:
        query = text(
            """
            SELECT c.id_conductor, c.nom_apell, v.placa, v.modelo,
                   ST_X(c.ubicacion::geometry) as lng, 
                   ST_Y(c.ubicacion::geometry) as lat
            FROM conductores c
            JOIN vehiculos v ON c.vehiculo_id = v.id
            WHERE c.ubicacion IS NOT NULL
            AND c.activo = TRUE 
            AND ST_DWithin(c.ubicacion, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :metros)
        """
        )
        res = await db.execute(
            query, {"lat": lat, "lng": lng, "metros": radio_km * 1000}
        )
        return [
            {
                "id": c.id_conductor,
                "nombre": c.nom_apell,
                "placa": c.placa,
                "modelo": c.modelo,
                "lat": c.lat,
                "lng": c.lng,
            }
            for c in res.fetchall()
        ]
    except:
        return []


@app.get("/conductores")
async def listar_conductores_todos(db: AsyncSession = Depends(get_db)):
    try:
        query = text(
            """
            SELECT c.id_conductor, c.nom_apell, c.telefono, c.activo, v.placa, u.id as usuario_id,
                   u.email, c.cedula, c.fecha_nacimiento,
                   c.foto_perfil, c.cedula_front, c.cedula_back,
                   c.foto_perfil_url, c.cedula_front_url, c.cedula_back_url
            FROM conductores c
            JOIN vehiculos v ON c.vehiculo_id = v.id
            JOIN usuarios u ON c.usuario_id = u.id
        """
        )
        res = await db.execute(query)
        return [
            {
                "id": r.usuario_id,
                "id_conductor": r.id_conductor,
                "nom_apell": r.nom_apell,
                "nombre": r.nom_apell,
                "telefono": r.telefono,
                "activo": r.activo,
                "placa": r.placa,
                "email": r.email,
                "cedula": r.cedula,
                "fecha_nacimiento": (
                    r.fecha_nacimiento.isoformat() if r.fecha_nacimiento else None
                ),
                "has_foto_perfil": (r.foto_perfil == "OK")
                or (r.foto_perfil_url is not None),
                "has_cedula_front": (r.cedula_front == "OK")
                or (r.cedula_front_url is not None),
                "has_cedula_back": (r.cedula_back == "OK")
                or (r.cedula_back_url is not None),
            }
            for r in res.fetchall()
        ]
    except Exception as e:
        return []


@app.get("/usuarios")
async def listar_usuarios_todos(db: AsyncSession = Depends(get_db)):
    try:
        query = text(
            """
            SELECT u.id, u.email, COALESCE(c.nom_apell, 'Sin Nombre') as nombre, c.telefono,
                   c.foto_cedulafrente, c.foto_cedulaposterior, c.foto_selfieci, c.foto_pasaporte,
                   c.foto_cedulafrente_url, c.foto_cedulaposterior_url, c.foto_selfieci_url, c.foto_pasaporte_url
            FROM usuarios u
            LEFT JOIN clientes c ON u.id = c.usuario_id
            WHERE u.role = 'cliente'
        """
        )
        res = await db.execute(query)
        return [
            {
                "id": r.id,
                "email": r.email,
                "nombre": r.nombre,
                "telefono": r.telefono,
                "has_cedula_front": (r.foto_cedulafrente == "OK")
                or (r.foto_cedulafrente_url is not None),
                "has_cedula_back": (r.foto_cedulaposterior == "OK")
                or (r.foto_cedulaposterior_url is not None),
                "has_selfie": (r.foto_selfieci == "OK")
                or (r.foto_selfieci_url is not None),
                "has_pasaporte": (r.foto_pasaporte == "OK")
                or (r.foto_pasaporte_url is not None),
            }
            for r in res.fetchall()
        ]
    except Exception as e:
        print(f"Error usuarios: {e}")
        return []


@app.get("/vehiculos")
async def listar_vehiculos_todos(db: AsyncSession = Depends(get_db)):
    try:
        query = text("SELECT id, marca, modelo, placa, color, anio FROM vehiculos")
        res = await db.execute(query)
        return [
            {
                "id": r.id,
                "marca": r.marca,
                "modelo": r.modelo,
                "placa": r.placa,
                "color": r.color,
                "anio": r.anio,
            }
            for r in res.fetchall()
        ]
    except Exception as e:
        print(f"Error vehiculos: {e}")
        return []


@app.put("/conductores/{id_conductor}")
async def modificar_estado_conductor(
    id_conductor: int, datos: EstadoConductorPut, db: AsyncSession = Depends(get_db)
):
    uid = (
        await db.execute(
            text("SELECT usuario_id FROM conductores WHERE id_conductor=:id"),
            {"id": id_conductor},
        )
    ).scalar()
    if uid:
        await db.execute(
            text("UPDATE conductores SET activo = :st WHERE usuario_id = :uid"),
            {"uid": uid, "st": datos.activo},
        )
        await db.commit()
        return {"mensaje": "Estado actualizado"}
    return {"error": "Conductor no encontrado"}


@app.put("/admin/conductores/actualizar")
async def admin_actualizar_conductor(
    d: AdminConductorUpdateRequest, db: AsyncSession = Depends(get_db)
):
    try:
        user = (
            await db.execute(
                text(
                    "SELECT id, email, role, supabase_uid FROM usuarios WHERE id = :uid"
                ),
                {"uid": d.usuario_id},
            )
        ).fetchone()
        if not user:
            return JSONResponse(
                status_code=404, content={"error": "Usuario no encontrado"}
            )
        if user.role != "conductor":
            return JSONResponse(
                status_code=400, content={"error": "El usuario no es conductor"}
            )

        if d.email and d.email != user.email:
            exists_email = (
                await db.execute(
                    text("SELECT 1 FROM usuarios WHERE email = :e AND id <> :uid"),
                    {"e": d.email, "uid": d.usuario_id},
                )
            ).scalar()
            if exists_email:
                return JSONResponse(
                    status_code=400, content={"error": "El correo ya existe"}
                )
            if user.supabase_uid:
                supa_res = await _supabase_admin_update_user(
                    user.supabase_uid, {"email": d.email}
                )
                if isinstance(supa_res, dict) and supa_res.get("error"):
                    return JSONResponse(
                        status_code=400, content={"error": supa_res["error"]}
                    )
            await db.execute(
                text("UPDATE usuarios SET email = :e WHERE id = :uid"),
                {"e": d.email, "uid": d.usuario_id},
            )

        if d.password:
            if not user.supabase_uid:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "No se pudo cambiar la clave (supabase_uid vacio)"
                    },
                )
            supa_res = await _supabase_admin_update_user(
                user.supabase_uid, {"password": d.password}
            )
            if isinstance(supa_res, dict) and supa_res.get("error"):
                return JSONResponse(
                    status_code=400, content={"error": supa_res["error"]}
                )
            password_segura = obtener_hash_password(d.password)
            await db.execute(
                text(
                    "UPDATE usuarios SET password_hash = :p, must_change_password = false WHERE id = :uid"
                ),
                {"p": password_segura, "uid": d.usuario_id},
            )

        vehiculo_id = None
        if d.vehiculo_placa:
            vehiculo_id = (
                await db.execute(
                    text("SELECT id FROM vehiculos WHERE placa = :p"),
                    {"p": d.vehiculo_placa},
                )
            ).scalar()
            if not vehiculo_id:
                return JSONResponse(
                    status_code=400, content={"error": "Vehï¿½culo no encontrado"}
                )

        cond_exists = (
            await db.execute(
                text("SELECT 1 FROM conductores WHERE usuario_id = :u"),
                {"u": d.usuario_id},
            )
        ).scalar()

        if not cond_exists:
            await db.execute(
                text(
                    "INSERT INTO conductores (usuario_id, nom_apell, telefono, fecha_nacimiento, cedula, activo, vehiculo_id) "
                    "VALUES (:uid, :nom, :tel, :fn, :ced, :act, :vid)"
                ),
                {
                    "uid": d.usuario_id,
                    "nom": d.nombre or "Conductor",
                    "tel": d.telefono,
                    "fn": d.fecha_nacimiento,
                    "ced": d.cedula,
                    "act": d.activo if d.activo is not None else True,
                    "vid": vehiculo_id,
                },
            )
        else:
            await db.execute(
                text(
                    "UPDATE conductores SET "
                    "nom_apell = COALESCE(:nom, nom_apell), "
                    "telefono = COALESCE(:tel, telefono), "
                    "fecha_nacimiento = COALESCE(:fn, fecha_nacimiento), "
                    "cedula = COALESCE(:ced, cedula), "
                    "activo = COALESCE(:act, activo), "
                    "vehiculo_id = COALESCE(:vid, vehiculo_id) "
                    "WHERE usuario_id = :uid"
                ),
                {
                    "uid": d.usuario_id,
                    "nom": d.nombre,
                    "tel": d.telefono,
                    "fn": d.fecha_nacimiento,
                    "ced": d.cedula,
                    "act": d.activo,
                    "vid": vehiculo_id,
                },
            )

        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/admin/conductores/fotos")
async def admin_actualizar_fotos_conductor(
    usuario_id: int = Form(...),
    foto_perfil: UploadFile = File(None),
    cedula_front: UploadFile = File(None),
    cedula_back: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        exists_cond = (
            await db.execute(
                text("SELECT 1 FROM conductores WHERE usuario_id = :u"),
                {"u": usuario_id},
            )
        ).scalar()
        if not exists_cond:
            return JSONResponse(
                status_code=404, content={"error": "Conductor no encontrado"}
            )

        ok_perfil = await _storage_upload(
            f"conductores/{usuario_id}/foto_perfil",
            foto_perfil,
        )
        ok_front = await _storage_upload(
            f"conductores/{usuario_id}/cedula_front",
            cedula_front,
        )
        ok_back = await _storage_upload(
            f"conductores/{usuario_id}/cedula_back",
            cedula_back,
        )
        updates = []
        params = {"uid": usuario_id}
        if ok_perfil:
            updates.append("foto_perfil = :fp")
            params["fp"] = "OK"
        if ok_front:
            updates.append("cedula_front = :cf")
            params["cf"] = "OK"
        if ok_back:
            updates.append("cedula_back = :cb")
            params["cb"] = "OK"
        if updates:
            updates.append("foto_perfil_url = NULL")
            updates.append("cedula_front_url = NULL")
            updates.append("cedula_back_url = NULL")
            await db.execute(
                text(
                    "UPDATE conductores SET "
                    + ", ".join(updates)
                    + " WHERE usuario_id = :uid"
                ),
                params,
            )
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})


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


# visualizar errores
@app.on_event("startup")
async def debug_rutas():
    print("🚀 RUTAS REGISTRADAS EN EL SERVIDOR:")
    for route in app.routes:
        print(f"URL: {route.path} | Métodos: {route.methods}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


@app.post("/usuarios/clear_password_flag")
async def clear_password_flag(d: dict, db: AsyncSession = Depends(get_db)):
    try:
        uid = d.get("usuario_id")
        if not uid:
            return dict(error="usuario_id requerido")
        await db.execute(
            text("UPDATE usuarios SET must_change_password = false WHERE id = :uid"),
            dict(uid=uid),
        )
        await db.commit()
        return dict(mensaje="OK")
    except Exception as e:
        await db.rollback()
        return dict(error=str(e))


@app.get("/usuarios/perfil/{usuario_id}")
async def obtener_perfil(usuario_id: int, db: AsyncSession = Depends(get_db)):
    try:
        user = (
            await db.execute(
                text("SELECT id, email, role FROM usuarios WHERE id = :uid"),
                {"uid": usuario_id},
            )
        ).fetchone()
        if not user:
            return JSONResponse(
                status_code=404, content={"error": "Usuario no encontrado"}
            )

        nombre = None
        foto_url = None

        if user.role == "cliente":
            row = (
                await db.execute(
                    text(
                        "SELECT nom_apell, foto_selfieci, foto_selfieci_url FROM clientes WHERE usuario_id = :uid"
                    ),
                    {"uid": usuario_id},
                )
            ).fetchone()
            if row:
                nombre = row.nom_apell
                if row.foto_selfieci == "OK":
                    foto_url = _build_public_url(f"/clientes/{usuario_id}/foto_selfie")
                elif row.foto_selfieci_url:
                    foto_url = row.foto_selfieci_url
        elif user.role == "conductor":
            row = (
                await db.execute(
                    text(
                        "SELECT nom_apell, foto_perfil, foto_perfil_url FROM conductores WHERE usuario_id = :uid"
                    ),
                    {"uid": usuario_id},
                )
            ).fetchone()
            if row:
                nombre = row.nom_apell
                if row.foto_perfil == "OK":
                    foto_url = _build_public_url(
                        f"/conductores/{usuario_id}/foto_perfil"
                    )
                elif row.foto_perfil_url:
                    foto_url = row.foto_perfil_url
        elif user.role == "propietario":
            row = (
                await db.execute(
                    text(
                        "SELECT nom_apell FROM propietarios WHERE usuario_id = :uid"
                    ),
                    {"uid": usuario_id},
                )
            ).fetchone()
            if row:
                nombre = row.nom_apell
                foto_url = _build_public_url(f"/conductores/{usuario_id}/foto_perfil")
        elif user.role == "admin":
            row = (
                await db.execute(
                    text(
                        "SELECT nom_apell FROM administradores WHERE usuario_id = :uid"
                    ),
                    {"uid": usuario_id},
                )
            ).fetchone()
            if row:
                nombre = row.nom_apell

        return {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "nombre": nombre or "Usuario",
            "foto_url": foto_url,
            "calificacion": 5.0,
            "conteo": 0,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
