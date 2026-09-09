"""Pruebas del reporte bancario y la validacion; solo usan SQLite temporal."""
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import auth, db, pagos, servidor, web, config
from openpyxl import Workbook


class ValidacionPagos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.usar_sqlite(Path(self.tmp.name) / "prueba.db")
        db.crear_esquema()
        self.admin = auth.crear_usuario("prueba", "Prueba", "claveprueba", "admin")
        self.insc = self.inscripcion("12345678", "2026-II")

    def tearDown(self):
        db.cerrar()
        self.tmp.cleanup()

    def inscripcion(self, dni, ciclo):
        alumno = db.q1("SELECT id FROM alumnos WHERE dni=%s", (dni,))
        aid = alumno["id"] if alumno else db.x(
            "INSERT INTO alumnos(dni,creado,actualizado) VALUES (%s,%s,%s)",
            (dni, "2026-09-08", "2026-09-08"))
        return db.x("INSERT INTO inscripciones(alumno_id,ciclo,voucher,creado,actualizado) VALUES (%s,%s,%s,%s,%s)",
                    (aid, ciclo, "1234567-1", "2026-09-08", "2026-09-08"))

    def archivo(self, importes=(200, 750), extras=()):
        wb = Workbook()
        ws = wb.active
        ws.append(["NRO", "COD.", "COD_ALUMNO", "DOCUMENTO", "VOUCHER", "CODIGO_TDOC",
                   "NOMBRE_TDOC", "SITUACION", "COD_PAGO", "CONCEPTO_PAGO", "APELLIDOS_NOMBRES",
                   "CUENTA", "FECHA_PAGO", "HORA", "IMPORTE_S/.", "CAJ.", "AGE."])
        for index, (cod, importe) in enumerate(zip((1096, 1097), importes)):
            ws.append([index + 1, "004", "-", 123456780000, 81234567 + index, "01", "DNI",
                       "00090009", cod, "", "ALUMNO DE PRUEBA", "0301029403",
                       datetime(2026, 7, 2), "09:57:20", importe, "3709", "0231"])
        for row in extras:
            ws.append(row)
        path = Path(self.tmp.name) / "banco.xlsx"
        wb.save(path)
        wb.close()
        return path

    def test_excel_numerico_dni_codigo_y_reimportacion(self):
        path = self.archivo()
        r = pagos.importar(path)
        self.assertEqual(r["nuevas"], 2)
        self.assertEqual(pagos.estado(self.insc)["situacion"], "completo")
        self.assertEqual(pagos.estados_por_inscripcion([self.insc])[self.insc], "completo")
        p = db.q1("SELECT * FROM pagos WHERE cod_pago='00001096'")
        self.assertEqual(p["dni"], "12345678")
        self.assertEqual(p["fecha_pago"], "02/07/2026")
        self.assertEqual(p["agencia"], "0231")
        self.assertEqual(pagos.importar(path)["actualizadas"], 2)
        self.assertEqual(db.q1("SELECT COUNT(*) n FROM pagos")["n"], 2)

    def test_100_y_550_no_validan(self):
        for importes in ((100, 750), (200, 550), (100, 550), (250, 750)):
            with self.subTest(importes=importes):
                pagos.importar(self.archivo(importes))
                self.assertEqual(pagos.estado(self.insc)["situacion"], "observado")
                self.assertEqual(pagos.estados_por_inscripcion([self.insc])[self.insc], "observado")

    def test_voucher_incorrecto_y_secuencia(self):
        pagos.importar(self.archivo())
        db.x("UPDATE inscripciones SET voucher='9999999-1' WHERE id=%s", (self.insc,))
        self.assertEqual(pagos.estado(self.insc)["situacion"], "observado")
        self.assertEqual(pagos.estados_por_inscripcion([self.insc])[self.insc], "observado")
        db.x("UPDATE inscripciones SET voucher='',secuencia='1234567-1' WHERE id=%s", (self.insc,))
        self.assertEqual(pagos.estado(self.insc)["situacion"], "completo")
        db.x("UPDATE inscripciones SET secuencia='' WHERE id=%s", (self.insc,))
        self.assertEqual(pagos.estado(self.insc)["situacion"], "observado")

    def test_pago_no_se_reutiliza_en_otro_ciclo(self):
        path = self.archivo()
        pagos.importar(path)
        otra = self.inscripcion("12345678", "2027-I")
        r = pagos.importar(path, ciclo="2027-I")
        self.assertEqual(r["omitidas"], 2)
        self.assertEqual(pagos.estado(otra)["situacion"], "sin_pago")
        self.assertEqual(pagos.estado(self.insc)["situacion"], "completo")
        self.assertEqual(pagos.estados_por_inscripcion([self.insc, otra]),
                         {self.insc: "completo", otra: "sin_pago"})

    def test_pago_antes_del_formulario(self):
        db.x("DELETE FROM inscripciones WHERE id=%s", (self.insc,))
        self.assertEqual(pagos.importar(self.archivo())["sin_inscripcion"], 2)
        nueva = self.inscripcion("12345678", "2026-II")
        self.assertEqual(pagos.conciliar()["aplicados"], 2)
        self.assertEqual(pagos.estado(nueva)["situacion"], "completo")

    def test_codigos_desconocidos_y_pagos_multiples(self):
        pagos.importar(self.archivo())
        db.x("UPDATE pagos SET cod_pago='00009999' WHERE cod_pago='00001097'")
        e = pagos.estado(self.insc)
        self.assertEqual(e["situacion"], "parcial")
        self.assertTrue(any("00009999" in x for x in e["observaciones"]))
        db.x("UPDATE pagos SET cod_pago='00001097' WHERE cod_pago='00009999'")
        db.x("INSERT INTO pagos(dni,voucher,cod_pago,importe,ciclo,inscripcion_id,creado) VALUES ('12345678','7777777','00001096',100,'2026-II',%s,'2026-09-08')", (self.insc,))
        self.assertEqual(pagos.estado(self.insc)["situacion"], "observado")

    def test_monto_malformado_omitido(self):
        for invalido in ("abc", "NaN", "-100", "0", "1,234", "1.234"):
            with self.subTest(invalido=invalido):
                r = pagos.importar(self.archivo((invalido, 750)))
                self.assertEqual(r["omitidas"], 1)
                self.assertIsNone(db.q1("SELECT id FROM pagos WHERE cod_pago='00001096'"))

    def test_faltan_columnas_no_importa(self):
        with patch.object(pagos, "leer_archivo_crudo", return_value=(["DOCUMENTO", "COD_PAGO"], [])):
            with self.assertRaisesRegex(ValueError, "Faltan columnas"):
                pagos.importar("banco.xlsx")

    def test_documento_no_inventa_otros_ocho_digitos(self):
        self.assertEqual(pagos.normalizar_documento(123456780000.0), "12345678")
        self.assertEqual(pagos.normalizar_documento("123456789012"), "")
        self.assertEqual(pagos.normalizar_documento("DNI 12345678"), "")

    def peticion(self, campos=None, consulta=None):
        p = servidor.Peticion("GET", "/tarifario", consulta or {}, campos or {}, {}, {})
        p.sesion = {"id": self.admin, "rol": "admin", "nombre": "Prueba"}
        return p

    def test_tarifario_editar_y_validacion(self):
        pagos.asegurar_tarifario()
        concepto = db.q1("SELECT id FROM conceptos_pago WHERE codigo='00001097'")
        html = web.ver_tarifario(self.peticion(consulta={"editar": str(concepto["id"])}))
        self.assertIn('value="750.00"', html)
        web.guardar_tarifario(self.peticion({"codigo": "1097", "nombre": "Ciclo", "importe": "550", "obligatorio": "1"}))
        self.assertEqual(db.q1("SELECT importe FROM conceptos_pago WHERE codigo='00001097'")["importe"], 550)
        web.guardar_tarifario(self.peticion({"codigo": "1097", "nombre": "Ciclo", "importe": "NaN"}))
        self.assertEqual(db.q1("SELECT importe FROM conceptos_pago WHERE codigo='00001097'")["importe"], 550)

    def test_ficha_exigida_bloquea_pago_observado(self):
        pagos.importar(self.archivo((100, 750)))
        with patch.object(config, "EXIGIR_PAGO", True), \
             patch.object(web.ficha, "datos_de_inscripcion", return_value={"ciclo": "2026-II"}), \
             patch.object(web.ficha, "faltantes", return_value=[]), \
             patch.object(web.ficha, "a_pdf") as pdf:
            respuesta = web.descargar_ficha(self.peticion(), str(self.insc))
            self.assertEqual(respuesta.estado, 303)
            pdf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
