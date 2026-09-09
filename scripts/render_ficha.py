"""
Genera una Constancia de Matricula sin pasar por el panel (util para probar
cambios en la plantilla).

    python scripts/render_ficha.py                  # datos de demostracion
    python scripts/render_ficha.py datos.json       # datos de un archivo JSON
    python scripts/render_ficha.py --inscripcion 12 # sacandolos de la base
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, ficha  # noqa: E402

DEMO = {
    "ciclo": config.CICLO,
    "nombres": "ELBER JESUS SANCHEZ QUIROZ",
    "dni": "12345678",
    "nacimiento": "01/07/2001",
    "sexo": "Masculino",
    "telefono": "937635827",
    "correo": "recursos0901@gmail.com",
    "direccion": "PACHACUTEC 149, TAMBOPATA, TAMBOPATA, MADRE DE DIOS",
    "apo_nombres": "ELBER JESUS QUISPE QUIROZ",
    "apo_dni": "12345673",
    "apo_telefono": "937635827",
    "apo_parentesco": "Padre",
    "colegio": "COLEGIO TEST ACADEMICO",
    "colegio_ubicacion": "MOQUEGUA / MARISCAL NIETO / CARUMAS",
    "colegio_egreso": "2019",
    "carrera": "ADMINISTRACIÓN",
    "sede": config.SEDE,
    "turno": "Mañana",
    "fecha_matricula": "12/06/2026",
    "voucher": "052135",
    "agencia": "0230",
    "fecha_pago": "12/06/2026",
}


def main():
    args = sys.argv[1:]
    if args and args[0] == "--inscripcion":
        ruta = ficha.generar(int(args[1]))
    else:
        datos = json.loads(Path(args[0]).read_text(encoding="utf-8")) if args else DEMO
        nombre = (f"constancia_{datos.get('dni', 'demo')}_"
                  f"{datos.get('ciclo', config.CICLO)}.pdf")
        ruta = ficha.a_pdf(datos, config.SALIDA / nombre)
    print("PDF generado:", ruta)


if __name__ == "__main__":
    main()
