import os
import urllib.parse
import random
from datetime import date, datetime, timedelta
from typing import Optional, List

import uvicorn
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, ForeignKey, text, Date, DateTime, Boolean
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func
from sqladmin import Admin, ModelView
from geoalchemy2 import Geometry

# --- CONFIGURACIÓN DE INFRAESTRUCTURA DB ---
# NOTA: En producción (Render), es mejor usar variables de entorno para PROJECT_ID y DB_PASSWORD
# pero para tu tesis, dejarlas aquí está bien si el repo es privado.

PROJECT_ID = "vjhggvxkhowlnbppuiuw" 
# DB_PASSWORD: Se recomienda no subir contraseñas reales a GitHub público.
# Si Render tiene problemas, verifica que esta contraseña sea la correcta de Supabase.
DB_PASSWORD = "XYZ*147258369*XYZ" 

# Configuración Connection Pooler (Puerto 6543 - IPv4)
SUPABASE_USER = f"postgres.{PROJECT_ID}"
SUPABASE_HOST = "aws-0-sa-east-1.pooler.supabase.com" # Ajustado a aws-0 que es común, verifica si es aws-1 en tu panel
SUPABASE_PORT = "6543" 
SUPABASE_DB   = "postgres"

encoded_pass = urllib.parse.quote_plus(DB_PASSWORD)

# URL Base para Supabase con Pooler
CLOUD_DATABASE_URL = f"postgresql+asyncpg://{SUPABASE_USER}:{encoded_pass}@{SUPABASE_HOST}:{SUPABASE_PORT}/{SUPABASE_DB}?ssl=require"

# Selección de entorno Inteligente
# Si Render provee DATABASE_URL, la usamos (ajustando el prefijo si es necesario)
# Si no, usamos la CLOUD_DATABASE_URL construida manualmente.
if os.getenv("DATABASE_URL"):
    url_env = os.getenv("DATABASE_URL")
    if url_env.startswith("postgres://"):
        url_env = url_env.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url_env.startswith("postgresql://"):
        url_env = url_env.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    DATABASE_URL = url_env
else:
    DATABASE_URL = CLOUD_DATABASE_URL

print(f"INFO: Conectando a DB: {DATABASE_URL.split('@')[-1]}") # Log seguro (sin password)

# Inicialización del Motor SQL
engine = None
try:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "jit": "off",
                "statement_cache_size": "0" # CRÍTICO PARA SUPABASE POOLER (Transaction Mode)
            }
        }
    )
except Exception as e:
    print(f"FATAL: Error inicializando engine DB: {e}")

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

PALABRAS_CLAVE = ["SOL", "LUNA", "MAR", "RIO", "LUZ", "PAZ", "ORO", "AZUL", "ROJO", "TIGRE", "LEON", "AGUA", "FUEGO", "AIRE", "JAZZ", "ROCK", "MENTA", "COCO", "LIMA"]

# -----------------------------------------------------------------------------
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

class EstadoViajeRequest(BaseModel):
    viaje_id: int; nuevo_estado: str

class CancelarViajeRequest(BaseModel):
    viaje_id: int; motivo: str = "Cancelado por usuario/conductor"

class IniciarViajeRequest(BaseModel):
    viaje_id: int; clave_ingresada: str

# -----------------------------------------------------------------------------
# CONFIGURACIÓN APP & ADMIN
# -----------------------------------------------------------------------------
app = FastAPI(title="Taxi App API", description="API REST para Tesis")

# CORS: Permitir acceso desde cualquier origen (importante para la app móvil)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if engine:
    try:
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
    except Exception as e:
        print(f"WARN: Error configurando Admin: {e}")

async def get_db():
    if not engine: raise HTTPException(status_code=500, detail="Error DB: Engine no inicializado")
    async with async_session() as session: yield session

# -----------------------------------------------------------------------------
# ENDPOINTS API
# -----------------------------------------------------------------------------
@app.get("/")
def leer_raiz(): 
    return {"mensaje": "API Taxi Running.", "estado": "OK"}

@app.post("/login")
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        res = await db.execute(text("SELECT id, email, password_hash, role FROM usuarios WHERE email = :email"), {"email": datos.email})
        user = res.fetchone()
        
        if not user: return {"error": "Usuario no encontrado"}
        if user.password_hash != datos.password: return {"error": "Contraseña incorrecta"}

        nombre_real = "Usuario"
        try:
            if user.role == 'cliente':
                res_cli = (await db.execute(text("SELECT nom_apell FROM clientes WHERE usuario_id = :uid"), {"uid": user.id})).fetchone()
                if res_cli: nombre_real = res_cli.nom_apell
            elif user.role == 'conductor':
                res_cond = (await db.execute(text("SELECT nom_apell FROM conductores WHERE usuario_id = :uid"), {"uid": user.id})).fetchone()
                if res_cond: nombre_real = res_cond.nom_apell
        except Exception: pass

        return {"mensaje": "Login OK", "usuario": {"id": user.id, "nombre": nombre_real, "role": user.role}}
    except Exception as e:
        return {"error": f"Error interno: {str(e)}"}

@app.post("/registrar_usuario")
async def registrar_usuario(datos: UsuarioRegistroRequest, db: AsyncSession = Depends(get_db)):
    try:
        if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": datos.email})).scalar(): return {"error": "Email existe."}
        
        uid = (await db.execute(text("INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"), {"e": datos.email, "p": datos.password, "r": "cliente"})).scalar()
        try:
            f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date() if datos.fecha_nacimiento else None
            await db.execute(text("INSERT INTO clientes (usuario_id, nom_apell, pais, ciudad, telefono, fecha_nacimiento) VALUES (:u, :n, :p, :c, :t, :f)"), 
            {"u": uid, "n": datos.nombre, "p": datos.pais, "c": datos.ciudad, "t": datos.telefono, "f": f_nac})
        except: pass
        
        await db.commit()
        return {"mensaje": "Registrado", "id": uid}
    except Exception as e: 
        await db.rollback()
        return {"error": str(e)}

@app.post("/registrar_conductor")
async def registrar_conductor(datos: RegistroConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": datos.email})).scalar(): return {"error": "Email existe."}
        
        uid = (await db.execute(text("INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"), {"e": datos.email, "p": datos.password, "r": "conductor"})).scalar()
        vid = (await db.execute(text("INSERT INTO vehiculos (marca, modelo, placa, color, anio) VALUES (:ma, :mo, :pl, :co, :an) RETURNING id"), {"ma": datos.vehiculo_marca, "mo": datos.vehiculo_modelo, "pl": datos.vehiculo_placa, "co": datos.vehiculo_color, "an": datos.vehiculo_anio})).scalar()
        
        f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date() if datos.fecha_nacimiento else None
        await db.execute(text("INSERT INTO conductores (usuario_id, vehiculo_id, nom_apell, telefono, fecha_nacimiento, activo) VALUES (:u, :v, :n, :t, :f, FALSE)"), {"u": uid, "v": vid, "n": datos.nombre, "t": datos.telefono, "f": f_nac})
        
        await db.commit()
        return {"mensaje": "Conductor registrado", "id": uid}
    except Exception as e: 
        await db.rollback()
        return {"error": str(e)}

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

@app.post("/conductores/ubicacion")
async def actualizar_ubicacion(datos: UbicacionConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("UPDATE conductores SET ubicacion = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) WHERE usuario_id = :uid"), {"uid": datos.usuario_id, "lat": datos.latitud, "lng": datos.longitud})
        await db.commit()
        return {"mensaje": "Ubicación OK"}
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

# -----------------------------------------------------------------------------
# ARRANQUE DEL SERVIDOR (IMPORTANTE PARA RENDER)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Render asigna el puerto en la variable de entorno 'PORT'
    port = int(os.getenv("PORT", 8000))
    # 'main:app' asume que este archivo se llama main.py
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)


