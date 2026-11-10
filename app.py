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

from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, session, url_for


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

# Configuración IA (meai / proveedor OpenAI-compatible)
MEAI_API_KEY = os.environ.get("MEAI_API_KEY", "").strip()
MEAI_BASE_URL = os.environ.get("MEAI_BASE_URL", "https://api.meai.cloud/v1").strip().rstrip("/")
MEAI_MODEL = os.environ.get("MEAI_MODEL", "claude-haiku-4.5").strip()

# Identidad de Marca y Correos Propios alfalubes.com
BRAND_NAME = os.environ.get("BRAND_NAME", "ALFA LUBES")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "contacto@alfalubes.com").strip()
SALES_EMAIL = os.environ.get("SALES_EMAIL", "ventas@alfalubes.com").strip()
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "soporte@alfalubes.com").strip()
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@alfalubes.com").strip()
SITE_URL = os.environ.get("SITE_URL", "https://alfalubes.com").strip().rstrip("/")

# Redes Sociales Oficiales ALFA LUBES y Canales
SOCIAL_FACEBOOK = os.environ.get("SOCIAL_FACEBOOK", "https://www.facebook.com/alfalubes").strip()
SOCIAL_INSTAGRAM = os.environ.get("SOCIAL_INSTAGRAM", "https://www.instagram.com/alfalubes").strip()
SOCIAL_TIKTOK = os.environ.get("SOCIAL_TIKTOK", "https://www.tiktok.com/@alfalubes").strip()
SOCIAL_YOUTUBE = os.environ.get("SOCIAL_YOUTUBE", "https://www.youtube.com/@alfalubes").strip()
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "+525500000000").strip()
WHATSAPP_URL = os.environ.get("WHATSAPP_URL", "https://wa.me/525500000000?text=Hola%20ALFA%20LUBES,%20deseo%20asesor%C3%ADa%20sobre%20aceites%20y%20lubricantes").strip()

# Google Analytics 4 (GA4) y Search Console
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "G-XXXXXXXXXX").strip()
GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip()

# Base de Datos en la Nube Supabase (PostgreSQL para Vercel y Producción)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://eihvypcvmjbcfumllxrv.supabase.co").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()

# Configuración SMTP institucional alfalubes.com
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.environ.get("SMTP_FROM", SALES_EMAIL).strip()
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1").strip() in ("1", "true", "True")


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
            """
        )
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            products = [
                ("Castrol EDGE 5W-30", "Castrol", "5W-30", 299.00, 150, "aceite-1.jpg", "Aceite sintético para protección y desempeño en motores modernos."),
                ("Mobil 1 Advanced 5W-30", "Mobil 1", "5W-30", 319.00, 200, "aceite-2.jpg", "Aceite sintético de alto desempeño para uso diario."),
                ("Shell Helix Ultra 5W-40", "Shell", "5W-40", 359.00, 120, "aceite-3.jpg", "Protección sintética para limpieza y desempeño del motor."),
                ("Valvoline Advanced 5W-20", "Valvoline", "5W-20", 279.00, 180, "aceite-4.jpg", "Aceite sintético para protección contra el desgaste."),
                ("Castrol GTX 10W-40", "Castrol", "10W-40", 189.00, 250, "aceite-5.jpg", "Aceite para protección confiable en el uso cotidiano."),
                ("Mobil 1 Extended Performance 0W-20", "Mobil 1", "0W-20", 389.00, 100, "aceite-1.jpg", "Aceite sintético de alto desempeño para motores compatibles."),
            ]
            conn.executemany(
                "INSERT INTO products (name, brand, viscosity, price, stock, image, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
                products,
            )
        if conn.execute("SELECT COUNT(*) FROM pallets").fetchone()[0] == 0:
            pallets = [
                ("Pallet ALFA LUBES DCT/DSG Full Synthetic", "ALFA LUBES", "Transmisión Doble Embrague (DCT/DSG)", "DCT/DSG Fluid",
                 60, 38400.00, 160.00, "pallet-tarima-cajas.jpg",
                 "Tarima completa de fluido sintético de transmisión DCT/DSG importado. Fórmula de tecnología alemana para transmisiones DSG, S-Tronic y PowerShift.",
                 "Importación Directa USA/Alemania", 1, datetime.now().isoformat(timespec="seconds")),
                ("Pallet Castrol EDGE Advanced 5W-30 Full Synthetic", "Castrol", "Motor Sintético Alto Desempeño", "5W-30",
                 48, 43200.00, 225.00, "pallet-almacen.jpg",
                 "Tarima sellada de fábrica con cajas de aceite sintético con tecnología Fluid Titanium. Máxima resistencia a la presión de motor.",
                 "Importación Directa USA", 1, datetime.now().isoformat(timespec="seconds")),
                ("Pallet Mobil 1 Extended Performance 0W-20", "Mobil 1", "Motor Sintético Avanzado", "0W-20",
                 48, 52800.00, 275.00, "pallet-tarima-cajas.jpg",
                 "Tarima mayorista de Mobil 1 0W-20 para vehículos modernos, híbridos y con arranque Start-Stop. Protección garantizada hasta 20,000 km.",
                 "Importación Directa USA", 1, datetime.now().isoformat(timespec="seconds")),
                ("Pallet Tambores 208L Castrol GTX 10W-40 / Alto Kilometraje", "Castrol", "Tambores Industriales (55 Gal)", "10W-40",
                 4, 58000.00, 69.70, "pallet-almacen.jpg",
                 "Tarima de 4 tambores de 208 litros (832 litros totales) ideal para centros de lubricación rápida, refaccionarias y flotillas de transporte.",
                 "Importación Grado Industrial", 1, datetime.now().isoformat(timespec="seconds")),
            ]
            conn.executemany(
                "INSERT INTO pallets (title, brand, oil_type, viscosity, units_per_pallet, pallet_price, unit_price_approx, image, description, origin, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                pallets,
            )
        if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO admins (email, password_hash, name, role, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (ADMIN_EMAIL,
                 hashlib.sha256("Calurore1028@".encode("utf-8")).hexdigest(),
                 "Administrador ALFA LUBES", "super", 1, datetime.now().isoformat(timespec="seconds")),
            )
        # Asegurar que el correo institucional admin@alfalubes.com exista
        corp_exists = conn.execute("SELECT id FROM admins WHERE lower(email) = ?", (ADMIN_EMAIL.lower(),)).fetchone()
        if not corp_exists:
            conn.execute(
                "INSERT INTO admins (email, password_hash, name, role, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (ADMIN_EMAIL,
                 hashlib.sha256("Calurore1028@".encode("utf-8")).hexdigest(),
                 "Administrador ALFA LUBES", "super", 1, datetime.now().isoformat(timespec="seconds")),
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
        with get_db() as conn:
            admin = conn.execute("SELECT role FROM admins WHERE id = ?", (session["admin_id"],)).fetchone()
            if not admin or admin["role"] not in ("admin", "super"):
                abort(403)
        return f(*args, **kwargs)
    return decorated_function


def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("admin_login", next=request.url))
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
        }
    return render_template("admin_panel.html", stats=stats)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if "admin_id" in session:
        return redirect(url_for("admin_panel"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        next_url = request.form.get("next") or request.args.get("next") or url_for("admin_panel")
        if not email or not password:
            flash("Ingresa correo y contraseña.", "error")
            return redirect(url_for("admin_login", next=next_url))
        with get_db() as conn:
            admin = conn.execute(
                "SELECT id, email, password_hash, name, role, active FROM admins WHERE lower(email)=?",
                (email,),
            ).fetchone()
        if not admin or not admin["active"] or not verify_password(password, admin["password_hash"]):
            flash("Credenciales inválidas o cuenta inactiva.", "error")
            return redirect(url_for("admin_login", next=next_url))
        session.clear()
        session["admin_id"] = admin["id"]
        session["admin_name"] = admin["name"]
        session["admin_role"] = admin["role"]
        return redirect(next_url)
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_name", None)
    session.pop("admin_role", None)
    flash("Sesión cerrada.", "success")
    return redirect(url_for("home"))



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
    if PREVIEW_MODE:
        flash("La vista de Vercel es una demostración visual; los pedidos se reciben en la instalación local.", "error")
        return redirect(url_for("cart"))
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
def dashboard():
    if PREVIEW_MODE:
        abort(404)
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
    if PREVIEW_MODE:
        abort(404)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY id DESC").fetchall()
    return render_template("clients.html", clients=rows)


@admin_required
@app.route("/suppliers")
def suppliers():
    if PREVIEW_MODE:
        abort(404)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM suppliers ORDER BY id DESC").fetchall()
    return render_template("suppliers.html", suppliers=rows)


@app.post("/add_supplier")
def add_supplier():
    if PREVIEW_MODE:
        abort(404)
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


@app.route("/ai-agent")
def ai_agent():
    return render_template("ai_agent.html")


def _alfa_system_prompt() -> str:
    """Construye el prompt de sistema con contexto exhaustivo de catálogo y marca ALFA LUBES."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT name, brand, viscosity, price, stock, description FROM products WHERE stock > 0 ORDER BY brand, name LIMIT 60"
            ).fetchall()
    except Exception:
        rows = []
    catalog = "\n".join(
        f"- {r['brand']} {r['name']} ({r['viscosity']}) · ${r['price']:.2f} MXN · Stock: {r['stock']} · {r['description']}"
        for r in rows
    ) or "(Catálogo no disponible en este momento)"
    return (
        f"Eres el ASESOR TÉCNICO Y COMERCIAL DE INTELIGENCIA ARTIFICIAL DE {BRAND_NAME} ({SITE_URL}). "
        "Eres un especialista automotriz experto en aceites de motor, lubricantes, viscosidades SAE, normativas API/ILSAC/ACEA y mantenimiento vehicular. "
        "Atiendes a clientes particulares, talleres mecánicos y flotillas de manera autónoma, profesional, cálida y orientada a cerrar ventas de forma honesta.\n\n"
        "IDENTIDAD INSTITUCIONAL Y CANALES OFICIALES:\n"
        f"- Sitio Web: {SITE_URL}\n"
        f"- Correo de Atención: {CONTACT_EMAIL}\n"
        f"- Correo de Ventas y Pedidos: {SALES_EMAIL}\n"
        f"- Correo de Soporte: {SUPPORT_EMAIL}\n"
        f"- WhatsApp Oficial: {WHATSAPP_URL} (Atención directa y pedidos al {WHATSAPP_NUMBER})\n"
        f"- Redes Sociales Oficiales: Facebook ({SOCIAL_FACEBOOK}), Instagram ({SOCIAL_INSTAGRAM}), TikTok ({SOCIAL_TIKTOK}) y YouTube ({SOCIAL_YOUTUBE}). En TikTok e Instagram compartimos tips rápidos y fichas técnicas; en YouTube tutoriales de cambio de aceite y análisis de lubricación.\n\n"
        "CONOCIMIENTO TÉCNICO FUNDAMENTAL:\n"
        "1. VISCOSIDAD SAE: El número antes de la 'W' (ej. 0W, 5W, 10W) es la fluidez en frío para proteger el motor en el arranque. El segundo número (20, 30, 40, 50) es la protección a temperatura de operación (100°C).\n"
        "2. SINTÉTICO VS MINERAL: Sintético = máxima durabilidad (10,000-15,000 km), resistencia a altas temperaturas, economía de combustible. Mineral = cambios frecuentes (5,000 km) para motores tradicionales.\n"
        "3. KILOMETRAJE: En motores con menos de 100,000 km, mantener estrictamente la recomendación del manual (0W-20, 5W-30 sintético). En motores con más de 100,000-150,000 km con consumo de aceite, evaluar formulaciones para Alto Kilometraje (ej. 10W-40) con acondicionadores de sellos.\n"
        "4. VENTA POR PALLETS Y ACEITES IMPORTADOS: Ofrecemos venta por tarimas/pallets completos de los mejores aceites importados (ALFA LUBES DCT/DSG fluido sintético de transmisión, Castrol EDGE 5W-30, Mobil 1 0W-20 y tambores de 208L). Es ideal para talleres mecánicos, refaccionarias y flotillas con precios de importación directa por volumen. El cliente puede cotizar por WhatsApp o en /pallets.\n"
        "5. DATOS NECESARIOS: Si el cliente pregunta qué aceite usar, pregúntale: Marca, Modelo, Año, Kilometraje y si presenta consumo de aceite.\n"
        "6. COMPRA Y ENVÍOS: Los pedidos se realizan directamente agregando productos al carrito en /products y registrando sus datos en /checkout. Se ofrecen envíos rápidos a todo México y atención personalizada.\n\n"
        "CATÁLOGO DE PRODUCTOS EN STOCK:\n"
        f"{catalog}\n\n"
        "PAUTAS DE RESPUESTA:\n"
        "- Responde siempre en español, con excelente formato (viñetas, negritas) y redacción técnica accesible.\n"
        "- Si preguntan por pallets o mayoreo de aceites importados, explica las tarimas disponibles (DCT/DSG, 5W-30, 0W-20, tambores) y sugiere cotizar en /pallets o vía WhatsApp.\n"
        "- Menciona precios y productos exactos del catálogo que se ajusten a la consulta.\n"
        "- Cuando pregunten por redes sociales o correos, proporciona los enlaces y correos oficiales de la marca alfalubes.com.\n"
        "- Sé claro, directo y no inventes compatibilidades OEM sin recordar al usuario verificar el manual de su vehículo."
    )


def _call_meai(history: list[dict]) -> str | None:
    """Llama a la API de meai (formato OpenAI-compatible). Devuelve el texto o None si falla."""
    if not MEAI_API_KEY:
        return None
    url = f"{MEAI_BASE_URL}/chat/completions"
    payload = json.dumps({
        "model": MEAI_MODEL,
        "messages": [{"role": "system", "content": _alfa_system_prompt()}] + history,
        "temperature": 0.4,
        "max_tokens": 900,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MEAI_API_KEY}",
    }
    req = urlrequest.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=25) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        if isinstance(body.get("response"), str):
            return body["response"].strip()
        if isinstance(body.get("content"), str):
            return body["content"].strip()
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError, OSError):
        return None
    return None


def _autonomous_fallback_reply(message: str) -> str:
    """Motor de respuesta autónomo de respaldo para ALFA LUBES."""
    low = (message or "").lower().strip()

    # 1. WhatsApp y atención directa
    if any(k in low for k in ["whatsapp", "whats", "wathsapp", "watsapp", "celular", "mensaje directo"]):
        return (
            f"📱 Puedes comunicarte directamente con nuestro equipo por **WhatsApp**:\n\n"
            f"👉 [Iniciar chat en WhatsApp]({WHATSAPP_URL}) (Número: **{WHATSAPP_NUMBER}**)\n\n"
            "Con gusto te asesoramos de inmediato con recomendaciones de aceites, cotizaciones para talleres o estado de tu pedido."
        )

    # 2. Venta por Pallets y Aceites Importados
    if any(k in low for k in ["pallet", "pallets", "tarima", "tarimas", "importado", "importados", "mayoreo", "flotilla", "cajas", "tambor", "tambores"]):
        pallets_data = get_all_pallets()
        p_lines = [f"- **{p.get('title')}** ({p.get('viscosity')} · {p.get('units_per_pallet')} unidades): **${float(p.get('pallet_price', 0)):,.2f} MXN**" for p in pallets_data]
        return (
            f"🏆 **¡LOS MEJORES ACEITES IMPORTADOS EN VENTA POR PALLETS!**\n\n"
            "En **ALFA LUBES** somos importadores directos y distribuimos tarimas completas con precios mayoristas para talleres mecánicos, refaccionarias y flotillas:\n\n"
            + "\n".join(p_lines) + "\n\n"
            f"📦 Todas las tarimas vienen selladas con film de alta resistencia y documentación de importación.\n\n"
            f"👉 Puedes consultar fotos y detalles en [/pallets](/pallets) o solicitar una cotización personalizada por [WhatsApp aquí]({WHATSAPP_URL}) o al correo **{SALES_EMAIL}**."
        )

    # 2. Redes sociales
    if any(k in low for k in ["redes", "red social", "facebook", "instagram", "tiktok", "youtube", "social", "seguirlos", "videos"]):
        return (
            f"¡En **{BRAND_NAME}** nos encanta estar cerca de ti! Puedes seguirnos y ver tips de lubricación en nuestras redes oficiales:\n\n"
            f"- 📱 **WhatsApp**: [{WHATSAPP_NUMBER}]({WHATSAPP_URL}) — Asesoría rápida y pedidos.\n"
            f"- 📘 **Facebook**: [{SOCIAL_FACEBOOK}]({SOCIAL_FACEBOOK}) — Novedades, promociones y comunidad.\n"
            f"- 📸 **Instagram**: [@alfalubes]({SOCIAL_INSTAGRAM}) — Fichas técnicas, especificaciones y fotos de producto.\n"
            f"- 🎵 **TikTok**: [@alfalubes]({SOCIAL_TIKTOK}) — Consejos rápidos de lubricación y mitos del motor.\n"
            f"- ▶️ **YouTube**: [@alfalubes]({SOCIAL_YOUTUBE}) — Guías técnicas y comparativas de aceites.\n\n"
            "¿Deseas conocer más sobre algún producto o viscosidad en específico?"
        )

    # 3. Correos y contacto institucional
    if any(k in low for k in ["correo", "email", "contacto", "telefono", "teléfono", "escribir", "soporte", "atencion", "atención"]):
        return (
            f"Nuestros canales de contacto oficiales para **{BRAND_NAME}** son:\n\n"
            f"- 📱 **WhatsApp Oficial:** [{WHATSAPP_NUMBER}]({WHATSAPP_URL})\n"
            f"- ✉️ **Atención general:** [{CONTACT_EMAIL}](mailto:{CONTACT_EMAIL})\n"
            f"- 💼 **Ventas y cotizaciones:** [{SALES_EMAIL}](mailto:{SALES_EMAIL})\n"
            f"- 🛠️ **Soporte y garantías:** [{SUPPORT_EMAIL}](mailto:{SUPPORT_EMAIL})\n\n"
            "Todos nuestros correos utilizan el dominio propio institucional **alfalubes.com**. También puedes explorar el catálogo y levantar tu pedido en [/products](/products)."
        )

    # 3. Marcas específicas de aceites
    matched_brand = None
    for b in ["castrol", "mobil", "shell", "valvoline"]:
        if b in low:
            matched_brand = b
            break
    if matched_brand:
        try:
            with get_db() as conn:
                prods = conn.execute(
                    "SELECT name, brand, viscosity, price, stock, description FROM products WHERE lower(brand) LIKE ? AND stock > 0",
                    (f"%{matched_brand}%",),
                ).fetchall()
            if prods:
                lines = [f"- **{p['name']}** ({p['viscosity']}): **${p['price']:,.2f} MXN** (Stock: {p['stock']} pzas) — {p['description']}" for p in prods]
                return (
                    f"En **ALFA LUBES** contamos con los siguientes aceites de la marca **{matched_brand.title()}**:\n\n"
                    + "\n".join(lines)
                    + f"\n\nPuedes agregarlos directamente al carrito desde nuestro catálogo en [/products](/products) o dime tu vehículo (marca, modelo y año) para validar compatibilidad."
                )
        except Exception:
            pass

    # 4. Viscosidades específicas
    viscosities = ["0w-20", "5w-20", "5w-30", "5w-40", "10w-40", "15w-40", "20w-50"]
    found_visc = None
    for v in viscosities:
        if v in low:
            found_visc = v
            break
    if found_visc:
        try:
            with get_db() as conn:
                prods = conn.execute(
                    "SELECT name, brand, viscosity, price, stock FROM products WHERE lower(viscosity) = ? AND stock > 0",
                    (found_visc,),
                ).fetchall()
            if prods:
                plist = ", ".join([f"**{p['name']}** (${p['price']:,.2f} MXN)" for p in prods])
                return (
                    f"El grado **{found_visc.upper()}** es excelente para una lubricación precisa según el fabricante.\n\n"
                    f"En nuestro inventario disponible tenemos: {plist}.\n\n"
                    "Recuerda siempre confirmar en el manual de propietario de tu auto que coincida la viscosidad y norma API. ¿Cuál es el año y modelo de tu vehículo?"
                )
        except Exception:
            pass

    # 5. Sintético vs Mineral
    if any(k in low for k in ["sintetico vs mineral", "sintético vs mineral", "diferencia", "mineral o sintetico", "mineral o sintético"]):
        return (
            "**Diferencias clave entre Aceite Sintético y Mineral:**\n\n"
            "1. **100% Sintético**:\n"
            "   - Máxima pureza molecular y resistencia a temperaturas extremas.\n"
            "   - Fluye al instante en arranques en frío (reduciendo hasta un 70% el desgaste inicial).\n"
            "   - Durabilidad: 10,000 a 15,000 km.\n"
            "   - Recomendado para motores modernos, con inyección directa o turbo.\n\n"
            "2. **Mineral**:\n"
            "   - Refinado de petróleo tradicional.\n"
            "   - Durabilidad: 5,000 km.\n"
            "   - Recomendado para motores antiguos o con tolerancias holgadas.\n\n"
            "En **ALFA LUBES** recomendamos usar la viscosidad sintética recomendada por tu fabricante para alargar la vida útil de tu motor."
        )

    # 6. Alto kilometraje
    if any(k in low for k in ["kilometraje", "alto kilometraje", "100000", "100,000", "150000", "gasta aceite", "humo"]):
        return (
            "**Recomendación para motores con Alto Kilometraje:**\n\n"
            "- Si tu vehículo supera los 100,000 o 150,000 km y **NO consume aceite**, lo ideal es seguir utilizando la viscosidad recomendada en el manual (generalmente 5W-30 o 0W-20 sintético).\n"
            "- Si ya presenta un consumo moderado de lubricante o pequeños rezumes en empaques, te recomendamos optar por un aceite con formulación **High Mileage / Alto Kilometraje** (como Castrol GTX 10W-40) que incluye acondicionadores de sellos.\n"
            "- Evita saltar de golpe a aceites muy pesados como 20W-50 si el manual no lo indica, ya que puede dificultar la lubricación al arranque."
        )

    # 7. Compra y envíos
    if any(k in low for k in ["comprar", "pedido", "catalogo", "catálogo", "envio", "envío", "pago", "precio", "costo"]):
        return (
            f"Comprar en **{BRAND_NAME}** es muy fácil:\n\n"
            "1. Explora los productos disponibles en [/products](/products).\n"
            "2. Selecciona la cantidad y haz clic en **Agregar al carrito**.\n"
            "3. En el carrito, haz clic en **Confirmar compra** y completa tus datos de contacto.\n"
            f"4. Nuestro equipo de ventas te contactará desde **{SALES_EMAIL}** para acordar la entrega y el medio de pago.\n\n"
            "¿Tienes dudas sobre qué aceite requiere tu motor? Dime marca, modelo y año para orientarte."
        )

    # Saludo o respuesta general
    return (
        f"¡Hola! Soy tu **Asesor de Lubricación {BRAND_NAME}**.\n\n"
        "Estoy listo para responder de manera autónoma todas tus dudas sobre aceites automotrices, viscosidades y productos de nuestro catálogo.\n\n"
        "Para darte la mejor recomendación, por favor compárteme:\n"
        "- **Marca y Modelo** de tu vehículo\n"
        "- **Año y Tipo de Motor**\n"
        "- **Kilometraje actual** y si tiene consumo de aceite\n\n"
        f"También puedes escribirnos a [{CONTACT_EMAIL}](mailto:{CONTACT_EMAIL}) o ver nuestro catálogo en [/products](/products)."
    )


def _should_suggest_products(text: str) -> bool:
    t = (text or "").lower()
    triggers = [
        "comprar", "catálogo", "catalogo", "producto", "productos", "precio", "precios",
        "carrito", "pedido", "envío", "envio", "recomiend", "suger", "ver más", "ver mas",
        "disponib", "stock", "viscosidad", "aceite para", "cuál me conviene", "cual me conviene",
        "castrol", "mobil", "shell", "valvoline",
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

    reply = _call_meai(history)
    source = "meai"
    if not reply:
        source = "fallback"
        reply = _autonomous_fallback_reply(message)

    return jsonify(reply=reply, suggest_product=_should_suggest_products(message + " " + reply), source=source)


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


init_db()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
