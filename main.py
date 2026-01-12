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

# --- CONFIGURACIÓN DE BASE DE DATOS ---
# Usamos variables de entorno si existen, si no, los valores hardcodeados (para dev)
PROJECT_ID = "vjhggvxkhowlnbppuiuw" 
DB_PASSWORD = "XYZ*147258369*XYZ"
SUPABASE_USER = f"postgres.{PROJECT_ID}"
SUPABASE_HOST = "aws-1-sa-east-1.pooler.supabase.com" 
SUPABASE_PORT = "6543"
SUPABASE_DB   = "postgres"

# Construcción de la URL de conexión
encoded_pass = urllib.parse.quote_plus(DB_PASSWORD)
CLOUD_DATABASE_URL = f"postgresql+asyncpg://{SUPABASE_USER}:{encoded_pass}@{SUPABASE_HOST}:{SUPABASE_PORT}/{SUPABASE_DB}?prepared_statement_cache_size=0"

# Selección automática: Nube (Render) o Local
if os.getenv("DATABASE_URL"):
    # En Render, a veces la URL viene sin el driver asyncpg, lo corregimos si es necesario
    url_env = os.getenv("DATABASE_URL")
    if url_env and url_env.startswith("postgres://"):
        url_env = url_env.replace("postgres://", "postgresql+asyncpg://", 1)
    DATABASE_URL = url_env
else:
    DATABASE_URL = CLOUD_DATABASE_URL

# Inicialización del Motor (Engine) con manejo de errores
try:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False, # Pon True si quieres ver cada consulta SQL en la consola
        pool_pre_ping=True
    )
except Exception as e:
    print(f"FATAL: Error conectando a la Base de Datos: {e}")
    # No detenemos la app aquí para permitir que uvicorn arranque y muestre logs, 
    # pero las peticiones fallarán.

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# Diccionario de palabras para validación de seguridad
PALABRAS_CLAVE = [
    "SOL", "LUNA", "MAR", "RIO", "LUZ", "PAZ", "ORO", "AZUL", 
    "ROJO", "TIGRE", "LEON", "AGUA", "FUEGO", "AIRE", "JAZZ", 
    "ROCK", "MENTA", "COCO", "LIMA", "ALFA", "BETA", "GAMA", 
    "RISA", "VIDA", "ARBOL", "CIEGO", "LINDO", "PIANO"
]

# -----------------------------------------------------------------------------
# DEFINICIÓN DE MODELOS (TABLAS)
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
    # PostGIS Geometry para ubicación en tiempo real
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
    estado = Column(String, default='pendiente') # pendiente, aceptado, en_curso, finalizado, cancelado
    tarifa = Column(Float)
    
    # Coordenadas numéricas para facilidad del frontend
    origen_lat = Column(Float, nullable=True)
    origen_lng = Column(Float, nullable=True)
    destino_lat = Column(Float, nullable=True)
    destino_lng = Column(Float, nullable=True)
    
    # Geometrías PostGIS para cálculos espaciales
    origen_geom = Column(Geometry('POINT', srid=4326), nullable=True)
    destino_geom = Column(Geometry('POINT', srid=4326), nullable=True)
    
    # Seguridad
    clave_seguridad = Column(String, nullable=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    
    cliente_usuario = relationship("Usuario", foreign_keys=[cliente_id])
    conductor_usuario = relationship("Usuario", foreign_keys=[conductor_id])

# -----------------------------------------------------------------------------
# DTOs (Data Transfer Objects) - Esquemas Pydantic
# -----------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str

class ViajeRequest(BaseModel):
    usuario_id: int
    origen: str
    destino: str
    tarifa: float
    origen_lat: Optional[float] = None
    origen_lng: Optional[float] = None
    destino_lat: Optional[float] = None
    destino_lng: Optional[float] = None

class AceptarViajeRequest(BaseModel):
    viaje_id: int
    conductor_id: int

class UsuarioRegistroRequest(BaseModel):
    nombre: str
    email: str
    password: str
    role: str = "cliente"
    telefono: Optional[str] = None
    fecha_nacimiento: Optional[str] = None
    pais: Optional[str] = None
    ciudad: Optional[str] = None

class RegistroConductorRequest(BaseModel):
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
    usuario_id: int
    nombre_contacto: str
    numero_whatsapp: str

class ContactoEditRequest(BaseModel):
    nombre_contacto: str
    numero_whatsapp: str

class AlertaRequest(BaseModel):
    usuario_id: int
    ubicacion: str
    mensaje: str

class UbicacionConductorRequest(BaseModel):
    usuario_id: int
    latitud: float
    longitud: float

class EstadoConductorRequest(BaseModel):
    usuario_id: int
    activo: bool

class EstadoViajeRequest(BaseModel):
    viaje_id: int
    nuevo_estado: str

class CancelarViajeRequest(BaseModel):
    viaje_id: int
    motivo: str = "Cancelado por usuario/conductor"

class IniciarViajeRequest(BaseModel):
    viaje_id: int
    clave_ingresada: str

# -----------------------------------------------------------------------------
# INICIALIZACIÓN DE LA APP
# -----------------------------------------------------------------------------

app = FastAPI(title="Taxi App API", description="API REST para gestión de transporte urbano.")

# Configuración CORS: Permitir todo para desarrollo/tesis
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Panel Administrativo (sqladmin)
admin = Admin(app, engine, title="Taxi Admin")

# Registro de Vistas en Admin
admin.add_view(ModelView(Usuario))
admin.add_view(ModelView(Cliente))
admin.add_view(ModelView(Conductor))
admin.add_view(ModelView(Vehiculo))
admin.add_view(ModelView(Viaje))
admin.add_view(ModelView(Emergencia))
admin.add_view(ModelView(Alerta))

# Dependencia para obtener sesión de DB
async def get_db():
    async with async_session() as session:
        yield session

# -----------------------------------------------------------------------------
# ENDPOINTS
# -----------------------------------------------------------------------------

@app.get("/")
def leer_raiz():
    """Health check."""
    return {"mensaje": "API Taxi Service Running (vFinal)."}

@app.post("/login")
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        # Nota: En producción usar bcrypt.verify, aquí comparamos texto plano por simplicidad del prototipo
        res = await db.execute(text(f"SELECT * FROM usuarios WHERE email='{datos.email}' AND password_hash='{datos.password}'"))
        user = res.fetchone()
        
        if not user:
            return {"error": "Credenciales inválidas"}

        nombre_real = "Usuario"
        if user.role == 'cliente':
            res_cli = (await db.execute(text(f"SELECT nom_apell FROM clientes WHERE usuario_id={user.id}"))).fetchone()
            if res_cli: nombre_real = res_cli.nom_apell
        elif user.role == 'conductor':
            res_cond = (await db.execute(text(f"SELECT nom_apell FROM conductores WHERE usuario_id={user.id}"))).fetchone()
            if res_cond: nombre_real = res_cond.nom_apell

        return {"mensaje": "Login OK", "usuario": {"id": user.id, "nombre": nombre_real, "role": user.role}}
    except Exception as e:
        return {"error": f"Error interno: {str(e)}"}

@app.post("/registrar_usuario")
async def registrar_usuario(datos: UsuarioRegistroRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": datos.email})).scalar():
                return {"error": "El correo ya está registrado."}
            
            uid = (await db.execute(text("INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"), {"e": datos.email, "p": datos.password, "r": "cliente"})).scalar()
            
            try:
                f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date() if datos.fecha_nacimiento else None
                await db.execute(text("INSERT INTO clientes (usuario_id, nom_apell, pais, ciudad, telefono, fecha_nacimiento) VALUES (:u, :n, :p, :c, :t, :f)"), 
                {"u": uid, "n": datos.nombre, "p": datos.pais, "c": datos.ciudad, "t": datos.telefono, "f": f_nac})
            except: pass
        return {"mensaje": "Usuario registrado exitosamente", "id": uid}
    except Exception as e:
        return {"error": str(e)}

@app.post("/registrar_conductor")
async def registrar_conductor(datos: RegistroConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": datos.email})).scalar():
                return {"error": "Email ya registrado."}
            
            uid = (await db.execute(text("INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"), {"e": datos.email, "p": datos.password, "r": "conductor"})).scalar()
            vid = (await db.execute(text("INSERT INTO vehiculos (marca, modelo, placa, color, anio) VALUES (:ma, :mo, :pl, :co, :an) RETURNING id"), {"ma": datos.vehiculo_marca, "mo": datos.vehiculo_modelo, "pl": datos.vehiculo_placa, "co": datos.vehiculo_color, "an": datos.vehiculo_anio})).scalar()
            
            f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date() if datos.fecha_nacimiento else None
            
            await db.execute(text("INSERT INTO conductores (usuario_id, vehiculo_id, nom_apell, telefono, fecha_nacimiento, activo) VALUES (:u, :v, :n, :t, :f, FALSE)"), 
            {"u": uid, "v": vid, "n": datos.nombre, "t": datos.telefono, "f": f_nac})
            
        return {"mensaje": "Conductor registrado exitosamente", "id": uid}
    except Exception as e:
        return {"error": str(e)}

@app.post("/viajes/solicitar")
async def solicitar(v: ViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            # Generar Token de Seguridad
            clave_generada = random.choice(PALABRAS_CLAVE)

            # Convertir coordenadas a geometría PostGIS
            geo_ori = f"ST_GeomFromText('POINT({v.origen_lng} {v.origen_lat})', 4326)" if v.origen_lng else "NULL"
            geo_des = f"ST_GeomFromText('POINT({v.destino_lng} {v.destino_lat})', 4326)" if v.destino_lng else "NULL"
            
            query = text(f"""
                INSERT INTO viajes (
                    cliente_id, origen, destino, tarifa, estado, 
                    origen_lat, origen_lng, destino_lat, destino_lng,
                    origen_geom, destino_geom, clave_seguridad, fecha_creacion
                ) VALUES (
                    :cid, :ori, :des, :tar, 'pendiente', 
                    :olat, :olng, :dlat, :dlng,
                    {geo_ori}, {geo_des}, :clave, NOW()
                )
                RETURNING id
            """)
            res = await db.execute(query, {
                "cid": v.usuario_id, "ori": v.origen, "des": v.destino, "tar": v.tarifa, 
                "olat": v.origen_lat, "olng": v.origen_lng, "dlat": v.destino_lat, "dlng": v.destino_lng,
                "clave": clave_generada
            })
            vid = res.scalar()
        
        return {"mensaje": "Viaje solicitado", "id_viaje": vid, "clave": clave_generada}
    except Exception as e: return {"error": str(e)}

@app.get("/viajes/pendientes")
async def ver_pendientes(db: AsyncSession = Depends(get_db)):
    try:
        # Solo mostrar pendientes recientes (últimos 30 minutos)
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
        return [{
            "id": v.id, "origen": v.origen, "destino": v.destino, "tarifa": v.tarifa, 
            "estado": v.estado, "cliente": v.nom_apell or "Cliente", 
            "origen_lat": v.origen_lat, "origen_lng": v.origen_lng, 
            "destino_lat": v.destino_lat, "destino_lng": v.destino_lng,
            "creado_en": v.fecha_creacion.isoformat() if v.fecha_creacion else None
        } for v in res.fetchall()]
    except: return []

@app.post("/viajes/aceptar")
async def aceptar(d: AceptarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            # Verificar si sigue disponible
            estado = await db.execute(text("SELECT estado FROM viajes WHERE id=:vid"), {"vid": d.viaje_id})
            st = estado.scalar()
            
            if st != 'pendiente':
                return {"error": "El viaje ya no está disponible (fue tomado o cancelado)."}

            await db.execute(text("UPDATE viajes SET conductor_id=:cid, estado='aceptado' WHERE id=:vid"), {"cid": d.conductor_id, "vid": d.viaje_id})
        return {"mensaje": "Viaje aceptado"}
    except Exception as e: return {"error": str(e)}

@app.post("/viajes/validar_inicio")
async def validar_inicio_viaje(d: IniciarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        res = await db.execute(text("SELECT clave_seguridad FROM viajes WHERE id=:vid"), {"vid": d.viaje_id})
        clave_real = res.scalar()
        
        if not clave_real:
             return {"error": "Datos no encontrados", "exito": False}
             
        if d.clave_ingresada.upper().strip() == clave_real:
            async with db.begin():
                await db.execute(text("UPDATE viajes SET estado='en_curso' WHERE id=:vid"), {"vid": d.viaje_id})
            return {"mensaje": "Validación exitosa", "exito": True}
        else:
            return {"error": "Clave incorrecta", "exito": False}
    except Exception as e: return {"error": str(e), "exito": False}

@app.post("/viajes/actualizar_estado")
async def actualizar_estado_viaje(d: EstadoViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("UPDATE viajes SET estado=:st WHERE id=:vid"), {"st": d.nuevo_estado, "vid": d.viaje_id})
        return {"mensaje": f"Estado actualizado: {d.nuevo_estado}"}
    except Exception as e: return {"error": str(e)}

@app.post("/viajes/cancelar")
async def cancelar_viaje(d: CancelarViajeRequest, db: AsyncSession = Depends(get_db)):
    """Permite cancelar viajes en estado: pendiente, aceptado y en_curso (emergencia)."""
    try:
        async with db.begin():
            res = await db.execute(text("SELECT estado FROM viajes WHERE id=:vid"), {"vid": d.viaje_id})
            estado_actual = res.scalar()
            
            if not estado_actual:
                return {"error": "Viaje no encontrado"}
            
            # Idempotencia: Si ya está cancelado, retornar éxito
            if estado_actual == 'cancelado':
                 return {"mensaje": "El viaje ya estaba cancelado."}
            
            # Restricción lógica: No cancelar si ya finalizó (ya se cobró)
            if estado_actual == 'finalizado':
                 return {"error": "No se puede cancelar un viaje finalizado."}

            # Permitimos cancelar en 'pendiente', 'aceptado' y 'en_curso'
            await db.execute(text("UPDATE viajes SET estado='cancelado' WHERE id=:vid"), {"vid": d.viaje_id})
            
        return {"mensaje": "Viaje cancelado correctamente"}
    except Exception as e: 
        print(f"Error cancelando: {e}")
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
        res = await db.execute(query, {"vid": viaje_id})
        v = res.fetchone()
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

# --- SEGURIDAD Y CONTACTOS ---

@app.post("/contactos/agregar")
async def agregar_contacto(d: ContactoRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("INSERT INTO emergencia (usuario_id, nombre_contacto, numero_whatsapp) VALUES (:uid, :nom, :num)"), {"uid": d.usuario_id, "nom": d.nombre_contacto, "num": d.numero_whatsapp})
        return {"mensaje": "Contacto guardado"}
    except Exception as e: return {"error": str(e)}

@app.get("/contactos/listar/{uid}")
async def listar_contactos(uid: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("SELECT id, nombre_contacto, numero_whatsapp FROM emergencia WHERE usuario_id = :uid"), {"uid": uid})
    return [{"id": c.id, "nombre": c.nombre_contacto, "numero": c.numero_whatsapp} for c in res.fetchall()]

@app.put("/contactos/editar/{cid}")
async def editar_contacto(cid: int, datos: ContactoEditRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("UPDATE emergencia SET nombre_contacto=:nom, numero_whatsapp=:num WHERE id=:id"), {"nom": datos.nombre_contacto, "num": datos.numero_whatsapp, "id": cid})
        return {"mensaje": "Contacto actualizado"}
    except Exception as e: return {"error": str(e)}

@app.delete("/contactos/eliminar/{cid}")
async def eliminar_contacto(cid: int, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("DELETE FROM emergencia WHERE id=:id"), {"id": cid})
        return {"mensaje": "Contacto eliminado"}
    except Exception as e: return {"error": str(e)}

@app.post("/sos/activar")
async def activar_sos(d: AlertaRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("INSERT INTO alertas (usuario_id, ubicacion, mensaje_extra) VALUES (:uid, :ubi, :msg)"), {"uid": d.usuario_id, "ubi": d.ubicacion, "msg": d.mensaje})
        return {"mensaje": "Alerta registrada"}
    except Exception as e: return {"error": str(e)}

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
    except Exception as e: return []

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
