# --- Importaciones ---
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from fastapi import FastAPI, Depends
from pydantic import BaseModel
import warnings
from typing import Optional, List
from datetime import datetime
import os # <--- Importante para leer variables de Render

# --- Importaciones de Admin y SQLAlchemy ---
from sqladmin import Admin, ModelView
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import Column, Integer, String, Float, ForeignKey, text, Date

# ==========================================
# 1. CONFIGURACIÓN DE BASE DE DATOS (INTELIGENTE)
# ==========================================

# A. Intentamos leer la Variable de Entorno de Render (Nube)
DATABASE_URL = os.getenv("DATABASE_URL")

# B. Si está vacía (significa que estamos en tu PC), usamos la local
if not DATABASE_URL:
    # Esta es tu conexión local para cuando trabajas en tu computadora
    DATABASE_URL = "postgresql+asyncpg://postgres:1234@localhost:5432/taxi_app_db"

# C. Corrección automática para Supabase (postgresql:// -> postgresql+asyncpg://)
# Esto arregla el error de conexión en la nube
if DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# ==========================================
# 2. MODELOS DE BASE DE DATOS (TABLAS)
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
    
    # Coordenadas para el mapa
    origen_lat = Column(Float, nullable=True)
    origen_lng = Column(Float, nullable=True)
    destino_lat = Column(Float, nullable=True)
    destino_lng = Column(Float, nullable=True)
    
    # Relaciones para el Admin
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
# 3. MODELOS PYDANTIC (Datos que envía Flutter)
# ==========================================
class LoginRequest(BaseModel):
    email: str
    password: str

class ViajeRequest(BaseModel):
    usuario_id: int
    origen: str
    destino: str
    tarifa: float
    # Coordenadas opcionales
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
    # Datos vehículo
    vehiculo_marca: str
    vehiculo_modelo: str
    vehiculo_placa: str
    vehiculo_color: Optional[str] = None
    vehiculo_anio: Optional[str] = None
    cedula: Optional[str] = None
    horario_trabajo: Optional[str] = None

# ==========================================
# 4. INICIALIZACIÓN DE API & ADMIN
# ==========================================
app = FastAPI(title="Taxi App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURACIÓN DEL PANEL ---
admin = Admin(app, engine, title="Taxi Admin")

class UsuarioAdmin(ModelView, model=Usuario):
    name = "Usuario"
    name_plural = "Usuarios"
    icon = "fa-solid fa-users"
    column_list = [Usuario.id, Usuario.nombre, Usuario.email, Usuario.role]

class ClienteAdmin(ModelView, model=Cliente):
    name = "Cliente"
    name_plural = "Clientes"
    icon = "fa-solid fa-person"
    column_list = [Cliente.id, "usuario.nombre", Cliente.usuario_id, Cliente.ciudad, Cliente.telefono]
    column_labels = {"usuario.nombre": "Nombre"}

class ConductorAdmin(ModelView, model=Conductor):
    name = "Conductor"
    name_plural = "Conductores"
    icon = "fa-solid fa-id-card"
    column_list = [Conductor.id, "usuario.nombre", "vehiculo.placa", Conductor.telefono]
    column_labels = {"usuario.nombre": "Chofer", "vehiculo.placa": "Placa"}

class VehiculoAdmin(ModelView, model=Vehiculo):
    name = "Vehículo"
    name_plural = "Vehículos"
    icon = "fa-solid fa-car"
    column_list = [Vehiculo.id, Vehiculo.placa, Vehiculo.marca, Vehiculo.modelo, Vehiculo.color]

class ViajeAdmin(ModelView, model=Viaje):
    name = "Viaje"
    name_plural = "Viajes"
    icon = "fa-solid fa-map-location-dot"
    # Mostramos datos directos para evitar errores si falta info
    column_list = [Viaje.id, Viaje.cliente_id, Viaje.origen, Viaje.destino, Viaje.tarifa, Viaje.estado]
    column_sortable_list = [Viaje.id, Viaje.estado]

admin.add_view(UsuarioAdmin)
admin.add_view(ClienteAdmin)
admin.add_view(ConductorAdmin)
admin.add_view(VehiculoAdmin)
admin.add_view(ViajeAdmin)

async def get_db():
    async with async_session() as session:
        yield session

# ==========================================
# 5. ENDPOINTS
# ==========================================

@app.get("/")
def leer_raiz():
    return {"mensaje": "API Taxi Funcionando con Supabase."}

@app.post("/login")
async def login(datos: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Verifica que la columna en tu BD sea password_hash
    query = text(f"SELECT * FROM usuarios WHERE email='{datos.email}' AND password_hash='{datos.password}'")
    result = await db.execute(query)
    user = result.fetchone()
    if user:
        return {"mensaje": "Login OK", "usuario": {"id": user.id, "nombre": user.nombre, "role": user.role}}
    else:
        return {"error": "Credenciales inválidas"}

@app.post("/registrar_usuario")
async def registrar_usuario(datos: UsuarioRegistroRequest, db: AsyncSession = Depends(get_db)):
    print(f"--> Registrando Pasajero: {datos.nombre}")
    try:
        async with db.begin():
            q_check = text("SELECT id FROM usuarios WHERE email = :ema")
            res = await db.execute(q_check, {"ema": datos.email})
            if res.scalar():
                return {"error": "El correo ya está registrado."}

            query_user = text("""
                INSERT INTO usuarios (nombre, email, password_hash, role) 
                VALUES (:nom, :ema, :pass, :rol) 
                RETURNING id
            """)
            result = await db.execute(query_user, {
                "nom": datos.nombre,
                "ema": datos.email, 
                "pass": datos.password, 
                "rol": "cliente"
            })
            user_id = result.scalar()

            # Guardamos perfil cliente
            # OJO: Verifica si es 'ciudad' o 'cuidad' en tu BD
            query_client = text("""
                INSERT INTO clientes (usuario_id, pais, ciudad, telefono, fecha_nacimiento)
                VALUES (:uid, :pais, :ciu, :tel, TO_DATE(:fec, 'YYYY-MM-DD'))
            """)
            await db.execute(query_client, {
                "uid": user_id,
                "pais": datos.pais,
                "ciu": datos.ciudad,
                "tel": datos.telefono,
                "fec": datos.fecha_nacimiento 
            })

        return {"mensaje": "Usuario registrado exitosamente", "id": user_id}
    except Exception as e:
        print(f"Error registrando usuario: {e}")
        return {"error": f"Error al registrar: {str(e)}"}

@app.post("/registrar_conductor")
async def registrar_conductor(datos: RegistroConductorRequest, db: AsyncSession = Depends(get_db)):
    print(f"--> Registrando Conductor: {datos.nombre}")
    try:
        async with db.begin():
            # A. Verificar email
            q_check = text("SELECT id FROM usuarios WHERE email = :ema")
            res = await db.execute(q_check, {"ema": datos.email})
            if res.scalar():
                return {"error": "El correo electrónico ya está registrado."}

            # B. Verificar placa (para no duplicar vehículos)
            q_placa = text("SELECT id FROM vehiculos WHERE placa = :placa")
            res_placa = await db.execute(q_placa, {"placa": datos.vehiculo_placa})
            if res_placa.scalar():
                return {"error": "Esa placa ya está registrada en el sistema."}

            # 1. Crear Usuario
            query_user = text("""
                INSERT INTO usuarios (nombre, email, password_hash, role) 
                VALUES (:nom, :ema, :pass, :rol) 
                RETURNING id
            """)
            result_user = await db.execute(query_user, {
                "nom": datos.nombre,
                "ema": datos.email, 
                "pass": datos.password, 
                "rol": "conductor"
            })
            user_id = result_user.scalar()

            # 2. Crear Vehículo
            query_vehiculo = text("""
                INSERT INTO vehiculos (marca, modelo, placa, color, anio)
                VALUES (:ma, :mo, :pl, :co, :an)
                RETURNING id
            """)
            result_vehiculo = await db.execute(query_vehiculo, {
                "ma": datos.vehiculo_marca,
                "mo": datos.vehiculo_modelo,
                "pl": datos.vehiculo_placa,
                "co": datos.vehiculo_color,
                "an": datos.vehiculo_anio
            })
            vehiculo_id = result_vehiculo.scalar()

            # 3. Crear Perfil Conductor
            query_driver = text("""
                INSERT INTO conductores (usuario_id, vehiculo_id, telefono, fecha_nacimiento)
                VALUES (:uid, :vid, :tel, TO_DATE(:fec, 'YYYY-MM-DD'))
            """)
            await db.execute(query_driver, {
                "uid": user_id,
                "vid": vehiculo_id,
                "tel": datos.telefono,
                "fec": datos.fecha_nacimiento
            })
            
        return {"mensaje": "Conductor registrado exitosamente", "id": user_id}
    except Exception as e:
        print(f"Error registrando conductor: {e}")
        return {"error": f"Error al registrar: {str(e)}"}

@app.post("/viajes/solicitar")
async def solicitar(viaje: ViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            query = text("""
                INSERT INTO viajes (
                    cliente_id, origen, destino, tarifa, estado,
                    origen_lat, origen_lng, destino_lat, destino_lng
                ) 
                VALUES (
                    :cid, :ori, :des, :tar, 'pendiente',
                    :olat, :olng, :dlat, :dlng
                )
            """)
            await db.execute(query, {
                "cid": viaje.usuario_id, 
                "ori": viaje.origen, 
                "des": viaje.destino, 
                "tar": viaje.tarifa,
                "olat": viaje.origen_lat,
                "olng": viaje.origen_lng,
                "dlat": viaje.destino_lat,
                "dlng": viaje.destino_lng
            })
        return {"mensaje": "Viaje solicitado"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/viajes/pendientes")
async def ver_pendientes(db: AsyncSession = Depends(get_db)):
    query = text("""
        SELECT v.id, v.origen, v.destino, v.tarifa, v.estado, u.nombre as cliente
        FROM viajes v
        JOIN usuarios u ON v.cliente_id = u.id
        WHERE v.estado='pendiente'
    """)
    result = await db.execute(query)
    viajes = result.fetchall()
    
    lista = []
    for v in viajes:
        lista.append({
            "id": v.id, 
            "origen": v.origen, 
            "destino": v.destino, 
            "tarifa": v.tarifa, 
            "estado": v.estado, 
            "cliente": v.cliente
        })
    return lista

@app.post("/viajes/aceptar")
async def aceptar(datos: AceptarViajeRequest, db: AsyncSession = Depends(get_db)):
    try:
        async with db.begin():
            query = text("UPDATE viajes SET conductor_id=:cid, estado='aceptado' WHERE id=:vid")
            await db.execute(query, {"cid": datos.conductor_id, "vid": datos.viaje_id})
        return {"mensaje": "Viaje aceptado"}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
