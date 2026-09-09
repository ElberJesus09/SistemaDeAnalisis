# Sistema de Inscripciones — CPU UNPRG

App de escritorio + servidor en red para importar las respuestas del formulario,
guardarlas en MySQL, completar los datos que faltan y emitir la Constancia de
Matrícula en PDF.

La constancia conserva el formato de una hoja A4. El ciclo se toma de cada
inscripción y se repite en la cabecera, los datos académicos y la declaración.
Siempre incluye espacio para la firma del alumno. El bloque del apoderado y su
firma aparecen para los menores; un alumno marcado como mayor de edad lleva
únicamente su firma, aunque conserve datos antiguos de apoderado. Las firmas tienen espacio
reservado, nombre y DNI. Si los datos son demasiado largos para una hoja legible,
el sistema pide revisarlos en vez de reducirlos excesivamente.

En este equipo, `ejecutar.bat` usa el entorno propio `.venv` y abre
**http://localhost:8011** (puerto de `[app]` en `config.ini`). La base sigue
siendo **MySQL**, `bdanalisis` en `localhost:3307`. El puerto 8011 evita el
conflicto con otros programas que usan 8000. Si el puerto está ocupado, el
arranque muestra un error y no abre el navegador.

---

## 1. Instalación (solo en la PC servidor)

1. Instala **Python 3.10 o superior** desde python.org marcando *"Add Python to PATH"*.
2. Doble clic en **`instalar.bat`**. Instala las librerías, descarga el motor de PDF,
   crea `config.ini`, te pide los datos de MySQL y arma la base de datos.
3. Doble clic en **`ejecutar.bat`**.

El instalador pregunta el servidor, el usuario y la contraseña de MySQL, comprueba la
conexión y guarda los datos en `config.ini`. No hace falta tener el comando `mysql` en
el PATH ni abrir Workbench.

Si `instalar.bat` no arrancara, abre una consola en la carpeta y ejecuta `py instalar.py`
— hace exactamente lo mismo.

La primera vez entra con **`admin` / `admin`** y cambia la contraseña en *Usuarios*.

Al arrancar, la ventana negra muestra la dirección para las demás computadoras:

```
 En esta PC       : http://localhost:8000
 Desde otras PCs  : http://192.168.1.10:8000     <- esta es la que reparte
```

### En las demás computadoras

Dos opciones, ambas válidas:

- **Solo el navegador** — entrar a `http://192.168.1.10:8000`. No se instala nada.
- **La app de escritorio** — copiar esta carpeta, correr `instalar.bat`, y en
  `config.ini` poner `modo = cliente` y `servidor_url = http://192.168.1.10:8000`.
  Así se abre en su propia ventana, sin barra de direcciones.

Un solo programa cubre los dos casos: `modo` decide si esa PC levanta el servidor
o solo se conecta.

> Si el firewall de Windows pregunta al primer arranque, hay que permitir el acceso
> en **redes privadas**; si no, las otras computadoras no llegarán.

---

## 2. Cómo se usa

**Importar** → subir el CSV o el XLSX tal como sale de Google Forms. Muestra cuántas
filas entraron, cuántas se actualizaron y cuáles se omitieron con el motivo.
Reimportar el mismo archivo **no duplica nada**: el alumno se identifica por DNI y la
inscripción por DNI + ciclo, y lo que alguien corrigió a mano en el panel no se pisa.

**Inscripciones** → listado con buscador (DNI, nombre o apellido) y filtros por ciclo,
carrera y estado. Cada fila indica si está *Completo* o cuántos datos le *Faltan*.
El botón **Ficha PDF** solo aparece cuando el registro está completo.

**Editar** → formulario con los campos en rojo cuando faltan. Con el formulario
ampliado casi todo llega lleno; lo que quede se completa aquí.

**Llenado masivo** → al final del listado, para aplicar un mismo valor (la fecha de
matrícula, típicamente) a todos los registros filtrados. Solo rellena los vacíos:
nunca pisa un dato ya puesto.

**Pagos** → todo lo que llegó del Banco de la Nación, con el alumno al que quedó
aplicado cada pago y, aparte, los que todavía no calzan con nadie.

**Tarifario** (solo admin) → qué conceptos se cobran en el ciclo y cuánto.

**Reportes** → inscritos por carrera, turno, agencia, departamento y día de pago,
recaudación por concepto y por agencia, y el conteo de completos, incompletos,
pagados y sin pagar. Todo se descarga en un Excel de ocho hojas.

**Usuarios** (solo admin) → crear cuentas, cambiar contraseñas, activar y desactivar.
Dos roles: *admin* (todo) y *secretaría* (importar, editar y emitir fichas).

---

## 3. El formulario y sus 34 columnas

El formulario ampliado ya pregunta casi todo. Así queda el balance:

| Antes | Ahora |
|---|---|
| Faltaban **10** datos en todos | Falta **1** en mayores de edad, **2** en menores |

Lo que ahora llega solo: género, sede, turno, colegio con su departamento, provincia
y distrito, año de egreso, y los datos del apoderado. Lo que sigue faltando: la
**fecha de matrícula** (esa la pone el CPU, no el alumno — para eso está el llenado
masivo) y el **parentesco del apoderado**, que el formulario todavía no pregunta.

> Si agregas una pregunta más — *"PARENTESCO DEL APODERADO"* con opciones Padre /
> Madre / Hermano(a) / Tío(a) / Abuelo(a) / Tutor(a) — el importador la reconoce sola
> y a los menores tampoco les faltaría nada.

### La trampa de los encabezados repetidos

El formulario tiene `DEPARTAMENTO`, `PROVINCIA` y `DISTRITO` **dos veces**: la primera
terna es del alumno y la segunda del colegio. Como los dos encabezados se llaman igual,
un importador ingenuo guardaría la ubicación del alumno como si fuera la del colegio,
y sin dar ningún error. El mapeo va **por posición** para evitarlo, y hay una prueba
automática que lo comprueba con ternas distintas a propósito.

Ojo que hay otra repetición que se resuelve al revés: `FECHA DE PAGO` sale dos veces
para el **mismo** dato (una casilla por forma de pago), así que ahí gana el primer
valor no vacío. Son dos reglas distintas para dos problemas distintos.

### Menores y mayores de edad

`ERES MENOR DE EDAD` cambia lo que se exige: a un mayor **no** se le piden los datos
del apoderado, porque el formulario no se los pregunta. Su ficha se emite sin ellos.

---

### Exportación actual de Google Forms: 35 columnas

Se admite el CSV original con MODALIDAD entre SEDE y TURNO, sin mover ni eliminar
columnas. Modalidad se guarda por inscripción, se puede corregir en el panel y
aparece en la ficha PDF y el reporte Excel. El correo de la respuesta y el correo
del alumno se conservan por separado. La primera ubicación corresponde al alumno
y la segunda al colegio; las dos fechas de pago se combinan tomando la primera
con valor. También se siguen aceptando los archivos anteriores sin modalidad.

En **Importar** hay una guía del orden de las 35 columnas. Un archivo que solo
contiene los encabezados muestra un aviso y no crea alumnos ni importaciones.
El archivo de referencia sin respuestas está en
`ejemplos/encabezados_formulario_2026-II.csv`.

## 4. Los pagos

Se importa el reporte del Banco de la Nación en la misma pantalla de *Importar*: no
hay que elegir el tipo, el sistema reconoce el archivo por sus encabezados
(`DOCUMENTO` y `COD_PAGO` lo delatan) y lo manda al lugar correcto.

### Cómo se amarra un pago con su alumno

**Por DNI.** El banco lo manda relleno con ceros — `619426920000000` — y el DNI real
son los ocho primeros dígitos: `61942692`.

**Por voucher, con la regla de Págalo.pe.** El alumno escribe en el formulario algo
como `1234567-1`; se toman los **7 dígitos anteriores al guion** y se comparan con los
**últimos 7 dígitos** del voucher del banco:

```
Alumno escribe:  1234567-1   ->  1234567
Banco entrega:    81234567   ->  1234567   coincide
```

Los dos números quedan guardados ya normalizados, así que la comparación es directa.
Si el voucher que declaró el alumno no coincide con ninguno de sus pagos, la ficha del
alumno lo dice en rojo: puede ser un error de tipeo o un voucher que no le pertenece.

### El tarifario

El banco manda `CONCEPTO_PAGO` en blanco (`*** DESCCONOCIDO ***`), así que el nombre
sale del tarifario según el `COD_PAGO`. Viene cargado así para 2026-II:

| Código | Concepto | Importe exigido |
|---|---|---|
| `00001096` | Derecho de inscripción | S/ 200.00 |
| `00001097` | Pensión del ciclo | S/ 750.00 |

Ambos conceptos son obligatorios. El importe debe coincidir exactamente con el
tarifario; S/100 o S/550 quedan observados con estos valores. No se deducen
descuentos ni se aceptan cuotas automáticamente. Varios pagos del mismo concepto
requieren revisión. En **Tarifario → Editar** se cambia el código, nombre, importe
y obligatoriedad por ciclo. El cambio afecta la validación de todo ese ciclo.

**Pagado** exige los conceptos obligatorios, montos correctos y coincidencia del
voucher (o secuencia, si no hay voucher). **Parcial** indica conceptos faltantes;
**Observado**, diferencias de monto, voucher, códigos sin tarifario o varios pagos
para un concepto. **Sin pago** indica que no hay pagos asociados. El listado, el
detalle, los reportes y el control de emisión usan la misma validación.

El Excel debe contener DOCUMENTO, VOUCHER, COD_PAGO, FECHA_PAGO e IMPORTE_S/.
También se guardan concepto, nombre, cuenta, hora, situación, caja y agencia si
están presentes. Las columnas NRO, COD. y COD_ALUMNO no identifican el concepto:
se usa COD_PAGO. Un código numérico 1096 se normaliza a 00001096. Los montos
inválidos se omiten con un aviso; no se convierten en pagos de cero soles.

### Un pago no se puede reutilizar

Tres cierres, no uno:

1. La base rechaza dos pagos con el mismo voucher + concepto + DNI, así que reimportar
   el archivo del banco no duplica nada.
2. Si una misma línea viene repetida **dentro** del archivo, se salta y se avisa; no se
   cuenta dos veces en el total recaudado.
3. Cada pago guarda a qué inscripción quedó aplicado, y al reconciliar **solo se tocan
   los pagos sueltos**. Uno ya aplicado a un alumno nunca se mueve a otro.
   Reimportar un pago con otro ciclo lo omite y avisa; no cambia su ciclo original.

### Pagos sin inscripción

Es normal que lleguen pagos de gente que todavía no llenó el formulario. Quedan
guardados y listados aparte, en *Pagos → Sin inscripción*, con el nombre que trae el
banco. Cuando esa persona llene el formulario, el botón **Volver a conciliar** los
amarra solos.

### ¿La ficha debe exigir el pago?

La emisión se controla mediante `[app]` en `config.ini`:

```
exigir_pago = no    ; el panel avisa, pero la ficha se emite igual  (por defecto)
exigir_pago = si    ; sin pago verificado no sale la ficha
```

Con `si`, los pagos observados, parciales o ausentes bloquean la ficha. Con `no`,
las observaciones se muestran pero no bloquean la emisión. Reinicia tras cambiarlo.

---

## 5. La ficha

Réplica exacta del modelo que enviaste, con el ciclo parametrizado. **Siempre sale en
una sola hoja**: antes de imprimir se mide el alto real y, si un alumno trae una
dirección o un colegio muy largos, se reduce el zoom lo mínimo necesario.

Para cambiar de ciclo el año que viene basta con editar `ciclo` en `config.ini`. El
texto *"Acepto inscribirme al 2026-II…"* de la declaración jurada se actualiza solo.

Probar la plantilla sin entrar al panel:

```bash
python scripts/render_ficha.py                   # datos de demostración
python scripts/render_ficha.py --inscripcion 12  # con datos reales de la base
```

---

## 6. Qué hay dentro

```
escritorio.py             App de escritorio: levanta el servidor o se conecta
instalar.bat              Instalación en un doble clic
instalar.py               Lo que hace el instalador (por si el .bat falla)
ejecutar.bat              Arranque diario
config.ini                Configuración de esta PC (se crea al instalar)

app/esquema.sql           Tablas de MySQL
app/config.py             Lectura de config.ini
app/db.py                 Conexión y consultas
app/auth.py               Contraseñas (PBKDF2) y sesiones firmadas
app/importador.py         Respuestas del formulario -> base de datos
app/pagos.py              Pagos del banco: importar, tarifario y conciliar
app/ficha.py              Datos -> PDF de una sola hoja
app/servidor.py           Servidor HTTP y enrutador
app/web.py                Las pantallas del panel
app/templates/            Plantillas del panel y de la ficha
app/static/               CSS, logo y tipografía DejaVu

tests/test_sistema.py     Prueba de extremo a extremo (112 comprobaciones)
ejemplos/                 Archivos de ejemplo para probar sin datos reales
```

**Sobre el servidor:** usa `ThreadingHTTPServer` de la librería estándar de Python en
lugar de un framework web. La razón es práctica: instalar el sistema no depende de
nada más que un `pip install`, y para una oficina con unas cuantas computadoras rinde
de sobra. Si algún día el uso creciera mucho, los manejadores de `web.py` son
funciones normales y pasarlos a FastAPI sería un cambio mecánico.

---

## 7. Qué está probado y qué no

`python tests/test_sistema.py` levanta el servidor de verdad y recorre el camino
completo: crear el esquema, importar CSV y XLSX, detectar el DNI repetido y el vacío,
reimportar sin duplicar, entrar con y sin contraseña correcta, rechazar una sesión
manipulada, listar, buscar, filtrar, bloquear la ficha incompleta, guardar los datos
faltantes, emitir el PDF (y verificar que trae una sola página con el ciclo correcto),
subir un archivo por el navegador, ver los reportes, bajar el Excel y comprobar que
secretaría no entra a Usuarios.

Sobre el formulario nuevo comprueba: que las dos ternas de departamento/provincia/
distrito no se pisan, que género y menor de edad se normalizan, que a un mayor de edad
no se le exige apoderado, que el llenado masivo no pisa datos existentes, y que una
base creada con la versión anterior recibe sola las columnas nuevas.

Sobre los pagos comprueba además: la regla de Págalo.pe en los dos sentidos (incluido
tu ejemplo `1234567-1` ↔ `81234567`), el recorte del DNI relleno con ceros, que
distingue solo cuál de los dos archivos es cuál, que reimportar no duplica, que una
línea repetida dentro del archivo no se cuenta dos veces, que un pago ya aplicado no se
mueve a otro alumno, que avisa cuando el voucher declarado no es del alumno, que detecta
un pago de menos en el concepto fijo, y que los pagos sin inscripción quedan aparte.
**Las 112 comprobaciones pasan.**

Dos cosas **no** pude probar desde aquí y conviene que las mires en el primer arranque:

1. **MySQL.** El entorno donde se escribió esto no tiene servidor MySQL, así que las
   pruebas corrieron sobre SQLite. Las consultas son SQL estándar y el esquema está
   escrito para MySQL. La conexión real ya se probó en la PC servidor y funciona.
2. **La ventana de pywebview.** Si no estuviera instalada, el sistema se abre igual en
   el navegador por defecto; no se queda bloqueado.

Si aparece algún error, pásame el mensaje y lo corrijo.

---

## 8. Si algo falla

**"/d no se reconoce como un comando"** o líneas partidas raro al abrir un `.bat` —
el archivo perdió los saltos de línea de Windows. Pasa si se edita con un editor de
Linux/Mac o se copia mal. Los `.bat` **deben** guardarse con finales de línea CRLF;
en el Bloc de notas o Notepad++ (Edición → Conversión EOL → Windows) se arregla.

**"No se encontro Python"** aunque esté instalado — no quedó en el PATH. Los `.bat`
ya lo buscan también con el lanzador `py` y en las carpetas habituales de instalación;
si aun así no lo encuentra, ejecuta `py instalar.py` a mano desde la consola.

**No se puede conectar a MySQL** — el mensaje dice exactamente qué revisar. Suele ser
el servicio apagado, la contraseña de `root` o el puerto. Vuelve a ejecutar `instalar.bat`.

**"Table 'loquesea.usuarios' doesn't exist"** — la base indicada en `config.ini`
(`[mysql] base`) no es donde están las tablas. El nombre de la base se decide **solo**
ahí; `esquema.sql` ya no lo fija. Corrige `base` y vuelve a ejecutar `instalar.bat`,
que crea la base si no existe.

**Al actualizar el sistema no hay que reinstalar nada.** Si una versión nueva agrega
columnas, al arrancar se agregan solas a las tablas que ya existen, sin tocar los datos.
Solo agrega columnas: nunca borra ni cambia una que tenga información.

**Ojo al reutilizar una base que ya usas para otra cosa** — si esa base ya tuviera una
tabla llamada `usuarios`, `alumnos` o similar, MySQL la respetaría en silencio y el
sistema fallaría más adelante sin explicación. Por eso al arrancar se comprueba que
cada tabla tenga las columnas necesarias y, si no, se avisa antes de empezar. Lo más
limpio es darle una base propia, por ejemplo `cpu_unprg`.

**Las otras computadoras no entran** — permite la app en el firewall de Windows para
**redes privadas**, y confirma que usan la IP que el servidor muestra al arrancar.

---

## 9. Siguientes pasos posibles

- Emitir fichas en lote (todas las de una carrera o un turno en un solo PDF).
- Empaquetar `CPU-UNPRG.exe` con PyInstaller para no depender de Python en cada PC.
- Copia de seguridad automática de la base de datos.
- Agregar al formulario la pregunta de parentesco del apoderado.
- Aviso automático a los alumnos con pago parcial.
- Que los pagos sin inscripción creen la ficha del alumno a medio llenar, si te
  resulta más cómodo que buscarlos a mano.
