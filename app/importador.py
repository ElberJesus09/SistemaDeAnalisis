"""
Importa las respuestas del formulario (CSV o XLSX) a la base de datos.

Reglas:
- La identidad del alumno es el DNI. Si ya existe, se completan los datos
  vacios pero NO se pisa lo que alguien corrigio a mano en el panel.
- La inscripcion es unica por (alumno, ciclo): reimportar el mismo archivo
  actualiza, no duplica.
"""
import csv
import io
import unicodedata
import threading
from functools import wraps
from datetime import date, datetime
from pathlib import Path

from . import config, db

_candado_importacion = threading.RLock()


def _serializar(fn):
    @wraps(fn)
    def ejecutar(*args, **kwargs):
        with _candado_importacion:
            return fn(*args, **kwargs)
    return ejecutar

# ------------------------------------------------------- mapeo de columnas
# clave = encabezado del formulario ya normalizado (sin tildes, sin espacios
# de sobra, en mayusculas); valor = campo interno.
COLUMNAS = {
    "MARCA TEMPORAL": "marca_temporal",
    "DIRECCION DE CORREO ELECTRONICO": "correo_form",
    "MEDIO DE PAGO": "medio_pago",
    "SEDE": "sede",
    "MODALIDAD": "modalidad",
    "TURNO": "turno",
    "OFERTAS": "oferta",                      # formulario anterior
    "NUMERO DE VOUCHER": "voucher",
    "FECHA DE PAGO": "fecha_pago",
    "AGENCIA DE PAGO": "agencia",
    "NUMERO DE SECUENCIA": "secuencia",
    "A QUE CARRERA PROFESIONAL DESEAS POSTULAR": "carrera",
    "DNI": "dni",
    "NOMBRE COMPLETO": "nombres",
    "APELLIDO PATERNO": "ap_paterno",
    "APELLIDO MATERNO": "ap_materno",
    "GENERO": "sexo",
    "FECHA DE NACIMIENTO": "nacimiento",
    "CELULAR": "telefono",
    "CORREO ELECTRONICO": "correo",
    "DIRECCION": "direccion",
    "ERES MENOR DE EDAD": "menor_edad",
    "NOMBRE DEL APODERADO": "apo_nombres",
    "APELLIDO PATERNO DEL APODERADO": "apo_ap_paterno",
    "APELLIDO MATERNO DEL APODERADO": "apo_ap_materno",
    "DNI DEL APODERADO": "apo_dni",
    "TELEFONO DEL APODERADO": "apo_telefono",
    "NOMBRE DEL COLEGIO": "colegio",
    "ANO DE EGRESO": "colegio_egreso",
}

# Encabezados que aparecen DOS VECES con significados distintos: la primera
# vez son del alumno y la segunda del colegio. Aqui no sirve la regla del
# "primer valor no vacio" — hay que ir por posicion, o la ubicacion del
# colegio quedaria pisada con la del alumno sin que nadie se entere.
REPETIDOS = {
    "DEPARTAMENTO": ["departamento", "colegio_departamento"],
    "PROVINCIA":    ["provincia",    "colegio_provincia"],
    "DISTRITO":     ["distrito",     "colegio_distrito"],
}

CAMPOS_ALUMNO = ("dni", "nombres", "ap_paterno", "ap_materno", "nacimiento",
                 "sexo", "telefono", "correo", "departamento", "provincia",
                 "distrito", "direccion", "menor_edad",
                 "colegio", "colegio_departamento", "colegio_provincia",
                 "colegio_distrito", "colegio_egreso",
                 "apo_nombres", "apo_ap_paterno", "apo_ap_materno",
                 "apo_dni", "apo_telefono")
CAMPOS_INSCRIPCION = ("carrera", "sede", "modalidad", "turno", "medio_pago", "oferta",
                      "voucher", "agencia", "secuencia", "fecha_pago",
                      "marca_temporal", "correo_form", "fecha_matricula")


def normalizar_encabezado(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("¿", " ").replace("?", " ").replace("¡", " ")
    return " ".join(t.upper().split())


def normalizar_fecha(valor) -> str:
    """Devuelve dd/mm/aaaa. Acepta texto, date y datetime."""
    if valor in (None, ""):
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    t = str(valor).strip()
    if not t:
        return ""
    t = t.split(" ")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(t, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return str(valor).strip()


def normalizar_dni(valor) -> str:
    if valor in (None, ""):
        return ""
    t = str(valor).strip()
    if t.endswith(".0"):           # Excel a veces lo trae como numero
        t = t[:-2]
    return "".join(c for c in t if c.isdigit())[:12]


def normalizar_sexo(valor) -> str:
    t = normalizar_encabezado(valor)
    if not t:
        return ""
    if t.startswith("F") or "FEMEN" in t or "MUJER" in t:
        return "Femenino"
    if t.startswith("M") or "MASCUL" in t or "HOMBRE" in t or t.startswith("V"):
        return "Masculino"
    return str(valor).strip().capitalize()


def normalizar_si_no(valor) -> str:
    t = normalizar_encabezado(valor)
    if not t:
        return ""
    if t.startswith("S"):
        return "Sí"
    if t.startswith("N"):
        return "No"
    return str(valor).strip().capitalize()


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return " ".join(str(valor).split())


# ------------------------------------------------------- lectura de archivos
def leer_archivo_crudo(ruta):
    """Devuelve (encabezados, filas) sin interpretar las columnas.

    Lo usan tanto este importador como el de pagos del banco, que trae
    encabezados distintos."""
    ruta = Path(ruta)
    if ruta.suffix.lower() in (".xlsx", ".xlsm"):
        return _crudo_xlsx(ruta)
    if ruta.suffix.lower() in (".csv", ".txt", ".tsv"):
        return _crudo_csv(ruta)
    raise ValueError(f"Formato no soportado: {ruta.suffix}. Usa .csv o .xlsx")


def leer_archivo(ruta) -> list:
    """Devuelve una lista de diccionarios {campo_interno: valor} por fila."""
    enc, cuerpo = leer_archivo_crudo(ruta)
    claves = {normalizar_encabezado(e) for e in enc}
    if not {"DNI", "NOMBRE COMPLETO"} <= claves:
        raise ValueError("El archivo de respuestas debe incluir DNI y NOMBRE COMPLETO.")
    return [_mapear(enc, v) for v in cuerpo
            if any(str(c).strip() for c in v if c is not None)]


def _mapear(encabezados, valores) -> dict:
    """Aplica el mapeo de columnas a campos internos.

    Dos casos con encabezados repetidos, y se resuelven distinto:
    - FECHA DE PAGO sale dos veces para el MISMO campo (una por cada forma
      de pago), asi que gana el primer valor no vacio.
    - DEPARTAMENTO / PROVINCIA / DISTRITO salen dos veces para campos
      DISTINTOS (alumno y colegio), asi que se reparten por posicion.
    """
    fila = {}
    veces = {}
    for enc, val in zip(encabezados, valores):
        clave = normalizar_encabezado(enc)
        n = veces.get(clave, 0)
        veces[clave] = n + 1

        if clave in REPETIDOS:
            destinos = REPETIDOS[clave]
            campo = destinos[min(n, len(destinos) - 1)]
        else:
            campo = COLUMNAS.get(clave)
        if not campo:
            continue

        val = _texto(val) if not isinstance(val, (date, datetime)) else val
        if campo not in fila or (not fila[campo] and val):
            fila[campo] = val
    return fila


def _separador(primera_linea: str) -> str:
    """El reporte del banco suele venir separado por tabuladores o ';'."""
    conteos = {s: primera_linea.count(s) for s in ("\t", ";", ",", "|")}
    mejor = max(conteos, key=conteos.get)
    return mejor if conteos[mejor] else ","


def _crudo_csv(ruta: Path):
    texto = None
    for cod in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = ruta.read_text(encoding=cod)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:                                # pragma: no cover
        raise ValueError("No se pudo leer el archivo (codificacion desconocida).")
    lineas = texto.splitlines()
    if not lineas:
        return [], []
    lector = list(csv.reader(io.StringIO(texto), delimiter=_separador(lineas[0])))
    enc, *cuerpo = lector
    return enc, cuerpo


def _crudo_xlsx(ruta: Path):
    import openpyxl

    wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    filas = ws.iter_rows(values_only=True)
    try:
        enc = list(next(filas))
    except StopIteration:
        wb.close()
        return [], []
    cuerpo = [list(v) for v in filas]
    wb.close()
    return enc, cuerpo


# ------------------------------------------------------- volcado a la base
def _limpiar(fila: dict) -> dict:
    d = {c: _texto(fila.get(c, "")) for c in
         set(CAMPOS_ALUMNO) | set(CAMPOS_INSCRIPCION)}
    d["dni"] = normalizar_dni(fila.get("dni"))
    d["apo_dni"] = normalizar_dni(fila.get("apo_dni"))
    d["nacimiento"] = normalizar_fecha(fila.get("nacimiento"))
    d["fecha_pago"] = normalizar_fecha(fila.get("fecha_pago"))
    # La fecha del envio del formulario se usa como matricula. Conservamos
    # aparte la marca original, incluida su hora, sin inventar fechas si falla.
    fecha_registro = normalizar_fecha(fila.get("marca_temporal"))
    try:
        d["fecha_matricula"] = datetime.strptime(fecha_registro, "%d/%m/%Y").strftime("%d/%m/%Y")
    except ValueError:
        d["fecha_matricula"] = ""
    d["sexo"] = normalizar_sexo(fila.get("sexo"))
    d["menor_edad"] = normalizar_si_no(fila.get("menor_edad"))
    d["modalidad"] = d["modalidad"].upper()
    for c in ("nombres", "ap_paterno", "ap_materno", "departamento",
              "provincia", "distrito", "direccion", "carrera",
              "colegio", "colegio_departamento", "colegio_provincia",
              "colegio_distrito", "apo_nombres", "apo_ap_paterno",
              "apo_ap_materno"):
        d[c] = d[c].upper()
    d["correo"] = d["correo"].lower()
    return d


@_serializar
def importar(ruta, usuario_id=None, ciclo=None, nombre_archivo=None) -> dict:
    """Importa un archivo. Devuelve un resumen con contadores y avisos."""
    ciclo = ciclo or config.CICLO
    nombre_archivo = nombre_archivo or Path(ruta).name
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    filas = leer_archivo(ruta)
    if not filas:
        raise ValueError("El archivo contiene solo encabezados, sin respuestas para importar. "
                         "Descarga nuevamente el CSV cuando haya inscripciones.")
    res = {"filas": len(filas), "nuevas": 0, "actualizadas": 0,
           "omitidas": 0, "avisos": []}
    vistos = set()

    for i, cruda in enumerate(filas, start=2):     # fila 1 = encabezados
        d = _limpiar(cruda)
        if len(d["dni"]) != 8:
            res["omitidas"] += 1
            res["avisos"].append(f"Fila {i}: DNI invalido o vacio ('{d['dni']}')")
            continue
        if d["dni"] in vistos:
            res["omitidas"] += 1
            res["avisos"].append(f"Fila {i}: DNI {d['dni']} repetido en el archivo")
            continue
        vistos.add(d["dni"])

        alumno = db.q1("SELECT * FROM alumnos WHERE dni = %s", (d["dni"],))
        if alumno:
            # solo rellena huecos: no pisa correcciones hechas en el panel
            cambios = {c: d[c] for c in CAMPOS_ALUMNO
                       if c != "dni" and d[c] and not str(alumno.get(c) or "").strip()}
            if cambios:
                sets = ", ".join(f"{c} = %s" for c in cambios)
                db.x(f"UPDATE alumnos SET {sets}, actualizado = %s WHERE id = %s",
                     (*cambios.values(), ahora, alumno["id"]))
            alumno_id = alumno["id"]
        else:
            cols = list(CAMPOS_ALUMNO)
            db.x(f"INSERT INTO alumnos ({', '.join(cols)}, creado, actualizado)"
                 f" VALUES ({', '.join(['%s'] * len(cols))}, %s, %s)",
                 (*[d[c] for c in cols], ahora, ahora))
            alumno_id = db.q1("SELECT id FROM alumnos WHERE dni = %s", (d["dni"],))["id"]

        insc = db.q1("SELECT * FROM inscripciones WHERE alumno_id = %s AND ciclo = %s",
                     (alumno_id, ciclo))
        if insc:
            cambios = {c: d[c] for c in CAMPOS_INSCRIPCION
                       if d[c] and not str(insc.get(c) or "").strip()}
            if cambios:
                sets = ", ".join(f"{c} = %s" for c in cambios)
                db.x(f"UPDATE inscripciones SET {sets}, actualizado = %s WHERE id = %s",
                     (*cambios.values(), ahora, insc["id"]))
            res["actualizadas"] += 1
        else:
            # La sede ahora la elige el alumno en el formulario; config.ini
            # solo cubre el caso de que venga vacia. Ojo: 'sede' ya esta
            # dentro de CAMPOS_INSCRIPCION, no se puede repetir en el INSERT.
            d["sede"] = d["sede"] or config.SEDE
            cols = list(CAMPOS_INSCRIPCION)
            db.x(f"INSERT INTO inscripciones (alumno_id, ciclo, {', '.join(cols)},"
                 f" origen, creado, actualizado)"
                 f" VALUES (%s, %s, {', '.join(['%s'] * len(cols))}, %s, %s, %s)",
                 (alumno_id, ciclo, *[d[c] for c in cols],
                  nombre_archivo, ahora, ahora))
            res["nuevas"] += 1

        if d["carrera"] and not db.q1("SELECT id FROM carreras WHERE nombre = %s",
                                      (d["carrera"],)):
            db.x("INSERT INTO carreras (nombre, activo) VALUES (%s, 1)", (d["carrera"],))

    db.x("INSERT INTO importaciones (archivo, filas, nuevas, actualizadas,"
         " omitidas, detalle, usuario_id, creado)"
         " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
         (nombre_archivo[:200], res["filas"], res["nuevas"], res["actualizadas"],
          res["omitidas"], "\n".join(res["avisos"][:200]), usuario_id, ahora))
    return res
