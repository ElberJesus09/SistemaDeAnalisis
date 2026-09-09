"""Contrato del CSV real: encabezados originales, respuestas ficticias."""
import csv
from datetime import datetime
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db, ficha, importador, web

RAIZ = Path(__file__).resolve().parents[1]
ENCABEZADOS = RAIZ / "ejemplos" / "encabezados_formulario_2026-II.csv"


class CsvReal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.usar_sqlite(Path(self.tmp.name) / "prueba.db")
        db.crear_esquema()

    def tearDown(self):
        db.cerrar()
        self.tmp.cleanup()

    def crear_csv(self):
        enc, _ = importador.leer_archivo_crudo(ENCABEZADOS)
        filas = []
        for dni, medio, fechas, menor in [
            ("12345678", "BANCO DE LA NACIÓN", ("02/07/2026", ""), "SI"),
            ("23456789", "PAGALO PE", ("", "03/07/2026"), "No"),
        ]:
            filas.append(["08/09/2026 18:00:00", "form@example.com", medio,
                          "SEDE CENTRAL", "ORDINARIA", "MAÑANA",
                          "1234567" if menor == "SI" else "", fechas[0], "0231",
                          "2345678-1" if menor == "No" else "", fechas[1], "DERECHO",
                          dni, "ANA", "PEREZ", "LOPEZ", "FEMENINO", "01/01/2000",
                          "999000111", "alumno@example.com", "LAMBAYEQUE", "CHICLAYO",
                          "LA VICTORIA", "CALLE UNO\nNUMERO 123", menor,
                          *(["MARIA", "TORRES", "DIAZ", "34567890", "999000222"] if menor == "SI" else [""] * 5),
                          "COLEGIO EJEMPLO", "PIURA", "SULLANA", "BELLAVISTA", "2025"])
        p = Path(self.tmp.name) / "respuestas.csv"
        with p.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(enc)
            w.writerows(filas)
        return p

    def test_35_columnas_todas_reconocidas(self):
        enc, filas = importador.leer_archivo_crudo(ENCABEZADOS)
        self.assertEqual(len(enc), 35)
        self.assertEqual(filas, [])
        self.assertEqual(enc[4], "MODALIDAD")
        for e in enc:
            self.assertIn(importador.normalizar_encabezado(e), importador.COLUMNAS | importador.REPETIDOS)

    def test_solo_encabezados_avisa_sin_crear_registros(self):
        with self.assertRaisesRegex(ValueError, "solo encabezados"):
            importador.importar(ENCABEZADOS)
        self.assertEqual(db.q1("SELECT COUNT(*) n FROM importaciones")["n"], 0)
        self.assertEqual(db.q1("SELECT COUNT(*) n FROM alumnos")["n"], 0)

    def test_importacion_dos_medios_y_reimportacion(self):
        p = self.crear_csv()
        r = importador.importar(p, ciclo="2027-I")
        self.assertEqual(r["nuevas"], 2)
        for dni, fecha, menor in [("12345678", "02/07/2026", True), ("23456789", "03/07/2026", False)]:
            alumno = db.q1("SELECT * FROM alumnos WHERE dni=%s", (dni,))
            insc = db.q1("SELECT * FROM inscripciones WHERE alumno_id=%s", (alumno["id"],))
            self.assertEqual(insc["modalidad"], "ORDINARIA")
            self.assertEqual(insc["fecha_pago"], fecha)
            self.assertEqual(insc["correo_form"], "form@example.com")
            self.assertEqual(insc["fecha_matricula"], "08/09/2026")
            self.assertEqual(insc["marca_temporal"], "08/09/2026 18:00:00")
            self.assertEqual(alumno["correo"], "alumno@example.com")
            self.assertEqual(alumno["departamento"], "LAMBAYEQUE")
            self.assertEqual(alumno["colegio_departamento"], "PIURA")
            self.assertEqual(alumno["distrito"], "LA VICTORIA")
            self.assertEqual(alumno["colegio_distrito"], "BELLAVISTA")
            self.assertEqual(alumno["direccion"], "CALLE UNO NUMERO 123")
            self.assertEqual(alumno["apo_ap_paterno"], "TORRES" if menor else "")
            datos = ficha.datos_de_inscripcion(insc["id"])
            edicion = web._fila_completa(insc["id"])
            self.assertEqual(edicion["menor_edad"], "Sí" if menor else "No")
            self.assertEqual(edicion["colegio_departamento"], "PIURA")
            self.assertEqual(edicion["colegio_provincia"], "SULLANA")
            self.assertEqual(edicion["colegio_distrito"], "BELLAVISTA")
            self.assertEqual(edicion["apo_ap_paterno"], "TORRES" if menor else "")
            self.assertEqual(edicion["apo_ap_materno"], "DIAZ" if menor else "")
            self.assertEqual(datos["modalidad"], "ORDINARIA")
            self.assertEqual(datos["ciclo"], "2027-I")
            self.assertEqual(ficha.preparar(datos)["tiene_apoderado"], menor)
        db.x("UPDATE inscripciones SET modalidad='EXTRAORDINARIA', fecha_matricula='10/09/2026' WHERE id=1")
        db.x("UPDATE inscripciones SET fecha_matricula='' WHERE id=2")
        r = importador.importar(p, ciclo="2027-I")
        self.assertEqual(r["nuevas"], 0)
        self.assertEqual(r["actualizadas"], 2)
        self.assertEqual(db.q1("SELECT modalidad FROM inscripciones WHERE id=1")["modalidad"], "EXTRAORDINARIA")
        self.assertEqual(db.q1("SELECT fecha_matricula FROM inscripciones WHERE id=1")["fecha_matricula"], "10/09/2026")
        self.assertEqual(db.q1("SELECT fecha_matricula FROM inscripciones WHERE id=2")["fecha_matricula"], "08/09/2026")

    def test_matricula_desde_marca_temporal_csv_y_excel(self):
        for valor in ("8/09/2026 19:16:44", datetime(2026, 9, 8, 19, 16, 44)):
            self.assertEqual(importador._limpiar({"marca_temporal": valor})["fecha_matricula"], "08/09/2026")
        for valor in ("", None, "31/02/2026 19:16:44", "sin fecha"):
            self.assertEqual(importador._limpiar({"marca_temporal": valor})["fecha_matricula"], "")

    def test_migracion_conserva_inscripciones(self):
        db.x("ALTER TABLE inscripciones DROP COLUMN modalidad")
        self.assertIn("inscripciones.modalidad", db.migrar())
        self.assertEqual(db.verificar_tablas(), "")


if __name__ == "__main__":
    unittest.main()
