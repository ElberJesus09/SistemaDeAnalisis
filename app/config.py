"""Lectura de config.ini. Sin dependencias externas."""
import configparser
import os
import secrets
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
APP = RAIZ / "app"
SALIDA = RAIZ / "out"
INI = RAIZ / "config.ini"

_POR_DEFECTO = {
    "app": {
        "modo": "servidor",                 # servidor | cliente
        "servidor_url": "http://localhost:8000",
        "puerto": "8000",
        "ciclo": "2026-II",
        "sede": "Centro Preuniversitario Juan Francisco Aguinaga Castro",
        "clave_firma": "",
        # si = no se emite la ficha sin pago verificado en el banco
        "exigir_pago": "no",
    },
    "mysql": {
        "host": "localhost",
        "puerto": "3306",
        "usuario": "root",
        "password": "",
        "base": "cpu_unprg",
    },
}


def _cargar() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read_dict(_POR_DEFECTO)
    if INI.exists():
        cp.read(INI, encoding="utf-8")
    # La clave que firma las sesiones se genera sola la primera vez.
    if not cp.get("app", "clave_firma", fallback=""):
        cp.set("app", "clave_firma", secrets.token_hex(32))
        try:
            with INI.open("w", encoding="utf-8") as fh:
                cp.write(fh)
        except OSError:
            pass
    return cp


CFG = _cargar()

MODO = CFG.get("app", "modo").strip().lower()
SERVIDOR_URL = CFG.get("app", "servidor_url").strip().rstrip("/")
PUERTO = CFG.getint("app", "puerto")
CICLO = CFG.get("app", "ciclo").strip()
SEDE = CFG.get("app", "sede").strip()
CLAVE_FIRMA = CFG.get("app", "clave_firma").strip()
EXIGIR_PAGO = CFG.get("app", "exigir_pago").strip().lower() in\
    ("si", "sí", "1", "true", "yes")

MYSQL = {
    "host": CFG.get("mysql", "host").strip(),
    "port": CFG.getint("mysql", "puerto"),
    "user": CFG.get("mysql", "usuario").strip(),
    "password": CFG.get("mysql", "password"),
    "database": CFG.get("mysql", "base").strip(),
}

# Variables MAIL_* compatibles con la configuracion habitual de Laravel.
# En esta aplicacion tambien se pueden guardar en [smtp] de config.ini.
def correo_opcion(nombre, defecto=""):
    return os.environ.get("MAIL_" + nombre.upper(), CFG.get("smtp", nombre.lower(), fallback=defecto, raw=True))


SMTP = {
    "host": correo_opcion("host", "smtp.gmail.com"),
    "port": correo_opcion("port", "465"),
    "scheme": correo_opcion("scheme", "smtps"),
    "username": correo_opcion("username"),
    "password": correo_opcion("password"),
    "from_address": correo_opcion("from_address"),
    "from_name": correo_opcion("from_name", "Centro Preuniversitario UNPRG"),
}
