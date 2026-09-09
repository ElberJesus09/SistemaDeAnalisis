"""
Usuarios, roles y sesiones. Todo con la libreria estandar:
- claves con PBKDF2-HMAC-SHA256 (200 000 iteraciones, sal aleatoria)
- sesion en una cookie firmada con HMAC, no reutilizable ni editable
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime

from . import config, db

ITERACIONES = 200_000
DURACION_SESION = 12 * 3600      # 12 horas
ROLES = ("admin", "secretaria")


# --------------------------------------------------------------- claves
def hash_clave(clave: str) -> str:
    sal = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), sal, ITERACIONES)
    return f"pbkdf2${ITERACIONES}${sal.hex()}${dk.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        algo, iters, sal, dk = guardado.split("$")
        if algo != "pbkdf2":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", clave.encode(),
                                   bytes.fromhex(sal), int(iters))
        return hmac.compare_digest(calc.hex(), dk)
    except (ValueError, AttributeError):
        return False


# --------------------------------------------------------------- usuarios
def crear_usuario(usuario: str, nombre: str, clave: str, rol: str = "secretaria") -> int:
    if rol not in ROLES:
        raise ValueError(f"Rol invalido: {rol}")
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return db.x(
        "INSERT INTO usuarios (usuario, nombre, rol, clave, activo, creado)"
        " VALUES (%s, %s, %s, %s, 1, %s)",
        (usuario.strip().lower(), nombre.strip(), rol, hash_clave(clave), ahora),
    )


def cambiar_clave(usuario_id: int, clave: str) -> None:
    db.x("UPDATE usuarios SET clave = %s WHERE id = %s",
         (hash_clave(clave), usuario_id))


def autenticar(usuario: str, clave: str):
    u = db.q1("SELECT * FROM usuarios WHERE usuario = %s AND activo = 1",
              (usuario.strip().lower(),))
    if u and verificar_clave(clave, u["clave"]):
        return u
    return None


def asegurar_admin_inicial() -> str:
    """Si no hay ningun usuario, crea admin/admin y avisa que hay que cambiarla."""
    if db.q1("SELECT id FROM usuarios LIMIT 1"):
        return ""
    crear_usuario("admin", "Administrador", "admin", "admin")
    return ("Se creo el usuario inicial  admin / admin  "
            "— cambia la contrasena al entrar.")


# --------------------------------------------------------------- sesiones
def _firmar(datos: bytes) -> str:
    firma = hmac.new(config.CLAVE_FIRMA.encode(), datos, hashlib.sha256).digest()
    return (base64.urlsafe_b64encode(datos).decode().rstrip("=") + "."
            + base64.urlsafe_b64encode(firma).decode().rstrip("="))


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def crear_sesion(usuario: dict) -> str:
    datos = json.dumps({
        "id": usuario["id"], "usuario": usuario["usuario"],
        "nombre": usuario["nombre"], "rol": usuario["rol"],
        "exp": int(time.time()) + DURACION_SESION,
        "n": secrets.token_hex(8),
    }, separators=(",", ":")).encode()
    return _firmar(datos)


def leer_sesion(cookie: str):
    if not cookie or "." not in cookie:
        return None
    cuerpo, firma = cookie.rsplit(".", 1)
    try:
        datos = _b64d(cuerpo)
        esperado = hmac.new(config.CLAVE_FIRMA.encode(), datos,
                            hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(firma), esperado):
            return None
        s = json.loads(datos)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if s.get("exp", 0) < time.time():
        return None
    return s


# --------------------------------------------------------------- auditoria
def registrar(usuario_id, accion: str, referencia: str = "", detalle: str = "") -> None:
    db.x("INSERT INTO auditoria (usuario_id, accion, referencia, detalle, creado)"
         " VALUES (%s, %s, %s, %s, %s)",
         (usuario_id, accion, referencia[:80], detalle[:255],
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
