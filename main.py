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
# CONFIGURACIÓN DE INFRAESTRUCTURA DE BASE DE DATOS
# -----------------------------------------------------------------------------

# Credenciales de acceso al cluster de base de datos (Supabase)
PROJECT_ID = "vjhggvxkhowlnbppuiuw"
DB_PASSWORD = "XYZ*147258369*XYZ"
SUPABASE_USER = f"postgres.{PROJECT_ID}"
SUPABASE_HOST = "aws-1-sa-east-1.pooler.supabase.com"
SUPABASE_PORT = "6543"
SUPABASE_DB = "postgres"

# Codificación de credenciales para cadena de conexión segura
encoded_pass = urllib.parse.quote_plus(DB_PASSWORD)

# Construcción de DSN para SQLAlchemy con soporte AsyncPG y Pooler
CLOUD_DATABASE_URL = f"postgresql+asyncpg://{SUPABASE_USER}:{encoded_pass}@{SUPABASE_HOST}:{SUPABASE_PORT}/{SUPABASE_DB}?prepared_statement_cache_size=0"

# Selección de entorno de ejecución
if os.getenv("DATABASE_URL"):
    DATABASE_URL = CLOUD_DATABASE_URL
else:
    # Entorno local de desarrollo
    DATABASE_URL = "postgresql+asyncpg://postgres:1234@localhost:5432/taxi_app_db"

# Inicialización del motor de base de datos con verificación de estado
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True
)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# -----------------------------------------------------------------------------
# DEFINICIÓN DE MODELOS ORM
# -----------------------------------------------------------------------------

class Usuario(Base):
    """Entidad principal para autenticación y roles de sistema."""
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    password_hash = Column(String)
    role = Column(String)
    
    perfil_cliente = relationship("Cliente", back_populates="usuario", uselist=False)
    perfil_conductor = relationship("Conductor", back_populates="usuario", uselist=False)
    perfil_admin = relationship("Administrador", back_populates="usuario", uselist=False)

class Cliente(Base):
    """Información de perfil para usuarios tipo pasajero."""
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
    """Registro de unidades de transporte."""
    __tablename__ = "vehiculos"
    id = Column(Integer, primary_key=True)
    marca = Column(String)
    modelo = Column(String)
    placa = Column(String, unique=True)
    color = Column(String, nullable=True)
    anio = Column(String, nullable=True)

class Conductor(Base):
    """Perfil operativo de conductor y estado en tiempo real."""
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
    """Perfil para gestión administrativa del sistema."""
    __tablename__ = "administradores"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    nom_apell = Column(String)
    cargo = Column(String)
    telefono = Column(String)

    usuario = relationship("Usuario", back_populates="perfil_admin")

class Emergencia(Base):
    """Agenda de contactos de emergencia por usuario."""
    __tablename__ = "emergencia"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    nombre_contacto = Column(String)
    numero_whatsapp = Column(String)
    fecha_registro = Column(DateTime(timezone=True), server_default=func.now())
    
    usuario = relationship("Usuario")

class Alerta(Base):
    """Registro de auditoría para eventos de seguridad."""
    __tablename__ = "alertas"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    ubicacion = Column(String)
    mensaje_extra = Column(String)
    fecha = Column(DateTime(timezone=True), server_default=func.now())
    
    usuario = relationship("Usuario")

class Viaje(Base):
    """Registro transaccional de servicios de transporte."""
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
# ESQUEMAS DE TRANSFERENCIA DE DATOS (DTOs)
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
# INICIALIZACIÓN DE LA APLICACIÓN Y PANEL ADMINISTRATIVO
# -----------------------------------------------------------------------------

app = FastAPI(title="Taxi App API", description="API REST para gestión de transporte urbano.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Configuración de vistas para SQLAdmin
admin = Admin(app, engine, title="Taxi Admin")

class UsuarioAdmin(ModelView, model=Usuario):
    name, name_plural, icon = "Usuario", "Usuarios", "fa-solid fa-user-lock"
    column_list = [Usuario.id, Usuario.email, Usuario.role]

class ClienteAdmin(ModelView, model=Cliente):
    name, name_plural, icon = "Cliente", "Clientes", "fa-solid fa-person"
    column_list = [Cliente.id_cliente, Cliente.nom_apell, Cliente.ciudad, Cliente.telefono]

class ConductorAdmin(ModelView, model=Conductor):
    name, name_plural, icon = "Conductor", "Conductores", "fa-solid fa-id-card"
    column_list = [Conductor.id_conductor, Conductor.nom_apell, "vehiculo.placa", Conductor.activo, Conductor.telefono]

class AdministradorAdmin(ModelView, model=Administrador):
    name, name_plural, icon = "Admin", "Administradores", "fa-solid fa-user-tie"
    column_list = [Administrador.nom_apell, Administrador.cargo, Administrador.telefono]

class VehiculoAdmin(ModelView, model=Vehiculo):
    name, name_plural, icon = "Vehículo", "Vehículos", "fa-solid fa-car"
    column_list = [Vehiculo.id, Vehiculo.placa, Vehiculo.marca, Vehiculo.modelo]

class ViajeAdmin(ModelView, model=Viaje):
    name, name_plural, icon = "Viaje", "Viajes", "fa-solid fa-map-location-dot"
    column_list = [Viaje.id, Viaje.cliente_id, Viaje.origen, Viaje.destino, Viaje.tarifa, Viaje.estado]

class EmergenciaAdmin(ModelView, model=Emergencia):
    name, name_plural, icon = "Contacto SOS", "Contactos SOS", "fa-solid fa-address-book"
    column_list = [Emergencia.id, Emergencia.usuario_id, Emergencia.nombre_contacto, Emergencia.numero_whatsapp]

class AlertaAdmin(ModelView, model=Alerta):
    name, name_plural, icon = "ALERTA SOS", "ALERTAS SOS", "fa-solid fa-triangle-exclamation"
    column_list = [Alerta.id, "usuario.email", Alerta.ubicacion, Alerta.fecha]

admin.add_view(UsuarioAdmin); admin.add_view(ClienteAdmin); admin.add_view(ConductorAdmin); admin.add_view(AdministradorAdmin)
admin.add_view(VehiculoAdmin); admin.add_view(ViajeAdmin); admin.add_view(EmergenciaAdmin); admin.add_view(AlertaAdmin)

# Dependencia para inyección de sesión de BD
async def get_db():
    async with async_session() as session: yield session

# -----------------------------------------------------------------------------
# CONTROLADORES DE API (ENDPOINTS)
# -----------------------------------------------------------------------------

@app.get("/")
def leer_raiz(): 
    """Verificación de estado del servicio."""
    return {"mensaje": "API Taxi Funcionando (v11.0 - IDs + Estado Activo)."}

@app.post("/login")
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Autentica usuario y recupera datos de perfil según rol."""
    try:
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
        elif user.role == 'admin':
            res_adm = (await db.execute(text(f"SELECT nom_apell FROM administradores WHERE usuario_id={user.id}"))).fetchone()
            if res_adm: nombre_real = res_adm.nom_apell

        return {"mensaje": "Login OK", "usuario": {"id": user.id, "nombre": nombre_real, "role": user.role}}
    except Exception as e: 
        print(f"Error Login: {e}")
        return {"error": "Error interno"}

@app.post("/registrar_usuario")
async def registrar_usuario(datos: UsuarioRegistroRequest, db: AsyncSession = Depends(get_db)):
    """Registra un nuevo usuario con perfil de cliente."""
    print(f"--> Registrando Pasajero: {datos.nombre}")
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
    except Exception as e: return {"error": f"Error: {str(e)}"}

@app.post("/registrar_conductor")
async def registrar_conductor(datos: RegistroConductorRequest, db: AsyncSession = Depends(get_db)):
    """Registra conductor, vehículo y vinculación de perfiles."""
    print(f"--> Registrando Conductor: {datos.nombre}")
    try:
        async with db.begin():
            if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": datos.email})).scalar(): return {"error": "Correo existe."}
            if (await db.execute(text("SELECT id FROM vehiculos WHERE placa = :p"), {"p": datos.vehiculo_placa})).scalar(): return {"error": "Placa existe."}
            
            uid = (await db.execute(text("INSERT INTO usuarios (email, password_hash, role) VALUES (:e, :p, :r) RETURNING id"), {"e": datos.email, "p": datos.password, "r": "conductor"})).scalar()
            vid = (await db.execute(text("INSERT INTO vehiculos (marca, modelo, placa, color, anio) VALUES (:ma, :mo, :pl, :co, :an) RETURNING id"), {"ma": datos.vehiculo_marca, "mo": datos.vehiculo_modelo, "pl": datos.vehiculo_placa, "co": datos.vehiculo_color, "an": datos.vehiculo_anio})).scalar()
            f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date() if datos.fecha_nacimiento else None
            
            await db.execute(text("INSERT INTO conductores (usuario_id, vehiculo_id, nom_apell, telefono, fecha_nacimiento, activo) VALUES (:u, :v, :n, :t, :f, FALSE)"), 
            {"u": uid, "v": vid, "n": datos.nombre, "t": datos.telefono, "f": f_nac})
            
            # Creación automática de perfil cliente para el conductor
            try:
                await db.execute(text("INSERT INTO clientes (usuario_id, nom_apell, pais, ciudad, telefono, fecha_nacimiento) VALUES (:u, :n, :p, :c, :t, :f)"), 
                {"u": uid, "n": datos.nombre, "p": "Ecuador", "c": "Santa Elena", "t": datos.telefono, "f": f_nac})
            except: pass

        return {"mensaje": "Conductor registrado", "id": uid}
    except Exception as e: return {"error": str(e)}

@app.post("/viajes/solicitar")
async def solicitar(v: ViajeRequest, db: AsyncSession = Depends(get_db)):
    """Crea una solicitud de viaje con coordenadas GPS (Manejo robusto WKT)."""
    try:
        async with db.begin():
            # ESTRATEGIA ROBUSTA: Usar WKT (Well-Known Text) para geometría
            # Construimos el string 'POINT(lng lat)' en Python para evitar errores de casting en SQL
            
            wkt_origen = None
            if v.origen_lng is not None and v.origen_lat is not None:
                wkt_origen = f"POINT({v.origen_lng} {v.origen_lat})"
            
            wkt_destino = None
            if v.destino_lng is not None and v.destino_lat is not None:
                wkt_destino = f"POINT({v.destino_lng} {v.destino_lat})"

            # Usamos ST_GeomFromText que acepta el string creado arriba o NULL
            query = text("""
                INSERT INTO viajes (
                    cliente_id, origen, destino, tarifa, estado, 
                    origen_lat, origen_lng, destino_lat, destino_lng,
                    origen_geom, destino_geom
                ) VALUES (
                    :cid, :ori, :des, :tar, 'pendiente', 
                    :olat, :olng, :dlat, :dlng,
                    ST_GeomFromText(:wkt_ori, 4326),
                    ST_GeomFromText(:wkt_des, 4326)
                )
            """)
            
            await db.execute(query, {
                "cid": v.usuario_id, 
                "ori": v.origen, 
                "des": v.destino, 
                "tar": v.tarifa, 
                "olat": v.origen_lat, 
                "olng": v.origen_lng, 
                "dlat": v.destino_lat, 
                "dlng": v.destino_lng,
                "wkt_ori": wkt_origen, # Pasamos el string o None
                "wkt_des": wkt_destino
            })
        return {"mensaje": "Viaje solicitado"}
    except Exception as e:
        print(f"Error detallado solicitando viaje: {e}")
        # Retornamos el error para que la App sepa qué pasó
        return {"error": f"Error base de datos: {str(e)}"}
@app.get("/viajes/pendientes")
async def ver_pendientes(db: AsyncSession = Depends(get_db)):
    """Lista viajes disponibles para conductores."""
    res = await db.execute(text("SELECT * FROM viajes WHERE estado='pendiente'"))
    return [{"id": v.id, "origen": v.origen, "destino": v.destino, "tarifa": v.tarifa, "estado": v.estado, "origen_lat": v.origen_lat, "origen_lng": v.origen_lng} for v in res.fetchall()]

@app.post("/viajes/aceptar")
async def aceptar(d: AceptarViajeRequest, db: AsyncSession = Depends(get_db)):
    """Asigna un conductor a un viaje pendiente."""
    try:
        async with db.begin():
            await db.execute(text("UPDATE viajes SET conductor_id=:cid, estado='aceptado' WHERE id=:vid"), {"cid": d.conductor_id, "vid": d.viaje_id})
        return {"mensaje": "Viaje aceptado"}
    except Exception as e: return {"error": str(e)}

@app.post("/contactos/agregar")
async def agregar_contacto(d: ContactoRequest, db: AsyncSession = Depends(get_db)):
    """Agrega un nuevo contacto de confianza."""
    try:
        async with db.begin():
            await db.execute(text("INSERT INTO emergencia (usuario_id, nombre_contacto, numero_whatsapp) VALUES (:uid, :nom, :num)"), {"uid": d.usuario_id, "nom": d.nombre_contacto, "num": d.numero_whatsapp})
        return {"mensaje": "Contacto guardado"}
    except Exception as e: return {"error": str(e)}

@app.get("/contactos/listar/{uid}")
async def listar_contactos(uid: int, db: AsyncSession = Depends(get_db)):
    """Obtiene agenda de contactos de un usuario."""
    res = await db.execute(text("SELECT id, nombre_contacto, numero_whatsapp FROM emergencia WHERE usuario_id = :uid"), {"uid": uid})
    return [{"id": c.id, "nombre": c.nombre_contacto, "numero": c.numero_whatsapp} for c in res.fetchall()]

@app.put("/contactos/editar/{cid}")
async def editar_contacto(cid: int, datos: ContactoEditRequest, db: AsyncSession = Depends(get_db)):
    """Modifica datos de un contacto existente."""
    try:
        async with db.begin():
            await db.execute(text("UPDATE emergencia SET nombre_contacto=:nom, numero_whatsapp=:num WHERE id=:id"), {"nom": datos.nombre_contacto, "num": datos.numero_whatsapp, "id": cid})
        return {"mensaje": "Contacto actualizado"}
    except Exception as e: return {"error": str(e)}

@app.delete("/contactos/eliminar/{cid}")
async def eliminar_contacto(cid: int, db: AsyncSession = Depends(get_db)):
    """Elimina un contacto de la agenda."""
    try:
        async with db.begin():
            await db.execute(text("DELETE FROM emergencia WHERE id=:id"), {"id": cid})
        return {"mensaje": "Contacto eliminado"}
    except Exception as e: return {"error": str(e)}

@app.post("/sos/activar")
async def activar_sos(d: AlertaRequest, db: AsyncSession = Depends(get_db)):
    """Registra un evento de pánico en la bitácora."""
    try:
        async with db.begin():
            await db.execute(text("INSERT INTO alertas (usuario_id, ubicacion, mensaje_extra) VALUES (:uid, :ubi, :msg)"), {"uid": d.usuario_id, "ubi": d.ubicacion, "msg": d.mensaje})
        return {"mensaje": "Alerta registrada"}
    except Exception as e: return {"error": str(e)}

@app.post("/conductores/ubicacion")
async def actualizar_ubicacion(datos: UbicacionConductorRequest, db: AsyncSession = Depends(get_db)):
    """Actualiza la ubicación GPS del conductor en tiempo real."""
    try:
        async with db.begin():
            await db.execute(text("UPDATE conductores SET ubicacion = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) WHERE usuario_id = :uid"), {"uid": datos.usuario_id, "lat": datos.latitud, "lng": datos.longitud})
        return {"mensaje": "Ubicación actualizada"}
    except Exception as e: return {"error": str(e)}

@app.post("/conductores/estado")
async def cambiar_estado(datos: EstadoConductorRequest, db: AsyncSession = Depends(get_db)):
    """Modifica el estado operativo del conductor (Online/Offline)."""
    try:
        async with db.begin():
            await db.execute(text("UPDATE conductores SET activo = :st WHERE usuario_id = :uid"), {"uid": datos.usuario_id, "st": datos.activo})
        return {"mensaje": "Estado actualizado"}
    except Exception as e: return {"error": str(e)}

@app.get("/conductores/cercanos")
async def obtener_conductores_cercanos(lat: float, lng: float, radio_km: float = 2.0, db: AsyncSession = Depends(get_db)):
    """Busca conductores activos dentro de un radio geográfico."""
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





