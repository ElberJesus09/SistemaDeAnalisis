"""
Pagos del Banco de la Nacion: importacion, tarifario y conciliacion.

Dos numeros amarran un pago con un alumno:

  DNI      El banco lo trae relleno con ceros ("619426920000000"); el DNI
           real son los 8 primeros digitos.

  VOUCHER  Regla de Pagalo.pe: el alumno escribe "1234567-1" en el
           formulario y hay que quedarse con los 7 digitos de antes del
           guion, que deben coincidir con los ULTIMOS 7 digitos del voucher
           del banco ("81234567" -> "1234567"). Por eso se guarda esa clave
           de 7 digitos ya normalizada en las dos puntas.

Un pago solo puede quedar aplicado a una inscripcion (columna
inscripcion_id), asi que no se puede reutilizar para dos alumnos.
"""
import unicodedata
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import config, db
from .importador import _texto, leer_archivo_crudo, normalizar_fecha

# Encabezados del reporte del banco -> campo interno
COLUMNAS = {
    "DOCUMENTO": "documento",
    "VOUCHER": "voucher",
    "CODIGO_TDOC": "cod_tdoc",
    "NOMBRE_TDOC": "nombre_tdoc",
    "SITUACION": "situacion",
    "COD_PAGO": "cod_pago",
    "CONCEPTO_PAGO": "concepto",
    "APELLIDOS_NOMBRES": "nombre_banco",
    "CUENTA": "cuenta",
    "FECHA_PAGO": "fecha_pago",
    "HORA": "hora",
    "IMPORTE_S/.": "importe",
    "IMPORTE S/.": "importe",
    "IMPORTE": "importe",
    "CAJ.": "caja",
    "CAJA": "caja",
    "AGE.": "agencia",
    "AGENCIA": "agencia",
}

# Tarifario inicial para validar los dos conceptos del ciclo.
TARIFARIO_BASE = [
    ("00001096", "Derecho de inscripción", Decimal("200.00"), 1, 1),
    ("00001097", "Pensión del ciclo",      Decimal("750.00"), 1, 1),
]


def normalizar_encabezado(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


# ------------------------------------------------------------ normalizadores
def clave_voucher(valor) -> str:
    """Los 7 digitos con los que se compara un voucher.

    Del formulario llega "1234567-1"  -> se corta en el guion -> "1234567".
    Del banco llega      "81234567"   -> ultimos 7 digitos    -> "1234567".
    """
    t = str(valor or "").strip()
    if not t:
        return ""
    if "-" in t:
        t = t.split("-", 1)[0]
    digitos = "".join(c for c in t if c.isdigit())
    return digitos[-7:] if len(digitos) >= 7 else digitos


def normalizar_documento(valor) -> str:
    """'619426920000000' -> '61942692'. El banco rellena con ceros a 15."""
    d = _texto(valor)
    if not d.isascii() or not d.isdigit():
        return ""
    if not d:
        return ""
    if len(d) > 8 and set(d[8:]) == {"0"}:
        return d[:8]
    if len(d) > 8:
        return ""
    return d.zfill(8)


def codigo_pago(valor) -> str:
    """Excel puede guardar 00001096 como el numero 1096."""
    t = _texto(valor)
    if not t.isascii() or not t.isdigit() or len(t) > 8:
        raise ValueError("El codigo de pago debe tener hasta 8 digitos.")
    return t.zfill(8)


def importe_valido(valor) -> Decimal:
    t = _texto(valor).replace("S/", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+\.\d{1,2}", t):
        t = t.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+,\d{1,2}", t):
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+([.,]\d{1,2})?", t):
        t = t.replace(",", ".")
    else:
        raise ValueError("Importe invalido; usa un monto como 200.00.")
    importe = Decimal(t)
    if not Decimal("0") < importe <= Decimal("99999999.99"):
        raise ValueError("El importe debe ser positivo y no superar 99999999.99.")
    return importe.quantize(Decimal("0.01"))


def a_decimal(valor) -> Decimal:
    t = str(valor or "0").strip().replace("S/", "").replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return Decimal(t or "0")
    except InvalidOperation:
        return Decimal("0")


def _num(valor) -> Decimal:
    """Los importes vuelven como Decimal en MySQL y como float en SQLite."""
    return valor if isinstance(valor, Decimal) else Decimal(str(valor or "0"))


# ------------------------------------------------------------------ tarifario
def asegurar_tarifario(ciclo=None) -> None:
    ciclo = ciclo or config.CICLO
    if db.q1("SELECT id FROM conceptos_pago WHERE ciclo = %s", (ciclo,)):
        return
    for codigo, nombre, importe, fijo, obligatorio in TARIFARIO_BASE:
        db.x("INSERT INTO conceptos_pago (ciclo, codigo, nombre, importe, fijo,"
             " obligatorio, activo) VALUES (%s, %s, %s, %s, %s, %s, 1)",
             (ciclo, codigo, nombre, str(importe), fijo, obligatorio))


def tarifario(ciclo=None) -> list:
    ciclo = ciclo or config.CICLO
    return db.q("SELECT * FROM conceptos_pago WHERE ciclo = %s AND activo = 1"
                " ORDER BY codigo", (ciclo,))


def _nombre_concepto(codigo, ciclo) -> str:
    r = db.q1("SELECT nombre FROM conceptos_pago WHERE ciclo = %s AND codigo = %s",
              (ciclo, codigo))
    return r["nombre"] if r else ""


# ----------------------------------------------------------------- importar
def es_archivo_de_pagos(encabezados) -> bool:
    """Distingue el reporte del banco del archivo de respuestas del formulario."""
    normal = {normalizar_encabezado(e) for e in encabezados}
    return "COD_PAGO" in normal and "DOCUMENTO" in normal


def importar(ruta, usuario_id=None, ciclo=None, nombre_archivo=None) -> dict:
    ciclo = ciclo or config.CICLO
    nombre_archivo = nombre_archivo or Path(ruta).name
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    asegurar_tarifario(ciclo)

    encabezados, cuerpo = leer_archivo_crudo(ruta)
    if not es_archivo_de_pagos(encabezados):
        raise ValueError(
            "Este archivo no parece el reporte de pagos del banco: faltan las "
            "columnas DOCUMENTO y COD_PAGO.")

    indices = {}
    for i, enc in enumerate(encabezados):
        campo = COLUMNAS.get(normalizar_encabezado(enc))
        if campo and campo not in indices:
            indices[campo] = i

    faltan = {"documento", "voucher", "cod_pago", "importe", "fecha_pago"} - indices.keys()
    if faltan:
        raise ValueError("Faltan columnas del reporte bancario: " + ", ".join(sorted(faltan)))

    res = {"filas": 0, "nuevas": 0, "actualizadas": 0, "omitidas": 0,
           "avisos": [], "importe": Decimal("0"), "repetidas": 0}
    vistos = set()   # para no sumar dos veces una linea repetida del archivo
    pagos_importados = []

    for n, valores in enumerate(cuerpo, start=2):
        if not any(str(v).strip() for v in valores if v is not None):
            continue
        res["filas"] += 1
        d = {c: (valores[i] if i < len(valores) else "")
             for c, i in indices.items()}

        dni = normalizar_documento(d.get("documento"))
        voucher = _texto(d.get("voucher"))
        try:
            cod = codigo_pago(d.get("cod_pago"))
            importe = importe_valido(d.get("importe"))
        except ValueError as exc:
            res["omitidas"] += 1
            res["avisos"].append(f"Fila {n}: {exc}")
            continue
        if len(dni) != 8 or not voucher:
            res["omitidas"] += 1
            res["avisos"].append(
                f"Fila {n}: sin DNI valido o sin voucher (DNI '{dni}')")
            continue

        fila = {
            "dni": dni,
            "voucher": voucher,
            "voucher_clave": clave_voucher(voucher),
            "cod_pago": cod,
            "concepto": _texto(d.get("concepto")) or _nombre_concepto(cod, ciclo),
            "fecha_pago": normalizar_fecha(d.get("fecha_pago")),
            "hora": _texto(d.get("hora")),
            "importe": str(importe),
            "agencia": _texto(d.get("agencia")),
            "caja": _texto(d.get("caja")),
            "cuenta": _texto(d.get("cuenta")),
            "nombre_banco": _texto(d.get("nombre_banco")).lstrip("#").strip(),
            "situacion": _texto(d.get("situacion")),
            "ciclo": ciclo,
        }
        # El banco deja CONCEPTO_PAGO en blanco o con "*** DESCONOCIDO ***":
        # en ese caso manda el nombre del tarifario.
        if "DESC" in fila["concepto"].upper() and "*" in fila["concepto"]:
            fila["concepto"] = _nombre_concepto(cod, ciclo)

        llave = (voucher, cod, dni)
        if llave in vistos:
            res["repetidas"] += 1
            res["avisos"].append(
                f"Fila {n}: pago repetido dentro del archivo "
                f"(voucher {voucher}, concepto {cod})")
            continue
        vistos.add(llave)

        ya = db.q1("SELECT id, ciclo FROM pagos WHERE voucher = %s AND cod_pago = %s"
                   " AND dni = %s", (voucher, cod, dni))
        if ya:
            if ya["ciclo"] != ciclo:
                res["omitidas"] += 1
                res["avisos"].append(f"Fila {n}: pago ya registrado en el ciclo {ya['ciclo']}; no se reutiliza.")
                continue
            cols = ", ".join(f"{c} = %s" for c in fila)
            db.x(f"UPDATE pagos SET {cols} WHERE id = %s",
                 (*fila.values(), ya["id"]))
            res["actualizadas"] += 1
            pago_id = ya["id"]
        else:
            cols = list(fila)
            pago_id = db.x(f"INSERT INTO pagos ({', '.join(cols)}, origen, creado)"
                 f" VALUES ({', '.join(['%s'] * len(cols))}, %s, %s)",
                 (*fila.values(), nombre_archivo, ahora))
            res["nuevas"] += 1
        pagos_importados.append(pago_id)
        res["importe"] += a_decimal(fila["importe"])

    conc = conciliar(ciclo)
    res.update({"conciliados": conc["aplicados"], "sin_inscripcion": conc["huerfanos"]})
    afectados = []
    if pagos_importados:
        marcas = ", ".join(["%s"] * len(pagos_importados))
        afectados = [r["inscripcion_id"] for r in db.q(
            f"SELECT DISTINCT inscripcion_id FROM pagos WHERE id IN ({marcas}) AND inscripcion_id IS NOT NULL",
            pagos_importados)]
    estados = estados_por_inscripcion(afectados, ciclo)
    res["validados"] = sum(e == "completo" for e in estados.values())
    res["observados"] = sum(e == "observado" for e in estados.values())
    res["parciales"] = sum(e == "parcial" for e in estados.values())

    db.x("INSERT INTO importaciones (archivo, filas, nuevas, actualizadas,"
         " omitidas, detalle, usuario_id, creado)"
         " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
         (f"[pagos] {nombre_archivo}"[:200], res["filas"], res["nuevas"],
          res["actualizadas"], res["omitidas"], "\n".join(res["avisos"][:200]),
          usuario_id, ahora))
    return res


# ---------------------------------------------------------------- conciliar
def conciliar(ciclo=None) -> dict:
    """Amarra cada pago con la inscripcion del alumno del mismo DNI.

    Solo toca pagos sueltos: uno ya aplicado no se mueve, para que no se
    pueda reutilizar."""
    ciclo = ciclo or config.CICLO
    aplicados = 0
    sueltos = db.q("SELECT p.id, p.dni FROM pagos p"
                   " WHERE p.inscripcion_id IS NULL AND p.ciclo = %s", (ciclo,))
    for p in sueltos:
        insc = db.q1(
            "SELECT i.id FROM inscripciones i JOIN alumnos a ON a.id = i.alumno_id"
            " WHERE a.dni = %s AND i.ciclo = %s", (p["dni"], ciclo))
        if insc:
            db.x("UPDATE pagos SET inscripcion_id = %s WHERE id = %s",
                 (insc["id"], p["id"]))
            aplicados += 1
    huerfanos = db.q1("SELECT COUNT(*) AS n FROM pagos"
                      " WHERE inscripcion_id IS NULL AND ciclo = %s", (ciclo,))
    return {"aplicados": aplicados, "huerfanos": huerfanos["n"] if huerfanos else 0}


# ------------------------------------------------------------ estado de pago
def _evaluar(conceptos, pagados, voucher_declarado):
    por_codigo = {}
    for p in pagados:
        por_codigo.setdefault(p["cod_pago"], []).append(p)
    detalle, faltan, observaciones = [], [], []
    if not conceptos:
        observaciones.append("Configura el tarifario de este ciclo.")
    conocidos = {c["codigo"] for c in conceptos}
    for codigo in por_codigo.keys() - conocidos:
        observaciones.append(f"Codigo {codigo} sin concepto activo en el tarifario.")
    for c in conceptos:
        movimientos = por_codigo.get(c["codigo"], [])
        p = movimientos[0] if movimientos else None
        esperado = _num(c["importe"])
        pagado = sum((_num(m["importe"]) for m in movimientos), Decimal("0")) if p else None
        avisos = []
        if p and len(movimientos) > 1:
            avisos.append("varios pagos para el mismo concepto; revisar, no se validan como cuotas")
        if p and (pagado != esperado or esperado <= 0):
            avisos.append(f"pagó S/ {pagado}; se exige S/ {esperado}")
        aviso = "; ".join(avisos)
        if aviso:
            observaciones.append(f"{c['nombre']}: {aviso}.")
        detalle.append({"codigo": c["codigo"], "nombre": c["nombre"],
                        "esperado": esperado, "fijo": True, "pago": p,
                        "movimientos": movimientos, "importe": pagado, "aviso": aviso})
        if c["obligatorio"] and not p:
            faltan.append(c["nombre"])
    clave = clave_voucher(voucher_declarado)
    voucher_ok = any(p["voucher_clave"] == clave for p in pagados) if clave else None
    if pagados:
        if not clave:
            observaciones.append("Falta el voucher o secuencia declarado en el formulario.")
        elif not voucher_ok:
            observaciones.append("El voucher declarado no coincide con los pagos de este DNI.")
    if not pagados:
        situacion = "sin_pago"
    elif faltan:
        situacion = "parcial"
    elif observaciones:
        situacion = "observado"
    else:
        situacion = "completo"
    return {"situacion": situacion, "detalle": detalle, "faltan": faltan,
            "observaciones": observaciones, "pagos": pagados,
            "total": sum((_num(p["importe"]) for p in pagados), Decimal("0")),
            "voucher_declarado": clave, "voucher_ok": voucher_ok}


def estado(inscripcion_id: int, ciclo=None, voucher_declarado=None) -> dict:
    """Misma validacion por codigo, monto y voucher que usa el listado."""
    insc = db.q1("SELECT ciclo, voucher, secuencia FROM inscripciones WHERE id = %s", (inscripcion_id,))
    ciclo = ciclo or (insc["ciclo"] if insc else config.CICLO)
    asegurar_tarifario(ciclo)
    if voucher_declarado is None:
        voucher_declarado = (insc.get("voucher") or insc.get("secuencia") or "") if insc else ""
    pagados = db.q("SELECT * FROM pagos WHERE inscripcion_id = %s AND ciclo = %s ORDER BY cod_pago, id",
                   (inscripcion_id, ciclo))
    return _evaluar(tarifario(ciclo), pagados, voucher_declarado)


def estados_por_inscripcion(ids, ciclo=None) -> dict:
    if not ids:
        return {}
    marcas = ", ".join(["%s"] * len(ids))
    inscripciones = db.q(f"SELECT id, ciclo, voucher, secuencia FROM inscripciones WHERE id IN ({marcas})", ids)
    filas = db.q(f"SELECT * FROM pagos WHERE inscripcion_id IN ({marcas}) ORDER BY cod_pago, id", ids)
    por_inscripcion = {}
    for p in filas:
        por_inscripcion.setdefault((p["inscripcion_id"], p["ciclo"]), []).append(p)
    tarifas = {}
    for i in inscripciones:
        if i["ciclo"] not in tarifas:
            asegurar_tarifario(i["ciclo"])
            tarifas[i["ciclo"]] = tarifario(i["ciclo"])
    return {i["id"]: _evaluar(tarifas[i["ciclo"]],
                             por_inscripcion.get((i["id"], i["ciclo"]), []),
                             i["voucher"] or i["secuencia"])["situacion"]
            for i in inscripciones}


def huerfanos(ciclo=None) -> list:
    """Pagos que no calzan con ninguna inscripcion (aun no llenaron el formulario)."""
    ciclo = ciclo or config.CICLO
    return db.q("SELECT * FROM pagos WHERE inscripcion_id IS NULL AND ciclo = %s"
                " ORDER BY nombre_banco, cod_pago", (ciclo,))
