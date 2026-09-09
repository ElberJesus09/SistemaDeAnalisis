"""La ficha usa el ciclo de la inscripcion y las firmas que correspondan."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ficha


class FichaCondicional(unittest.TestCase):
    def test_adulto_sin_apoderado(self):
        html = ficha.construir_html({"menor_edad": "No", "ciclo": "2027-I"})
        self.assertNotIn("DATOS DEL APODERADO", html)
        self.assertNotIn("Firma apoderado", html)
        self.assertIn("Firma de alumno", html)
        self.assertEqual(html.count("2027-I"), 4)
        self.assertNotIn("2026-II", html)

    def test_menor_con_apoderado(self):
        html = ficha.construir_html({"menor_edad": "Sí", "apo_nombres": "ANA",
                                     "apo_ap_paterno": "PEREZ", "apo_dni": "12345678"})
        self.assertIn("DATOS DEL APODERADO", html)
        self.assertIn("Firma apoderado", html)
        self.assertIn("ANA PEREZ", html)
        self.assertIn("DNI: 12345678", html)

    def test_adulto_omite_apoderado_aunque_tenga_datos_guardados(self):
        html = ficha.construir_html({"menor_edad": "No", "apo_nombres": "ANA"})
        self.assertNotIn("Firma apoderado", html)
        self.assertNotIn("DATOS DEL APODERADO", html)
        self.assertNotIn("DNI de apoderado", html)
        self.assertNotIn("Apoderado", ficha.faltantes({"menor_edad": "No"}))
        self.assertNotIn("Parentesco", ficha.faltantes({"menor_edad": "No"}))

    def test_menor_sin_datos_reserva_espacio_y_exige_completarlos(self):
        html = ficha.construir_html({"menor_edad": "Sí"})
        self.assertIn("Firma apoderado", html)
        self.assertIn("Apoderado", ficha.faltantes({"menor_edad": "Sí"}))

    def test_etiquetas_castellano_y_secuencia(self):
        datos = ficha.preparar({"sexo": "male", "apo_parentesco": "father",
                               "secuencia": "1234567-1"})
        self.assertEqual(datos["sexo"], "Masculino")
        self.assertEqual(datos["apo_parentesco"], "Padre")
        self.assertEqual(datos["voucher"], "1234567-1")

    def test_nombres_no_insertan_html(self):
        html = ficha.construir_html({"apo_nombres": "<script>prueba</script>"})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
