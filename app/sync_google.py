"""Lectura periodica y privada de una pestaña de Google Sheets."""
import csv
import hashlib
import hmac
import json
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import config, db, importador, pagos

_candado = threading.Lock()
_arranque = threading.Lock()
_hilo = None
_estado = {"ultimo_intento": "", "ultimo_exito": "", "mensaje": "Pendiente de conexión", "error": False}
_archivo_estado = config.SALIDA / "google-sync.json"


def opciones():
    c = config.CFG
    def leer(k, defecto=""):
        return c.get("google_sheets", k, fallback=defecto, raw=True).strip()
    try:
        intervalo = max(60, int(leer("intervalo_segundos", "300")))
    except ValueError:
        intervalo = 300
    ruta = Path(leer("credenciales", "credenciales/google-sheets.json"))
    if not ruta.is_absolute():
        ruta = config.RAIZ / ruta
    return {"activo": leer("activo", "no").lower() in ("si", "sí", "1", "true"),
            "spreadsheet_id": leer("spreadsheet_id"), "sheet_id": leer("sheet_id"),
            "ciclo": leer("ciclo", config.CICLO), "intervalo": intervalo, "credenciales": ruta,
            "dni_omitidos": set(leer("dni_omitidos").split())}


def estado():
    c = opciones()
    return {**_estado, "activo": c["activo"], "credenciales_listas": c["credenciales"].is_file(),
            "minutos": c["intervalo"] // 60, "ciclo": c["ciclo"]}


def token(sesion):
    return hmac.new(config.CLAVE_FIRMA.encode(), ("google-sync:" + sesion['n']).encode(), hashlib.sha256).hexdigest()


def leer_google(c):
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession

    cred = service_account.Credentials.from_service_account_file(
        str(c["credenciales"]), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    base = "https://sheets.googleapis.com/v4/spreadsheets/" + quote(c["spreadsheet_id"], safe="")
    with AuthorizedSession(cred) as sesion:
        r = sesion.get(base, params={"fields": "sheets(properties(sheetId,title))"}, timeout=30)
        r.raise_for_status()
        hojas = r.json().get("sheets", [])
        hoja = next((s["properties"] for s in hojas if str(s["properties"]["sheetId"]) == c["sheet_id"]), None)
        if not hoja:
            raise ValueError("No se encontró la pestaña configurada en Google Sheets.")
        rango = "'" + hoja["title"].replace("'", "''") + "'"
        r = sesion.get(base + "/values/" + quote(rango, safe=""),
                       params={"valueRenderOption": "FORMATTED_VALUE"}, timeout=30)
        r.raise_for_status()
        return r.json().get("values", [])


def _checkpoint():
    try:
        return json.loads(_archivo_estado.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sincronizar(usuario_id=None):
    if not opciones()["activo"]:
        return "La sincronización con Google Sheets está desactivada."
    if not _candado.acquire(blocking=False):
        return "Ya hay una sincronización en curso."
    try:
        c = opciones()
        _estado.update(ultimo_intento=datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        if not c["credenciales"].is_file():
            raise ValueError("Falta conectar Google: coloca la credencial de lectura en credenciales/google-sheets.json.")
        if not all(c[k] for k in ("spreadsheet_id", "sheet_id", "ciclo")):
            raise ValueError("Completa la hoja, pestaña y ciclo en config.ini.")
        filas = leer_google(c)
        if not filas:
            raise ValueError("La pestaña está vacía: faltan los encabezados del formulario.")
        claves = {importador.normalizar_encabezado(e) for e in filas[0]}
        if not {"MARCA TEMPORAL", "DNI", "NOMBRE COMPLETO"} <= claves:
            raise ValueError("La pestaña no tiene los encabezados esperados del formulario.")
        dni_indice = next(i for i, e in enumerate(filas[0]) if importador.normalizar_encabezado(e) == "DNI")
        filas = [filas[0]] + [f for f in filas[1:] if importador.normalizar_dni(f[dni_indice] if len(f) > dni_indice else '') not in c['dni_omitidos']]
        huella = hashlib.sha256(json.dumps([c['spreadsheet_id'], c['sheet_id'], c['ciclo'], filas], ensure_ascii=False).encode()).hexdigest()
        anterior = _checkpoint()
        # No repetir la importacion mientras la hoja y el ciclo no cambien.
        if anterior.get("huella") == huella:
            mensaje = "Sin respuestas nuevas ni cambios en la hoja."
        elif not any(any(str(v).strip() for v in fila) for fila in filas[1:]):
            mensaje = "La hoja todavía no contiene respuestas."
        else:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                archivo = Path(tmp) / "respuestas-google.csv"
                with archivo.open("w", encoding="utf-8-sig", newline="") as f:
                    csv.writer(f).writerows(filas)
                res = importador.importar(archivo, usuario_id, c["ciclo"], "Google Sheets · respuestas")
            pagos.conciliar(c["ciclo"])
            mensaje = (f"{res['nuevas']} nueva(s), {res['actualizadas']} existente(s), "
                       f"{res['omitidas']} omitida(s).")
            if res['avisos']:
                mensaje += " Revisa las observaciones en Importar."
        _estado.update(ultimo_exito=datetime.now().strftime("%d/%m/%Y %H:%M:%S"), mensaje=mensaje, error=False)
        _archivo_estado.parent.mkdir(parents=True, exist_ok=True)
        temporal = _archivo_estado.with_suffix('.tmp')
        temporal.write_text(json.dumps({"huella": huella, **_estado}, ensure_ascii=False), encoding="utf-8")
        temporal.replace(_archivo_estado)
        return mensaje
    except ValueError as exc:
        _estado.update(error=True, mensaje=str(exc))
        return str(exc)
    except Exception:
        # No exponer tokens, claves ni respuestas de Google en el panel o logs.
        mensaje = "No se pudo leer Google Sheets. Revisa internet, la credencial, el permiso de lector y que Google Sheets API esté habilitada. Se reintentará en la siguiente revisión."
        _estado.update(error=True, mensaje=mensaje)
        return mensaje
    finally:
        db.cerrar()
        _candado.release()


def iniciar():
    global _hilo
    with _arranque:
        if _hilo is not None and _hilo.is_alive():
            return
        c = opciones()
        if not c["activo"]:
            return
        def ejecutar():
            while True:
                sincronizar()
                threading.Event().wait(c["intervalo"])
        _hilo = threading.Thread(target=ejecutar, name="google-sheets", daemon=True)
        _hilo.start()
