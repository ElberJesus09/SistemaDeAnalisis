"""Copias automaticas de MySQL en ZIP, con destino elegido por el administrador."""
import hashlib
import hmac
import json
import threading
import time
import zipfile
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

from . import config

AJUSTES = config.RAIZ / "config-copias.json"
ESTADO = config.SALIDA / "copias-estado.json"
_lock = threading.Lock()
_arranque = threading.Lock()
_hilo = None


def _leer(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar(path, datos):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def opciones():
    return {"activo": True, "carpeta": str(config.RAIZ / "copias_seguridad"), "horas": 24, **_leer(AJUSTES)}


def guardar_opciones(carpeta, horas, activo):
    carpeta = Path(carpeta.strip())
    if not carpeta.is_absolute():
        raise ValueError("Escribe una ruta completa, por ejemplo D:\\CopiasCPU.")
    try:
        horas = int(horas)
    except (ValueError, TypeError):
        raise ValueError("La frecuencia debe ser un número de horas.") from None
    if not 1 <= horas <= 168:
        raise ValueError("Elige una frecuencia entre 1 y 168 horas.")
    # No escribir en una carpeta nueva hasta que el administrador guarde la ruta.
    carpeta.mkdir(parents=True, exist_ok=True)
    datos = {"activo": bool(activo), "carpeta": str(carpeta.resolve()), "horas": horas}
    with _lock:
        _guardar(AJUSTES, datos)


def estado():
    return {**opciones(), **_leer(ESTADO)}


def token(sesion):
    return hmac.new(config.CLAVE_FIRMA.encode(), ("copias:" + sesion['n']).encode(), hashlib.sha256).hexdigest()


def _ident(nombre):
    return '`' + nombre.replace('`', '``') + '`'


def _valor(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    if isinstance(v, (datetime, date)):
        v = v.isoformat(sep=' ') if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, bytes):
        return "X'" + v.hex() + "'"
    # Literales hex evitan depender del modo de escape de MySQL al restaurar.
    return "CONVERT(X'" + str(v).encode('utf-8').hex() + "' USING utf8mb4)"


def exportar_sql(archivo):
    import pymysql
    con = pymysql.connect(charset='utf8mb4', autocommit=False, **config.MYSQL)
    conteos = {}
    try:
        cur = con.cursor()
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        cur.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
        tablas = [r[0] for r in cur.fetchall()]
        archivo.write('-- Copia del Sistema de Inscripciones CPU UNPRG\nSET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\n')
        for tabla in tablas:
            cur.execute('SHOW CREATE TABLE ' + _ident(tabla))
            archivo.write(cur.fetchone()[1] + ';\n')
            cur.execute('SELECT * FROM ' + _ident(tabla))
            columnas = ','.join(_ident(d[0]) for d in cur.description)
            n = 0
            while True:
                filas = cur.fetchmany(500)
                if not filas:
                    break
                for fila in filas:
                    archivo.write('INSERT INTO ' + _ident(tabla) + ' (' + columnas + ') VALUES (' + ','.join(_valor(v) for v in fila) + ');\n')
                n += len(filas)
            conteos[tabla] = n
        archivo.write('SET FOREIGN_KEY_CHECKS=1;\n')
        con.rollback()
        return conteos
    finally:
        con.close()


def crear():
    if not _lock.acquire(blocking=False):
        return {'ok': False, 'mensaje': 'Ya hay una copia o cambio de configuración en curso.'}
    temporal = None
    try:
        c = opciones()
        destino = Path(c['carpeta']).resolve()
        destino.mkdir(parents=True, exist_ok=True)
        instante = datetime.now()
        nombre = 'cpu_unprg_' + instante.strftime('%Y-%m-%d_%H-%M-%S_%f') + '.zip'
        final = destino / nombre
        temporal = final.with_suffix('.tmp')
        import io
        sql = io.StringIO()
        conteos = exportar_sql(sql)
        contenido = sql.getvalue().encode('utf-8')
        meta = {'version': 1, 'base': config.MYSQL['database'], 'fecha': instante.isoformat(),
                'tablas': conteos, 'sha256_sql': hashlib.sha256(contenido).hexdigest()}
        with zipfile.ZipFile(temporal, 'x', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('base_datos.sql', contenido)
            z.writestr('resumen.json', json.dumps(meta, ensure_ascii=False, indent=2))
            z.writestr('LEEME.txt', 'Copia de la base de datos del Sistema de Inscripciones CPU UNPRG.\n'
                       'Incluye alumnos, inscripciones, pagos, usuarios, tarifario e historiales.\n'
                       'No incluye el programa, config.ini ni credenciales de correo o Google.\n\n'
                       'Restaurar en una base MySQL VACIA, con el sistema detenido:\n'
                       '1. Crear una base nueva con codificacion utf8mb4.\n'
                       '2. Importar base_datos.sql en esa base con MySQL Workbench o el cliente mysql.\n'
                       '3. Cambiar la base en config.ini y comprobar los conteos de resumen.json.\n'
                       'La copia no borra ni reemplaza automaticamente la base original.\n')
        with zipfile.ZipFile(temporal) as z:
            if z.testzip() is not None or hashlib.sha256(z.read('base_datos.sql')).hexdigest() != meta['sha256_sql']:
                raise ValueError('No se pudo verificar la copia.')
        temporal.replace(final)
        _guardar(ESTADO, {'ultima_copia': instante.strftime('%d/%m/%Y %H:%M:%S'),
                         'ultimo_epoch': time.time(), 'archivo': str(final),
                         'destino': str(destino), 'error': '', 'tablas': conteos})
        return {'ok': True, 'mensaje': 'Copia creada y verificada.', 'archivo': str(final)}
    except Exception:
        estado_anterior = _leer(ESTADO)
        estado_anterior['error'] = 'No se pudo crear la copia. Revisa que la carpeta esté disponible, tenga espacio y permita escritura, y que MySQL esté conectado.'
        try:
            _guardar(ESTADO, estado_anterior)
        except OSError:
            pass
        return {'ok': False, 'mensaje': estado_anterior['error']}
    finally:
        try:
            if temporal is not None and temporal.exists():
                temporal.unlink(missing_ok=True)
        finally:
            _lock.release()


def pendiente():
    c = opciones()
    e = _leer(ESTADO)
    return c['activo'] and (e.get('destino') != str(Path(c['carpeta']).resolve())
                           or time.time() - e.get('ultimo_epoch', 0) >= c['horas'] * 3600)


def iniciar():
    global _hilo
    with _arranque:
        if _hilo is not None and _hilo.is_alive():
            return
        def ejecutar():
            while True:
                if pendiente():
                    crear()
                threading.Event().wait(60)
        _hilo = threading.Thread(target=ejecutar, name='copias-mysql', daemon=True)
        _hilo.start()
