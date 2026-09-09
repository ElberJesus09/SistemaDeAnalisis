"""Evita que el lanzador abra un programa ajeno al compartir puerto."""
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import servidor
import escritorio


class PruebasArranque(unittest.TestCase):
    def test_puerto_reservado_no_se_comparte(self):
        with servidor.crear(0) as activo:
            puerto = activo.server_address[1]
            with socket.socket() as otro:
                otro.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                with self.assertRaises(OSError):
                    otro.bind(("127.0.0.1", puerto))

    def test_error_de_arranque_no_abre_navegador(self):
        with patch.object(escritorio.config, "MODO", "servidor"), \
             patch.object(escritorio, "arrancar_servidor", side_effect=SystemExit(1)), \
             patch.object(escritorio, "abrir_ventana") as ventana:
            with self.assertRaises(SystemExit):
                escritorio.main()
            ventana.assert_not_called()


if __name__ == "__main__":
    unittest.main()
