"""
Servidor HTTP del panel. Usa solo la libreria estandar (ThreadingHTTPServer),
para que instalar el sistema no dependa de un framework web.

Piezas: enrutador por decorador, lectura de formularios (incluida la subida
de archivos multipart) y servido de archivos estaticos.
"""
import html
import mimetypes
import re
import socket
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import config

RUTAS = []          # (metodo, regex, funcion, requiere_rol)


# --------------------------------------------------------------- peticion
class Peticion:
    def __init__(self, metodo, ruta, consulta, campos, archivos, cookies):
        self.metodo = metodo
        self.ruta = ruta
        self.consulta = consulta      # ?a=1  -> {"a": "1"}
        self.campos = campos          # formulario -> {"nombre": "valor"}
        self.archivos = archivos      # {"campo": (nombre_archivo, bytes)}
        self.cookies = cookies
        self.sesion = None

    def campo(self, nombre, por_defecto=""):
        return self.campos.get(nombre, por_defecto)

    def arg(self, nombre, por_defecto=""):
        return self.consulta.get(nombre, por_defecto)


class Respuesta:
    def __init__(self, cuerpo=b"", estado=200, tipo="text/html; charset=utf-8",
                 cabeceras=None):
        if isinstance(cuerpo, str):
            cuerpo = cuerpo.encode("utf-8")
        self.cuerpo = cuerpo
        self.estado = estado
        self.tipo = tipo
        self.cabeceras = cabeceras or []

    def cookie(self, nombre, valor, dias=None):
        trozos = [f"{nombre}={valor}", "Path=/", "HttpOnly", "SameSite=Lax"]
        if dias == 0:
            trozos.append("Max-Age=0")
        elif dias:
            trozos.append(f"Max-Age={int(dias * 86400)}")
        self.cabeceras.append(("Set-Cookie", "; ".join(trozos)))
        return self


def redirigir(destino, mensaje=None):
    if mensaje:
        from urllib.parse import quote
        destino += ("&" if "?" in destino else "?") + "msg=" + quote(mensaje)
    return Respuesta(b"", 303, cabeceras=[("Location", destino)])


def ruta(metodo, patron, rol=None):
    def envoltura(fn):
        RUTAS.append((metodo, re.compile(f"^{patron}$"), fn, rol))
        return fn
    return envoltura


# --------------------------------------------------------------- multipart
def leer_multipart(cuerpo: bytes, frontera: str):
    """Devuelve (campos, archivos) de un cuerpo multipart/form-data."""
    campos, archivos = {}, {}
    sep = ("--" + frontera).encode()
    for parte in cuerpo.split(sep):
        if parte in (b"", b"--", b"--\r\n") or not parte.strip(b"-\r\n"):
            continue
        parte = parte.lstrip(b"\r\n")
        if b"\r\n\r\n" not in parte:
            continue
        crudas, datos = parte.split(b"\r\n\r\n", 1)
        if datos.endswith(b"\r\n"):
            datos = datos[:-2]
        cabeceras = crudas.decode("utf-8", "replace")
        m = re.search(r'name="([^"]*)"', cabeceras)
        if not m:
            continue
        nombre = m.group(1)
        f = re.search(r'filename="([^"]*)"', cabeceras)
        if f:
            if f.group(1):
                archivos[nombre] = (f.group(1), datos)
        else:
            campos[nombre] = datos.decode("utf-8", "replace")
    return campos, archivos


# --------------------------------------------------------------- handler
class Manejador(BaseHTTPRequestHandler):
    server_version = "CPU-UNPRG"
    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *args):        # silencio en consola
        pass

    # -- utilidades
    def _cookies(self):
        crudas = self.headers.get("Cookie", "")
        salida = {}
        for trozo in crudas.split(";"):
            if "=" in trozo:
                k, v = trozo.split("=", 1)
                salida[k.strip()] = unquote(v.strip())
        return salida

    def _cuerpo(self):
        largo = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(largo) if largo else b""

    def _responder(self, r: Respuesta):
        self.send_response(r.estado)
        self.send_header("Content-Type", r.tipo)
        self.send_header("Content-Length", str(len(r.cuerpo)))
        for k, v in r.cabeceras:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(r.cuerpo)

    # -- estaticos
    def _estatico(self, ruta_url):
        rel = ruta_url[len("/static/"):]
        destino = (config.APP / "static" / rel).resolve()
        base = (config.APP / "static").resolve()
        if base not in destino.parents or not destino.is_file():
            return Respuesta("No encontrado", 404, "text/plain; charset=utf-8")
        tipo = mimetypes.guess_type(destino.name)[0] or "application/octet-stream"
        return Respuesta(destino.read_bytes(), 200, tipo,
                         [("Cache-Control", "max-age=3600")])

    # -- despacho
    def _atender(self, metodo):
        try:
            u = urlparse(self.path)
            camino = unquote(u.path)
            if camino.startswith("/static/"):
                return self._responder(self._estatico(camino))

            consulta = {k: v[0] for k, v in parse_qs(u.query).items()}
            campos, archivos = {}, {}
            if metodo == "POST":
                tipo = self.headers.get("Content-Type", "")
                cuerpo = self._cuerpo()
                if tipo.startswith("multipart/form-data"):
                    m = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", tipo)
                    frontera = (m.group(1) or m.group(2)).strip() if m else ""
                    campos, archivos = leer_multipart(cuerpo, frontera)
                else:
                    campos = {k: v[0] for k, v in
                              parse_qs(cuerpo.decode("utf-8", "replace")).items()}

            pet = Peticion(metodo, camino, consulta, campos, archivos, self._cookies())
            from . import auth
            pet.sesion = auth.leer_sesion(pet.cookies.get("sesion", ""))

            for m_ruta, patron, fn, rol in RUTAS:
                if m_ruta != metodo:
                    continue
                coincide = patron.match(camino)
                if not coincide:
                    continue
                if rol is not None:
                    if not pet.sesion:
                        return self._responder(redirigir("/login"))
                    if rol != "*" and pet.sesion.get("rol") != rol:
                        return self._responder(Respuesta(
                            "<h3>Sin permiso para esta sección.</h3>"
                            "<p><a href='/'>Volver</a></p>", 403))
                r = fn(pet, *coincide.groups())
                if isinstance(r, str):
                    r = Respuesta(r)
                return self._responder(r)

            return self._responder(Respuesta(
                "<h3>Página no encontrada.</h3><p><a href='/'>Volver</a></p>", 404))

        except BrokenPipeError:                      # pragma: no cover
            pass
        except Exception:
            detalle = traceback.format_exc()
            print(detalle)
            self._responder(Respuesta(
                "<h3>Ocurrió un error en el servidor.</h3><pre>"
                + html.escape(detalle) + "</pre>", 500))

    def do_GET(self):
        self._atender("GET")

    def do_POST(self):
        self._atender("POST")


class ServidorHTTP(ThreadingHTTPServer):
    # Windows permite compartir un puerto con SO_REUSEADDR. Reservarlo evita
    # que localhost termine mostrando otro programa que usa el mismo puerto.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def crear(puerto=None):
    return ServidorHTTP(("0.0.0.0", config.PUERTO if puerto is None else puerto), Manejador)


def servir(puerto=None):                             # pragma: no cover
    s = crear(puerto)
    s.serve_forever()
