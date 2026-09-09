-- Sistema de Inscripciones CPU UNPRG — tablas del sistema.
--
-- Este archivo NO decide en que base de datos se instala: el nombre sale
-- siempre de config.ini ([mysql] base). El instalador crea esa base si no
-- existe y luego ejecuta estas sentencias dentro de ella.

-- ---------------------------------------------------------------- usuarios
CREATE TABLE IF NOT EXISTS usuarios (
  id        INT AUTO_INCREMENT PRIMARY KEY,
  usuario   VARCHAR(40)  NOT NULL UNIQUE,
  nombre    VARCHAR(120) NOT NULL,
  rol       VARCHAR(20)  NOT NULL DEFAULT 'secretaria',  -- admin | secretaria
  clave     VARCHAR(255) NOT NULL,
  activo    TINYINT      NOT NULL DEFAULT 1,
  creado    DATETIME     NOT NULL
);

-- ---------------------------------------------------------------- catalogos
CREATE TABLE IF NOT EXISTS carreras (
  id     INT AUTO_INCREMENT PRIMARY KEY,
  nombre VARCHAR(120) NOT NULL UNIQUE,
  activo TINYINT      NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS ciclos (
  id     INT AUTO_INCREMENT PRIMARY KEY,
  codigo VARCHAR(20)  NOT NULL UNIQUE,   -- 2026-II
  activo TINYINT      NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------- alumnos
CREATE TABLE IF NOT EXISTS alumnos (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  dni               VARCHAR(12)  NOT NULL UNIQUE,
  nombres           VARCHAR(120) NOT NULL DEFAULT '',
  ap_paterno        VARCHAR(60)  NOT NULL DEFAULT '',
  ap_materno        VARCHAR(60)  NOT NULL DEFAULT '',
  nacimiento        VARCHAR(10)  NOT NULL DEFAULT '',   -- dd/mm/aaaa
  sexo              VARCHAR(15)  NOT NULL DEFAULT '',
  telefono          VARCHAR(20)  NOT NULL DEFAULT '',
  correo            VARCHAR(120) NOT NULL DEFAULT '',
  departamento      VARCHAR(60)  NOT NULL DEFAULT '',
  provincia         VARCHAR(60)  NOT NULL DEFAULT '',
  distrito          VARCHAR(60)  NOT NULL DEFAULT '',
  direccion         VARCHAR(200) NOT NULL DEFAULT '',
  menor_edad        VARCHAR(10)  NOT NULL DEFAULT '',
  -- colegio de procedencia
  colegio           VARCHAR(150) NOT NULL DEFAULT '',
  colegio_departamento VARCHAR(60) NOT NULL DEFAULT '',
  colegio_provincia VARCHAR(60)  NOT NULL DEFAULT '',
  colegio_distrito  VARCHAR(60)  NOT NULL DEFAULT '',
  colegio_ubicacion VARCHAR(150) NOT NULL DEFAULT '',
  colegio_egreso    VARCHAR(10)  NOT NULL DEFAULT '',
  -- apoderado (el formulario lo pide solo a los menores de edad)
  apo_nombres       VARCHAR(120) NOT NULL DEFAULT '',
  apo_ap_paterno    VARCHAR(60)  NOT NULL DEFAULT '',
  apo_ap_materno    VARCHAR(60)  NOT NULL DEFAULT '',
  apo_dni           VARCHAR(12)  NOT NULL DEFAULT '',
  apo_telefono      VARCHAR(20)  NOT NULL DEFAULT '',
  apo_parentesco    VARCHAR(30)  NOT NULL DEFAULT '',
  creado            DATETIME     NOT NULL,
  actualizado       DATETIME     NOT NULL
);

-- ---------------------------------------------------------------- inscripciones
CREATE TABLE IF NOT EXISTS inscripciones (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  alumno_id       INT          NOT NULL,
  ciclo           VARCHAR(20)  NOT NULL,
  carrera         VARCHAR(120) NOT NULL DEFAULT '',
  turno           VARCHAR(20)  NOT NULL DEFAULT '',
  sede            VARCHAR(150) NOT NULL DEFAULT '',
  modalidad       VARCHAR(40)  NOT NULL DEFAULT '',
  fecha_matricula VARCHAR(10)  NOT NULL DEFAULT '',
  medio_pago      VARCHAR(60)  NOT NULL DEFAULT '',
  oferta          VARCHAR(80)  NOT NULL DEFAULT '',
  voucher         VARCHAR(40)  NOT NULL DEFAULT '',
  agencia         VARCHAR(40)  NOT NULL DEFAULT '',
  secuencia       VARCHAR(40)  NOT NULL DEFAULT '',
  fecha_pago      VARCHAR(10)  NOT NULL DEFAULT '',
  marca_temporal  VARCHAR(30)  NOT NULL DEFAULT '',
  correo_form     VARCHAR(120) NOT NULL DEFAULT '',
  estado          VARCHAR(20)  NOT NULL DEFAULT 'inscrito',
  origen          VARCHAR(160) NOT NULL DEFAULT '',
  creado          DATETIME     NOT NULL,
  actualizado     DATETIME     NOT NULL,
  UNIQUE KEY uk_alumno_ciclo (alumno_id, ciclo),
  KEY ix_ciclo (ciclo),
  KEY ix_carrera (carrera),
  CONSTRAINT fk_insc_alumno FOREIGN KEY (alumno_id) REFERENCES alumnos (id)
);

-- ---------------------------------------------------------------- importaciones
CREATE TABLE IF NOT EXISTS importaciones (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  archivo      VARCHAR(200) NOT NULL,
  filas        INT NOT NULL DEFAULT 0,
  nuevas       INT NOT NULL DEFAULT 0,
  actualizadas INT NOT NULL DEFAULT 0,
  omitidas     INT NOT NULL DEFAULT 0,
  detalle      TEXT,
  usuario_id   INT,
  creado       DATETIME NOT NULL
);

-- ---------------------------------------------------------------- auditoria
CREATE TABLE IF NOT EXISTS auditoria (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  usuario_id  INT,
  accion      VARCHAR(40)  NOT NULL,
  referencia  VARCHAR(80)  NOT NULL DEFAULT '',
  detalle     VARCHAR(255) NOT NULL DEFAULT '',
  creado      DATETIME     NOT NULL
);

-- ---------------------------------------------------------------- tarifario
-- Conceptos e importes exigidos por ciclo. La validacion compara siempre
-- el importe exacto. fijo se conserva por compatibilidad con datos anteriores.
CREATE TABLE IF NOT EXISTS conceptos_pago (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  ciclo       VARCHAR(20)   NOT NULL,
  codigo      VARCHAR(20)   NOT NULL,
  nombre      VARCHAR(80)   NOT NULL,
  importe     DECIMAL(10,2) NOT NULL DEFAULT 0,
  fijo        TINYINT       NOT NULL DEFAULT 1,
  obligatorio TINYINT       NOT NULL DEFAULT 1,
  activo      TINYINT       NOT NULL DEFAULT 1,
  UNIQUE KEY uk_ciclo_codigo (ciclo, codigo)
);

-- ---------------------------------------------------------------- pagos
-- Una fila por pago del reporte del Banco de la Nacion. inscripcion_id
-- amarra el pago a UN alumno: como la columna es unica por fila, un mismo
-- pago no puede quedar aplicado a dos inscripciones distintas.
CREATE TABLE IF NOT EXISTS pagos (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  dni            VARCHAR(12)   NOT NULL DEFAULT '',
  voucher        VARCHAR(40)   NOT NULL DEFAULT '',
  voucher_clave  VARCHAR(7)    NOT NULL DEFAULT '',
  cod_pago       VARCHAR(20)   NOT NULL DEFAULT '',
  concepto       VARCHAR(80)   NOT NULL DEFAULT '',
  fecha_pago     VARCHAR(10)   NOT NULL DEFAULT '',
  hora           VARCHAR(10)   NOT NULL DEFAULT '',
  importe        DECIMAL(10,2) NOT NULL DEFAULT 0,
  agencia        VARCHAR(20)   NOT NULL DEFAULT '',
  caja           VARCHAR(20)   NOT NULL DEFAULT '',
  cuenta         VARCHAR(30)   NOT NULL DEFAULT '',
  nombre_banco   VARCHAR(120)  NOT NULL DEFAULT '',
  situacion      VARCHAR(20)   NOT NULL DEFAULT '',
  ciclo          VARCHAR(20)   NOT NULL DEFAULT '',
  inscripcion_id INT           NULL,
  origen         VARCHAR(160)  NOT NULL DEFAULT '',
  creado         DATETIME      NOT NULL,
  UNIQUE KEY uk_pago (voucher, cod_pago, dni),
  KEY ix_pago_dni (dni),
  KEY ix_pago_clave (voucher_clave),
  KEY ix_pago_insc (inscripcion_id)
);
