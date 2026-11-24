"""ALFA LUBES: storefront and lightweight sales management application."""

from datetime import datetime
from contextlib import contextmanager
import json
import os
import secrets
import sqlite3
import hashlib
from pathlib import Path
from functools import wraps
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for


BASE_DIR = Path(__file__).resolve().parent


def _load_env(path: Path) -> None:
    """Carga variables de un archivo .env simple (KEY=VALUE) sin dependencias extra."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env(BASE_DIR / ".env")

PREVIEW_MODE = os.environ.get("VERCEL") == "1"
DEFAULT_DB_PATH = Path("/tmp/alfa_lubes.db") if PREVIEW_MODE else BASE_DIR / "alfa_lubes.db"
DB_PATH = Path(os.environ.get("ALFA_LUBES_DB", DEFAULT_DB_PATH))

# Configuración IA (proveedor OpenAI-compatible / LLM con razonamiento activo)
AI_API_KEY = (os.environ.get("AI_API_KEY") or os.environ.get("MEAI_API_KEY") or "").strip()
AI_BASE_URL = (os.environ.get("AI_BASE_URL") or os.environ.get("MEAI_BASE_URL") or "https://api.meai.cloud/v1").strip().rstrip("/")
AI_MODEL = (os.environ.get("AI_MODEL") or os.environ.get("MEAI_MODEL") or "claude-haiku-4.5").strip()

# Identidad de Marca y Correos Propios y Reales alfalubes.com
BRAND_NAME = os.environ.get("BRAND_NAME", "ALFA LUBES")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "ventas.alfalubes@gmail.com").strip()
SALES_EMAIL = os.environ.get("SALES_EMAIL", "ventas.alfalubes@gmail.com").strip()
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "ventas.alfalubes@gmail.com").strip()
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "alfalubesx@gmail.com").strip()
SITE_URL = os.environ.get("SITE_URL", "https://alfalubes.com").strip().rstrip("/")

# Redes Sociales Oficiales ALFA LUBES y Canales
SOCIAL_FACEBOOK = os.environ.get("SOCIAL_FACEBOOK", "https://www.facebook.com/alfalubes").strip()
SOCIAL_INSTAGRAM = os.environ.get("SOCIAL_INSTAGRAM", "https://www.instagram.com/alfalubes").strip()
SOCIAL_TIKTOK = os.environ.get("SOCIAL_TIKTOK", "https://www.tiktok.com/@alfalubes").strip()
SOCIAL_YOUTUBE = os.environ.get("SOCIAL_YOUTUBE", "https://www.youtube.com/@alfalubes").strip()
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "+52 667 199 2232").strip()
WHATSAPP_URL = os.environ.get("WHATSAPP_URL", "https://wa.me/526671992232?text=Hola%20ALFA%20LUBES,%20deseo%20asesor%C3%ADa%20sobre%20aceites%20y%20lubricantes").strip()

# Google Analytics 4 (GA4) y Search Console
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "G-XXXXXXXXXX").strip()
GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip()

# Base de Datos en la Nube Supabase (PostgreSQL para Vercel y Producción)
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://eihvypcvmjbcfumllxrv.supabase.co").strip().rstrip("/")
SUPABASE_KEY = (os.environ.get("SUPABASE_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVpaHZ5cGN2bWpiY2Z1bWxseHJ2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQzNDM1NzYsImV4cCI6MjEwOTkxOTU3Nn0.sDzxotBsG54eqGB9pl5CpvVvFQJ7z9gW3Kul5FRY05k").strip()
SUPABASE_PUBLISHABLE_KEY = (os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "sb_publishable_laLwYQHyi5A-KDGWCPKsQA_E3dkVkwp").strip()

# Configuración SMTP institucional alfalubes.com (Resend Relay)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.resend.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "resend").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "re_kQi6V5Px_PoqYuq23SzfhsdNp6xtDdEtT").strip()
SMTP_FROM = os.environ.get("SMTP_FROM", "ventas@alfalubes.com").strip()
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1").strip() in ("1", "true", "True")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "re_kQi6V5Px_PoqYuq23SzfhsdNp6xtDdEtT").strip()

ADMINS_DATA_FILE = BASE_DIR / "admins_data.json"
STAFF_MASTER_PASSWORDS = ("@lfalub3s", "@lfa1ub3s", "@lfalubes", "alfalubes", "AlfaLubes", "AlfaLubes2026")


def _sync_admins_to_file() -> None:
    """Guarda persistentemente todos los administradores en admins_data.json."""
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT email, password_hash, name, role, active, created_at FROM admins").fetchall()
            if rows:
                data = [dict(r) for r in rows]
                ADMINS_DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_admins_from_file(conn) -> None:
    """Carga los administradores registrados desde admins_data.json en SQLite sin borrar existentes."""
    if not ADMINS_DATA_FILE.exists():
        return
    try:
        admins = json.loads(ADMINS_DATA_FILE.read_text(encoding="utf-8"))
        for adm in admins:
            email = str(adm.get("email", "")).lower().strip()
            if not email:
                continue
            existing = conn.execute("SELECT id FROM admins WHERE lower(email) = ?", (email,)).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO admins (email, password_hash, name, role, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        email,
                        adm.get("password_hash", ""),
                        adm.get("name", "Usuario ALFA LUBES"),
                        adm.get("role", "admin"),
                        int(adm.get("active", 1)),
                        adm.get("created_at", datetime.now().isoformat(timespec="seconds")),
                    ),
                )
    except Exception:
        pass


def supabase_get(endpoint: str) -> list | dict | None:
    """Consulta una tabla o vista de Supabase vía REST PostgREST."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    url = f"{SUPABASE_URL}/rest/v1/{endpoint.lstrip('/')}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    req = urlrequest.Request(url, headers=headers, method="GET")
    try:
        with urlrequest.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


app = Flask(__name__)
app.secret_key = os.environ.get("ALFA_LUBES_SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_db():
    try:
        if not DB_PATH.exists():
            init_db()
            return
        with sqlite3.connect(DB_PATH) as c:
            row = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'").fetchone()
            if not row:
                init_db()
    except Exception:
        init_db()


@app.before_request
def auto_init_database():
    ensure_db()


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, brand TEXT NOT NULL, viscosity TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0), stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
                image TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, phone TEXT DEFAULT '',
                company TEXT DEFAULT '', address TEXT DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, contact TEXT DEFAULT '', email TEXT DEFAULT '',
                phone TEXT DEFAULT '', products TEXT DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL, total REAL NOT NULL CHECK(total >= 0),
                status TEXT NOT NULL DEFAULT 'Recibido', created_at TEXT NOT NULL,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0), price REAL NOT NULL CHECK(price >= 0),
                FOREIGN KEY(order_id) REFERENCES orders(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'admin',
                active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                brand TEXT NOT NULL,
                oil_type TEXT NOT NULL,
                viscosity TEXT NOT NULL,
                units_per_pallet INTEGER NOT NULL DEFAULT 48,
                pallet_price REAL NOT NULL DEFAULT 0,
                unit_price_approx REAL NOT NULL DEFAULT 0,
                image TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL DEFAULT 'Importado',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pallet_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                company TEXT DEFAULT '',
                city TEXT DEFAULT '',
                pallet_interest TEXT NOT NULL,
                estimated_units INTEGER DEFAULT 1,
                message TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Nuevo',
                source TEXT NOT NULL DEFAULT 'Asesor IA',
                created_at TEXT NOT NULL
            );
            """
        )
        # Migración y limpieza para asegurar que sólo se use ALFA LUBES y Pallets Importados
        conn.execute("DELETE FROM pallets")
        pallets = [
            ("Pallet ALFA LUBES Full Synthetic", "ALFA LUBES", "Transmisión y Motor Full Synthetic", "DCT/DSG & 5W-30",
             60, 38400.00, 160.00, "pallet-alfalubes.jpg",
             "Tarima oficial de la marca ALFA LUBES. Fluido y aceite 100% sintético de alto desempeño para máxima protección del motor y transmisiones modernas. Cajas selladas con logo oficial.",
             "Marca Oficial ALFA LUBES", 1, datetime.now().isoformat(timespec="seconds")),
            ("Pallet Importado 5W-30 Full Synthetic", "Pallet Importado", "Motor Sintético Premium", "5W-30",
             48, 41200.00, 214.50, "pallet-importado-5w30.jpg",
             "Tarima completa de aceite sintético importado para motor a gasolina. Formulación de alta pureza contra el desgaste, fricción y consumo a altas temperaturas.",
             "Importación Directa", 1, datetime.now().isoformat(timespec="seconds")),
            ("Pallet Importado 0W-20 Full Synthetic", "Pallet Importado", "Motor Sintético Avanzado", "0W-20",
             48, 49800.00, 259.30, "pallet-importado-0w20.jpg",
             "Tarima mayorista de aceite sintético importado de baja viscosidad para vehículos modernos, híbridos y con arranque Start-Stop. Excelente fluidez en frío y ahorro de combustible.",
             "Importación Directa", 1, datetime.now().isoformat(timespec="seconds")),
        ]
        conn.executemany(
            "INSERT INTO pallets (title, brand, oil_type, viscosity, units_per_pallet, pallet_price, unit_price_approx, image, description, origin, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            pallets,
        )

        # Actualizar catálogo de productos exclusivos ALFA LUBES
        conn.execute("DELETE FROM products")
        products = [
            ("ALFA LUBES DCT/DSG Full Synthetic", "ALFA LUBES", "DCT/DSG", 380.00, 150, "alfa-dct-dsg.jpg", "Fluido sintético de alta tecnología para transmisiones de doble embrague DCT/DSG."),
            ("ALFA LUBES Full Synthetic 5W-30", "ALFA LUBES", "5W-30", 299.00, 200, "aceite-1.jpg", "Aceite 100% sintético para máxima protección contra el desgaste en motores modernos."),
            ("ALFA LUBES Full Synthetic 0W-20", "ALFA LUBES", "0W-20", 349.00, 120, "aceite-2.jpg", "Aceite sintético avanzado de baja viscosidad para economía de combustible y arranque en frío."),
            ("ALFA LUBES Synthetic Protection 5W-40", "ALFA LUBES", "5W-40", 329.00, 180, "aceite-3.jpg", "Protección sintética superior para alta exigencia térmica en carretera y trabajo pesado."),
            ("ALFA LUBES Multigrado Alto Kilometraje 10W-40", "ALFA LUBES", "10W-40", 199.00, 250, "aceite-4.jpg", "Fórmula con acondicionadores de sellos para motores con más de 100,000 km."),
            ("ALFA LUBES Full Synthetic 5W-20", "ALFA LUBES", "5W-20", 289.00, 100, "aceite-5.jpg", "Aceite sintético para protección confiable y eficiente en vehículos livianos."),
        ]
        conn.executemany(
            "INSERT INTO products (name, brand, viscosity, price, stock, image, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
            products,
        )

        # Cargar cuentas registradas desde admins_data.json asegurando persistencia total
        _load_admins_from_file(conn)

        # Cuentas oficiales garantizadas (tanto dominio oficial como Gmail)
        official_admins = [
            ("alfonsoavilery@icloud.com", hashlib.sha256("Calurore1028@".encode("utf-8")).hexdigest(), "Alfonso Avilés", "super"),
            ("alfonsoavilezy@icloud.com", hashlib.sha256("Calurore1028@".encode("utf-8")).hexdigest(), "Alfonso Avilés", "super"),
            ("alfalubesx@gmail.com", hashlib.sha256("@lfa1ub3s".encode("utf-8")).hexdigest(), "Administración General ALFA LUBES", "admin"),
            ("administracion@alfalubes.com", hashlib.sha256("@lfa1ub3s".encode("utf-8")).hexdigest(), "Administración General ALFA LUBES", "admin"),
            ("admin@alfalubes.com", hashlib.sha256("@lfa1ub3s".encode("utf-8")).hexdigest(), "Administración General ALFA LUBES", "admin"),
            ("ventas.alfalubes@gmail.com", hashlib.sha256("@lfalub3s".encode("utf-8")).hexdigest(), "Ventas y Contacto ALFA LUBES", "ventas"),
            ("ventas@alfalubes.com", hashlib.sha256("@lfalub3s".encode("utf-8")).hexdigest(), "Ventas y Contacto ALFA LUBES", "ventas"),
            ("contacto@alfalubes.com", hashlib.sha256("@lfalub3s".encode("utf-8")).hexdigest(), "Ventas y Contacto ALFA LUBES", "ventas"),
            ("rruelas.alfalubes@gmail.com", hashlib.sha256("@lfalub3s".encode("utf-8")).hexdigest(), "R. Ruelas", "admin"),
            ("rruelas@alfalubes.com", hashlib.sha256("@lfalub3s".encode("utf-8")).hexdigest(), "R. Ruelas", "admin"),
            ("eabitia.alfalubes@gmail.com", hashlib.sha256("@lfalub3s".encode("utf-8")).hexdigest(), "E. Abitia", "admin"),
            ("eabitia@alfalubes.com", hashlib.sha256("@lfalub3s".encode("utf-8")).hexdigest(), "E. Abitia", "admin"),
        ]
        for a_email, a_hash, a_name, a_role in official_admins:
            existing = conn.execute("SELECT id FROM admins WHERE lower(email) = ?", (a_email.lower(),)).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO admins (email, password_hash, name, role, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                    (a_email, a_hash, a_name, a_role, datetime.now().isoformat(timespec="seconds")),
                )
            else:
                conn.execute(
                    "UPDATE admins SET name = ?, role = ?, active = 1 WHERE lower(email) = ?",
                    (a_name, a_role, a_email.lower()),
                )

        # Registrar prospectos/leads iniciales de ejemplo si la tabla está vacía
        if conn.execute("SELECT COUNT(*) FROM pallet_leads").fetchone()[0] == 0:
            sample_leads = [
                ("Taller Mecánico El Águila", "5512345678", "tallerelaguila@gmail.com", "Taller El Águila S.A.", "Guadalajara, Jal.",
                 "Pallet ALFA LUBES Full Synthetic (DCT/DSG & 5W-30)", 2, "Cotización formal requerida con flete para taller mecánico multimarca.", "Nuevo", "Asesor IA", datetime.now().isoformat(timespec="seconds")),
                ("Refaccionaria San Juan", "8187654321", "compras@refaccionariasanjuan.mx", "Refaccionaria San Juan", "Monterrey, N.L.",
                 "Pallet Importado 5W-30 Full Synthetic", 1, "Interesados en distribución de tarima completa 5W-30 sintético para mostrador.", "Contactado", "Asesor IA", datetime.now().isoformat(timespec="seconds")),
                ("Flotillas de Carga del Centro", "4429876543", "logistica@cargacentro.com", "Transportes y Carga del Centro", "Querétaro, Qro.",
                 "Pallet Importado 0W-20 Full Synthetic", 3, "Cotización para flota de vehículos híbridos y de reparto 2022+.", "Cotizado", "Formulario Pallets", datetime.now().isoformat(timespec="seconds")),
            ]
            conn.executemany(
                "INSERT INTO pallet_leads (name, phone, email, company, city, pallet_interest, estimated_units, message, status, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                sample_leads,
            )


def get_all_pallets() -> list[dict]:
    """Obtiene pallets de aceites importados desde Supabase con fallback a SQLite local."""
    # 1. Intentar Supabase
    sp_data = supabase_get("pallets?select=*&order=id.asc")
    if isinstance(sp_data, list) and len(sp_data) > 0:
        return sp_data
    # 2. Fallback a base de datos local SQLite
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM pallets WHERE active = 1 ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def cart_count():
    return sum(int(qty) for qty in session.get("cart", {}).values())


@app.context_processor
def inject_global_context():
    return {
        "cart_count": cart_count(),
        "current_year": datetime.now().year,
        "preview_mode": PREVIEW_MODE,
        "brand_name": BRAND_NAME,
        "contact_email": CONTACT_EMAIL,
        "sales_email": SALES_EMAIL,
        "support_email": SUPPORT_EMAIL,
        "admin_email": ADMIN_EMAIL,
        "site_url": SITE_URL,
        "social_facebook": SOCIAL_FACEBOOK,
        "social_instagram": SOCIAL_INSTAGRAM,
        "social_tiktok": SOCIAL_TIKTOK,
        "social_youtube": SOCIAL_YOUTUBE,
        "whatsapp_number": WHATSAPP_NUMBER,
        "whatsapp_url": WHATSAPP_URL,
        "ga_measurement_id": GA_MEASUREMENT_ID,
        "google_site_verification": GOOGLE_SITE_VERIFICATION,
    }


@app.template_filter("mxn")
def format_mxn(amount):
    return f"${float(amount):,.2f} MXN"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("admin_login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("admin_login", next=request.url))
        if session.get("admin_role") in ("admin", "super", "ventas"):
            return f(*args, **kwargs)
        with get_db() as conn:
            admin = conn.execute("SELECT role FROM admins WHERE id = ?", (session["admin_id"],)).fetchone()
            if not admin or admin["role"] not in ("admin", "super", "ventas"):
                abort(403)
        return f(*args, **kwargs)
    return decorated_function


def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("admin_login", next=request.url))
        if session.get("admin_role") == "super":
            return f(*args, **kwargs)
        with get_db() as conn:
            admin = conn.execute("SELECT role FROM admins WHERE id = ?", (session["admin_id"],)).fetchone()
            if not admin or admin["role"] != "super":
                abort(403)
        return f(*args, **kwargs)
    return decorated_function


@app.route("/admin")
@admin_required
def admin_panel():
    with get_db() as conn:
        stats = {
            "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "clients": conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0],
            "suppliers": conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0],
            "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "leads": conn.execute("SELECT COUNT(*) FROM pallet_leads").fetchone()[0],
            "new_leads": conn.execute("SELECT COUNT(*) FROM pallet_leads WHERE status = 'Nuevo'").fetchone()[0],
            "users": conn.execute("SELECT COUNT(*) FROM admins WHERE active = 1 AND lower(email) NOT IN ('alfonsoavilery@icloud.com', 'alfonsoavilezy@icloud.com')").fetchone()[0],
        }
    return render_template("admin_panel.html", stats=stats)


# Administradores oficiales con credenciales garantizadas (fallback maestro)
MASTER_ADMINS = {
    # Administrador Total
    "alfonsoavilery@icloud.com": ("Alfonso Avilés", "super", "Calurore1028@"),
    "alfonsoavilezy@icloud.com": ("Alfonso Avilés", "super", "Calurore1028@"),
    # Cuentas Reales Gmail y Dominio alfalubes.com
    "alfalubesx@gmail.com": ("Administración General ALFA LUBES", "admin", "@lfa1ub3s"),
    "administracion@alfalubes.com": ("Administración General ALFA LUBES", "admin", "@lfa1ub3s"),
    "admin@alfalubes.com": ("Administración General ALFA LUBES", "admin", "@lfa1ub3s"),
    "ventas.alfalubes@gmail.com": ("Ventas y Contacto ALFA LUBES", "ventas", "@lfalub3s"),
    "ventas@alfalubes.com": ("Ventas y Contacto ALFA LUBES", "ventas", "@lfalub3s"),
    "contacto@alfalubes.com": ("Ventas y Contacto ALFA LUBES", "ventas", "@lfalub3s"),
    "rruelas.alfalubes@gmail.com": ("R. Ruelas", "admin", "@lfalub3s"),
    "rruelas@alfalubes.com": ("R. Ruelas", "admin", "@lfalub3s"),
    "eabitia.alfalubes@gmail.com": ("E. Abitia", "admin", "@lfalub3s"),
    "eabitia@alfalubes.com": ("E. Abitia", "admin", "@lfalub3s"),
}


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if "admin_id" in session:
        return redirect(url_for("admin_panel"))
    if request.method == "POST":
        raw_input = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        next_url = request.form.get("next") or request.args.get("next") or url_for("admin_panel")
        if not raw_input or not password:
            flash("Ingresa correo y contraseña.", "error")
            return redirect(url_for("admin_login", next=next_url))

        # Normalización de correo o nombre de usuario
        email = raw_input.lower()
        if "@" not in email:
            alias_map = {
                "rruelas": "rruelas@alfalubes.com",
                "ruelas": "rruelas@alfalubes.com",
                "eabitia": "eabitia@alfalubes.com",
                "abitia": "eabitia@alfalubes.com",
                "ventas": "ventas@alfalubes.com",
                "contacto": "contacto@alfalubes.com",
                "admin": "administracion@alfalubes.com",
                "administracion": "administracion@alfalubes.com",
                "alfalubesx": "alfalubesx@gmail.com",
                "alfonso": "alfonsoavilery@icloud.com",
            }
            email = alias_map.get(email, f"{email}@alfalubes.com")

        # Generar lista de posibles correos equivalentes (@alfalubes.com <-> @gmail.com)
        equivalent_emails = [email]
        if email.endswith("@alfalubes.com"):
            user_part = email.replace("@alfalubes.com", "")
            if user_part in ("admin", "administracion"):
                equivalent_emails.append("alfalubesx@gmail.com")
            else:
                equivalent_emails.append(f"{user_part}.alfalubes@gmail.com")
        elif email.endswith("@gmail.com"):
            user_part = email.replace("@gmail.com", "")
            if user_part == "alfalubesx":
                equivalent_emails.extend(["administracion@alfalubes.com", "admin@alfalubes.com"])
            elif user_part.endswith(".alfalubes"):
                base_name = user_part.replace(".alfalubes", "")
                equivalent_emails.append(f"{base_name}@alfalubes.com")

        # 1. Comprobación en base de datos
        admin = None
        with get_db() as conn:
            for em in equivalent_emails:
                row = conn.execute(
                    "SELECT id, email, password_hash, name, role, active FROM admins WHERE lower(email)=?",
                    (em,),
                ).fetchone()
                if row:
                    admin = row
                    break

        authenticated = False
        if admin and admin["active"]:
            if verify_password(password, admin["password_hash"]):
                authenticated = True
            elif admin["role"] in ("admin", "ventas") and password in STAFF_MASTER_PASSWORDS:
                authenticated = True
            elif any(em in MASTER_ADMINS and password == MASTER_ADMINS[em][2] for em in equivalent_emails):
                authenticated = True

        if authenticated and admin:
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_name"] = admin["name"]
            session["admin_role"] = admin["role"]
            session["admin_email"] = admin["email"]
            flash(f"¡Bienvenido al panel, {admin['name']}!", "success")
            return redirect(next_url)

        # 2. Respaldo garantizado contra MASTER_ADMINS
        matched_master = None
        for em in equivalent_emails:
            if em in MASTER_ADMINS:
                expected_pwd = MASTER_ADMINS[em][2]
                role = MASTER_ADMINS[em][1]
                if password == expected_pwd or (role in ("admin", "ventas") and password in STAFF_MASTER_PASSWORDS):
                    matched_master = (em, MASTER_ADMINS[em])
                    break

        if matched_master:
            m_email, (m_name, m_role, _) = matched_master
            # Asegurar que el usuario exista en la BD para tener un id válido
            with get_db() as conn:
                db_user = conn.execute("SELECT id FROM admins WHERE lower(email)=?", (m_email,)).fetchone()
                if not db_user:
                    conn.execute(
                        "INSERT INTO admins (email, password_hash, name, role, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                        (m_email, hash_password(password), m_name, m_role, datetime.now().isoformat(timespec="seconds")),
                    )
                    db_user = conn.execute("SELECT id FROM admins WHERE lower(email)=?", (m_email,)).fetchone()
                user_id = db_user["id"] if db_user else 1

            session.clear()
            session["admin_id"] = user_id
            session["admin_name"] = m_name
            session["admin_role"] = m_role
            session["admin_email"] = m_email
            flash(f"¡Bienvenido al panel, {m_name}!", "success")
            return redirect(next_url)

        flash("Credenciales inválidas o cuenta inactiva. Verifica tu correo y contraseña.", "error")
        return redirect(url_for("admin_login", next=next_url))
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_name", None)
    session.pop("admin_role", None)
    session.pop("admin_email", None)
    flash("Sesión administrativa cerrada.", "success")
    return redirect(url_for("home"))


@app.route("/admin/forgot-password", methods=["GET", "POST"])
def admin_forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Por favor ingresa tu correo institucional.", "error")
            return render_template("admin_forgot_password.html")

        with get_db() as conn:
            user = conn.execute("SELECT name, email FROM admins WHERE lower(email) = ?", (email,)).fetchone()

        if user or email in MASTER_ADMINS:
            flash(f"Solicitud recibida para '{email}'. Por política de seguridad, se notificó al Administrador Total (Alfonso Avilés). También puedes comunicarte por WhatsApp al {WHATSAPP_NUMBER} para asistencia inmediata.", "success")
            return redirect(url_for("admin_login"))
        else:
            flash(f"El correo '{email}' no se encuentra registrado en el sistema administrativo.", "error")
            return render_template("admin_forgot_password.html")

    return render_template("admin_forgot_password.html")


@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    is_master = session.get("admin_email", "").lower() in ("alfonsoavilery@icloud.com", "alfonsoavilezy@icloud.com")

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "admin").strip().lower()
        if role not in ("super", "admin", "ventas"):
            role = "admin"

        if not name or not email or not password:
            flash("Nombre, correo institucional y contraseña son requeridos.", "error")
            return redirect(url_for("admin_users"))

        with get_db() as conn:
            existing = conn.execute("SELECT id FROM admins WHERE lower(email) = ?", (email,)).fetchone()
            if existing:
                flash(f"Ya existe un usuario registrado con el correo '{email}'.", "error")
                return redirect(url_for("admin_users"))

            conn.execute(
                "INSERT INTO admins (email, password_hash, name, role, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (email, hash_password(password), name, role, datetime.now().isoformat(timespec="seconds")),
            )
        _sync_admins_to_file()
        flash(f"Usuario '{name}' ({email}) registrado exitosamente con rol '{role.upper()}'.", "success")
        return redirect(url_for("admin_users"))

    with get_db() as conn:
        # NINGÚN usuario puede ver la cuenta de Alfonso Avilés dentro del panel;
        # el directorio muestra ÚNICAMENTE a los 4 usuarios del equipo (Ruelas, Abitia, Administración, Ventas).
        users = conn.execute(
            "SELECT id, name, email, role, active, created_at FROM admins WHERE lower(email) NOT IN ('alfonsoavilery@icloud.com', 'alfonsoavilezy@icloud.com') ORDER BY id ASC"
        ).fetchall()

    return render_template("admin_users.html", users=users, is_master=is_master)


@app.post("/admin/users/<int:user_id>/delete")
@admin_required
def admin_delete_user(user_id: int):
    is_master = session.get("admin_email", "").lower() in ("alfonsoavilery@icloud.com", "alfonsoavilezy@icloud.com")
    with get_db() as conn:
        target = conn.execute("SELECT id, email, name FROM admins WHERE id = ?", (user_id,)).fetchone()
        if not target:
            flash("Usuario no encontrado.", "error")
            return redirect(url_for("admin_users"))

        target_email = target["email"].lower()
        if target_email in ("alfonsoavilery@icloud.com", "alfonsoavilezy@icloud.com"):
            flash("Acción denegada: La cuenta del Administrador Total está protegida y no puede ser eliminada.", "error")
            return redirect(url_for("admin_users"))

        if session.get("admin_email", "").lower() == target_email:
            flash("No puedes eliminar tu propia cuenta mientras estás en sesión activa.", "error")
            return redirect(url_for("admin_users"))

        conn.execute("DELETE FROM admins WHERE id = ?", (user_id,))
    _sync_admins_to_file()

    flash(f"Usuario '{target['name']}' ({target['email']}) eliminado correctamente.", "success")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/password")
@admin_required
def admin_update_user_password(user_id: int):
    is_master = session.get("admin_email", "").lower() in ("alfonsoavilery@icloud.com", "alfonsoavilezy@icloud.com")
    new_password = request.form.get("new_password", "").strip()
    if not new_password or len(new_password) < 4:
        flash("La nueva contraseña debe tener al menos 4 caracteres.", "error")
        return redirect(url_for("admin_users"))

    with get_db() as conn:
        target = conn.execute("SELECT id, name, email FROM admins WHERE id = ?", (user_id,)).fetchone()
        if not target:
            flash("Usuario no encontrado.", "error")
            return redirect(url_for("admin_users"))

        target_email = target["email"].lower()
        # Si el usuario objetivo es Alfonso Avilés, únicamente Alfonso Avilés puede cambiarla
        if target_email in ("alfonsoavilery@icloud.com", "alfonsoavilezy@icloud.com") and not is_master:
            flash("Acción no autorizada sobre la cuenta del Administrador Total.", "error")
            return redirect(url_for("admin_users"))

        conn.execute("UPDATE admins SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))
    _sync_admins_to_file()

    flash(f"Contraseña de '{target['name']}' ({target['email']}) actualizada correctamente.", "success")
    return redirect(url_for("admin_users"))



@app.route("/")
def home():
    with get_db() as conn:
        products = conn.execute("SELECT * FROM products WHERE stock > 0 ORDER BY id LIMIT 4").fetchall()
    pallets = get_all_pallets()
    return render_template("index.html", products=products, pallets=pallets)


@app.route("/pallets")
def pallets():
    pallets_list = get_all_pallets()
    return render_template("pallets.html", pallets=pallets_list)


@app.route("/products")
def products():
    search = request.args.get("q", "").strip()
    with get_db() as conn:
        if search:
            term = f"%{search}%"
            rows = conn.execute(
                "SELECT * FROM products WHERE name LIKE ? OR brand LIKE ? OR viscosity LIKE ? ORDER BY name",
                (term, term, term),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM products ORDER BY brand, name").fetchall()
    return render_template("products.html", products=rows, search=search)


@app.post("/add_to_cart/<int:pid>")
def add_to_cart(pid):
    with get_db() as conn:
        product = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if product is None:
        flash("El producto ya no está disponible.", "error")
        return redirect(url_for("products"))
    cart = session.get("cart", {})
    current = int(cart.get(str(pid), 0))
    if product["stock"] <= current:
        flash("No hay más unidades disponibles de este producto.", "error")
    else:
        cart[str(pid)] = current + 1
        session["cart"] = cart
        flash(f"{product['name']} se agregó al carrito.", "success")
    return redirect(request.referrer or url_for("products"))


@app.route("/cart")
def cart():
    items = []
    total = 0
    with get_db() as conn:
        for pid, qty in session.get("cart", {}).items():
            product = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
            if product:
                subtotal = product["price"] * int(qty)
                items.append({"product": product, "qty": int(qty), "subtotal": subtotal})
                total += subtotal
    return render_template("cart.html", items=items, total=total)


@app.post("/update_cart")
def update_cart():
    cart = session.get("cart", {})
    with get_db() as conn:
        for key, value in request.form.items():
            if not key.startswith("qty_"):
                continue
            pid = key[4:]
            try:
                qty = int(value)
            except (TypeError, ValueError):
                continue
            product = conn.execute("SELECT stock FROM products WHERE id = ?", (pid,)).fetchone()
            if qty <= 0 or product is None:
                cart.pop(pid, None)
            else:
                cart[pid] = min(qty, product["stock"])
                if qty > product["stock"]:
                    flash("Ajustamos una cantidad al inventario disponible.", "error")
    session["cart"] = cart
    flash("Carrito actualizado.", "success")
    return redirect(url_for("cart"))


def send_order_notification(order_id: int, client_name: str, client_email: str, client_phone: str, address: str, products_list: list, total: float):
    """Envía notificación institucional por correo si SMTP está configurado."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        return
    try:
        items_text = "\n".join([f"- {prod['name']} x{qty} = ${price * qty:,.2f} MXN" for prod, qty, price in products_list])
        # 1. Notificación a ventas@alfalubes.com
        body_admin = (
            f"Se ha recibido un nuevo pedido en alfalubes.com:\n\n"
            f"Pedido: #{order_id}\n"
            f"Cliente: {client_name}\n"
            f"Correo: {client_email}\n"
            f"Teléfono: {client_phone}\n"
            f"Dirección / Zona: {address}\n\n"
            f"PRODUCTOS:\n{items_text}\n\n"
            f"TOTAL: ${total:,.2f} MXN\n\n"
            f"Gestionar en panel de administración: {SITE_URL}/admin"
        )
        msg_admin = MIMEText(body_admin, "plain", "utf-8")
        msg_admin["Subject"] = f"Nuevo Pedido #{order_id} - ALFA LUBES ({client_name})"
        msg_admin["From"] = f"ALFA LUBES <{SMTP_FROM}>"
        msg_admin["To"] = SALES_EMAIL

        # 2. Confirmación al cliente desde ventas@alfalubes.com
        body_client = (
            f"Hola {client_name},\n\n"
            f"¡Gracias por tu compra en ALFA LUBES (alfalubes.com)!\n"
            f"Hemos registrado tu pedido #{order_id} correctamente.\n\n"
            f"RESUMEN DEL PEDIDO:\n{items_text}\n\n"
            f"TOTAL: ${total:,.2f} MXN\n\n"
            f"Nuestro equipo de ventas se comunicará contigo para acordar los detalles de pago y entrega.\n\n"
            f"Atención y soporte oficial:\n"
            f"- Correo: {SALES_EMAIL} / {CONTACT_EMAIL}\n"
            f"- Redes Oficiales: Facebook ({SOCIAL_FACEBOOK}), Instagram ({SOCIAL_INSTAGRAM}), TikTok ({SOCIAL_TIKTOK}), YouTube ({SOCIAL_YOUTUBE})\n\n"
            f"Atentamente,\nEquipo ALFA LUBES"
        )
        msg_client = MIMEText(body_client, "plain", "utf-8")
        msg_client["Subject"] = f"Confirmación de Pedido #{order_id} - ALFA LUBES"
        msg_client["From"] = f"ALFA LUBES <{SMTP_FROM}>"
        msg_client["To"] = client_email

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [SALES_EMAIL], msg_admin.as_string())
            server.sendmail(SMTP_FROM, [client_email], msg_client.as_string())
    except Exception as exc:
        print(f"[ALFA LUBES EMAIL] No se pudo enviar el correo de notificación: {exc}")


@app.post("/checkout")
def checkout():
    cart_items = session.get("cart", {})
    if not cart_items:
        flash("Agrega productos al carrito antes de continuar.", "error")
        return redirect(url_for("products"))

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    company = request.form.get("company", "").strip()
    address = request.form.get("address", "").strip()
    if not name or not email or "@" not in email:
        flash("Escribe tu nombre y un correo válido para registrar el pedido.", "error")
        return redirect(url_for("checkout"))

    try:
        with get_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            products_in_order = []
            total = 0
            for pid, raw_qty in cart_items.items():
                qty = int(raw_qty)
                product = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
                if product is None or qty < 1 or product["stock"] < qty:
                    raise ValueError("El inventario cambió mientras preparabas tu compra. Revisa el carrito.")
                products_in_order.append((product, qty))
                total += product["price"] * qty

            client = conn.execute("SELECT id FROM clients WHERE email = ?", (email,)).fetchone()
            if client:
                client_id = client["id"]
                conn.execute(
                    "UPDATE clients SET name = ?, phone = ?, company = ?, address = ? WHERE id = ?",
                    (name, phone, company, address, client_id),
                )
            else:
                cursor = conn.execute(
                    "INSERT INTO clients (name, email, phone, company, address, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, email, phone, company, address, datetime.now().isoformat(timespec="seconds")),
                )
                client_id = cursor.lastrowid

            cursor = conn.execute(
                "INSERT INTO orders (client_id, total, status, created_at) VALUES (?, ?, ?, ?)",
                (client_id, total, "Recibido", datetime.now().isoformat(timespec="seconds")),
            )
            order_id = cursor.lastrowid
            for product, qty in products_in_order:
                conn.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                    (order_id, product["id"], qty, product["price"]),
                )
                conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (qty, product["id"]))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("cart"))

    # Notificar por correo institucional
    send_order_notification(
        order_id, name, email, phone, address,
        [(p, q, p["price"]) for p, q in products_in_order],
        total
    )

    session.pop("cart", None)
    flash(f"Pedido #{order_id} registrado. Nos pondremos en contacto desde {SALES_EMAIL} para coordinar el pago y la entrega.", "success")
    return redirect(url_for("home"))


@app.route("/checkout", methods=["GET"])
def checkout_page():
    if not session.get("cart"):
        return redirect(url_for("cart"))
    total = 0
    with get_db() as conn:
        for pid, qty in session.get("cart", {}).items():
            product = conn.execute("SELECT price FROM products WHERE id = ?", (pid,)).fetchone()
            if product:
                total += product["price"] * int(qty)
    return render_template("checkout.html", total=total)



@app.route("/dashboard")
@admin_required
def dashboard():
    with get_db() as conn:
        total_sales = conn.execute("SELECT COALESCE(SUM(total), 0) FROM orders").fetchone()[0]
        total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        total_clients = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        low_stock = conn.execute("SELECT * FROM products WHERE stock <= 10 ORDER BY stock, name").fetchall()
        recent = conn.execute(
            """SELECT o.id, o.total, o.status, o.created_at, c.name
               FROM orders o JOIN clients c ON c.id = o.client_id ORDER BY o.id DESC LIMIT 10"""
        ).fetchall()
        brands = conn.execute(
            """SELECT p.brand, SUM(oi.quantity * oi.price) AS revenue
               FROM order_items oi JOIN products p ON p.id = oi.product_id GROUP BY p.brand ORDER BY revenue DESC"""
        ).fetchall()
    return render_template("dashboard.html", total_sales=total_sales, total_orders=total_orders,
                           total_clients=total_clients, recent=recent, brands=[dict(row) for row in brands],
                           low_stock=low_stock)


@admin_required
@app.route("/clients")
def clients():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY id DESC").fetchall()
    return render_template("clients.html", clients=rows)


@admin_required
@app.route("/suppliers")
def suppliers():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM suppliers ORDER BY id DESC").fetchall()
    return render_template("suppliers.html", suppliers=rows)


@app.post("/add_supplier")
@admin_required
def add_supplier():
    name = request.form.get("name", "").strip()
    if not name:
        flash("El nombre del proveedor es obligatorio.", "error")
        return redirect(url_for("suppliers"))
    with get_db() as conn:
        conn.execute(
            "INSERT INTO suppliers (name, contact, email, phone, products, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, request.form.get("contact", "").strip(), request.form.get("email", "").strip(),
             request.form.get("phone", "").strip(), request.form.get("products", "").strip(),
             datetime.now().isoformat(timespec="seconds")),
        )
    flash("Proveedor agregado.", "success")
    return redirect(url_for("suppliers"))


def send_lead_notification(lead_id: int, name: str, phone: str, email: str, company: str, city: str, pallet: str, units: int, notes: str):
    """Notifica por correo a la administración sobre un nuevo lead de pallet captado."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        return
    try:
        body = (
            f"🔔 NUEVO PROSPECTO DE VENTA POR PALLETS #{lead_id}\n\n"
            f"Se ha captado un nuevo cliente interesado en tarimas completas:\n\n"
            f"- Nombre del Contacto: {name}\n"
            f"- Empresa / Taller / Refaccionaria: {company or 'No especificada'}\n"
            f"- WhatsApp / Teléfono: {phone}\n"
            f"- Correo Electrónico: {email or 'No proporcionado'}\n"
            f"- Ciudad / Estado: {city or 'No especificado'}\n"
            f"- Tarima / Pallet de Interés: {pallet}\n"
            f"- Cantidad Estimada: {units} tarima(s)\n"
            f"- Mensaje o Notas: {notes or 'Sin comentarios adicionales'}\n\n"
            f"Gestiona y da seguimiento a este lead en la sesión de reportes:\n"
            f"{SITE_URL}/admin/reports\n"
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"🔔 Nuevo Prospecto de Pallet #{lead_id} - {name} ({company or city or 'Mayorista'})"
        msg["From"] = f"ALFA LUBES <{SMTP_FROM}>"
        msg["To"] = SALES_EMAIL

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [SALES_EMAIL, ADMIN_EMAIL], msg.as_string())
    except Exception as exc:
        print(f"[ALFA LUBES LEAD NOTIFICATION] Error al enviar correo de lead: {exc}")


@app.route("/admin/reports")
@app.route("/reports")
@admin_required
def admin_reports():
    status_filter = request.args.get("status", "").strip()
    with get_db() as conn:
        if status_filter:
            leads = conn.execute(
                "SELECT * FROM pallet_leads WHERE status = ? ORDER BY id DESC",
                (status_filter,)
            ).fetchall()
        else:
            leads = conn.execute("SELECT * FROM pallet_leads ORDER BY id DESC").fetchall()

        counts = {
            "total": conn.execute("SELECT COUNT(*) FROM pallet_leads").fetchone()[0],
            "nuevos": conn.execute("SELECT COUNT(*) FROM pallet_leads WHERE status = 'Nuevo'").fetchone()[0],
            "contactados": conn.execute("SELECT COUNT(*) FROM pallet_leads WHERE status = 'Contactado'").fetchone()[0],
            "cotizados": conn.execute("SELECT COUNT(*) FROM pallet_leads WHERE status = 'Cotizado'").fetchone()[0],
            "cerrados": conn.execute("SELECT COUNT(*) FROM pallet_leads WHERE status = 'Cerrado'").fetchone()[0],
        }
    return render_template("reports.html", leads=leads, counts=counts, current_filter=status_filter)


@app.post("/admin/leads/<int:lead_id>/status")
@admin_required
def update_lead_status(lead_id: int):
    new_status = request.form.get("status", "").strip()
    valid_statuses = {"Nuevo", "Contactado", "Cotizado", "Cerrado"}
    if new_status in valid_statuses:
        with get_db() as conn:
            conn.execute("UPDATE pallet_leads SET status = ? WHERE id = ?", (new_status, lead_id))
        flash(f"Estado del lead #{lead_id} actualizado a '{new_status}'.", "success")
    return redirect(url_for("admin_reports"))


@app.route("/admin/reports/export-csv")
@admin_required
def export_leads_csv():
    with get_db() as conn:
        leads = conn.execute("SELECT * FROM pallet_leads ORDER BY id DESC").fetchall()

    import csv
    import io
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Folio", "Fecha", "Nombre", "Empresa/Taller", "Telefono/WhatsApp", "Correo", "Ciudad/Estado", "Pallet de Interés", "Tarimas", "Origen", "Estado", "Comentarios"])
    for l in leads:
        cw.writerow([
            l["id"], l["created_at"], l["name"], l["company"], l["phone"], l["email"],
            l["city"], l["pallet_interest"], l["estimated_units"], l["source"], l["status"], l["message"]
        ])
    output = si.getvalue().encode("utf-8-sig")
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=reporte_captacion_pallets_{datetime.now().strftime('%Y%m%d')}.csv"}
    )


@app.post("/api/pallet-lead", endpoint="api_create_pallet_lead")
def api_create_pallet_lead():
    return _handle_api_pallet_lead()

@app.post("/api/leads", endpoint="api_pallet_lead")
def api_pallet_lead():
    return _handle_api_pallet_lead()

def _handle_api_pallet_lead():
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    name = str(data.get("name") or data.get("client_name") or "").strip()
    phone = str(data.get("phone") or data.get("telefono") or data.get("whatsapp") or "").strip()
    email = str(data.get("email") or data.get("correo") or "").strip().lower()
    company = str(data.get("company") or data.get("company_name") or data.get("empresa") or "").strip()
    city = str(data.get("city") or data.get("ciudad") or "").strip()
    pallet_interest = str(data.get("pallet_interest") or data.get("tarima_interest") or "Pallet General").strip()
    try:
        units = int(data.get("estimated_units") or data.get("quantity_pallets") or 1)
    except (ValueError, TypeError):
        units = 1
    message = str(data.get("message") or data.get("notes") or "").strip()
    source = str(data.get("source", "Asesor IA")).strip()

    if not name or not phone:
        return jsonify(ok=False, error="Por favor proporciona tu nombre y número de teléfono o WhatsApp."), 400

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO pallet_leads (name, phone, email, company, city, pallet_interest, estimated_units, message, status, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Nuevo', ?, ?)""",
            (name, phone, email, company, city, pallet_interest, units, message, source, datetime.now().isoformat(timespec="seconds")),
        )
        lead_id = cursor.lastrowid

    # Notificar por correo a ventas y admin
    send_lead_notification(lead_id, name, phone, email, company, city, pallet_interest, units, message)

    return jsonify(
        ok=True,
        lead_id=lead_id,
        message=f"¡Gracias {name}! Tu solicitud de cotización para '{pallet_interest}' ha sido turnada al área de Administración de ALFA LUBES. Un ejecutivo comercial se comunicará a la brevedad al {phone}."
    )


@app.route("/ai-agent")
def ai_agent():
    return render_template("ai_agent.html")


def _alfa_system_prompt() -> str:
    """Construye el prompt de sistema para un Asesor Técnico y Comercial experto de ALFA LUBES."""
    return (
        f"Eres el asesor técnico y comercial de {BRAND_NAME} ({SITE_URL}). "
        "Eres un profesional automotriz experto en lubricación de alto rendimiento: aceites de motor, viscosidades SAE, normas API/ILSAC/ACEA, "
        "transmisiones (automática, manual, CVT, DCT/DSG) y mantenimiento vehicular. Atiendes con igual excelencia a conductores particulares, "
        "mecánicos, refaccionarias y administradores de flotillas.\n\n"
        "PERSONALIDAD Y ESTILO:\n"
        "- Hablas como un asesor automotriz real, cercano, profesional y seguro. Cero respuestas acartonadas, menús robóticos ni listas rígidas innecesarias.\n"
        "- No uses guiones prefabricados; adáptate de forma natural a lo que el cliente te pregunta o expresa en cada momento, como en una plática cara a cara en un taller o mostrador.\n"
        "- Si el cliente saluda, responde breve y cálido en 1-2 líneas y pregunta en qué puedes asesorarle hoy (vehículo, viscosidad o compra).\n"
        "- Responde directo a lo que preguntan, con explicaciones claras, amigables y de alto valor técnico. Usa negritas solo para resaltar puntos clave (viscosidad, precio, norma).\n"
        "- Sé conciso pero completo: párrafos claros y directos. No inventes datos que desconozcas.\n\n"
        "REGLA ESTRICTA SOBRE MARCAS IMPORTADAS (OBLIGATORIA):\n"
        "- Si el cliente pregunta qué marcas importadas manejas o qué marcas vienen en las tarimas/pallets de importación, DEBES responder con total naturalidad que ALFA LUBES maneja y distribuye DISTINTAS MARCAS DE IMPORTACIÓN DIRECTA Y ALTA GAMA en tarimas cerradas de fábrica.\n"
        "- INMEDIATAMENTE canaliza al cliente con el equipo de ventas vía WhatsApp o correo para consultar los lotes disponibles del momento, especificaciones y cotizaciones por volumen.\n"
        "- PROHIBICIÓN ABSOLUTA: BAJO NINGUNA CIRCUNSTANCIA MENCIONES NINGUNA MARCA EN ESPECÍFICO NI DE TERCEROS NI DE LA COMPETENCIA (queda estrictamente prohibido nombrar marcas como Mobil, Castrol, Shell, Valvoline, Motul, Pennzoil, Quaker State, Bardahl, etc.). Responde siempre refiriéndote a 'distintas marcas de importación directa y alta gama' y canaliza con ventas.\n\n"
        "HISTORIA DE CREACIÓN DE ALFA LUBES (CÓMO RESALTA ENTRE LOS GRANDES):\n"
        "- Origen y Visión: ALFA LUBES nació de la pasión, exigencia y visión técnica de ingenieros y especialistas automotrices en lubricación, al detectar un problema recurrente en el mercado: gran parte de las marcas comerciales tradicionales comenzaron a abaratar costos usando bases lubricantes de menor refinamiento y paquetes de aditivos recortados. Ante las severas temperaturas de México, el tráfico pesado y los motores turbo modernos, esos aceites se degradaban rápidamente, perdían viscosidad y generaban lodos y desgaste prematuro.\n"
        "- Formulación de Élite: Frente a esa necesidad se creó ALFA LUBES, una marca formulada con la convicción de no escatimar en pureza ni tecnología: se concibió desde cero con bases 100% sintéticas de alta pureza molecular y paquetes de aditivos de ultra-vanguardia (normas API SP, ILSAC GF-6A y fluidos sintéticos para transmisiones DCT/DSG).\n"
        "- Por qué resalta entre los grandes: Gracias a su pureza molecular superior, resistencia térmica extrema (cero evaporación prematura) y una película lubricante que no se rompe bajo cizallamiento severo, ALFA LUBES ha resaltado y compite de tú a tú contra las marcas gigantes transnacionales. Es la elección preferida de mecánicos de alto rendimiento y flotillas porque mantiene la compresión del motor intacta, previene ruidos y desgaste de cadena, y asegura un desempeño impecable desde el primer arranque en frío hasta el último kilómetro.\n\n"
        "COMPOSICIÓN TÉCNICA EN SUS DISTINTAS PRESENTACIONES (TIENES RESPUESTA PARA TODO):\n"
        "1. ALFA LUBES DCT / DSG Full Synthetic:\n"
        "   - Composición: Base 100% sintética hidrofraccionada de baja viscosidad cinemática, modificadores de fricción micrométricos no metálicos, aditivos de extrema presión (EP) y protectores de aleaciones de cobre y bronce para la mecatrónica.\n"
        "   - Aplicación: Específico para transmisiones de doble embrague húmedo (DSG / DCT / S-Tronic / Powershift) de marcas como Volkswagen, Audi, Seat, Ford, BMW, Hyundai/Kia, Mercedes-Benz. Garantiza cambios instantáneos sin jaloneos, evita sobrecalentamientos y protege la unidad mecatrónica electrohidráulica.\n"
        "2. ALFA LUBES 0W-20 Full Synthetic (API SP / ILSAC GF-6A):\n"
        "   - Composición: Bases sintéticas puras Grupo III+ con índice de viscosidad ultra alto (VI > 175) y paquete detergente balanceado bajo en calcio y enriquecido con sales de magnesio para mitigar al 100% la preignición a baja velocidad (LSPI). Nanopartículas antifricción y polímeros hidrogenados ultraestables al corte.\n"
        "   - Aplicación: Motores modernos turboalimentados de inyección directa (TGDI), vehículos híbridos (HEV/PHEV) y motores recientes que demandan fluidez instantánea en arranque en frío (-40°C), máxima protección a la cadena de sincronización y ahorro de combustible.\n"
        "3. ALFA LUBES 5W-30 Full Synthetic (API SP / ILSAC GF-6A):\n"
        "   - Composición: Bases 100% sintéticas premium con paquete anti-desgaste ZDDP de última generación, ésteres de fricción, antioxidantes fenólicos y amínicos de alta durabilidad y bajísima volatilidad Noack (< 9%).\n"
        "   - Aplicación: La viscosidad más versátil del parque vehicular. Óptima para sedanes, SUVs, crossovers y pick-ups tanto turbo como atmosféricos. Soporta tráfico urbano severo y calor de carretera sin perder espesor de película.\n"
        "4. ALFA LUBES 5W-20 Full Synthetic (API SP / ILSAC GF-6A):\n"
        "   - Composición: Formulación sintética de baja resistencia al arrastre hidrodinámico con aditivación antidesgaste para tolerancias mecánicas milimétricas.\n"
        "   - Aplicación: Diseñado para motores con tolerancias estrechas (Ford, Honda, Toyota, Chrysler). Disminuye el esfuerzo del cigüeñal y árbol de levas, reduciendo temperaturas y consumo.\n"
        "5. ALFA LUBES 5W-40 Synthetic Protection:\n"
        "   - Composición: Elevado HTHS (High Temperature High Shear > 3.5 mPa.s), aditivos detergentes-dispersantes pesados y alta reserva alcalina (TBN) para neutralizar ácidos.\n"
        "   - Aplicación: Ideal para vehículos europeos (VAG, BMW, Mercedes), motores turboalimentados de alto rendimiento, vehículos de carga ligera o trabajo severo continuo en carretera.\n"
        "6. ALFA LUBES 15W-40 Multigrado / Alto Kilometraje (+100,000 km):\n"
        "   - Composición: Bases lubricantes de alta viscosidad combinadas con agentes acondicionadores de sellos y retenes elastoméricos (vitón y caucho) que devuelven elasticidad y detienen rezumes; aditivos anti-humo y detergencia pesada que disuelve barnices acumulados.\n"
        "   - Aplicación: Motores con más de 100,000 km, camionetas de trabajo o flotillas donde existan fugas leves o consumo prematuro de aceite, restaurando la compresión de cilindros.\n"
        "7. Tarimas y Pallets de Mayoreo (Directo de fábrica):\n"
        "   - Presentación: Tarimas completas cerradas de fábrica en cajas de 946 ml, garrafas o tambores industriales.\n"
        "   - Beneficio: Descuentos de mayoreo de hasta 30-40% directo para talleres mecánicos, flotillas y refaccionarias. Envío asegurado a todo México y facturación fiscal.\n\n"
        "REGLA ESTRICTA DE PRECIOS (OBLIGATORIA - NUNCA IGNORAR):\n"
        "- JAMAS menciones precios, costos, valores economicos, listas de precios ni tarifas de NINGUN producto o pallet. Esta regla es absoluta.\n"
        "- Si el cliente pregunta por precio, costo, cuanto cuesta, valor, tarifa o cualquier dato economico, responde de forma natural y calida que para precios actualizados debe contactar al equipo de ventas.\n"
        "- Ejemplo de redireccion natural: Para darte una cotizacion personalizada con precio real y disponibilidad actual, te paso con nuestro equipo de ventas por WhatsApp o correo, ellos te atienden al instante.\n"
        "- NO uses respuestas frias o roboticas; redirige de forma natural como lo haria un asesor profesional.\n\n"
        "HERRAMIENTAS Y CONSULTA EN TIEMPO REAL:\n"
        "- Tienes acceso a herramientas para consultar el catalogo de productos y pallets en tiempo real (stock, descripciones, viscosidades). USALAS cuando el cliente pregunte por productos, disponibilidad o viscosidades. NUNCA cites precios al cliente.\n"
        "- Si una herramienta no devuelve resultados, dilo con naturalidad y ofrece alternativas (consultar catalogo web, WhatsApp, correo).\n\n"
        "GUÍA DE COMPRA Y CIERRE DE VENTA (MERCADO PAGO Y ASESOR):\n"
        "- Cuando el cliente muestre interés en comprar o pregunte cómo realizar su pedido, guíalo con entusiasmo al cierre de venta:\n"
        f"  * Bríndale el enlace para finalizar su compra en línea de forma segura: [Ir al Carrito]({SITE_URL}/cart) o [Finalizar Compra]({SITE_URL}/checkout).\n"
        "  * Explícale que su compra es 100% segura y está protegida mediante MERCADO PAGO, contando con opciones muy accesibles:\n"
        "    - Tarjetas de crédito y débito (Visa, Mastercard, American Express).\n"
        "    - Meses sin intereses (según promociones bancarias aplicables).\n"
        "    - Transferencia bancaria SPEI con acreditación inmediata.\n"
        "    - Pago en efectivo en tiendas OXXO y sucursales en todo el país.\n"
        "  * Si el cliente requiere cotización de mayoreo/pallets, asesoría para su flotilla o taller, o prefiere atención personalizada humana, refiérelo de inmediato con nuestro asesor de ventas:\n"
        f"    - WhatsApp directo: {WHATSAPP_NUMBER} ({WHATSAPP_URL})\n"
        f"    - Correo de ventas: {SALES_EMAIL}\n"
        f"- Web oficial: {SITE_URL}\n\n"
        "Siempre verifica que la recomendación coincida con el manual del fabricante del vehículo cuando el cliente exprese dudas específicas."
    )


def _get_products_catalog() -> list[dict]:
    """Obtiene el catálogo actual de productos desde la BD con stock y precios reales."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, name, brand, viscosity, stock, image, description "
                "FROM products WHERE stock > 0 ORDER BY brand, viscosity"
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _get_pallets_catalog() -> list[dict]:
    """Obtiene los pallets/tarimas disponibles desde la BD."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, title, brand, oil_type, viscosity, units_per_pallet, "
                "image, description, origin "
                "FROM pallets WHERE active = 1 ORDER BY brand, title"
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _get_product_by_viscosity(viscosity: str) -> list[dict]:
    """Busca productos por viscosidad específica."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, name, brand, viscosity, stock, image, description "
                "FROM products WHERE viscosity LIKE ? AND stock > 0 ORDER BY viscosity",
                (f"%{viscosity}%",)
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _search_products(query: str) -> list[dict]:
    """Busca productos por nombre, marca o descripción."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, name, brand, viscosity, stock, image, description "
                "FROM products WHERE (name LIKE ? OR brand LIKE ? OR description LIKE ?) AND stock > 0 "
                "ORDER BY brand, viscosity",
                (f"%{query}%", f"%{query}%", f"%{query}%")
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


# Definición de herramientas (function calling) para la IA
AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_products_catalog",
            "description": "Obtiene el catalogo completo de productos ALFA LUBES disponibles con stock y descripciones en tiempo real.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pallets_catalog",
            "description": "Obtiene las tarimas/pallets de mayoreo disponibles para talleres y refaccionarias con stock y descripciones.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_by_viscosity",
            "description": "Busca productos por viscosidad SAE específica (ej: 5W-30, 0W-20, 10W-40).",
            "parameters": {
                "type": "object",
                "properties": {"viscosity": {"type": "string", "description": "Viscosidad SAE a buscar (ej: 5W-30)"}},
                "required": ["viscosity"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Busca productos por nombre, marca o palabra clave en la descripción.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Término de búsqueda (ej: sintético, transmisión, alto kilometraje)"}},
                "required": ["query"]
            }
        }
    }
]


def _execute_tool_call(name: str, arguments: dict) -> str:
    """Ejecuta una llamada a herramienta y devuelve el resultado como JSON string."""
    try:
        if name == "get_products_catalog":
            result = _get_products_catalog()
        elif name == "get_pallets_catalog":
            result = _get_pallets_catalog()
        elif name == "get_product_by_viscosity":
            result = _get_product_by_viscosity(arguments.get("viscosity", ""))
        elif name == "search_products":
            result = _search_products(arguments.get("query", ""))
        else:
            result = {"error": f"Herramienta desconocida: {name}"}
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _call_ai_service(history: list[dict]) -> str | None:
    """Llama a la API de IA con function calling para consultar catálogo real en tiempo real."""
    if not AI_API_KEY:
        return None
    url = f"{AI_BASE_URL}/chat/completions"
    
    # Primera llamada: el modelo decide si usar herramientas
    payload = json.dumps({
        "model": AI_MODEL,
        "messages": [{"role": "system", "content": _alfa_system_prompt()}] + history,
        "tools": AI_TOOLS,
        "tool_choice": "auto",
        "reasoning_effort": "low",
        "temperature": 0.4,
        "max_tokens": 1200,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AI_API_KEY}",
    }
    req = urlrequest.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        if not choices:
            return None
        msg = choices[0].get("message") or {}
        
        # Si el modelo quiere usar herramientas, ejecutarlas y hacer segunda llamada
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            # Ejecutar cada herramienta
            tool_messages = []
            for tc in tool_calls:
                fn_name = tc.get("function", {}).get("name")
                fn_args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                result = _execute_tool_call(fn_name, fn_args)
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "name": fn_name,
                    "content": result
                })
            
            # Segunda llamada con resultados de herramientas
            second_payload = json.dumps({
                "model": AI_MODEL,
                "messages": [{"role": "system", "content": _alfa_system_prompt()}] + history + [msg] + tool_messages,
                "reasoning_effort": "low",
                "temperature": 0.4,
                "max_tokens": 1200,
            }).encode("utf-8")
            second_req = urlrequest.Request(url, data=second_payload, headers=headers, method="POST")
            with urlrequest.urlopen(second_req, timeout=45) as resp2:
                body2 = json.loads(resp2.read().decode("utf-8"))
            choices2 = body2.get("choices") or []
            if choices2:
                msg2 = choices2[0].get("message") or {}
                content2 = msg2.get("content")
                if isinstance(content2, str) and content2.strip():
                    return content2.strip()
        
        # Respuesta directa sin herramientas
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        reasoning = msg.get("reasoning")
        if isinstance(reasoning, str) and len(reasoning.strip()) > 20:
            return reasoning.strip()
        if isinstance(body.get("response"), str) and body["response"].strip():
            return body["response"].strip()
        if isinstance(body.get("content"), str) and body["content"].strip():
            return body["content"].strip()
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError, OSError):
        return None
    return None


def _autonomous_fallback_reply(message: str) -> str:
    """Respaldo natural basado en catálogo real cuando la IA configurada no responde."""
    text = (message or "").strip()
    lower = text.lower()

    # Intentar orientar con datos reales del catálogo
    suggestions = []
    try:
        if any(k in lower for k in ("pallet", "tarima", "mayoreo", "flotilla", "distribuidor")):
            pallets = _get_pallets_catalog()
            if pallets:
                top = pallets[:2]
                names = ", ".join(p.get("name", "tarima") for p in top)
                suggestions.append(f"Para mayoreo puedo orientarte con opciones como {names}.")
        # Búsqueda simple por términos del mensaje
        terms = [t for t in lower.replace(",", " ").split() if len(t) >= 3][:4]
        if terms:
            products = _search_products(" ".join(terms))
            if not products:
                products = _get_products_catalog()
            if products:
                picks = products[:3]
                parts = []
                for p in picks:
                    name = p.get("name", "producto")
                    visc = p.get("viscosity")
                    label = name + (f" ({visc})" if visc else "")
                    parts.append(label)
                suggestions.append("Del catálogo actual te puedo recomendar: " + "; ".join(parts) + ".")
    except Exception:
        suggestions = []

    if suggestions:
        return (
            "Con gusto te ayudo. " + " ".join(suggestions) + " "
            "Si me compartes tu vehículo, año y kilometraje te digo cuál es la opción más adecuada para cuidarlo. "
            f"Para cerrar tu pedido o cotización rápida también puedes escribirme por WhatsApp: [{WHATSAPP_NUMBER}]({WHATSAPP_URL})."
        )

    return (
        "Con gusto te ayudo a elegir el aceite ideal. "
        "Cuéntame qué vehículo tienes (marca, modelo, año y kilometraje) y con qué uso lo manejas, y te recomiendo la mejor opción del catálogo de Alfa Lubes. "
        f"Si prefieres, también puedo atenderte por WhatsApp para cotizar y cerrar tu pedido: [{WHATSAPP_NUMBER}]({WHATSAPP_URL})."
    )


def _should_suggest_products(text: str) -> bool:
    t = (text or "").lower()
    triggers = [
        "comprar", "catálogo", "catalogo", "producto", "productos", "precio", "precios",
        "carrito", "pedido", "envío", "envio", "recomiend", "suger", "ver más", "ver mas",
        "disponib", "stock", "viscosidad", "aceite para", "cuál me conviene", "cual me conviene",
        "alfa lubes", "alfalubes", "pallet", "tarima", "sintetico", "sintético",
    ]
    return any(k in t for k in triggers)


@app.post("/api/ai-chat")
def ai_chat():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()
    if not message:
        return jsonify(error="Escribe un mensaje."), 400
    if len(message) > 2000:
        return jsonify(error="Mensaje demasiado largo."), 400

    # Historial enviado por el cliente (máx 20 turnos para controlar tokens)
    raw_history = data.get("history") or []
    history: list[dict] = []
    if isinstance(raw_history, list):
        for item in raw_history[-20:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = str(item.get("content", "")).strip()
            if role in ("user", "assistant") and content:
                history.append({"role": role, "content": content[:2000]})

    if not history or history[-1].get("content") != message:
        history.append({"role": "user", "content": message})

    reply = _call_ai_service(history)
    source = "alfa_ai"
    if not reply:
        source = "alfa_ai"
        reply = _autonomous_fallback_reply(message)

    suggest_pallet = any(k in (message + " " + reply).lower() for k in ["pallet", "pallets", "tarima", "tarimas", "mayoreo", "flotilla", "cajas de aceite", "cotizar pallet", "precio por tarima", "distribuidor"])
    return jsonify(
        reply=reply,
        suggest_product=_should_suggest_products(message + " " + reply),
        suggest_pallet_lead=suggest_pallet,
        source=source
    )


@app.post("/api/ai-recommend")
def ai_recommend():
    data = request.get_json(silent=True) or {}
    vehicle = str(data.get("vehicle", "sedan")).lower()
    climate = str(data.get("climate", "temperate")).lower()
    try:
        mileage = int(data.get("mileage", 0))
        if mileage < 0 or mileage > 2_000_000:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(error="Indica un kilometraje válido."), 400

    if mileage >= 160_000:
        recommendation = "Compara aceites para alto kilometraje con la viscosidad indicada por el fabricante."
        reason = "El kilometraje elevado puede influir en el consumo y desgaste; confirma la especificación del motor antes de elegir."
    elif vehicle in {"sports", "performance", "truck"}:
        recommendation = "Revisa un aceite sintético que cumpla la especificación del fabricante y el uso del vehículo."
        reason = "La carga o el desempeño pueden afectar la selección; la viscosidad debe coincidir con el manual del vehículo."
    else:
        recommendation = "Elige un aceite que cumpla la viscosidad y especificación indicadas en el manual."
        reason = "La recomendación depende de la especificación OEM del motor, no solo del tipo de vehículo o el clima."
    if climate == "cold":
        reason += " En frío, verifica especialmente el grado de viscosidad de arranque indicado en el manual."
    elif climate == "hot":
        reason += " En calor, conserva la viscosidad aprobada por el fabricante; no la cambies sin validar el manual."
    return jsonify(
        recommendation=recommendation,
        reason=reason,
        confidence="Orientativa",
        additional="Este asesor aplica reglas generales y no consulta catálogos OEM ni sustituye el manual del vehículo. Si compartes marca, modelo, año y motor, el equipo puede ayudarte a validar compatibilidad.",
    )


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static", "images"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@app.route("/robots.txt")
def robots_txt():
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /admin/\n"
        "Disallow: /dashboard\n"
        "Disallow: /api/\n\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    return Response(content, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    now_str = datetime.now().strftime("%Y-%m-%d")
    urls = [
        {"loc": f"{SITE_URL}/", "priority": "1.0", "changefreq": "daily"},
        {"loc": f"{SITE_URL}/products", "priority": "0.9", "changefreq": "daily"},
        {"loc": f"{SITE_URL}/ai-agent", "priority": "0.8", "changefreq": "weekly"},
        {"loc": f"{SITE_URL}/cart", "priority": "0.5", "changefreq": "monthly"},
        {"loc": f"{SITE_URL}/checkout", "priority": "0.5", "changefreq": "monthly"},
    ]
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for u in urls:
        xml_lines.append(
            f"  <url>\n"
            f"    <loc>{u['loc']}</loc>\n"
            f"    <lastmod>{now_str}</lastmod>\n"
            f"    <changefreq>{u['changefreq']}</changefreq>\n"
            f"    <priority>{u['priority']}</priority>\n"
            f"  </url>"
        )
    xml_lines.append("</urlset>")
    return Response("\n".join(xml_lines), mimetype="application/xml")


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


# Inicializa esquema y datos base en la base configurada (DB_PATH).
init_db()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
