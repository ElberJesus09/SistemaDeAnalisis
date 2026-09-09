"""
App de escritorio del Sistema de Inscripciones CPU UNPRG.

Un solo programa para todas las computadoras. Segun config.ini:

  [app] modo = servidor  -> esta PC levanta el servidor y abre la ventana.
                            Las demas computadoras de la red entran a
                            http://IP-DE-ESTA-PC:8000
  [app] modo = cliente   -> solo abre la ventana apuntando a servidor_url.

Si pywebview no esta instalado, se abre en el navegador por defecto.
"""
import socket
import sys
import threading
import time
import webbrowser

from app import config


def ip_local() -> str:
    """IP de esta PC en la red local (para decirsela a las demas)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def arrancar_servidor() -> str:
    from app import db, servidor, web        # noqa: F401  (web registra las rutas)

    problema = db.comprobar()
    if problema:
        print(problema)
        input("\nPresiona Enter para cerrar...")
        sys.exit(1)

    db.crear_esquema()
    estructura = db.verificar_tablas()
    if estructura:
        print("\n" + estructura)
        input("\nPresiona Enter para cerrar...")
        sys.exit(1)

    from app import auth
    aviso = auth.asegurar_admin_inicial()

    try:
        s = servidor.crear(config.PUERTO)
    except OSError as exc:
        print(f"No se pudo iniciar Sistema de Inscripciones en el puerto {config.PUERTO}.")
        print("Puede estar ocupado por otra instancia u otro programa. Revisa el puerto")
        print("en la seccion [app] de config.ini antes de volver a ejecutar.")
        print(f"Detalle: {exc}")
        sys.exit(1)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    from app import sync_google
    sync_google.iniciar()
    from app import copias
    copias.iniciar()

    print("=" * 62)
    print(" Sistema de Inscripciones CPU UNPRG — servidor encendido")
    print(f" Base de datos       : {config.MYSQL['database']}"
          f" en {config.MYSQL['host']}:{config.MYSQL['port']}")
    print(f" En esta PC          : http://localhost:{config.PUERTO}")
    print(f" Desde otras PCs     : http://{ip_local()}:{config.PUERTO}")
    if aviso:
        print(f" {aviso}")
    print("=" * 62)
    return f"http://localhost:{config.PUERTO}"


def abrir_ventana(url: str) -> None:
    try:
        import webview
    except ImportError:
        print("pywebview no esta instalado; abriendo en el navegador.")
        webbrowser.open(url)
        print("Cierra esta ventana negra para apagar el sistema.")
        while True:
            time.sleep(3600)
        return

    webview.create_window("Sistema de Inscripciones — CPU UNPRG", url,
                          width=1280, height=820, min_size=(1024, 680))
    webview.start()


def main() -> None:
    if config.MODO == "cliente":
        url = config.SERVIDOR_URL
        print(f"Modo cliente — conectando a {url}")
    else:
        url = arrancar_servidor()
    abrir_ventana(url)


if __name__ == "__main__":
    main()
