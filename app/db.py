"""
Acceso a la base de datos.

En produccion habla con MySQL a traves de PyMySQL. Para las pruebas
automaticas se puede cambiar a SQLite con usar_sqlite(); las consultas
se escriben una sola vez con marcadores %s y aqui se traducen.
"""
import re
import threading
from pathlib import Path

from . import config

_local = threading.local()
_MOTOR = "mysql"          # mysql | sqlite
_RUTA_SQLITE = None


def usar_sqlite(ruta) -> None:
    """Solo para pruebas: dirige todo a un archivo SQLite."""
    global _MOTOR, _RUTA_SQLITE
    _MOTOR, _RUTA_SQLITE = "sqlite", str(ruta)
    cerrar()


def motor() -> str:
    return _MOTOR


def conexion():
    con = getattr(_local, "con", None)
    if con is not None:
        return con
    if _MOTOR == "sqlite":
        import sqlite3

        con = sqlite3.connect(_RUTA_SQLITE)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
    else:
        import pymysql
        from pymysql.cursors import DictCursor

        con = pymysql.connect(charset="utf8mb4", cursorclass=DictCursor,
                              autocommit=False, **config.MYSQL)
    _local.con = con
    return con


def cerrar() -> None:
    con = getattr(_local, "con", None)
    if con is not None:
        try:
            con.close()
        except Exception:
            pass
        _local.con = None


def _adaptar(sql: str) -> str:
    return sql.replace("%s", "?") if _MOTOR == "sqlite" else sql


def q(sql: str, params=()) -> list:
    """Consulta que devuelve filas como diccionarios."""
    con = conexion()
    cur = con.cursor()
    cur.execute(_adaptar(sql), tuple(params))
    filas = cur.fetchall()
    cur.close()
    return [dict(f) for f in filas]


def q1(sql: str, params=()):
    filas = q(sql, params)
    return filas[0] if filas else None


def x(sql: str, params=()) -> int:
    """Insert/update/delete. Devuelve el id insertado (o el nro de filas)."""
    con = conexion()
    cur = con.cursor()
    cur.execute(_adaptar(sql), tuple(params))
    nuevo = cur.lastrowid or cur.rowcount
    cur.close()
    con.commit()
    return nuevo


# --------------------------------------------------------------- esquema
def _ddl_para_sqlite(sql: str) -> str:
    sql = re.sub(r"(?im)^\s*(CREATE DATABASE|USE)\b[^;]*;", "", sql)
    sql = sql.replace("INT AUTO_INCREMENT PRIMARY KEY",
                      "INTEGER PRIMARY KEY AUTOINCREMENT")
    sql = re.sub(r",\s*\n\s*UNIQUE KEY \w+ \(([^)]*)\)", r", UNIQUE (\1)", sql)
    sql = re.sub(r",\s*\n\s*KEY \w+ \([^)]*\)", "", sql)
    sql = re.sub(r",\s*\n\s*CONSTRAINT \w+ (FOREIGN KEY)", r", \1", sql)
    return sql


def _sentencias(sql: str):
    """Quita los comentarios -- y parte el script en sentencias.

    Hay que quitarlos ANTES de partir por ';': un comentario puede contener
    un punto y coma y cortaria la sentencia por la mitad."""
    limpio = []
    for linea in sql.splitlines():
        fuera, comilla = [], None
        i = 0
        while i < len(linea):
            c = linea[i]
            if comilla:
                fuera.append(c)
                if c == comilla:
                    comilla = None
            elif c in "'\"`":
                comilla = c
                fuera.append(c)
            elif c == "-" and linea[i:i + 2] == "--":
                break
            else:
                fuera.append(c)
            i += 1
        limpio.append("".join(fuera).rstrip())
    for trozo in "\n".join(limpio).split(";"):
        if trozo.strip():
            yield trozo


def crear_esquema() -> None:
    """Crea las tablas si faltan. En MySQL requiere que la base ya exista."""
    sql = (config.APP / "esquema.sql").read_text(encoding="utf-8")
    if _MOTOR == "sqlite":
        sql = _ddl_para_sqlite(sql)
    con = conexion()
    cur = con.cursor()
    for sentencia in _sentencias(sql):
        cur.execute(sentencia)
    cur.close()
    con.commit()
    migrar()


def tablas_esperadas() -> dict:
    """{tabla: {columna: definicion}} leido de esquema.sql."""
    sql = (config.APP / "esquema.sql").read_text(encoding="utf-8")
    salida = {}
    for sentencia in _sentencias(sql):
        m = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*)\)\s*$",
                      sentencia, re.S | re.I)
        if not m:
            continue
        cols = {}
        for linea in m.group(2).splitlines():
            linea = linea.strip().rstrip(",")
            c = re.match(r"(\w+)\s+(\w.*)$", linea)
            if c and c.group(1).upper() not in ("UNIQUE", "KEY", "CONSTRAINT",
                                                "PRIMARY", "FOREIGN", "INDEX"):
                cols[c.group(1)] = c.group(2).strip()
        salida[m.group(1)] = cols
    return salida


def _columnas_actuales(tabla) -> set:
    if _MOTOR == "sqlite":
        return {f["name"] for f in q(f"PRAGMA table_info({tabla})")}
    return {f["Field"] for f in q(f"SHOW COLUMNS FROM {tabla}")}


def migrar() -> list:
    """Agrega a las tablas existentes las columnas nuevas de esquema.sql.

    CREATE TABLE IF NOT EXISTS respeta una tabla que ya existe, asi que sin
    esto una version nueva del sistema arrancaria sin sus columnas. Solo
    agrega; nunca borra ni cambia una columna con datos."""
    hechos = []
    for tabla, columnas in tablas_esperadas().items():
        try:
            hay = _columnas_actuales(tabla)
        except Exception:
            continue                      # la tabla aun no existe
        for nombre, definicion in columnas.items():
            if nombre in hay:
                continue
            # AUTO_INCREMENT y las claves no se pueden agregar despues
            if "AUTO_INCREMENT" in definicion.upper():
                continue
            if _MOTOR == "sqlite":
                definicion = definicion.replace("AUTO_INCREMENT", "")
            x(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {definicion}")
            hechos.append(f"{tabla}.{nombre}")
    return hechos


def verificar_tablas() -> str:
    """Comprueba que las tablas del sistema tengan las columnas que la app usa.

    Sirve para el caso en que la base elegida en config.ini ya contenga una
    tabla con el mismo nombre de otro proyecto: CREATE TABLE IF NOT EXISTS la
    respeta en silencio y el sistema fallaria mas tarde sin explicacion."""
    problemas = []
    for tabla, columnas in tablas_esperadas().items():
        try:
            hay = _columnas_actuales(tabla)
        except Exception:
            problemas.append(f"  - falta la tabla '{tabla}'")
            continue
        faltan = [c for c in columnas if c not in hay]
        if faltan:
            problemas.append(f"  - la tabla '{tabla}' ya existia y no tiene: "
                             + ", ".join(faltan))
    if not problemas:
        return ""
    return (
        f"La base '{config.MYSQL['database']}' no tiene la estructura que el "
        "sistema necesita:\n" + "\n".join(problemas) + "\n\n"
        "Lo mas probable es que esa base ya se use para otro proyecto y haya\n"
        "tablas con el mismo nombre. Cambia 'base' en config.ini por un nombre\n"
        "propio (por ejemplo cpu_unprg) y vuelve a ejecutar instalar.bat."
    )


def comprobar() -> str:
    """Mensaje legible sobre el estado de la conexion (para el arranque)."""
    try:
        conexion()
        return ""
    except Exception as e:  # pragma: no cover - depende del entorno
        return (
            f"No se pudo conectar a MySQL en {config.MYSQL['host']}:"
            f"{config.MYSQL['port']} como '{config.MYSQL['user']}'.\n"
            f"Detalle: {e}\n\n"
            "Revisa config.ini (seccion [mysql]) y que el servicio MySQL este encendido."
        )
