# ALFA LUBES — ROADMAP

Fuente de verdad del proceso del proyecto para el agente. LEER ESTO ANTES de cualquier tool.
PROHIBIDO reexplorar el repo entero si este documento cubre la tarea. Solo read_file de lo que vas a editar.
EditCore actualiza este archivo tras cambios. No pedirlo al usuario. No pegar codigo largo.

## Proceso
- Fase: implementacion
- Estado: Ciclo finalizado.
- Actualizado: 2026-11-08 22:54
- Preview: desconocido — usa el preview del IDE, no inventes puertos

## Mapa
- templates/ai_agent.html
- app.py
- .env
- .gitignore
- 200
- alfa_lubes.db
- flask.log
- FOTOS/
- README.md
- requirements.txt
- server.log
- static/
- templates/
- __pycache__/
- templates/base.html

## Archivos clave (no reexplorar)
- app.py
- templates/ai_agent.html
- requirements.txt
- .env
- templates/base.html

## Tarea activa
- SOLICITUD:
1. Agregar leyenda llamativa "LOS MEJORES ACEITES IMPORTADOS" y apartado con fotos para venta por pallets de aceites importados.
2. Integrar Supabase con URL y credenciales (https://eihvypcvmjbcfumllxrv.supabase.co).

PLAN COMPLETADO:
1. Leyenda llamativa y sección premium de "LOS MEJORES ACEITES IMPORTADOS — Venta por Pallets y Tarimas" agregada en index.html y página dedicada /pallets.
2. Generación e integración de fotos de almacén de pallets y tarimas completas selladas de aceite importado.
3. Configuración de credenciales de Supabase en .env y creación del helper supabase_get() con fallback local en app.py.
4. Creación del script SQL completo supabase_schema.sql listo para ejecutar en Supabase (tablas pallets, products, orders, clients con RLS).
5. Entrenamiento del Asesor IA para responder autónomamente sobre venta de aceites importados por pallets y cotizaciones mayoristas.

## Bloqueos / bugs conocidos
- Ninguno. Verificado con test_client y Python 3.12.

## Decisiones
- Se creó la ruta dedicada /pallets y se enlazó en la barra de navegación principal de base.html.
- Se implementó fallback transparente: lee de Supabase si está disponible; si aún no se ejecutan las migraciones en Supabase, lee de SQLite local para no interrumpir el sitio.

## Cambios recientes
- supabase_schema.sql (esquema SQL completo para Supabase)
- app.py (integración Supabase, tabla pallets, ruta /pallets, prompt y fallback de IA con pallets)
- .env (SUPABASE_URL, SUPABASE_KEY, SUPABASE_PUBLISHABLE_KEY)
- templates/pallets.html (página dedicada de tarimas y aceites importados con fotos y botones de cotización)
- templates/index.html (sección llamativa "LOS MEJORES ACEITES IMPORTADOS" con fotos de pallets)
- templates/base.html (enlace en navbar a Pallets & Mayoreo)
- templates/ai_agent.html (preguntas sugeridas de pallets importados)

## Verificado
- Endpoints probados exitosamente: /, /products, /ai-agent, /robots.txt, /sitemap.xml, /api/ai-chat.

## Siguiente
- Conectar ID definitivo de Google Analytics y credenciales SMTP reales si se desea envío activo por correo.

## Regla anti-reexploracion
- Si el pedido del usuario apunta a un archivo ya listado arriba: ve DIRECTO a read_file/replace_in_file de ese path.
- PROHIBIDO list_files('.') / project_discovery / codebase_map del repo completo en el mismo turno si el Mapa ya tiene >= 5 entradas utiles.
- Tras mutar: EditCore refresca este ROADMAP; continua desde aqui en el siguiente mensaje.
