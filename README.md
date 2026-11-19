# Sonex — audífonos con IA integrada

Sitio web completo de Sonex, la empresa que diseña y produce audífonos con
inteligencia artificial integrada. Hecho en Python con Flask + SQLite.

Incluye:
- Registro e inicio de sesión con contraseña, panel de cuenta, favoritos, carrito y pedidos.
- **Huella / Face ID de verdad** con llaves de acceso WebAuthn. Tu huella o tu rostro nunca salen de tu celular: Sonex solo guarda la llave pública.
- **Inicio de sesión con QR** desde otro celular (5 minutos, un solo uso, se aprueba desde tu cuenta).
- **Avatar al crear la cuenta**: robot rosa o robot turquesa, cambiable después.
- Tienda: Sonex Buds $2,499, Sonex One (diadema) $5,999, Sonex Studio (diadema) $7,499 y Sonex Air $3,499 MXN, todos con Neural Core, ANC adaptativo y traducción en vivo.
- Paleta del logo: morado `#3B276E`, rosa `#FF69B3`, turquesa `#00FFF7`, azul `#2585CA`, negro `#191E24`, blanco `#FFFFFF`.

## Correr en local

```bash
python -m venv .venv
source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Abre http://localhost:5000

En local la huella / Face ID funciona solo si tu navegador lo permite en
localhost y tu dispositivo tiene sensor biométrico.

## Subirlo a GitHub

```bash
git init
git add .
git commit -m "Sonex: sitio web con Flask"
git branch -M main
git remote add origin https://github.com/TU-USUARIO/sonex.git
git push -u origin main
```

No subas `sonex.db` ni `.env`: ya están en `.gitignore`.

## Publicarlo en Render (gratis)

1. Entra a https://render.com y crea una cuenta (o inicia sesión).
2. **New + → Web Service** → **Build and deploy from a Git repository**.
3. Conecta tu cuenta de GitHub y elige el repositorio `sonex`.
4. Render detecta el `render.yaml`: plan **Free**, `pip install -r requirements.txt` y `gunicorn app:app`.
5. En **Environment**, agrega estas variables:
   - `SECRET_KEY`: Render la genera sola (está en el `render.yaml`).
   - `RP_ID`: el hostname de tu app en Render, sin `https://`. Ejemplo: si tu app queda en `https://sonex.onrender.com`, pon `sonex.onrender.com`.
   - `DB_PATH`: `/tmp/sonex.db` (ya viene en el `render.yaml`).
   - `SECURE_COOKIES`: `1`
6. Dale a **Deploy** y espera a que diga **Live**. Tu página quedará en algo como `https://sonex.onrender.com`.

## Importante: la huella y el rostro

La huella / Face ID **solo funciona sobre HTTPS** (Render ya te da HTTPS) y en
un dispositivo con sensor de huella o Face ID. **No funciona** abriendo el
archivo como `file://`, ni en una página `http://` sin certificado. Por eso la
versión estática anterior no te agarraba la huella: no tenía servidor ni
HTTPS. Esta versión sí es el servidor real, así que en Render funciona.

Si en tu celular no te aparece la opción, revisa que:
- estés entrando a la dirección `https://` de Render (no al archivo descargado),
- tu celular tenga huella o Face ID configurada,
- uses Chrome o Safari actualizado.
