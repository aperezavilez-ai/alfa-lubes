# ALFA LUBES — ROADMAP

Fuente de verdad del proceso del proyecto para el agente. LEER ESTO ANTES de cualquier tool.
PROHIBIDO reexplorar el repo entero si este documento cubre la tarea. Solo read_file de lo que vas a editar.
EditCore actualiza este archivo tras cambios. No pedirlo al usuario. No pegar codigo largo.

## Proceso
- Fase: implementacion
- Estado: Patch OK: app.py (2026-11-11 01:55)
- Actualizado: 2026-11-11 01:55
- Preview: desconocido — usa el preview del IDE, no inventes puertos

## Mapa
- app.py
- .env.example
- templates/ai_agent.html
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
- (raiz)/
- supabase_schema.sql
- templates/index.html
- templates/pallets.html

## Archivos clave (no reexplorar)
- app.py
- .env.example
- .gitignore
- requirements.txt
- supabase_schema.sql
- templates/index.html
- templates/pallets.html
- .env
- templates/ai_agent.html
- templates/base.html

## Tarea activa
- AUTORIZACION DE EJECUCION (PROCEDE): las reglas de DIAGNOSTICO / NO MODIFICAR del analisis previo quedan ANULADAS para esta corrida.

## Bloqueos / bugs conocidos
- Ninguno registrado

## Decisiones
- Se creó la ruta dedicada /pallets y se enlazó en la barra de navegación principal de base.html.
- Se implementó fallback transparente: lee de Supabase si está disponible; si aún no se ejecutan las migraciones en Supabase, lee de SQLite local para no interrumpir el sitio.

## Cambios recientes
- app.py — parche aplicado (kernel) (2026-11-11 01:55)
- app.py — parche aplicado (kernel) (2026-11-11 01:54)
- .env.example — archivo escrito (kernel) (2026-11-11 01:52)
- app.py
- .gitignore
- requirements.txt
- supabase_schema.sql
- templates/index.html
- templates/pallets.html
- .env
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
- Proponer optimización o nueva funcionalidad.

## Regla anti-reexploracion
- Si el pedido del usuario apunta a un archivo ya listado arriba: ve DIRECTO a read_file/replace_in_file de ese path.
- PROHIBIDO list_files('.') / project_discovery / codebase_map del repo completo en el mismo turno si el Mapa ya tiene >= 5 entradas utiles.
- Tras mutar: EditCore refresca este ROADMAP; continua desde aqui en el siguiente mensaje.
