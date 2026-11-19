"""
Sonex — audífonos con IA integrada.
Sitio web completo en Flask + SQLite.

Funciones reales (no demo):
- Registro / inicio de sesión con contraseña (hash) y sesiones en el servidor.
- Llaves de acceso WebAuthn (huella / Face ID): la huella o el rostro nunca
  salen del dispositivo; Sonex solo guarda la llave pública.
  OJO: WebAuthn solo funciona sobre HTTPS (Render) o en localhost, y en un
  dispositivo con sensor biométrico. No funciona en file:// ni en http.
- Inicio de sesión con QR desde otro celular: el celular con sesión crea un
  código QR (5 minutos, un solo uso), el otro celular lo escanea y el primero
  lo aprueba.
- Avatar al crear la cuenta: robot rosa o robot turquesa.
- Tienda: favoritos, carrito y pedidos guardados en la base de datos.

Ejecutar en local:
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python app.py
"""
import base64
import io
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta

import qrcode
from flask import (
    Flask, g, jsonify, redirect, render_template, request,
    send_file, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

# ------------------------------------------------------------------ config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SECURE_COOKIES", "0") == "1"

DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "sonex.db"))
RP_NAME = "Sonex"
RP_ID = os.environ.get("RP_ID", "localhost")  # en Render: el hostname, ej. sonex.onrender.com

AVATARES = {
    "rosa": {"nombre": "Robot rosa", "img": "img/avatar-rosa.jpg"},
    "turquesa": {"nombre": "Robot turquesa", "img": "img/avatar-turquesa.jpg"},
}

PRODUCTOS = {
    "buds": {
        "id": "buds", "nombre": "Sonex Buds", "precio": 2499,
        "tipo": "Audífonos inalámbricos in-ear",
        "img": "img/audifonos-buds.jpg",
        "desc": "Los audífonos del diseño original de Sonex: blancos con negro, "
                "luz LED azul y estuche negro con carga. IA integrada para "
                "traducción en vivo y sonido que se ajusta a tu oído.",
        "specs": ["Neural Core S2", "ANC adaptativo", "Traducción en vivo (32 idiomas)",
                  "Batería: 8 h + 24 h con estuche", "Bluetooth 5.4", "Resistencia IPX5"],
    },
    "one": {
        "id": "one", "nombre": "Sonex One", "precio": 5999,
        "tipo": "Diadema inalámbrica",
        "img": "img/diadema.svg",
        "desc": "Diadema insignia de Sonex con IA integrada. El Neural Core S2 aprende "
                "cómo escuchas y ajusta el sonido y la cancelación de ruido en tiempo real.",
        "specs": ["Neural Core S2", "ANC adaptativo con 6 micrófonos",
                  "Traducción en vivo (32 idiomas)", "Batería: 40 h",
                  "Audio espacial 360°", "Carga rápida USB-C (10 min = 5 h)"],
    },
    "studio": {
        "id": "studio", "nombre": "Sonex Studio", "precio": 7499,
        "tipo": "Diadema inalámbrica de estudio",
        "img": "img/diadema.svg",
        "desc": "Diadema de estudio para creadores: sonido plano y fiel, con IA que "
                "separa voces e instrumentos y cancela el ruido del cuarto.",
        "specs": ["Neural Core S2 Pro", "ANC adaptativo de estudio",
                  "Traducción en vivo (32 idiomas)", "Batería: 45 h",
                  "Drivers de 40 mm", "Modo estudio / modo calle"],
    },
    "air": {
        "id": "air", "nombre": "Sonex Air", "precio": 3499,
        "tipo": "Diadema ultraligera",
        "img": "img/diadema.svg",
        "desc": "Diadema ultraligera para todo el día: pesa poco, se dobla y la IA "
                "ajusta los bajos y las voces según lo que estés escuchando.",
        "specs": ["Neural Core S2", "ANC adaptativo", "Traducción en vivo (32 idiomas)",
                  "Batería: 30 h", "Plegable, 180 g", "Micrófono con IA anti-ruido"],
    },
}


def precio_mxn(n):
    return f"${n:,} MXN"


app.jinja_env.filters["mxn"] = precio_mxn

# ------------------------------------------------------------------ base de datos
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        avatar TEXT NOT NULL DEFAULT 'rosa',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS passkeys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        credential_id TEXT UNIQUE NOT NULL,
        public_key TEXT NOT NULL,
        sign_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS favoritos (
        user_id INTEGER NOT NULL REFERENCES users(id),
        producto TEXT NOT NULL,
        PRIMARY KEY (user_id, producto)
    );
    CREATE TABLE IF NOT EXISTS carrito (
        user_id INTEGER NOT NULL REFERENCES users(id),
        producto TEXT NOT NULL,
        cantidad INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (user_id, producto)
    );
    CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        total INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS pedido_items (
        pedido_id INTEGER NOT NULL REFERENCES pedidos(id),
        producto TEXT NOT NULL,
        cantidad INTEGER NOT NULL,
        precio INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS qr_logins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        codigo TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id),
        estado TEXT NOT NULL DEFAULT 'pendiente',
        session_token TEXT,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL
    );
    """)
    db.commit()
    db.close()


with app.app_context():
    init_db()


def usuario_actual():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not usuario_actual():
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


# ------------------------------------------------------------------ helpers WebAuthn
def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _origin():
    return request.host_url.rstrip("/")


def _options_to_dict(options):
    """Serializa las opciones WebAuthn (dataclasses) a JSON para el navegador."""
    import dataclasses
    from enum import Enum

    def convert(v):
        if isinstance(v, bytes):
            return _b64url_encode(v)
        if isinstance(v, Enum):
            return v.value
        if dataclasses.is_dataclass(v):
            return {k: convert(val) for k, val in dataclasses.asdict(v).items()}
        if isinstance(v, dict):
            return {k: convert(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [convert(x) for x in v]
        return v

    return convert(options)


# ------------------------------------------------------------------ rutas públicas
@app.route("/")
def index():
    return render_template("index.html", productos=PRODUCTOS, usuario=usuario_actual())


@app.route("/tienda")
def tienda():
    favs = set()
    u = usuario_actual()
    if u:
        favs = {r["producto"] for r in get_db().execute(
            "SELECT producto FROM favoritos WHERE user_id = ?", (u["id"],))}
    return render_template("tienda.html", productos=PRODUCTOS,
                           usuario=u, favoritos=favs)


@app.route("/producto/<pid>")
def producto(pid):
    p = PRODUCTOS.get(pid)
    if not p:
        return "Producto no encontrado", 404
    u = usuario_actual()
    fav = False
    if u:
        fav = get_db().execute(
            "SELECT 1 FROM favoritos WHERE user_id = ? AND producto = ?",
            (u["id"], pid)).fetchone() is not None
    return render_template("producto.html", producto=p, usuario=u, favorito=fav)


# ------------------------------------------------------------------ cuentas
@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        avatar = request.form.get("avatar", "rosa")
        if avatar not in AVATARES:
            avatar = "rosa"
        if not nombre or not email or len(password) < 6:
            return render_template("registro.html", error="Completa todos los campos (la contraseña necesita 6 caracteres o más).",
                                   avatares=AVATARES, usuario=None)
        db = get_db()
        try:
            cur = db.execute(
                "INSERT INTO users (nombre, email, password_hash, avatar, created_at) VALUES (?, ?, ?, ?, ?)",
                (nombre, email, generate_password_hash(password), avatar,
                 datetime.now().isoformat(timespec="seconds")))
            db.commit()
        except sqlite3.IntegrityError:
            return render_template("registro.html", error="Ese correo ya tiene cuenta. Inicia sesión.",
                                   avatares=AVATARES, usuario=None)
        session["user_id"] = cur.lastrowid
        return redirect(url_for("dashboard"))
    return render_template("registro.html", avatares=AVATARES, usuario=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        u = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if u and check_password_hash(u["password_hash"], password):
            session["user_id"] = u["id"]
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Correo o contraseña incorrectos.", usuario=None)
    return render_template("login.html", usuario=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/cuenta", methods=["GET", "POST"])
@login_required
def dashboard():
    u = usuario_actual()
    db = get_db()
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        avatar = request.form.get("avatar", u["avatar"])
        if nombre:
            db.execute("UPDATE users SET nombre = ? WHERE id = ?", (nombre, u["id"]))
        if avatar in AVATARES:
            db.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar, u["id"]))
        db.commit()
        return redirect(url_for("dashboard"))
    pedidos = db.execute(
        "SELECT * FROM pedidos WHERE user_id = ? ORDER BY id DESC", (u["id"],)).fetchall()
    pedidos_con_items = []
    for p in pedidos:
        items = db.execute(
            "SELECT * FROM pedido_items WHERE pedido_id = ?", (p["id"],)).fetchall()
        pedidos_con_items.append((p, items))
    favs = [PRODUCTOS[r["producto"]] for r in db.execute(
        "SELECT producto FROM favoritos WHERE user_id = ?", (u["id"],))
        if r["producto"] in PRODUCTOS]
    passkeys = db.execute(
        "SELECT id, created_at FROM passkeys WHERE user_id = ?", (u["id"],)).fetchall()
    qr_pendientes = db.execute(
        "SELECT * FROM qr_logins WHERE user_id = ? AND estado = 'pendiente' AND expires_at > ?",
        (u["id"], time.time())).fetchall()
    return render_template("dashboard.html", usuario=u, avatares=AVATARES,
                           pedidos=pedidos_con_items, favoritos=favs,
                           passkeys=passkeys, qr_pendientes=qr_pendientes)


# ------------------------------------------------------------------ favoritos / carrito / pedidos
@app.route("/api/favorito/<pid>", methods=["POST"])
@login_required
def favorito(pid):
    if pid not in PRODUCTOS:
        return jsonify({"ok": False}), 404
    u = usuario_actual()
    db = get_db()
    existe = db.execute("SELECT 1 FROM favoritos WHERE user_id = ? AND producto = ?",
                        (u["id"], pid)).fetchone()
    if existe:
        db.execute("DELETE FROM favoritos WHERE user_id = ? AND producto = ?",
                   (u["id"], pid))
        db.commit()
        return jsonify({"ok": True, "favorito": False})
    db.execute("INSERT INTO favoritos (user_id, producto) VALUES (?, ?)", (u["id"], pid))
    db.commit()
    return jsonify({"ok": True, "favorito": True})


@app.route("/api/carrito/agregar/<pid>", methods=["POST"])
@login_required
def carrito_agregar(pid):
    if pid not in PRODUCTOS:
        return jsonify({"ok": False}), 404
    u = usuario_actual()
    db = get_db()
    db.execute(
        "INSERT INTO carrito (user_id, producto, cantidad) VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, producto) DO UPDATE SET cantidad = cantidad + 1",
        (u["id"], pid))
    db.commit()
    return jsonify({"ok": True})


@app.route("/carrito")
@login_required
def carrito():
    u = usuario_actual()
    rows = get_db().execute(
        "SELECT * FROM carrito WHERE user_id = ?", (u["id"],)).fetchall()
    items = [(PRODUCTOS[r["producto"]], r["cantidad"]) for r in rows if r["producto"] in PRODUCTOS]
    total = sum(p["precio"] * c for p, c in items)
    return render_template("carrito.html", usuario=u, items=items, total=total)


@app.route("/api/pedido", methods=["POST"])
@login_required
def crear_pedido():
    u = usuario_actual()
    db = get_db()
    rows = db.execute("SELECT * FROM carrito WHERE user_id = ?", (u["id"],)).fetchall()
    if not rows:
        return jsonify({"ok": False, "error": "El carrito está vacío."}), 400
    total = sum(PRODUCTOS[r["producto"]]["precio"] * r["cantidad"] for r in rows
                if r["producto"] in PRODUCTOS)
    cur = db.execute("INSERT INTO pedidos (user_id, total, created_at) VALUES (?, ?, ?)",
                     (u["id"], total, datetime.now().isoformat(timespec="seconds")))
    pid = cur.lastrowid
    for r in rows:
        if r["producto"] in PRODUCTOS:
            db.execute("INSERT INTO pedido_items VALUES (?, ?, ?, ?)",
                       (pid, r["producto"], r["cantidad"], PRODUCTOS[r["producto"]]["precio"]))
    db.execute("DELETE FROM carrito WHERE user_id = ?", (u["id"],))
    db.commit()
    return jsonify({"ok": True, "pedido": pid, "total": total})


# ------------------------------------------------------------------ WebAuthn (huella / Face ID)
@app.route("/passkey/registro/inicio", methods=["POST"])
@login_required
def passkey_registro_inicio():
    from webauthn import generate_registration_options
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria, ResidentKeyRequirement,
        UserVerificationRequirement,
    )
    u = usuario_actual()
    options = generate_registration_options(
        rp_id=RP_ID, rp_name=RP_NAME,
        user_id=str(u["id"]).encode(),
        user_name=u["email"], user_display_name=u["nombre"],
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment="platform",
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED),
    )
    session["webauthn_challenge"] = _b64url_encode(options.challenge)
    return jsonify(_options_to_dict(options))


@app.route("/passkey/registro/fin", methods=["POST"])
@login_required
def passkey_registro_fin():
    from webauthn import verify_registration_response
    u = usuario_actual()
    challenge = session.pop("webauthn_challenge", None)
    if not challenge:
        return jsonify({"ok": False, "error": "Sesión expirada, inténtalo de nuevo."}), 400
    try:
        verified = verify_registration_response(
            credential=request.get_json(),
            expected_challenge=_b64url_decode(challenge),
            expected_origin=_origin(),
            expected_rp_id=RP_ID,
            require_user_verification=True)
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo verificar la llave: {e}"}), 400
    cred_id = verified.credential_id
    if isinstance(cred_id, bytes):
        cred_id = _b64url_encode(cred_id)
    pub_key = verified.credential_public_key
    if isinstance(pub_key, bytes):
        pub_key = _b64url_encode(pub_key)
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO passkeys (user_id, credential_id, public_key, sign_count, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (u["id"], cred_id, pub_key,
         verified.sign_count, datetime.now().isoformat(timespec="seconds")))
    db.commit()
    return jsonify({"ok": True})


@app.route("/passkey/login/inicio", methods=["POST"])
def passkey_login_inicio():
    from webauthn import generate_authentication_options
    from webauthn.helpers.structs import UserVerificationRequirement
    options = generate_authentication_options(
        rp_id=RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED)
    session["webauthn_challenge"] = _b64url_encode(options.challenge)
    return jsonify(_options_to_dict(options))


@app.route("/passkey/login/fin", methods=["POST"])
def passkey_login_fin():
    from webauthn import verify_authentication_response
    challenge = session.pop("webauthn_challenge", None)
    if not challenge:
        return jsonify({"ok": False, "error": "Sesión expirada, inténtalo de nuevo."}), 400
    try:
        data = request.get_json()
        raw_id = data["rawId"]
    except Exception as e:
        return jsonify({"ok": False, "error": f"Respuesta inválida: {e}"}), 400
    row = get_db().execute(
        "SELECT * FROM passkeys WHERE credential_id = ?", (raw_id,)).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "Esa llave no está registrada en este dispositivo/cuenta."}), 400
    try:
        verified = verify_authentication_response(
            credential=data,
            expected_challenge=_b64url_decode(challenge),
            expected_origin=_origin(),
            expected_rp_id=RP_ID,
            credential_public_key=_b64url_decode(row["public_key"]),
            credential_current_sign_count=row["sign_count"],
            require_user_verification=True)
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo verificar: {e}"}), 400
    db = get_db()
    db.execute("UPDATE passkeys SET sign_count = ? WHERE id = ?",
               (verified.new_sign_count, row["id"]))
    db.commit()
    session["user_id"] = row["user_id"]
    return jsonify({"ok": True})


@app.route("/passkey/eliminar/<int:pid>", methods=["POST"])
@login_required
def passkey_eliminar(pid):
    u = usuario_actual()
    get_db().execute("DELETE FROM passkeys WHERE id = ? AND user_id = ?", (pid, u["id"]))
    get_db().commit()
    return redirect(url_for("dashboard"))


# ------------------------------------------------------------------ QR login (otro celular)
@app.route("/qr/crear", methods=["POST"])
@login_required
def qr_crear():
    u = usuario_actual()
    token = secrets.token_urlsafe(24)
    codigo = f"{secrets.randbelow(900000) + 100000}"
    ahora = time.time()
    get_db().execute(
        "INSERT INTO qr_logins (token, codigo, user_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?)", (token, codigo, u["id"], ahora, ahora + 300))
    get_db().commit()
    return redirect(url_for("qr_mostrar", token=token))


@app.route("/qr/<token>")
def qr_mostrar(token):
    row = get_db().execute(
        "SELECT * FROM qr_logins WHERE token = ?", (token,)).fetchone()
    if not row:
        return "Código QR no válido.", 404
    u = usuario_actual()
    # El celular que ya tiene sesión ve el QR para escanearlo desde el otro.
    # El otro celular (sin sesión) ve la pantalla de espera de aprobación.
    return render_template("qr.html", qr=row, usuario=u,
                           url=request.host_url.rstrip("/") + url_for("qr_mostrar", token=token))


@app.route("/qr/imagen/<token>")
def qr_imagen(token):
    row = get_db().execute(
        "SELECT * FROM qr_logins WHERE token = ?", (token,)).fetchone()
    if not row:
        return "No válido", 404
    url = request.host_url.rstrip("/") + url_for("qr_mostrar", token=token)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/qr/codigo", methods=["GET", "POST"])
def qr_codigo():
    if request.method == "POST":
        codigo = request.form.get("codigo", "").strip()
        row = get_db().execute(
            "SELECT * FROM qr_logins WHERE codigo = ?", (codigo,)).fetchone()
        if row:
            return redirect(url_for("qr_mostrar", token=row["token"]))
        return render_template("qr_codigo.html", error="Código no válido.", usuario=usuario_actual())
    return render_template("qr_codigo.html", usuario=usuario_actual())


@app.route("/qr/estado/<token>")
def qr_estado(token):
    row = get_db().execute(
        "SELECT * FROM qr_logins WHERE token = ?", (token,)).fetchone()
    if not row:
        return jsonify({"estado": "no_valido"})
    if row["estado"] == "pendiente" and time.time() > row["expires_at"]:
        get_db().execute("UPDATE qr_logins SET estado = 'expirado' WHERE token = ?", (token,))
        get_db().commit()
        return jsonify({"estado": "expirado"})
    data = {"estado": row["estado"]}
    if row["estado"] == "aprobado":
        data["session_token"] = row["session_token"]
    return jsonify(data)


@app.route("/qr/aprobar/<int:qid>", methods=["POST"])
@login_required
def qr_aprobar(qid):
    u = usuario_actual()
    row = get_db().execute(
        "SELECT * FROM qr_logins WHERE id = ? AND user_id = ?", (qid, u["id"])).fetchone()
    if not row or row["estado"] != "pendiente" or time.time() > row["expires_at"]:
        return redirect(url_for("dashboard"))
    session_token = secrets.token_urlsafe(32)
    get_db().execute(
        "UPDATE qr_logins SET estado = 'aprobado', session_token = ? WHERE id = ?",
        (session_token, qid))
    get_db().commit()
    return redirect(url_for("dashboard"))


@app.route("/qr/rechazar/<int:qid>", methods=["POST"])
@login_required
def qr_rechazar(qid):
    u = usuario_actual()
    get_db().execute(
        "UPDATE qr_logins SET estado = 'rechazado' WHERE id = ? AND user_id = ?",
        (qid, u["id"]))
    get_db().commit()
    return redirect(url_for("dashboard"))


@app.route("/qr/canjear", methods=["POST"])
def qr_canjear():
    data = request.get_json(force=True, silent=True) or {}
    token = data.get("token")
    session_token = data.get("session_token")
    row = get_db().execute(
        "SELECT * FROM qr_logins WHERE token = ? AND session_token = ?",
        (token, session_token)).fetchone()
    if not row or row["estado"] != "aprobado":
        return jsonify({"ok": False}), 400
    # Un solo uso: al canjearlo se marca como usado.
    get_db().execute("UPDATE qr_logins SET estado = 'usado' WHERE token = ?", (token,))
    get_db().commit()
    session["user_id"] = row["user_id"]
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
