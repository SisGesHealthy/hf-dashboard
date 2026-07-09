"""
directrices_config.py — Configuración y helpers de Microsoft Graph para el
sistema de Directrices por Teams.

Gerencia escribe las directrices directamente en el canal de Teams
(mencionando al responsable del área) — el sistema solo LEE, nunca publica.
Reutiliza el mismo patrón client_credentials de odoo_to_csv.py
(get_ms_token/graph_get, secrets AZURE_TENANT_ID/AZURE_CLIENT_ID/AZURE_CLIENT_SECRET).

Permisos de Application necesarios en esa app (con consentimiento del admin):
- ChannelMessage.Read.All — listar mensajes del canal y sus respuestas/reacciones
- Channel.ReadBasic.All / Team.ReadBasic.All — direccionar el canal
- User.Read.All — resolver el correo de cada responsable (area_responsables.json)
  a su id de Azure AD, para poder identificar a quién mencionó gerencia
"""

import os
import json
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("OUTPUT_DIR", os.path.join(BASE_DIR, "dashboard-data"))
ESTADO_PATH = os.path.join(OUT_DIR, "directrices_estado.json")
AREAS_PATH = os.path.join(BASE_DIR, "area_responsables.json")

# area_responsables.json NO se commitea (repo público) — el workflow lo
# materializa en tiempo de ejecución a partir del secret AREA_RESPONSABLES_JSON.
# Ver area_responsables.example.json para el esquema.

TEAM_ID = os.environ.get("TEAMS_TEAM_ID", "")
CHANNEL_ID = os.environ.get("TEAMS_CHANNEL_ID", "")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Horas sin respuesta/reacción antes de escalar, según prioridad de la directriz
UMBRALES_HORAS = {
    "Urgente": 2,
    "Normal": 8,
    "Baja": 24,
}


def get_ms_token():
    tenant = os.environ["AZURE_TENANT_ID"]
    payload = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["AZURE_CLIENT_ID"],
        "client_secret": os.environ["AZURE_CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def graph_call(token, url, method="GET", body=None, params=None):
    if params:
        # NO usar urlencode: codifica $ como %24 y Graph no reconoce %24expand
        url = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def cargar_areas():
    with open(AREAS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.pop("_comentario", None)
    return data


def cargar_estado():
    if not os.path.exists(ESTADO_PATH):
        return {"actualizado": "", "directrices": []}
    with open(ESTADO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_estado(estado):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
