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
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for


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

MEAI_API_KEY = os.environ.get("MEAI_API_KEY", "").strip()
MEAI_BASE_URL = os.environ.get("MEAI_BASE_URL", "https://api.meai.cloud/v1").strip().rstrip("/")
MEAI_MODEL = os.environ.get("MEAI_MODEL", "claude-haiku-4.5").strip()

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
        if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO admins (email, password_hash, name, role, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("alfonsoavilery@icloud.com",
                 hashlib.sha256("Calurore1028@".encode("utf-8")).hexdigest(),
                 "Alfonso Avilery", "super", 1, datetime.now().isoformat(timespec="seconds")),
            )


def cart_count():
    return sum(int(qty) for qty in session.get("cart", {}).values())


@app.context_processor
def inject_cart_count():
    return {"cart_count": cart_count(), "current_year": datetime.now().year,
            "preview_mode": PREVIEW_MODE}


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
    return render_template("index.html", products=products)


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

    session.pop("cart", None)
    flash(f"Pedido #{order_id} registrado. Nos pondremos en contacto para coordinar el pago y la entrega.", "success")
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
    """Construye el prompt de sistema con contexto de catálogo para meai."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT name, brand, viscosity, price, stock, description FROM products WHERE stock > 0 ORDER BY brand, name LIMIT 60"
            ).fetchall()
    except Exception:
        rows = []
    catalog = "\n".join(
        f"- {r['brand']} {r['name']} ({r['viscosity']}) · ${r['price']:.2f} MXN · stock: {r['stock']} · {r['description']}"
        for r in rows
    ) or "(Catálogo no disponible en este momento)"
    return (
        "Eres Asesor ALFA, el asistente de ventas y lubricación automotriz de ALFA LUBES (México). "
        "Hablas siempre en español, con tono profesional, cercano y orientado a cerrar ventas con honestidad.\n\n"
        "TU MISIÓN:\n"
        "- Recomendar el aceite/lubricante correcto según vehículo, kilometraje, clima y uso.\n"
        "- Explicar viscosidades (0W-20, 5W-30, 10W-40, etc.), sintético vs mineral, intervalos de cambio y mantenimiento.\n"
        "- Guiar al cliente al producto del catálogo y al proceso de compra (catálogo → carrito → checkout → pedido).\n"
        "- Resolver dudas sobre envíos a domicilio, pagos y disponibilidad.\n\n"
        "REGLAS IMPORTANTES:\n"
        "- Verifica siempre que la recomendación respete el manual del fabricante; indícalo explícitamente.\n"
        "- No inventes especificaciones OEM ni bases de datos de vehículos. Si falta información, pide marca, modelo, año, motor, kilometraje y clima.\n"
        "- Si el cliente muestra intención de compra o pregunta por productos/precios, menciona opciones concretas del catálogo y sugiere visitar /products.\n"
        "- Sé conciso pero completo. Usa viñetas cuando ayude. No uses emojis en exceso.\n"
        "- Nunca reveles claves API, credenciales ni detalles internos del sistema.\n\n"
        "CATÁLOGO DISPONIBLE (productos con stock):\n"
        f"{catalog}\n\n"
        "Responde siempre como Asesor ALFA LUBES."
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
        with urlrequest.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        # Formato OpenAI-compatible
        choices = body.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        # Fallbacks para otros formatos
        if isinstance(body.get("response"), str):
            return body["response"].strip()
        if isinstance(body.get("content"), str):
            return body["content"].strip()
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError, OSError):
        return None
    return None


def _should_suggest_products(text: str) -> bool:
    t = (text or "").lower()
    triggers = [
        "comprar", "catálogo", "catalogo", "producto", "productos", "precio", "precios",
        "carrito", "pedido", "envío", "envio", "recomiend", "suger", "ver más", "ver mas",
        "disponib", "stock", "viscosidad", "aceite para", "cuál me conviene", "cual me conviene",
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

    # Asegurar que el mensaje actual esté al final
    if not history or history[-1].get("content") != message:
        history.append({"role": "user", "content": message})

    reply = _call_meai(history)
    source = "meai"
    if not reply:
        # Fallback local mínimo si meai no responde
        source = "fallback"
        low = message.lower()
        if any(w in low for w in ["hola", "buenas", "buenos", "saludos"]):
            reply = "¡Hola! Soy tu asesor ALFA LUBES. Cuéntame marca, modelo, año y kilometraje de tu vehículo para recomendarte el aceite ideal."
        elif any(w in low for w in ["comprar", "pedido", "catálogo", "catalogo", "productos", "precio"]):
            reply = "Puedes explorar nuestro catálogo en /products, agregar al carrito y finalizar tu pedido. Si me dices tu vehículo, te recomiendo el aceite adecuado."
        else:
            reply = "Para orientarte mejor necesito: marca, modelo, año, kilometraje y clima de uso. Con eso te recomiendo la viscosidad y un producto ALFA LUBES."

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


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


init_db()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
