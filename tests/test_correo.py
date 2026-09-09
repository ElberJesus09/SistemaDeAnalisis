import sys
import smtplib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config, correo, web, servidor


class Correo(unittest.TestCase):
    def setUp(self):
        self.cfg = patch.dict(config.SMTP, {
            'host': 'smtp.example.com', 'port': '465', 'scheme': 'smtps',
            'username': 'remitente@example.com', 'password': 'clave-prueba',
            'from_address': 'remitente@example.com', 'from_name': 'CPU UNPRG'})
        self.cfg.start()
        self.addCleanup(self.cfg.stop)
        self.datos = {'ciclo': '2026-II', 'dni': '99990001', 'nombres': 'ALUMNO PRUEBA', 'correo': 'alumno@example.com'}
        self.sesion = {'id': 1, 'n': 'sesion-prueba', 'rol': 'admin'}

    def pet(self, campos=None):
        return SimpleNamespace(sesion=self.sesion, campo=lambda k: (campos or {}).get(k, ''), arg=lambda k: '')

    def test_adjunto_destinatario_y_cifrado(self):
        with patch('app.correo.smtplib.SMTP_SSL') as ssl, patch('app.correo.smtplib.SMTP') as plano:
            smtp = ssl.return_value
            smtp.send_message.return_value = {}
            correo.enviar_ficha(self.datos, 'alumno@example.com', b'%PDF-1.7\nprueba')
            plano.assert_not_called()
            self.assertEqual(ssl.call_args.args[:2], ('smtp.example.com', 465))
            smtp.login.assert_called_once_with('remitente@example.com', 'clave-prueba')
            msg = smtp.send_message.call_args.args[0]
            self.assertEqual(msg['To'], 'alumno@example.com')
            self.assertEqual(smtp.send_message.call_args.kwargs['to_addrs'], ['alumno@example.com'])
            adjunto = list(msg.iter_attachments())[0]
            self.assertEqual(adjunto.get_content_type(), 'application/pdf')
            self.assertEqual(adjunto.get_payload(decode=True), b'%PDF-1.7\nprueba')
            self.assertNotIn('clave-prueba', msg.as_string())

    def test_starttls_antes_de_autenticar(self):
        with patch.dict(config.SMTP, {'scheme': 'starttls', 'port': '587'}), patch('app.correo.smtplib.SMTP') as cls:
            smtp = correo.conectar()
            nombres = [c[0] for c in smtp.method_calls]
            self.assertLess(nombres.index('starttls'), nombres.index('login'))

    def test_destinatarios_invalidos_no_conectan(self):
        with patch('app.correo.conectar') as conectar:
            for destinatario in ('', 'sin-correo', 'a@example.com,b@example.com', 'a@example.com\r\nBcc: b@example.com'):
                with self.assertRaises(ValueError):
                    correo.enviar_ficha(self.datos, destinatario, b'%PDF-1.7')
            conectar.assert_not_called()

    def test_token_sesion_registro_caducidad_y_doble_envio(self):
        token = correo.crear_token(self.sesion, 1)
        self.assertFalse(correo.consumir_token(token, {'n': 'otro'}, 1))
        self.assertFalse(correo.consumir_token(token, self.sesion, 2))
        self.assertTrue(correo.consumir_token(token, self.sesion, 1))
        self.assertFalse(correo.consumir_token(token, self.sesion, 1))
        with patch('app.correo.time.time', return_value=1):
            token = correo.crear_token(self.sesion, 1)
        self.assertFalse(correo.consumir_token(token, self.sesion, 1))

    def test_get_previsualiza_sin_enviar(self):
        with patch('app.web._datos_para_correo', return_value=self.datos), patch('app.correo.enviar_ficha') as enviar:
            html = web.ver_correo(self.pet(), '1')
            self.assertIn('alumno@example.com', html)
            self.assertIn('Enviar correo con PDF', html)
            self.assertNotIn('clave-prueba', html)
            enviar.assert_not_called()

    def test_post_envia_una_vez_y_registra(self):
        token = correo.crear_token(self.sesion, '1')
        pet = self.pet({'token': token, 'destinatario': 'alumno@example.com'})
        def generar(datos, destino):
            destino.write_bytes(b'%PDF-1.7')
            return destino
        with patch('app.web._datos_para_correo', return_value=self.datos), patch('app.web.ficha.a_pdf', side_effect=generar), patch('app.correo.enviar_ficha') as enviar, patch('app.web.auth.registrar') as registrar:
            self.assertEqual(web.enviar_correo(pet, '1').estado, 303)
            self.assertEqual(web.enviar_correo(pet, '1').estado, 409)
            enviar.assert_called_once_with(self.datos, 'alumno@example.com', b'%PDF-1.7')
            registrar.assert_called_once_with(1, 'correo_ficha', 'inscripcion 1', 'alumno@example.com')

    def test_faltantes_y_pago_bloquean_el_envio(self):
        with patch('app.web.ficha.datos_de_inscripcion', return_value=self.datos), patch('app.web.ficha.faltantes', return_value=['Colegio']):
            with self.assertRaisesRegex(ValueError, 'Completa primero'):
                web._datos_para_correo('1')
        with patch('app.web.ficha.datos_de_inscripcion', return_value=self.datos), patch('app.web.ficha.faltantes', return_value=[]), patch.object(config, 'EXIGIR_PAGO', True), patch('app.web.pagos.estado', return_value={'situacion': 'parcial'}):
            with self.assertRaisesRegex(ValueError, 'pago'):
                web._datos_para_correo('1')

    def test_error_smtp_sin_exponer_respuesta_privada(self):
        token = correo.crear_token(self.sesion, '1')
        pet = self.pet({'token': token, 'destinatario': 'alumno@example.com'})
        pdf = MagicMock()
        pdf.read_bytes.return_value = b'%PDF-1.7'
        with patch('app.web._datos_para_correo', return_value=self.datos), patch('app.web.ficha.a_pdf', return_value=pdf), patch('app.correo.enviar_ficha', side_effect=smtplib.SMTPAuthenticationError(535, b'contenido privado')), patch('app.web.auth.registrar') as registrar:
            r = web.enviar_correo(pet, '1')
            self.assertEqual(r.estado, 303)
            self.assertNotIn('contenido privado', str(r.cabeceras))
            registrar.assert_not_called()

    def test_rutas_exigen_sesion(self):
        rutas = [r for r in servidor.RUTAS if r[2] in (web.ver_correo, web.enviar_correo)]
        self.assertEqual(len(rutas), 2)
        self.assertTrue(all(r[3] == '*' for r in rutas))


if __name__ == '__main__':
    unittest.main()
