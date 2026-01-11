# Importaciones estándar y de terceros
import os
import urllib.parse
from datetime import date, datetime
from typing import Optional, List

import uvicorn
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, ForeignKey, text, Date, DateTime, Boolean
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from sqladmin import Admin, ModelView
from geoalchemy2 import Geometry

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE BASE DE DATOS
# -----------------------------------------------------------------------------
PROJECT_ID = "vjhggvxkhowlnbppuiuw" 
DB_PASSWORD = "XYZ*147258369*XYZ"
SUPABASE_USER = f"postgres.{PROJECT_ID}"
SUPABASE_HOST = "aws-1-sa-east-1.pooler.supabase.com" 
SUPABASE_PORT = "6543"
SUPABASE_DB   = "postgres"

encoded_pass = urllib.parse.quote_plus(DB_PASSWORD)
CLOUD_DATABASE_URL = f"postgresql+asyncpg://{SUPABASE_USER}:{encoded_pass}@{SUPABASE_HOST}:{SUPABASE_PORT}/{SUPABASE_DB}?prepared_statement_cache_size=0"

if os.getenv("DATABASE_URL"):
    DATABASE_URL = CLOUD_DATABASE_URL
else:
    DATABASE_URL = "postgresql+asyncpg://postgres:1234@localhost:5432/taxi_app_db"

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# -----------------------------------------------------------------------------
# DEFINICIÓN DE MODELOS ORM
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
    cliente_usuario = relationship("Usuario", foreign_keys=[cliente_id])
    conductor_usuario = relationship("Usuario", foreign_keys=[conductor_id])

# -----------------------------------------------------------------------------
# DTOs
# -----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str; password: str
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
class UbicacionConductorRequest(BaseModel):
    usuario_id: int; latitud: float; longitud: float
class EstadoConductorRequest(BaseModel):
    usuario_id: int; activo: bool

# -----------------------------------------------------------------------------
# APP & ADMIN
# -----------------------------------------------------------------------------
app = FastAPI(title="Taxi App API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

admin = Admin(app, engine, title="Taxi Admin")
class UsuarioAdmin(ModelView, model=Usuario):
    name, name_plural, icon = "Usuario", "Usuarios", "fa-solid fa-user-lock"
    column_list = [Usuario.id, Usuario.email, Usuario.role]
class ClienteAdmin(ModelView, model=Cliente):
    name, name_plural, icon = "Cliente", "Clientes", "fa-solid fa-person"
    column_list = [Cliente.id_cliente, Cliente.nom_apell, Cliente.ciudad]
class ConductorAdmin(ModelView, model=Conductor):
    name, name_plural, icon = "Conductor", "Conductores", "fa-solid fa-id-card"
    column_list = [Conductor.id_conductor, Conductor.nom_apell, "vehiculo.placa", Conductor.activo]
class VehiculoAdmin(ModelView, model=Vehiculo):
    name, name_plural, icon = "Vehículo", "Vehículos", "fa-solid fa-car"
    column_list = [Vehiculo.id, Vehiculo.placa, Vehiculo.marca]
class ViajeAdmin(ModelView, model=Viaje):
    name, name_plural, icon = "Viaje", "Viajes", "fa-solid fa-map-location-dot"
    column_list = [Viaje.id, Viaje.cliente_id, Viaje.origen, Viaje.destino, Viaje.estado]
class EmergenciaAdmin(ModelView, model=Emergencia):
    name, name_plural, icon = "Contacto SOS", "Contactos SOS", "fa-solid fa-address-book"
    column_list = [Emergencia.id, Emergencia.nombre_contacto, Emergencia.numero_whatsapp]
class AlertaAdmin(ModelView, model=Alerta):
    name, name_plural, icon = "ALERTA SOS", "ALERTAS SOS", "fa-solid fa-triangle-exclamation"
    column_list = [Alerta.id, "usuario.email", Alerta.ubicacion, Alerta.fecha]

admin.add_view(UsuarioAdmin); admin.add_view(ClienteAdmin); admin.add_view(ConductorAdmin); admin.add_view(VehiculoAdmin); admin.add_view(ViajeAdmin); admin.add_view(EmergenciaAdmin); admin.add_view(AlertaAdmin)

async def get_db():
    async with async_session() as session: yield session

# -----------------------------------------------------------------------------
# ENDPOINTS
# -----------------------------------------------------------------------------
@app.get("/")
def leer_raiz(): return {"mensaje": "API Taxi Funcionando (v13.0 - Rastreo)."}

@app.post("/login")
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        res = await db.execute(text(f"SELECT * FROM usuarios WHERE email='{datos.email}' AND password_hash='{datos.password}'"))
        user = res.fetchone()
        if not user: return {"error": "Credenciales inválidas"}
        nombre_real = "Usuario"
        if user.role == 'cliente':
            cli = (await db.execute(text(f"SELECT nom_apell FROM clientes WHERE usuario_id={user.id}"))).fetchone()
            if cli: nombre_real = cli.nom_apell
        elif user.role == 'conductor':
            cond = (await db.execute(text(f"SELECT nom_apell FROM conductores WHERE usuario_id={user.id}"))).fetchone()
            if cond: nombre_real = cond.nom_apell
        elif user.role == 'admin':
            adm = (await db.execute(text(f"SELECT nom_apell FROM administradores WHERE usuario_id={user.id}"))).fetchone()
            if adm: nombre_real = adm.nom_apell
        return {"mensaje": "Login OK", "usuario": {"id": user.id, "nombre": nombre_real, "role": user.role}}
    except Exception as e: return {"error": "Error interno"}

@app.post("/registrar_usuario")
async def registrar_usuario(d: UsuarioRegistroRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": d.email})).scalar(): return {"error": "Email registrado."}
            uid = (await db.execute(text("INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"), {"e": d.email, "p": d.password, "r": "cliente"})).scalar()
            try:
                f = datetime.strptime(d.fecha_nacimiento, "%Y-%m-%d").date() if d.fecha_nacimiento else None
                await db.execute(text("INSERT INTO clientes (usuario_id, nom_apell, pais, ciudad, telefono, fecha_nacimiento) VALUES (:u, :n, :p, :c, :t, :f)"), {"u": uid, "n": d.nombre, "p": d.pais, "c": d.ciudad, "t": d.telefono, "f": f})
            except: pass
        return {"mensaje": "Usuario registrado", "id": uid}
    except Exception as e: return {"error": str(e)}

@app.post("/registrar_conductor")
async def registrar_conductor(d: RegistroConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": d.email})).scalar(): return {"error": "Email existe."}
            if (await db.execute(text("SELECT id FROM vehiculos WHERE placa = :p"), {"p": d.vehiculo_placa})).scalar(): return {"error": "Placa existe."}
            uid = (await db.execute(text("INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"), {"e": d.email, "p": d.password, "r": "conductor"})).scalar()
            vid = (await db.execute(text("INSERT INTO vehiculos (marca, modelo, placa, color, anio) VALUES (:ma, :mo, :pl, :co, :an) RETURNING id"), {"ma": d.vehiculo_marca, "mo": d.vehiculo_modelo, "pl": d.vehiculo_placa, "co": d.vehiculo_color, "an": d.vehiculo_anio})).scalar()
            f = datetime.strptime(d.fecha_nacimiento, "%Y-%m-%d").date() if d.fecha_nacimiento else None
            await db.execute(text("INSERT INTO conductores (usuario_id, vehiculo_id, nom_apell, telefono, fecha_nacimiento, activo) VALUES (:u, :v, :n, :t, :f, FALSE)"), {"u": uid, "v": vid, "n": d.nombre, "t": d.telefono, "f": f})
        return {"mensaje": "Conductor registrado", "id": uid}
    except Exception as e: return {"error": str(e)}

# --- SOLICITAR VIAJE ACTUALIZADO (Devuelve ID del viaje) ---
@app.post("/viajes/solicitar")
async def solicitar(v: ViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            geo_ori = f"ST_GeomFromText('POINT({v.origen_lng} {v.origen_lat})', 4326)" if v.origen_lng else "NULL"
            geo_des = f"ST_GeomFromText('POINT({v.destino_lng} {v.destino_lat})', 4326)" if v.destino_lng else "NULL"
            
            query = text(f"""
                INSERT INTO viajes (cliente_id, origen, destino, tarifa, estado, origen_lat, origen_lng, destino_lat, destino_lng, origen_geom, destino_geom) 
                VALUES (:cid, :ori, :des, :tar, 'pendiente', :olat, :olng, :dlat, :dlng, {geo_ori}, {geo_des})
                RETURNING id
            """)
            res = await db.execute(query, {"cid": v.usuario_id, "ori": v.origen, "des": v.destino, "tar": v.tarifa, "olat": v.origen_lat, "olng": v.origen_lng, "dlat": v.destino_lat, "dlng": v.destino_lng})
            vid = res.scalar()
        return {"mensaje": "Viaje solicitado", "id_viaje": vid}
    except Exception as e: return {"error": str(e)}

# --- NUEVO: OBTENER ESTADO DEL VIAJE ---
@app.get("/viajes/{viaje_id}")
async def obtener_viaje(viaje_id: int, db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT v.estado, v.conductor_id, c.nom_apell as nombre_conductor, ve.placa, ve.modelo, ve.color,
                   c.telefono
            FROM viajes v
            LEFT JOIN conductores c ON v.conductor_id = c.usuario_id
            LEFT JOIN vehiculos ve ON c.vehiculo_id = ve.id
            WHERE v.id = :vid
        """)
        res = await db.execute(query, {"vid": viaje_id})
        v = res.fetchone()
        if v:
            return {
                "estado": v.estado, 
                "conductor": {
                    "nombre": v.nombre_conductor,
                    "placa": v.placa,
                    "modelo": v.modelo,
                    "color": v.color,
                    "telefono": v.telefono
                } if v.conductor_id else None
            }
        return {"error": "No encontrado"}
    except Exception as e: return {"error": str(e)}

@app.get("/viajes/pendientes")
async def ver_pendientes(db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT v.id, v.origen, v.destino, v.tarifa, v.estado, v.origen_lat, v.origen_lng, v.destino_lat, v.destino_lng, c.nom_apell
            FROM viajes v
            LEFT JOIN clientes c ON v.cliente_id = c.usuario_id
            WHERE v.estado='pendiente'
        """)
        res = await db.execute(query)
        return [{"id": v.id, "origen": v.origen, "destino": v.destino, "tarifa": v.tarifa, "estado": v.estado, "cliente": v.nom_apell, "origen_lat": v.origen_lat, "origen_lng": v.origen_lng, "destino_lat": v.destino_lat, "destino_lng": v.destino_lng} for v in res.fetchall()]
    except: return []

@app.post("/viajes/aceptar")
async def aceptar(d: AceptarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("UPDATE viajes SET conductor_id=:cid, estado='aceptado' WHERE id=:vid"), {"cid": d.conductor_id, "vid": d.viaje_id})
        return {"mensaje": "Viaje aceptado"}
    except Exception as e: return {"error": str(e)}

# --- CONDUCTORES CERCANOS ---
@app.get("/conductores/cercanos")
async def obtener_conductores_cercanos(lat: float, lng: float, radio_km: float = 5.0, db: AsyncSession = Depends(get_db)):
    try:
        query = text("""
            SELECT c.usuario_id, c.nom_apell, v.placa, v.modelo,
                   ST_X(c.ubicacion::geometry) as lng, 
                   ST_Y(c.ubicacion::geometry) as lat
            FROM conductores c
            JOIN vehiculos v ON c.vehiculo_id = v.id
            WHERE c.ubicacion IS NOT NULL AND c.activo = TRUE 
            AND ST_DWithin(c.ubicacion, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, :metros)
        """)
        res = await db.execute(query, {"lat": lat, "lng": lng, "metros": radio_km * 1000})
        return [{"id": c.usuario_id, "nombre": c.nom_apell, "placa": c.placa, "modelo": c.modelo, "lat": c.lat, "lng": c.lng} for c in res.fetchall()]
    except: return []

@app.post("/conductores/ubicacion")
async def actualizar_ubicacion(datos: UbicacionConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("UPDATE conductores SET ubicacion = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) WHERE usuario_id = :uid"), {"uid": datos.usuario_id, "lat": datos.latitud, "lng": datos.longitud})
        return {"mensaje": "Ubicación actualizada"}
    except Exception as e: return {"error": str(e)}

@app.post("/conductores/estado")
async def cambiar_estado(datos: EstadoConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("UPDATE conductores SET activo = :st WHERE usuario_id = :uid"), {"uid": datos.usuario_id, "st": datos.activo})
        return {"mensaje": "Estado actualizado"}
    except Exception as e: return {"error": str(e)}

# --- EXTRAS ---
@app.post("/contactos/agregar")
async def agregar_contacto(d: ContactoRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin(): await db.execute(text("INSERT INTO emergencia (usuario_id, nombre_contacto, numero_whatsapp) VALUES (:uid, :nom, :num)"), {"uid": d.usuario_id, "nom": d.nombre_contacto, "num": d.numero_whatsapp})
        return {"mensaje": "Guardado"}
    except: return {"error": "Error"}

@app.get("/contactos/listar/{uid}")
async def listar_contactos(uid: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("SELECT id, nombre_contacto, numero_whatsapp FROM emergencia WHERE usuario_id = :uid"), {"uid": uid})
    return [{"id": c.id, "nombre": c.nombre_contacto, "numero": c.numero_whatsapp} for c in res.fetchall()]

@app.put("/contactos/editar/{cid}")
async def editar_contacto(cid: int, d: ContactoEditRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin(): await db.execute(text("UPDATE emergencia SET nombre_contacto=:nom, numero_whatsapp=:num WHERE id=:id"), {"nom": d.nombre_contacto, "num": d.numero_whatsapp, "id": cid})
        return {"mensaje": "Editado"}
    except: return {"error": "Error"}

@app.delete("/contactos/eliminar/{cid}")
async def eliminar_contacto(cid: int, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin(): await db.execute(text("DELETE FROM emergencia WHERE id=:id"), {"id": cid})
        return {"mensaje": "Eliminado"}
    except: return {"error": "Error"}

@app.post("/sos/activar")
async def activar_sos(d: AlertaRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin(): await db.execute(text("INSERT INTO alertas (usuario_id, ubicacion, mensaje_extra) VALUES (:uid, :ubi, :msg)"), {"uid": d.usuario_id, "ubi": d.ubicacion, "msg": d.mensaje})
        return {"mensaje": "Alerta registrada"}
    except: return {"error": "Error"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
