"""
directrices_revisar.py — Corre cada 15 min (ver
.github/workflows/directrices_revisar.yml) y hace todo el trabajo del
sistema de Directrices por Teams:

1. Lista los mensajes recientes del canal de Teams (gerencia escribe ahí
   directamente, el sistema nunca publica). Cualquier mensaje que @mencione
   a uno de los responsables configurados en area_responsables.json se
   registra como una directriz nueva, en estado "pendiente", con el área
   derivada de a quién mencionaron.
2. Para las directrices ya pendientes, revisa si tuvieron respuesta (hilo)
   o reacción → se marcan "atendido". Si superan el umbral de horas de su
   prioridad sin actividad, se marcan "escalado" (queda así hasta que se
   atienda).

Reescribe dashboard-data/directrices_estado.json (correos nunca se incluyen
en ese JSON público — ver area_responsables.json / directrices_config.py).
"""

import logging
import re
from datetime import datetime, timedelta

from directrices_config import (
    TEAM_ID, CHANNEL_ID, GRAPH_BASE, UMBRALES_HORAS,
    get_ms_token, graph_call, cargar_areas, cargar_estado, guardar_estado,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

UTC_OFFSET_HORAS = -5  # Ecuador


def limpiar_texto(contenido_html):
    """Quita las etiquetas HTML (incluida la del <at>mención</at>) del cuerpo del mensaje."""
    texto = re.sub(r"<at[^>]*>.*?</at>", "", contenido_html or "", flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def resolver_aad_por_area(token, areas):
    """área → id de Azure AD del responsable (para reconocer sus menciones)."""
    resultado = {}
    for area, info in areas.items():
        correo = info.get("correo")
        if not correo:
            continue
        try:
            user = graph_call(token, f"{GRAPH_BASE}/users/{correo}", params={"$select": "id"})
            resultado[area] = user["id"]
        except Exception as e:
            log.warning(f"  ⚠ No se pudo resolver el usuario de {area} ({correo}): {e}")
    return resultado


def area_mencionada(mensaje, aad_por_area):
    for mencion in mensaje.get("mentions") or []:
        aad_id = (mencion.get("mentioned") or {}).get("user", {}).get("id")
        if not aad_id:
            continue
        for area, area_aad_id in aad_por_area.items():
            if aad_id == area_aad_id:
                return area
    return None


def detectar_directrices_nuevas(token, areas, aad_por_area, ids_conocidos):
    url = f"{GRAPH_BASE}/teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages"
    try:
        data = graph_call(token, url, params={"$top": "50"})
    except Exception as e:
        log.error(f"  ✗ No se pudo listar mensajes del canal: {e}")
        return []

    nuevas = []
    for m in data.get("value", []):
        if m.get("id") in ids_conocidos:
            continue
        if (m.get("messageType") or "message") != "message":
            continue
        area = area_mencionada(m, aad_por_area)
        if not area:
            continue

        texto = limpiar_texto((m.get("body") or {}).get("content"))
        if not texto:
            continue

        creado_utc = datetime.strptime(m["createdDateTime"][:19], "%Y-%m-%dT%H:%M:%S")
        fecha_envio = creado_utc + timedelta(hours=UTC_OFFSET_HORAS)

        nuevas.append({
            "id": f"d-{creado_utc.strftime('%Y%m%d-%H%M%S')}-{m['id'][-6:]}",
            "texto": texto,
            "area": area,
            "responsable_nombre": areas[area].get("nombre", area),
            "prioridad": "Normal",
            "fecha_envio": fecha_envio.strftime("%Y-%m-%d %H:%M:%S"),
            "message_id": m["id"],
            "estado": "pendiente",
            "escalado": False,
            "fecha_atencion": "",
            "horas_pendiente": 0,
        })
        log.info(f"  + Nueva directriz detectada para {area}: {texto[:60]}...")

    return nuevas


def tiene_actividad(token, message_id):
    """True si el mensaje tiene al menos una respuesta o una reacción."""
    base = f"{GRAPH_BASE}/teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages/{message_id}"

    try:
        respuestas = graph_call(token, f"{base}/replies")
        if respuestas.get("value"):
            return True
    except Exception as e:
        log.warning(f"  ⚠ No se pudo leer respuestas de {message_id}: {e}")

    try:
        mensaje = graph_call(token, base)
        if mensaje.get("reactions"):
            return True
    except Exception as e:
        log.warning(f"  ⚠ No se pudo leer reacciones de {message_id}: {e}")

    return False


def main():
    if not TEAM_ID or not CHANNEL_ID:
        raise SystemExit("Faltan TEAMS_TEAM_ID / TEAMS_CHANNEL_ID (variables de GitHub Actions)")

    areas = cargar_areas()
    token = get_ms_token()
    aad_por_area = resolver_aad_por_area(token, areas)

    estado = cargar_estado()
    directrices = estado.get("directrices", [])
    ids_conocidos = {d["message_id"] for d in directrices if d.get("message_id")}

    nuevas = detectar_directrices_nuevas(token, areas, aad_por_area, ids_conocidos)
    directrices.extend(nuevas)

    pendientes = [d for d in directrices if d["estado"] == "pendiente"]
    if not pendientes:
        log.info("No hay directrices pendientes por revisar.")
    else:
        ahora = datetime.now()
        for d in pendientes:
            if d.get("message_id") and tiene_actividad(token, d["message_id"]):
                d["estado"] = "atendido"
                d["fecha_atencion"] = ahora.strftime("%Y-%m-%d %H:%M:%S")
                log.info(f"  ✓ {d['id']} ({d['area']}) atendida")
                continue

            enviada = datetime.strptime(d["fecha_envio"], "%Y-%m-%d %H:%M:%S")
            horas_transcurridas = (ahora - enviada).total_seconds() / 3600
            d["horas_pendiente"] = round(horas_transcurridas, 1)

            umbral = UMBRALES_HORAS.get(d.get("prioridad", "Normal"), UMBRALES_HORAS["Normal"])
            if horas_transcurridas > umbral and not d.get("escalado"):
                d["escalado"] = True
                log.warning(f"  ⚠ {d['id']} ({d['area']}) ESCALADA — {horas_transcurridas:.1f}h sin respuesta")

    estado["actualizado"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    estado["directrices"] = directrices
    guardar_estado(estado)
    log.info(f"Estado guardado: {len(directrices)} directriz(ces) en total ({len(nuevas)} nuevas).")


if __name__ == "__main__":
    main()
