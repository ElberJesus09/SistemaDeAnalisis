"""
Genera la Constancia de Matricula en PDF a partir de la plantilla HTML.
Garantiza que el resultado ocupe siempre UNA sola hoja A4.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config, db

MARGEN_PT = 13.5                                   # igual que el @page de la plantilla
ALTO_UTIL_PX = (297 - 2 * MARGEN_PT * 25.4 / 72) * 96 / 25.4
ANCHO_UTIL_PX = round((210 - 2 * MARGEN_PT * 25.4 / 72) * 96 / 25.4)

CAMPOS = [
    "ciclo", "nombres", "dni", "nacimiento", "sexo", "telefono", "correo",
    "direccion", "apo_nombres", "apo_dni", "apo_telefono", "apo_parentesco",
    "colegio", "colegio_ubicacion", "colegio_egreso", "carrera", "sede", "modalidad",
    "turno", "fecha_matricula", "voucher", "agencia", "fecha_pago",
]

# Partes sueltas que el formulario nuevo trae por separado y la ficha muestra
# ya juntas.
PARTES_COLEGIO = ("colegio_departamento", "colegio_provincia", "colegio_distrito")
PARTES_APODERADO = ("apo_nombres", "apo_ap_paterno", "apo_ap_materno")

# Sin estos datos la ficha no se puede emitir.
OBLIGATORIOS_BASE = [
    "sexo", "colegio", "colegio_ubicacion", "colegio_egreso",
    "turno", "fecha_matricula",
]
# El formulario pide el apoderado solo a los menores de edad, asi que a un
# alumno mayor no se le exige.
OBLIGATORIOS_APODERADO = [
    "apo_nombres", "apo_dni", "apo_telefono", "apo_parentesco",
]
OBLIGATORIOS = OBLIGATORIOS_BASE + OBLIGATORIOS_APODERADO

ETIQUETAS = {
    "sexo": "Sexo", "colegio": "Colegio", "colegio_ubicacion": "Ubicación del colegio",
    "colegio_egreso": "Año de egreso", "apo_nombres": "Apoderado",
    "apo_dni": "DNI del apoderado", "apo_telefono": "Teléfono del apoderado",
    "apo_parentesco": "Parentesco", "turno": "Turno",
    "fecha_matricula": "Fecha de matrícula", "carrera": "Carrera",
}


def _t(v) -> str:
    return "" if v is None else str(v).strip()


def datos_de_inscripcion(inscripcion_id: int) -> dict:
    """Arma el diccionario de la ficha juntando alumno + inscripcion."""
    r = db.q1(
        "SELECT i.*, a.dni, a.nombres, a.ap_paterno, a.ap_materno, a.nacimiento,"
        " a.sexo, a.telefono, a.correo, a.departamento, a.provincia, a.distrito,"
        " a.direccion, a.menor_edad, a.colegio, a.colegio_departamento,"
        " a.colegio_provincia, a.colegio_distrito, a.colegio_ubicacion,"
        " a.colegio_egreso, a.apo_nombres, a.apo_ap_paterno, a.apo_ap_materno,"
        " a.apo_dni, a.apo_telefono, a.apo_parentesco"
        " FROM inscripciones i JOIN alumnos a ON a.id = i.alumno_id"
        " WHERE i.id = %s", (inscripcion_id,))
    if not r:
        raise LookupError(f"No existe la inscripcion {inscripcion_id}")

    nombre = " ".join(x for x in (_t(r["nombres"]), _t(r["ap_paterno"]),
                                  _t(r["ap_materno"])) if x)
    direccion = ", ".join(x for x in (_t(r["direccion"]), _t(r["distrito"]),
                                      _t(r["provincia"]), _t(r["departamento"])) if x)
    d = {c: _t(r.get(c)) for c in CAMPOS if c in r}
    d.update({
        "nombres": nombre,
        "direccion": direccion,
        "ciclo": _t(r["ciclo"]) or config.CICLO,
        "sede": _t(r["sede"]) or config.SEDE,
        "colegio_ubicacion": ubicacion_colegio(r),
        "apo_nombres": nombre_apoderado(r) or _t(r.get("apo_nombres")),
        "menor_edad": _t(r.get("menor_edad")),
    })
    return d


def ubicacion_colegio(fila: dict) -> str:
    """'DEPARTAMENTO / PROVINCIA / DISTRITO' con lo que haya.

    El formulario nuevo trae las tres partes por separado; si no vinieran, se
    usa el texto que alguien haya escrito a mano en colegio_ubicacion."""
    partes = [_t(fila.get(c)) for c in PARTES_COLEGIO]
    if any(partes):
        return " / ".join(p for p in partes if p)
    return _t(fila.get("colegio_ubicacion"))


def nombre_apoderado(fila: dict) -> str:
    partes = [_t(fila.get(c)) for c in PARTES_APODERADO]
    return " ".join(p for p in partes if p)


def tiene_apoderado(fila: dict) -> bool:
    """Los mayores no llevan apoderado, aunque queden datos antiguos."""
    if _t(fila.get("menor_edad")).lower().startswith("n"):
        return False
    return (_t(fila.get("menor_edad")).lower().startswith("s") or
            any(_t(fila.get(c)) for c in
                (*PARTES_APODERADO, "apo_dni", "apo_telefono", "apo_parentesco")))


def obligatorios_de(fila: dict) -> list:
    """Que campos se le exigen a ESTE alumno.

    A un mayor de edad no se le pide apoderado: el formulario solo se lo
    pregunta a los menores."""
    if _t(fila.get("menor_edad")).lower().startswith("n"):
        return list(OBLIGATORIOS_BASE)
    return OBLIGATORIOS_BASE + OBLIGATORIOS_APODERADO


def faltantes(fila: dict) -> list:
    """Nombres legibles de los campos obligatorios que estan vacios."""
    valores = dict(fila)
    valores["colegio_ubicacion"] = ubicacion_colegio(fila)
    if not _t(valores.get("apo_nombres")):
        valores["apo_nombres"] = nombre_apoderado(fila)
    return [ETIQUETAS.get(c, c) for c in obligatorios_de(fila)
            if not _t(valores.get(c))]


def preparar(datos: dict) -> dict:
    f = {c: "" for c in CAMPOS}
    f.update({k: _t(v) for k, v in datos.items() if k in CAMPOS})
    f["ciclo"] = f["ciclo"] or config.CICLO
    f["sede"] = f["sede"] or config.SEDE
    f["tiene_apoderado"] = tiene_apoderado(datos)
    f["apo_nombres"] = nombre_apoderado(datos)
    f["sexo"] = {"male": "Masculino", "female": "Femenino"}.get(
        f["sexo"].lower(), f["sexo"])
    f["apo_parentesco"] = {
        "father": "Padre", "mother": "Madre", "guardian": "Tutor(a)",
        "brother": "Hermano", "sister": "Hermana", "uncle": "Tío", "aunt": "Tía",
        "grandfather": "Abuelo", "grandmother": "Abuela",
    }.get(f["apo_parentesco"].lower(), f["apo_parentesco"])
    f["voucher"] = f["voucher"] or _t(datos.get("secuencia"))
    dni = "".join(c for c in f["dni"] if c.isdigit())[:8]
    f["dni_casillas"] = list(dni.ljust(8))
    return f


def construir_html(datos: dict) -> str:
    env = Environment(loader=FileSystemLoader(config.APP / "templates"),
                      autoescape=select_autoescape(["html"]))
    return env.get_template("ficha/constancia.html").render(
        f=preparar(datos), base=config.APP.as_uri())


def a_pdf(datos: dict, destino: Path) -> Path:
    """Renderiza una hoja A4 conservando un espacio util para las firmas."""
    from playwright.sync_api import sync_playwright

    destino = Path(destino).resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp.html")
    tmp.write_text(construir_html(datos), encoding="utf-8")
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            # El viewport debe medir lo mismo que la caja imprimible; si no,
            # la medicion del alto sale falseada y el PDF se parte en dos.
            pag = nav.new_page(viewport={"width": ANCHO_UTIL_PX, "height": 1200})
            pag.goto(tmp.as_uri(), wait_until="networkidle")
            pag.evaluate("document.fonts.ready")
            ajuste = pag.evaluate(
                """(limite) => {
                    const h = document.getElementById('hoja');
                    let z = 1;
                    for (let i = 0; i < 6; i++) {
                        h.style.zoom = z;
                        const alto = h.getBoundingClientRect().height;
                        if (alto <= limite) break;
                        z = Math.max(0.90, z * (limite / alto) - 0.002);
                    }
                    return h.getBoundingClientRect().height <= limite;
                }""", ALTO_UTIL_PX)
            if not ajuste:
                nav.close()
                raise ValueError("Los datos son demasiado extensos para una ficha A4 legible. "
                                 "Revisa los campos largos antes de emitirla.")
            # margin=0 porque el margen ya esta en el @page de la plantilla
            pag.pdf(path=str(destino), format="A4", print_background=True,
                    prefer_css_page_size=False,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            nav.close()
    finally:
        tmp.unlink(missing_ok=True)
    return destino


def generar(inscripcion_id: int, carpeta=None) -> Path:
    d = datos_de_inscripcion(inscripcion_id)
    carpeta = Path(carpeta) if carpeta else config.SALIDA
    nombre = f"constancia_{d['dni'] or inscripcion_id}_{d['ciclo']}.pdf"
    return a_pdf(d, carpeta / nombre)
