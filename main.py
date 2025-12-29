# --- Importaciones ---
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from fastapi import FastAPI, Depends
from pydantic import BaseModel
import warnings
from typing import Optional, List
from datetime import datetime
import os
import urllib.parse # Para codificar la contraseña correctamente

# --- Importaciones de Admin y SQLAlchemy ---
from sqladmin import Admin, ModelView
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import Column, Integer, String, Float, ForeignKey, text, Date

# ==========================================
# 1. CONFIGURACIÓN DE BASE DE DATOS (BLINDADA)
# ==========================================

# A. Credenciales Maestras de Supabase (Hardcoded para evitar errores de config)
# Estas son las credenciales EXACTAS para el Connection Pooler (IPv4 compatible con Render)
SUPABASE_USER = "postgres.vjhggvxkhowlnbppuiuw"
SUPABASE_PASS = "XYZ*147258369*XYZ"
SUPABASE_HOST = "aws-0-sa-east-1.pooler.supabase.com"
SUPABASE_PORT = "6543"
SUPABASE_DB   = "postgres"

# B. Codificamos la contraseña (los * pueden dar problemas si no se escapan)
encoded_pass = urllib.parse.quote_plus(SUPABASE_PASS)

# C. Construimos la URL de Conexión Definitiva
CLOUD_DATABASE_URL = f"postgresql+asyncpg://{SUPABASE_USER}:{encoded_pass}@{SUPABASE_HOST}:{SUPABASE_PORT}/{SUPABASE_DB}"

# D. Lógica de Selección de Entorno
# Si estamos en Render (existe la variable DATABASE_URL), ignoramos su contenido y usamos nuestra URL Maestra.
if os.getenv("DATABASE_URL"):
    print("☁️ ENTORNO NUBE DETECTADO: Usando conexión directa a Supabase Pooler (6543)")
    DATABASE_URL = CLOUD_DATABASE_URL
else:
    print("💻 ENTORNO LOCAL DETECTADO: Usando base de datos local")
    DATABASE_URL = "postgresql+asyncpg://postgres:1234@localhost:5432/taxi_app_db"

# E. Diagnóstico
print(f"🚀 CONECTANDO A HOST: {DATABASE_URL.split('@')[-1]}") 

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True, # Mantiene viva la conexión
)

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

# ==========================================
# 4. APP & ADMIN
# ==========================================
app = FastAPI(title="Taxi App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

admin = Admin(app, engine, title="Taxi Admin")

class UsuarioAdmin(ModelView, model=Usuario):
    name, name_plural, icon = "Usuario", "Usuarios", "fa-solid fa-users"
    column_list = [Usuario.id, Usuario.nombre, Usuario.email, Usuario.role]

class ClienteAdmin(ModelView, model=Cliente):
    name, name_plural, icon = "Cliente", "Clientes", "fa-solid fa-person"
    column_list = [Cliente.id, "usuario.nombre", Cliente.ciudad, Cliente.telefono]
    column_labels = {"usuario.nombre": "Nombre"}

class ConductorAdmin(ModelView, model=Conductor):
    name, name_plural, icon = "Conductor", "Conductores", "fa-solid fa-id-card"
    column_list = [Conductor.id, "usuario.nombre", "vehiculo.placa", Conductor.telefono]
    column_labels = {"usuario.nombre": "Chofer", "vehiculo.placa": "Placa"}

class VehiculoAdmin(ModelView, model=Vehiculo):
    name, name_plural, icon = "Vehículo", "Vehículos", "fa-solid fa-car"
    column_list = [Vehiculo.id, Vehiculo.placa, Vehiculo.marca, Vehiculo.modelo]

class ViajeAdmin(ModelView, model=Viaje):
    name, name_plural, icon = "Viaje", "Viajes", "fa-solid fa-map-location-dot"
    column_list = [Viaje.id, Viaje.cliente_id, Viaje.origen, Viaje.destino, Viaje.tarifa, Viaje.estado]

admin.add_view(UsuarioAdmin); admin.add_view(ClienteAdmin); admin.add_view(ConductorAdmin)
admin.add_view(VehiculoAdmin); admin.add_view(ViajeAdmin)

async def get_db():
    async with async_session() as session:
        yield session

# ==========================================
# 5. ENDPOINTS
# ==========================================

@app.get("/")
def leer_raiz():
    return {"mensaje": "API Taxi Funcionando (v3.0 - Conexión Blindada)."}

@app.post("/login")
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        # Validar password_hash
        query = text(f"SELECT * FROM usuarios WHERE email='{datos.email}' AND password_hash='{datos.password}'")
        result = await db.execute(query)
        user = result.fetchone()
        if user:
            return {"mensaje": "Login OK", "usuario": {"id": user.id, "nombre": user.nombre, "role": user.role}}
        else:
            return {"error": "Credenciales inválidas"}
    except Exception as e:
        print(f"Error Login: {e}")
        return {"error": "Error interno del servidor (BD)"}

@app.post("/registrar_usuario")
async def registrar_usuario(datos: UsuarioRegistroRequest, db: AsyncSession = Depends(get_db)):
    print(f"--> Registrando Pasajero: {datos.nombre}")
    try:
        async with db.begin():
            # Verificar si existe correo
            if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": datos.email})).scalar():
                return {"error": "El correo ya está registrado."}

            # Insertar Usuario
            uid = (await db.execute(text("INSERT INTO usuarios (nombre, email, password_hash, role) VALUES (:n, :e, :p, :r) RETURNING id"), {"n": datos.nombre, "e": datos.email, "p": datos.password, "r": "cliente"})).scalar()
            
            # Insertar Cliente (OJO: Manejo de errores específico aquí)
            try:
                # Verificamos que la fecha venga bien, si no, NULL
                f_nac = None
                if datos.fecha_nacimiento:
                    f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date()

                await db.execute(text("INSERT INTO clientes (usuario_id, pais, ciudad, telefono, fecha_nacimiento) VALUES (:u, :p, :c, :t, :f)"), 
                {"u": uid, "p": datos.pais, "c": datos.ciudad, "t": datos.telefono, "f": f_nac})
            except Exception as e_cli:
                print(f"Nota: Detalle cliente falló, pero usuario creado. Causa: {e_cli}")

        return {"mensaje": "Usuario registrado exitosamente", "id": uid}
    except Exception as e:
        print(f"Error CRITICO registrando usuario: {e}")
        return {"error": f"Error al registrar: {str(e)}"}

@app.post("/registrar_conductor")
async def registrar_conductor(datos: RegistroConductorRequest, db: AsyncSession = Depends(get_db)):
    print(f"--> Registrando Conductor: {datos.nombre}")
    try:
        async with db.begin():
            if (await db.execute(text("SELECT id FROM usuarios WHERE email = :e"), {"e": datos.email})).scalar(): return {"error": "El correo ya existe."}
            if (await db.execute(text("SELECT id FROM vehiculos WHERE placa = :p"), {"p": datos.vehiculo_placa})).scalar(): return {"error": "Placa registrada."}

            uid = (await db.execute(text("INSERT INTO usuarios (nombre, email, password_hash, role) VALUES (:n, :e, :p, :r) RETURNING id"), {"n": datos.nombre, "e": datos.email, "p": datos.password, "r": "conductor"})).scalar()
            vid = (await db.execute(text("INSERT INTO vehiculos (marca, modelo, placa, color, anio) VALUES (:ma, :mo, :pl, :co, :an) RETURNING id"), {"ma": datos.vehiculo_marca, "mo": datos.vehiculo_modelo, "pl": datos.vehiculo_placa, "co": datos.vehiculo_color, "an": datos.vehiculo_anio})).scalar()
            
            # Fecha Nacimiento
            f_nac = None
            if datos.fecha_nacimiento:
                 f_nac = datetime.strptime(datos.fecha_nacimiento, "%Y-%m-%d").date()

            await db.execute(text("INSERT INTO conductores (usuario_id, vehiculo_id, telefono, fecha_nacimiento) VALUES (:u, :v, :t, :f)"), 
            {"u": uid, "v": vid, "t": datos.telefono, "f": f_nac})
            
        return {"mensaje": "Conductor registrado exitosamente", "id": uid}
    except Exception as e:
        print(f"Error registrando conductor: {e}")
        return {"error": f"Error al registrar: {str(e)}"}

@app.post("/viajes/solicitar")
async def solicitar(v: ViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("INSERT INTO viajes (cliente_id, origen, destino, tarifa, estado, origen_lat, origen_lng, destino_lat, destino_lng) VALUES (:cid, :ori, :des, :tar, 'pendiente', :olat, :olng, :dlat, :dlng)"), 
            {"cid": v.usuario_id, "ori": v.origen, "des": v.destino, "tar": v.tarifa, "olat": v.origen_lat, "olng": v.origen_lng, "dlat": v.destino_lat, "dlng": v.destino_lng})
        return {"mensaje": "Viaje solicitado"}
    except Exception as e: return {"error": str(e)}

@app.get("/viajes/pendientes")
async def ver_pendientes(db: AsyncSession = Depends(get_db)):
    query = text("SELECT * FROM viajes WHERE estado='pendiente'")
    result = await db.execute(query)
    viajes = result.fetchall()
    lista = []
    for v in viajes:
        lista.append({"id": v.id, "origen": v.origen, "destino": v.destino, "tarifa": v.tarifa, "estado": v.estado})
    return lista

@app.post("/viajes/aceptar")
async def aceptar(datos: AceptarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            await db.execute(text("UPDATE viajes SET conductor_id=:cid, estado='aceptado' WHERE id=:vid"), {"cid": datos.conductor_id, "vid": datos.viaje_id})
        return {"mensaje": "Viaje aceptado"}
    except Exception as e: return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
