/* Sonex — JavaScript: passkeys (huella / Face ID), QR y tienda */
function b64urlToBuffer(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}
function bufferToB64url(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  bytes.forEach(b => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function publicKeyToJson(cred) {
  const out = {
    id: cred.id, rawId: bufferToB64url(cred.rawId), type: cred.type,
    response: {},
  };
  const r = cred.response;
  if (r.clientDataJSON) out.response.clientDataJSON = bufferToB64url(r.clientDataJSON);
  if (r.attestationObject) out.response.attestationObject = bufferToB64url(r.attestationObject);
  if (r.authenticatorData) out.response.authenticatorData = bufferToB64url(r.authenticatorData);
  if (r.signature) out.response.signature = bufferToB64url(r.signature);
  if (r.userHandle) out.response.userHandle = bufferToB64url(r.userHandle);
  return out;
}
function optionsFromServer(o) {
  if (o.challenge) o.challenge = b64urlToBuffer(o.challenge);
  if (o.user && o.user.id) o.user.id = b64urlToBuffer(o.user.id);
  if (o.allowCredentials) o.allowCredentials.forEach(c => { c.id = b64urlToBuffer(c.id); });
  if (o.excludeCredentials) o.excludeCredentials.forEach(c => { c.id = b64urlToBuffer(c.id); });
  return o;
}
async function avisoBiometria() {
  const el = document.getElementById("aviso-biometria");
  if (!el) return;
  if (window.location.protocol !== "https:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
    el.textContent = "La huella / Face ID solo funciona sobre HTTPS. En esta página sin HTTPS no se puede usar; súbela a Render para que funcione.";
    el.style.display = "block";
    return;
  }
  if (!window.PublicKeyCredential) {
    el.textContent = "Este navegador no soporta llaves de acceso (WebAuthn).";
    el.style.display = "block";
    return;
  }
  try {
    const ok = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
    if (!ok) {
      el.textContent = "Este dispositivo o navegador no tiene sensor de huella ni Face ID disponible. Puedes seguir entrando con correo y contraseña.";
      el.style.display = "block";
    }
  } catch (e) { /* si no se puede detectar, no bloqueamos nada */ }
}
document.addEventListener("DOMContentLoaded", avisoBiometria);

async function registrarPasskey(btn) {
  try {
    const inicio = await fetch("/passkey/registro/inicio", { method: "POST" });
    const options = optionsFromServer(await inicio.json());
    const cred = await navigator.credentials.create({ publicKey: options });
    const fin = await fetch("/passkey/registro/fin", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(publicKeyToJson(cred)),
    });
    const res = await fin.json();
    if (res.ok) { alert("Huella / rostro activados en este dispositivo."); location.reload(); }
    else alert("No se pudo activar: " + (res.error || "error desconocido"));
  } catch (e) {
    alert("No se pudo usar la huella / Face ID en este dispositivo: " + e.message);
  }
}
async function entrarPasskey() {
  try {
    const inicio = await fetch("/passkey/login/inicio", { method: "POST" });
    const data = await inicio.json();
    if (data.error) { alert(data.error); return; }
    const options = optionsFromServer(data);
    const cred = await navigator.credentials.get({ publicKey: options });
    const fin = await fetch("/passkey/login/fin", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(publicKeyToJson(cred)),
    });
    const res = await fin.json();
    if (res.ok) window.location.href = "/cuenta";
    else alert("No se pudo entrar con huella / rostro: " + (res.error || "error desconocido"));
  } catch (e) {
    alert("No se pudo usar la huella / Face ID en este dispositivo: " + e.message);
  }
}
async function postJson(url) {
  const r = await fetch(url, { method: "POST" });
  return r.json();
}
async function agregarCarrito(pid, btn) {
  const res = await postJson("/api/carrito/agregar/" + pid);
  if (res.ok) { btn.textContent = "Agregado ✓"; setTimeout(() => { btn.textContent = "Agregar al carrito"; }, 1500); }
  else { alert("Primero inicia sesión para agregar al carrito."); window.location.href = "/login"; }
}
async function toggleFavorito(pid, btn) {
  const res = await postJson("/api/favorito/" + pid);
  if (res.ok) btn.textContent = res.favorito ? "♥ En favoritos" : "♡ Favorito";
  else { alert("Primero inicia sesión."); window.location.href = "/login"; }
}
async function confirmarPedido(btn) {
  const res = await postJson("/api/pedido");
  if (res.ok) { alert("Pedido #" + res.pedido + " confirmado por $" + res.total.toLocaleString() + " MXN. Gracias por comprar en Sonex."); window.location.href = "/cuenta"; }
  else alert(res.error || "No se pudo confirmar el pedido.");
}
// QR: el otro celular espera la aprobación y canjea la sesión una sola vez.
(function () {
  const box = document.getElementById("qr-espera");
  if (!box) return;
  const token = box.dataset.token;
  const timer = setInterval(async () => {
    const r = await fetch("/qr/estado/" + token);
    const d = await r.json();
    if (d.estado === "aprobado" && d.session_token) {
      clearInterval(timer);
      const fin = await fetch("/qr/canjear", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token, session_token: d.session_token }),
      });
      const res = await fin.json();
      if (res.ok) window.location.href = "/cuenta";
    } else if (d.estado === "expirado" || d.estado === "rechazado" || d.estado === "no_valido") {
      clearInterval(timer);
      document.getElementById("qr-mensaje").textContent = "Este código expiró o fue rechazado. Pide uno nuevo en tu otro dispositivo.";
    }
  }, 2000);
})();
