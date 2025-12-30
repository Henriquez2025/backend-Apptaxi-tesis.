# --- Importaciones ---
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from fastapi import FastAPI, Depends
from pydantic import BaseModel
import warnings
from typing import Optional, List
from datetime import datetime
import os
import urllib.parse 

# --- Importaciones de Admin y SQLAlchemy ---
from sqladmin import Admin, ModelView
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import Column, Integer, String, Float, ForeignKey, text, Date, DateTime
from sqlalchemy.sql import func

# ==========================================
# 1. CONFIGURACIÓN DE BASE DE DATOS
# ==========================================
PROJECT_ID = "vjhggvxkhowlnbppuiuw" 
DB_PASSWORD = "XYZ*147258369*XYZ"
SUPABASE_USER = f"postgres.{PROJECT_ID}"
SUPABASE_HOST = "aws-1-sa-east-1.pooler.supabase.com" 
SUPABASE_PORT = "6543"
SUPABASE_DB   = "postgres"

encoded_pass = urllib.parse.quote_plus(DB_PASSWORD)
CLOUD_DATABASE_URL = f"postgresql+asyncpg://{SUPABASE_USER}:{encoded_pass}@{SUPABASE_HOST}:{SUPABASE_PORT}/{SUPABASE_DB}?prepared_statement_cache_size=0"

if os.getenv("DATABASE_URL"):
    print(f"☁️ MODO NUBE: Conectando a {SUPABASE_HOST}...")
    DATABASE_URL = CLOUD_DATABASE_URL
else:
    print("💻 MODO LOCAL: Usando base de datos local")
    DATABASE_URL = "postgresql+asyncpg://postgres:1234@localhost:5432/taxi_app_db"

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# ==========================================
# 2. MODELOS DE BASE DE DATOS
# ==========================================

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    nombre = Column(String)
    email = Column(String, unique=True)
    password_hash = Column(String) 
    role = Column(String) 

class Alerta(Base):
    __tablename__ = "alertas"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    ubicacion = Column(String)
    mensaje_extra = Column(String)
    fecha = Column(DateTime(timezone=True), server_default=func.now())
    usuario = relationship("Usuario")

class ContactoEmergencia(Base):
    __tablename__ = "contactos_emergencia"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    nombre_contacto = Column(String)
    numero_whatsapp = Column(String)
    fecha_registro = Column(DateTime(timezone=True), server_default=func.now())
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
    cliente_usuario = relationship("Usuario", foreign_keys=[cliente_id])
    conductor_usuario = relationship("Usuario", foreign_keys=[conductor_id])

class Cliente(Base):
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id")) 
    pais = Column(String)
    ciudad = Column(String)
    telefono = Column(String)
    fecha_nacimiento = Column(Date)
    usuario = relationship("Usuario")

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
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"))
    telefono = Column(String)
    fecha_nacimiento = Column(Date)
    usuario = relationship("Usuario")
    vehiculo = relationship("Vehiculo")

# ==========================================
# 3. SCHEMAS PYDANTIC
# ==========================================
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
    usuario_id: int
    ubicacion: str
    mensaje: str

# ==========================================
# 4. APP & ADMIN
# ==========================================
app = FastAPI(title="Taxi App API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

admin = Admin(app, engine, title="Taxi Admin")

class UsuarioAdmin(ModelView, model=Usuario):
    name, name_plural, icon = "Usuario", "Usuarios", "fa-solid fa-users"
    column_list = [Usuario.id, Usuario.nombre, Usuario.email, Usuario.role]

class ClienteAdmin(ModelView, model=Cliente):
    name, name_plural, icon = "Cliente", "Clientes", "fa-solid fa-person"
    column_list = [Cliente.id, "usuario.nombre", Cliente.ciudad, Cliente.telefono]

class ConductorAdmin(ModelView, model=Conductor):
    name, name_plural, icon = "Conductor", "Conductores", "fa-solid fa-id-card"
    column_list = [Conductor.id, "usuario.nombre", "vehiculo.placa", Conductor.telefono]

class VehiculoAdmin(ModelView, model=Vehiculo):
    name, name_plural, icon = "Vehículo", "Vehículos", "fa-solid fa-car"
    column_list = [Vehiculo.id, Vehiculo.placa, Vehiculo.marca, Vehiculo.modelo]

class ViajeAdmin(ModelView, model=Viaje):
    name, name_plural, icon = "Viaje", "Viajes", "fa-solid fa-map-location-dot"
    column_list = [Viaje.id, Viaje.cliente_id, Viaje.origen, Viaje.destino, Viaje.estado]

class ContactoAdmin(ModelView, model=ContactoEmergencia):
    name, name_plural, icon = "Contacto SOS", "Contactos SOS", "fa-solid fa-address-book"
    column_list = [ContactoEmergencia.id, ContactoEmergencia.usuario_id, ContactoEmergencia.nombre_contacto, ContactoEmergencia.numero_whatsapp]

class AlertaAdmin(ModelView, model=Alerta):
    name, name_plural, icon = "ALERTA SOS", "ALERTAS SOS", "fa-solid fa-triangle-exclamation"
    column_list = [Alerta.id, "usuario.nombre", Alerta.ubicacion, Alerta.fecha, Alerta.mensaje_extra]
    column_labels = {"usuario.nombre": "Usuario en Peligro"}

admin.add_view(UsuarioAdmin); admin.add_view(ClienteAdmin); admin.add_view(ConductorAdmin)
admin.add_view(VehiculoAdmin); admin.add_view(ViajeAdmin); admin.add_view(ContactoAdmin); admin.add_view(AlertaAdmin)

async def get_db():
    async with async_session() as session: yield session

# ==========================================
# 5. ENDPOINTS
# ==========================================
@app.get("/")
def leer_raiz(): return {"mensaje": "API Taxi Funcionando (v5.0 - Gestión Contactos)."}

@app.post("/login")
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        res = await db.execute(text(f"SELECT * FROM usuarios WHERE email='{datos.email}' AND password_hash='{datos.password}'"))
        user = res.fetchone()
        return {"mensaje": "Login OK", "usuario": {"id": user.id, "nombre": user.nombre, "role": user.role}} if user else {"error": "Credenciales inválidas"}
    except Exception as e: return {"error": "Error interno"}

@app.post("/registrar_usuario")
async def registrar_usuario(datos: UsuarioRegistroRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": datos.email})).scalar(): return {"error": "El correo ya está registrado."}
            uid = (await db.execute(text("INSERT INTO usuarios (nombre, email, password_hash, role) VALUES (:n, :e, :p, :r) RETURNING id"), {"n": datos.nombre, "e": datos.email, "p": datos.password, "r": "cliente"})).scalar()
            try:
                f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date() if datos.fecha_nacimiento else None
                await db.execute(text("INSERT INTO clientes (usuario_id, pais, ciudad, telefono, fecha_nacimiento) VALUES (:u, :p, :c, :t, :f)"), {"u": uid, "p": datos.pais, "c": datos.ciudad, "t": datos.telefono, "f": f_nac})
            except: pass
        return {"mensaje": "Usuario registrado exitosamente", "id": uid}
    except Exception as e: return {"error": f"Error: {str(e)}"}

@app.post("/registrar_conductor")
async def registrar_conductor(datos: RegistroConductorRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": datos.email})).scalar(): return {"error": "Correo existe."}
            if (await db.execute(text("SELECT id FROM vehiculos WHERE placa = :p"), {"p": datos.vehiculo_placa})).scalar(): return {"error": "Placa existe."}
            uid = (await db.execute(text("INSERT INTO usuarios (nombre, email, password_hash, role) VALUES (:n, :e, :p, :r) RETURNING id"), {"n": datos.nombre, "e": datos.email, "p": datos.password, "r": "conductor"})).scalar()
            vid = (await db.execute(text("INSERT INTO vehiculos (marca, modelo, placa, color, anio) VALUES (:ma, :mo, :pl, :co, :an) RETURNING id"), {"ma": datos.vehiculo_marca, "mo": datos.vehiculo_modelo, "pl": datos.vehiculo_placa, "co": datos.vehiculo_color, "an": datos.vehiculo_anio})).scalar()
            f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date() if datos.fecha_nacimiento else None
            await db.execute(text("INSERT INTO conductores (usuario_id, vehiculo_id, telefono, fecha_nacimiento) VALUES (:u, :v, :t, :f)"), {"u": uid, "v": vid, "t": datos.telefono, "f": f_nac})
        return {"mensaje": "Conductor registrado", "id": uid}
    except Exception as e: return {"error": str(e)}

@app.post("/viajes/solicitar")
async def solicitar(v: ViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("INSERT INTO viajes (cliente_id, origen, destino, tarifa, estado, origen_lat, origen_lng, destino_lat, destino_lng) VALUES (:cid, :ori, :des, :tar, 'pendiente', :olat, :olng, :dlat, :dlng)"), {"cid": v.usuario_id, "ori": v.origen, "des": v.destino, "tar": v.tarifa, "olat": v.origen_lat, "olng": v.origen_lng, "dlat": v.destino_lat, "dlng": v.destino_lng})
        return {"mensaje": "Viaje solicitado"}
    except Exception as e: return {"error": str(e)}

@app.get("/viajes/pendientes")
async def ver_pendientes(db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("SELECT * FROM viajes WHERE estado='pendiente'"))
    return [{"id": v.id, "origen": v.origen, "destino": v.destino, "tarifa": v.tarifa} for v in res.fetchall()]

@app.post("/viajes/aceptar")
async def aceptar(d: AceptarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("UPDATE viajes SET conductor_id=:cid, estado='aceptado' WHERE id=:vid"), {"cid": d.conductor_id, "vid": d.viaje_id})
        return {"mensaje": "Viaje aceptado"}
    except Exception as e: return {"error": str(e)}

# --- CONTACTOS Y SOS ---
@app.post("/contactos/agregar")
async def agregar_contacto(d: ContactoRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("INSERT INTO contactos_emergencia (usuario_id, nombre_contacto, numero_whatsapp) VALUES (:uid, :nom, :num)"), {"uid": d.usuario_id, "nom": d.nombre_contacto, "num": d.numero_whatsapp})
        return {"mensaje": "Contacto guardado"}
    except Exception as e: return {"error": str(e)}

# EDITAR CONTACTO
@app.put("/contactos/editar/{contacto_id}")
async def editar_contacto(contacto_id: int, datos: ContactoEditRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("UPDATE contactos_emergencia SET nombre_contacto=:nom, numero_whatsapp=:num WHERE id=:id"), {"nom": datos.nombre_contacto, "num": datos.numero_whatsapp, "id": contacto_id})
        return {"mensaje": "Contacto actualizado"}
    except Exception as e: return {"error": str(e)}

# ELIMINAR CONTACTO
@app.delete("/contactos/eliminar/{contacto_id}")
async def eliminar_contacto(contacto_id: int, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("DELETE FROM contactos_emergencia WHERE id=:id"), {"id": contacto_id})
        return {"mensaje": "Contacto eliminado"}
    except Exception as e: return {"error": str(e)}

@app.get("/contactos/listar/{uid}")
async def listar_contactos(uid: int, db: AsyncSession = Depends(get_db)):
    # AHORA DEVUELVE EL ID TAMBIÉN
    res = await db.execute(text("SELECT id, nombre_contacto, numero_whatsapp FROM contactos_emergencia WHERE usuario_id = :uid"), {"uid": uid})
    return [{"id": c.id, "nombre": c.nombre_contacto, "numero": c.numero_whatsapp} for c in res.fetchall()]

@app.post("/sos/activar")
async def activar_sos(d: AlertaRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("INSERT INTO alertas (usuario_id, ubicacion, mensaje_extra) VALUES (:uid, :ubi, :msg)"), {"uid": d.usuario_id, "ubi": d.ubicacion, "msg": d.mensaje})
        return {"mensaje": "Alerta registrada"}
    except Exception as e: return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
