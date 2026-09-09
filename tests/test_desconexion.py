"""Regresiones para desconexiones al enviar respuestas HTTP."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.servidor import Manejador, Respuesta


class PruebasDesconexion(unittest.TestCase):
    def manejador(self):
        h = object.__new__(Manejador)
        h.command = 'GET'
        h.path = '/static/prueba.css'
        h.close_connection = False
        h.send_response = Mock()
        h.send_header = Mock()
        h.end_headers = Mock()
        h.wfile = Mock()
        h._estatico = Mock(return_value=Respuesta('contenido'))
        return h

    def test_desconexion_no_reintenta_respuesta(self):
        for error in (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            for etapa in ('end_headers', 'wfile'):
                with self.subTest(error=error, etapa=etapa):
                    h = self.manejador()
                    destino = h.end_headers if etapa == 'end_headers' else h.wfile.write
                    destino.side_effect = error(10053, 'conexion cerrada')
                    with patch('sys.stdout', new_callable=io.StringIO) as salida:
                        h._atender('GET')
                    self.assertTrue(h.close_connection)
                    h.send_response.assert_called_once_with(200)
                    self.assertEqual(salida.getvalue(), '')

    def test_desconexion_durante_respuesta_de_error(self):
        h = self.manejador()
        h._estatico.side_effect = ValueError('fallo interno')
        h.end_headers.side_effect = ConnectionAbortedError(10053, 'cerrada')
        with patch('sys.stdout', new_callable=io.StringIO) as salida:
            h._atender('GET')
        self.assertIn('fallo interno', salida.getvalue())
        h.send_response.assert_called_once_with(500)
        self.assertTrue(h.close_connection)

    def test_error_distinto_no_se_oculta(self):
        h = self.manejador()
        h.wfile.write.side_effect = OSError('otro fallo')
        with self.assertRaises(OSError):
            h._responder(Respuesta('contenido'))


if __name__ == '__main__':
    unittest.main()
