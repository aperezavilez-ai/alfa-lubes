# core:README.md

Fecha de ingesta: 2026-11-08T22:09:27.974Z
Fuente: D:\PROGRAMAS IA\ALFA LUBES\README.md
Tags: core, auto-ingest

# ALFA LUBES

Aplicación web en español para presentar un catálogo de aceites y lubricantes, recibir pedidos y consultar operaciones básicas de ventas. Incluye el logo oficial proporcionado para este proyecto.

## Ejecutar en Windows

Requiere Python 3.9 o posterior.

```powershell
cd "D:\PROGRAMAS IA\ALFA LUBES"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:ALFA_LUBES_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
python app.py
```

Abre <http://127.0.0.1:5000>. En macOS o Linux, crea el entorno con `python3 -m venv .venv`, activa `.venv/bin/activate` e instala los mismos requisitos.

La base SQLite se crea como `alfa_lubes.db` junto a `app.py`. Puedes cambiar su ubicación con `ALFA_LUBES_DB`. La clave de sesión se recomienda definir mediante `ALFA_LUBES_SECRET_KEY`; si se omite, se genera una clave aleatoria al iniciar y las sesiones activas no se conservarán tras reiniciar.

## Funciones incluidas

- Página de inicio con identidad de ALFA LUBES y productos destacados.
- Catálogo con búsqueda por marca, producto o viscosidad.
- Carrito con ajuste de cantidades y control de existencias.
- Envío de pedidos, registro de clientes y descuento transaccional de inventario.
- Panel local con ventas, pedidos, clientes, alertas de inventario bajo y ventas por marca.
- Registro de proveedores.
- Asesor de lubricantes con reglas generales y límites explicados al usuario.

## Publicar una vista previa en Vercel

Vercel detecta la aplicación Flask a partir de `app.py` y `requirements.txt`. Importa el repositorio de GitHub en Vercel y deja que el framework se configure automáticamente. La variable `VERCEL=1` activa el modo de demostración: oculta el panel administrativo, bloquea los envíos de pedidos y usa almacenamiento temporal. La vista en Vercel es para revisar el diseño; los pedidos y datos persistentes deben manejarse en la instalación local hasta conectar una base de datos y autenticación adecuadas.

Los productos iniciales son ejemplos y se cargan solo cuando la tabla de productos está vacía. Actualiza catálogo, existencias, precios y descripciones antes de ofrecerlos a clientes. Los importes iniciales se muestran en MXN.

## Alcance operativo

El checkout registra una solicitud de pedido; no cobra con tarjeta ni calcula envío. El asesor no consulta una API de IA ni bases de datos OEM: orienta al cliente para revisar el manual del vehículo. El panel de ventas y las pantallas de clientes y proveedores no tienen inicio de sesión en esta versión; la aplicación se enlaza a `127.0.0.1` para uso local. Antes de publicarla en Internet, añade autenticación y controles de operación, configura HTTPS y conecta un proveedor de pagos y entrega si los necesitas.

## Estructura

- `app.py`: servidor Flask, rutas y datos SQLite.
- `templates/`: páginas del sitio.
- `static/images/`: logo, banner e imágenes de catálogo.
- `requirements.txt`: dependencias Python.

