"""Envio individual de fichas PDF por SMTP cifrado."""
import re
import secrets
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from . import config


def direccion(valor):
    valor = str(valor or "").strip()
    if len(valor) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", valor):
        raise ValueError("Indica un solo correo electrónico válido.")
    return valor


def comprobar_config():
    c = config.SMTP
    if not all(c.get(k) for k in ("host", "username", "password", "from_address")):
        raise ValueError("Completa la configuración SMTP en el servidor.")
    direccion(c["from_address"])
    if c["scheme"].lower() not in ("smtps", "starttls", "smtp"):
        raise ValueError("SMTP requiere smtps o starttls.")
    try:
        if not 1 <= int(c["port"]) <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("El puerto SMTP no es válido.") from None


def conectar():
    comprobar_config()
    c = config.SMTP
    contexto = ssl.create_default_context()
    if c["scheme"].lower() == "smtps":
        smtp = smtplib.SMTP_SSL(c["host"], int(c["port"]), timeout=30, context=contexto)
    else:
        smtp = smtplib.SMTP(c["host"], int(c["port"]), timeout=30)
    try:
        if c["scheme"].lower() != "smtps":
            smtp.ehlo()
            smtp.starttls(context=contexto)
            smtp.ehlo()
        smtp.login(c["username"], c["password"])
        return smtp
    except Exception:
        smtp.close()
        raise


def asunto(datos):
    return f"Ficha de inscripción · CPU UNPRG · {datos['ciclo']}"


def cuerpo(datos):
    return (f"Hola, {datos['nombres']}:\n\n"
            f"Adjuntamos tu ficha de inscripción del ciclo {datos['ciclo']}.\n"
            "Revisa los datos y conserva el documento.\n\n"
            "Centro Preuniversitario UNPRG")


def enviar_ficha(datos, destinatario, pdf):
    destinatario = direccion(destinatario)
    comprobar_config()
    if not pdf.startswith(b"%PDF-"):
        raise ValueError("No se pudo generar un PDF válido.")
    msg = EmailMessage()
    msg["From"] = formataddr((config.SMTP["from_name"], config.SMTP["from_address"]))
    msg["To"] = destinatario
    msg["Subject"] = asunto(datos)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(cuerpo(datos))
    nombre = re.sub(r"[^A-Za-z0-9_.-]", "_", f"ficha_{datos['dni']}_{datos['ciclo']}.pdf")
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=nombre)
    smtp = conectar()
    try:
        rechazados = smtp.send_message(msg, from_addr=config.SMTP["from_address"], to_addrs=[destinatario])
        if rechazados:
            raise smtplib.SMTPRecipientsRefused(rechazados)
    finally:
        # Una desconexion durante QUIT no convierte un mensaje aceptado en fallo.
        smtp.close()
    return msg["Message-ID"]


# Confirmacion de un solo uso: evita envios por formularios externos o doble clic.
_pendientes = {}
_cerrojo = threading.Lock()


def crear_token(sesion, inscripcion):
    with _cerrojo:
        ahora = time.time()
        for t in list(_pendientes):
            if _pendientes[t][2] < ahora:
                del _pendientes[t]
        if len(_pendientes) >= 1000:
            del _pendientes[next(iter(_pendientes))]
        token = secrets.token_urlsafe(32)
        _pendientes[token] = (sesion['n'], str(inscripcion), ahora + 600)
        return token


def consumir_token(token, sesion, inscripcion):
    with _cerrojo:
        esperado = _pendientes.get(token)
        if not esperado or esperado[:2] != (sesion['n'], str(inscripcion)) or esperado[2] < time.time():
            return False
        del _pendientes[token]
        return True
