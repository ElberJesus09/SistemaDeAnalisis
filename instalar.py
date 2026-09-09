"""
Instalador del Sistema de Inscripciones CPU UNPRG.

Hace todo lo necesario para dejar la PC servidor lista:
  1. instala las librerias
  2. descarga el motor que genera los PDF
  3. crea config.ini
  4. pide los datos de MySQL, crea la base y las tablas
  5. crea el usuario admin inicial

Se ejecuta con  instalar.bat  o directamente:   py instalar.py
"""
import getpass
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PY = sys.executable


def titulo(texto):
    print("\n" + "=" * 62)
    print(" " + texto)
    print("=" * 62)


def paso(n, texto):
    print(f"\n[{n}] {texto}")


def pip(*args, obligatorio=True) -> bool:
    r = subprocess.run([PY, "-m", "pip", "install", *args])
    if r.returncode and obligatorio:
        print("\n[X] Fallo la instalacion de librerias. Revisa el mensaje de arriba.")
        sys.exit(1)
    return r.returncode == 0


def main():
    titulo("Instalacion del Sistema de Inscripciones CPU UNPRG")
    print(f" Python: {sys.version.split()[0]}  ({PY})")

    if sys.version_info < (3, 10):
        print("\n[X] Se necesita Python 3.10 o superior.")
        sys.exit(1)

    # ------------------------------------------------------------ 1
    paso("1/5", "Instalando las librerias necesarias...")
    pip("--upgrade", "pip", obligatorio=False)
    pip("-r", str(RAIZ / "requirements.txt"))

    print("\n    Ventana de escritorio (opcional)...")
    if not pip("pywebview", obligatorio=False):
        print("    [!] pywebview no se instalo. No es grave:")
        print("        el sistema se abrira en el navegador por defecto.")

    # ------------------------------------------------------------ 2
    paso("2/5", "Descargando el motor que genera los PDF (puede tardar)...")
    if subprocess.run([PY, "-m", "playwright", "install", "chromium"]).returncode:
        print("    [X] No se pudo descargar. Revisa la conexion a internet")
        print("        y vuelve a ejecutar el instalador.")
        sys.exit(1)

    # ------------------------------------------------------------ 3
    paso("3/5", "Preparando la configuracion...")
    ini = RAIZ / "config.ini"
    if ini.exists():
        print("    config.ini ya existe, se conserva.")
    else:
        ini.write_bytes((RAIZ / "config.ini.ejemplo").read_bytes())
        print("    config.ini creado.")

    sys.path.insert(0, str(RAIZ))
    from app import config  # noqa: E402  (despues de instalar las librerias)

    # ------------------------------------------------------------ 4
    paso("4/5", "Conectando con MySQL...")
    print("    Enter para aceptar el valor entre corchetes.\n")
    datos = dict(config.MYSQL)
    datos["host"] = input(f"    Servidor  [{datos['host']}]: ").strip() or datos["host"]
    puerto = input(f"    Puerto    [{datos['port']}]: ").strip()
    datos["port"] = int(puerto) if puerto.isdigit() else datos["port"]
    datos["user"] = input(f"    Usuario   [{datos['user']}]: ").strip() or datos["user"]
    clave = getpass.getpass("    Contrasena (no se ve al escribir): ")
    if clave:
        datos["password"] = clave
    base = input(f"    Base      [{datos['database']}]: ").strip() or datos["database"]
    datos.pop("database")

    import pymysql

    try:
        con = pymysql.connect(charset="utf8mb4", **datos)
    except Exception as e:
        print(f"\n    [X] No se pudo conectar: {e}")
        print("        Revisa que el servicio MySQL este encendido y que el")
        print("        usuario, la contrasena y el puerto sean correctos.")
        sys.exit(1)

    from app.db import _sentencias                     # noqa: E402

    cur = con.cursor()
    # La base la decide config.ini, no el archivo SQL.
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{base}`"
                " DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cur.execute(f"USE `{base}`")
    sql = (RAIZ / "app" / "esquema.sql").read_text(encoding="utf-8")
    for sentencia in _sentencias(sql):
        cur.execute(sentencia)
    con.commit()
    cur.close()
    con.close()
    print(f"    Base '{base}' y tablas listas.")

    # guarda lo que acaba de funcionar
    config.CFG.set("mysql", "host", datos["host"])
    config.CFG.set("mysql", "puerto", str(datos["port"]))
    config.CFG.set("mysql", "usuario", datos["user"])
    config.CFG.set("mysql", "password", datos["password"])
    config.CFG.set("mysql", "base", base)
    with ini.open("w", encoding="utf-8") as fh:
        config.CFG.write(fh)
    print("    Configuracion guardada en config.ini.")

    config.MYSQL.update({"host": datos["host"], "port": datos["port"],
                         "user": datos["user"], "password": datos["password"],
                         "database": base})

    from app import db as _db                          # noqa: E402
    _db.cerrar()
    problema = _db.verificar_tablas()
    if problema:
        print("\n    [X] " + problema.replace("\n", "\n    "))
        sys.exit(1)

    # ------------------------------------------------------------ 5
    paso("5/5", "Creando el usuario inicial...")
    from app import auth                                # noqa: E402

    aviso = auth.asegurar_admin_inicial()
    print("    " + (aviso or "Ya habia usuarios, no se creo ninguno."))

    titulo("Listo. Ejecuta  ejecutar.bat  para abrir el sistema.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInstalacion cancelada.")
    input("\nPresiona Enter para cerrar...")
