import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import copias, db, importador, sync_google, web


class Automaticos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        db.usar_sqlite(self.raiz / 'prueba.db')
        db.crear_esquema()
        self.ajustes = patch.object(copias, 'AJUSTES', self.raiz / 'ajustes.json')
        self.estado = patch.object(copias, 'ESTADO', self.raiz / 'estado.json')
        self.ajustes.start()
        self.estado.start()
        self.addCleanup(self.ajustes.stop)
        self.addCleanup(self.estado.stop)

    def tearDown(self):
        db.cerrar()
        self.tmp.cleanup()

    def test_copia_atomica_configurable_y_fallo_conserva_anterior(self):
        destino = self.raiz / 'Mis copias'
        copias.guardar_opciones(str(destino), 24, True)
        self.assertTrue(copias.pendiente())
        def exportar(archivo):
            archivo.write('CREATE TABLE prueba (id INT);')
            return {'prueba': 0}
        with patch.object(copias, 'exportar_sql', side_effect=exportar):
            resultado = copias.crear()
        self.assertTrue(resultado['ok'])
        archivo = Path(resultado['archivo'])
        self.assertEqual(archivo.parent, destino)
        with zipfile.ZipFile(archivo) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(json.loads(z.read('resumen.json'))['tablas'], {'prueba': 0})
        self.assertFalse(copias.pendiente())
        with patch.object(copias, 'exportar_sql', side_effect=OSError('prueba')):
            self.assertFalse(copias.crear()['ok'])
        self.assertTrue(archivo.is_file())
        self.assertEqual(list(destino.glob('*.tmp')), [])
        copias.guardar_opciones(str(self.raiz / 'otro'), 24, True)
        self.assertTrue(copias.pendiente())
        copias.guardar_opciones(str(destino), 24, False)
        self.assertFalse(copias.pendiente())

    def test_destino_y_frecuencia_invalidos(self):
        with self.assertRaises(ValueError):
            copias.guardar_opciones('relativa', 24, True)
        for h in (0, 169, 'texto'):
            with self.assertRaises(ValueError):
                copias.guardar_opciones(str(self.raiz), h, True)

    def test_clasificacion_por_registro_no_por_matricula(self):
        p = self.raiz / 'filas.csv'
        with p.open('w', encoding='utf-8', newline='') as f:
            csv.writer(f).writerows([
                ['DNI', 'NOMBRE COMPLETO', 'Marca temporal'],
                ['12345678', 'PRIMERO', '8/09/2026 23:59:59'],
                ['23456789', 'SEGUNDO', '9/09/2026 00:00:01'],
                ['34567890', 'SIN FECHA', '']])
        importador.importar(p, ciclo='2026-II')
        db.x("UPDATE inscripciones SET fecha_matricula='10/09/2026'")
        filtros = {'q':'', 'ciclo':'2026-II', 'carrera':'', 'estado':'', 'pago':''}
        filas = web._buscar(filtros)
        self.assertEqual([r['dni'] for r in filas], ['23456789', '12345678', '34567890'])
        self.assertEqual(len(web._buscar({**filtros, 'fecha':'2026-09-08'})), 1)
        self.assertEqual(len(web._buscar({**filtros, 'fecha':'2026-09-10'})), 0)

    def test_sync_no_duplica_omite_demo_y_reintenta(self):
        credencial = self.raiz / 'credencial.json'
        credencial.write_text('{}')
        opciones = {'activo':True, 'spreadsheet_id':'prueba', 'sheet_id':'1', 'ciclo':'2026-II',
                    'intervalo':300, 'credenciales':credencial, 'dni_omitidos':{'99990001'}}
        filas = [['Marca temporal','DNI','NOMBRE COMPLETO'],
                 ['08/09/2026 12:00:00','99990001','DEMO'],
                 ['09/09/2026 10:00:00','12345678','ANA']]
        with patch.object(sync_google, 'opciones', return_value=opciones), patch.object(sync_google, '_archivo_estado', self.raiz / 'sync.json'), patch.object(sync_google, 'leer_google', return_value=filas) as leer:
            self.assertIn('1 nueva', sync_google.sincronizar())
            self.assertEqual(db.q1('SELECT COUNT(*) n FROM alumnos')['n'], 1)
            self.assertIn('Sin respuestas nuevas', sync_google.sincronizar())
            self.assertEqual(db.q1('SELECT COUNT(*) n FROM importaciones')['n'], 1)
            leer.side_effect = OSError('token privado')
            mensaje = sync_google.sincronizar()
            self.assertNotIn('token privado', mensaje)
            self.assertTrue(sync_google.estado()['error'])
            leer.side_effect = None
            filas.append(['09/09/2026 11:00:00','23456789','LUIS'])
            self.assertIn('1 nueva', sync_google.sincronizar())
            self.assertEqual(db.q1('SELECT COUNT(*) n FROM alumnos')['n'], 2)
            self.assertFalse(sync_google.estado()['error'])

    def test_rutas_configuracion_solo_admin(self):
        from app.servidor import RUTAS
        funciones = {web.ver_copias,web.configurar_copias,web.crear_copia,web.ver_google_sheets,web.sincronizar_google_sheets}
        self.assertTrue(all(rol == 'admin' for _,_,fn,rol in RUTAS if fn in funciones))


if __name__ == '__main__':
    unittest.main()
