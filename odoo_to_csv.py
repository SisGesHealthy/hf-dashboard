"""
odoo_to_csv.py — Extractor de datos Odoo → CSV para Power BI
Healthy Food Marcalman Ecuador S.A.

Genera 4 archivos CSV en la carpeta dashboard-data:
  - despachos.csv      → Órdenes de venta + estado de entrega
  - despachos_lineas.csv → Líneas de productos por orden de venta
  - compras_lineas.csv → Líneas de productos por orden de compra
  - produccion.csv     → Órdenes de fabricación + órdenes de trabajo

Power BI apunta a esta carpeta y se refresca automáticamente.
El script sobreescribe los archivos anteriores en cada ejecución.

Programar con el Programador de tareas de Windows cada 30 minutos.
"""

import os
import csv
import logging
import xmlrpc.client
from datetime import datetime, timedelta

UTC_OFFSET = -5  # America/Guayaquil (Ecuador, sin horario de verano)

def utc_a_local(fecha_str, formato="%Y-%m-%d %H:%M"):
    """Convierte string UTC (Odoo o SharePoint ISO 8601) a hora local Ecuador (UTC-5)."""
    if not fecha_str or fecha_str is False:
        return ""
    try:
        s = str(fecha_str)[:19].replace("T", " ")  # soporta 2026-06-25T14:52:00Z
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        dt_local = dt + timedelta(hours=UTC_OFFSET)
        return dt_local.strftime(formato)
    except Exception:
        return str(fecha_str)[:16]

# ── Configuración ──────────────────────────────────────────────────────────────

ODOO_URL  = os.environ["ODOO_URL"]
ODOO_DB   = os.environ["ODOO_DB"]
ODOO_USER = os.environ["ODOO_USER"]
ODOO_PASS = os.environ["ODOO_PASS"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR  = os.environ.get("OUTPUT_DIR", os.path.join(BASE_DIR, "dashboard-data"))

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "odoo_to_csv.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Conexión Odoo ──────────────────────────────────────────────────────────────

def conectar():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASS, {})
    if not uid:
        raise ConnectionError("Autenticación fallida en Odoo")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)
    return uid, models

def odoo_get(models, uid, model, domain, fields, limit=5000):
    return models.execute_kw(
        ODOO_DB, uid, ODOO_PASS,
        model, "search_read", [domain],
        {"fields": fields, "limit": limit}
    )

def val(v, fallback=""):
    """Convierte False/None de Odoo a cadena vacía. Many2one → nombre."""
    if v is False or v is None:
        return fallback
    if isinstance(v, list):
        return v[1] if len(v) > 1 else v[0]
    return v

def limpiar_html(texto):
    """Elimina etiquetas HTML simples de campos note/términos."""
    import re
    if not texto:
        return ""
    return re.sub(r"<[^>]+>", " ", str(texto)).strip()

def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── Escritura CSV ──────────────────────────────────────────────────────────────

def escribir_csv(nombre, filas, encabezados):
    ruta = os.path.join(OUT_DIR, nombre)
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=encabezados)
        writer.writeheader()
        writer.writerows(filas)
    log.info(f"  ✓ {nombre} — {len(filas)} filas")

# ── DESPACHOS: cabecera de órdenes de venta ────────────────────────────────────

ESTADO_VENTA = {
    "draft": "Borrador", "sent": "Enviada", "sale": "Confirmada",
    "done": "Bloqueada", "cancel": "Cancelada",
}
ESTADO_ENTREGA = {
    "draft": "Borrador", "waiting": "Esperando", "confirmed": "Confirmada",
    "assigned": "Lista para despachar", "done": "Despachada", "cancel": "Cancelada",
}

def extraer_despachos(models, uid):
    log.info("Extrayendo despachos (sale.order)...")

    ventas = odoo_get(models, uid, "sale.order",
        [["state", "in", ["sale", "done"]]],
        ["id", "name", "partner_id", "date_order", "commitment_date",
         "amount_total", "state", "picking_ids", "user_id", "note"]
    )

    # Pickings de salida
    picking_ids = [pid for v in ventas for pid in (v.get("picking_ids") or [])]
    pickings_raw = odoo_get(models, uid, "stock.picking",
        [["id", "in", picking_ids], ["picking_type_code", "=", "outgoing"]],
        ["id", "state", "scheduled_date", "date_done", "sale_id"]
    ) if picking_ids else []

    pick_por_venta = {}
    for p in pickings_raw:
        if p.get("sale_id"):
            pick_por_venta.setdefault(p["sale_id"][0], []).append(p)

    filas = []
    for v in ventas:
        picks = pick_por_venta.get(v["id"], [])
        estados = [p["state"] for p in picks]

        if not estados:
            estado_entrega = "Sin entrega"
        elif all(s == "done" for s in estados):
            estado_entrega = "Despachada"
        elif any(s == "done" for s in estados):
            estado_entrega = "Parcialmente despachada"
        elif any(s == "assigned" for s in estados):
            estado_entrega = "Lista para despachar"
        else:
            estado_entrega = "Pendiente"

        fechas_done = [p["date_done"] for p in picks if p.get("date_done") and p["date_done"] is not False]
        fecha_despacho_real = max(fechas_done) if fechas_done else ""

        commitment = val(v.get("commitment_date"))
        if commitment and fecha_despacho_real:
            comprometido = datetime.strptime(str(commitment)[:19], "%Y-%m-%d %H:%M:%S")
            real         = datetime.strptime(str(fecha_despacho_real)[:19], "%Y-%m-%d %H:%M:%S")
            cumplimiento = "A tiempo" if real <= comprometido else "Tarde"
        elif commitment and estado_entrega != "Despachada":
            comprometido = datetime.strptime(str(commitment)[:19], "%Y-%m-%d %H:%M:%S")
            cumplimiento = "Pendiente" if datetime.now() <= comprometido else "Vencida"
        else:
            cumplimiento = ""

        filas.append({
            "orden_venta":         val(v["name"]),
            "cliente":             val(v["partner_id"]),
            "vendedor":            val(v.get("user_id")),
            "fecha_orden":         utc_a_local(val(v["date_order"]), "%Y-%m-%d %H:%M"),
            "fecha_compromiso":    utc_a_local(commitment, "%Y-%m-%d %H:%M"),
            "estado_venta":        ESTADO_VENTA.get(v["state"], v["state"]),
            "estado_entrega":      estado_entrega,
            "fecha_despacho_real": utc_a_local(fecha_despacho_real, "%Y-%m-%d %H:%M"),
            "cumplimiento":        cumplimiento,
            "monto_total":         round(float(v.get("amount_total") or 0), 2),
            "num_entregas":        len(picks),
            "terminos_condiciones":limpiar_html(val(v.get("note"))),
            "actualizado":         ahora(),
        })

    encabezados = ["orden_venta","cliente","vendedor","fecha_orden","fecha_compromiso",
                   "estado_venta","estado_entrega","fecha_despacho_real","cumplimiento",
                   "monto_total","num_entregas","terminos_condiciones","actualizado"]
    escribir_csv("despachos.csv", filas, encabezados)

# ── DESPACHOS: líneas de productos por orden de venta ─────────────────────────

def extraer_despachos_lineas(models, uid):
    log.info("Extrayendo líneas de despachos (sale.order.line)...")

    lineas = odoo_get(models, uid, "sale.order.line",
        [["order_id.state", "in", ["sale", "done"]]],
        ["id", "order_id", "product_id", "product_template_id",
         "product_uom_qty", "product_uom", "price_unit", "price_subtotal"]
    )

    filas = []
    for l in lineas:
        filas.append({
            "orden_venta":    val(l.get("order_id")),
            "producto":       val(l.get("product_id")),
            "producto_template": val(l.get("product_template_id")),
            "cantidad":       round(float(l.get("product_uom_qty") or 0), 3),
            "unidad_medida":  val(l.get("product_uom")),
            "precio_unitario":round(float(l.get("price_unit") or 0), 4),
            "subtotal":       round(float(l.get("price_subtotal") or 0), 2),
            "actualizado":    ahora(),
        })

    encabezados = ["orden_venta","producto","producto_template","cantidad",
                   "unidad_medida","precio_unitario","subtotal","actualizado"]
    escribir_csv("despachos_lineas.csv", filas, encabezados)

# ── COMPRAS: líneas de productos por orden de compra ──────────────────────────

ESTADO_COMPRA = {
    "draft": "Borrador", "sent": "Enviada", "to approve": "Por aprobar",
    "purchase": "Orden de compra", "done": "Bloqueada", "cancel": "Cancelada",
}

def extraer_compras_lineas(models, uid):
    log.info("Extrayendo líneas de compras (purchase.order + purchase.order.line)...")

    # Cabecera de compras
    compras = odoo_get(models, uid, "purchase.order",
        [["state", "in", ["purchase", "done", "sent"]]],
        ["id", "name", "partner_id", "date_order", "date_planned",
         "amount_total", "state", "user_id", "picking_ids"]
    )

    # Estado de recepción por compra
    picking_ids = [pid for c in compras for pid in (c.get("picking_ids") or [])]
    pickings_raw = odoo_get(models, uid, "stock.picking",
        [["id", "in", picking_ids], ["picking_type_code", "=", "incoming"]],
        ["id", "state", "purchase_id"]
    ) if picking_ids else []

    pick_por_compra = {}
    for p in pickings_raw:
        if p.get("purchase_id"):
            pick_por_compra.setdefault(p["purchase_id"][0], []).append(p["state"])

    # Índice de cabeceras por id
    compras_idx = {c["id"]: c for c in compras}
    compra_ids  = list(compras_idx.keys())

    # Líneas de compra
    lineas = odoo_get(models, uid, "purchase.order.line",
        [["order_id", "in", compra_ids]],
        ["id", "order_id", "product_id", "product_qty",
         "product_uom", "price_unit", "price_subtotal", "date_planned"]
    )

    filas = []
    for l in lineas:
        cid = l["order_id"][0] if l.get("order_id") else None
        cab = compras_idx.get(cid, {})

        estados_pick = pick_por_compra.get(cid, [])
        if not estados_pick:
            estado_recepcion = "Sin recepción"
        elif all(s == "done" for s in estados_pick):
            estado_recepcion = "Recibida completa"
        elif any(s == "done" for s in estados_pick):
            estado_recepcion = "Recibida parcial"
        else:
            estado_recepcion = "Pendiente recepción"

        date_planned = val(l.get("date_planned")) or val(cab.get("date_planned"))
        vencida = ""
        if date_planned and estado_recepcion not in ("Recibida completa",):
            dp = datetime.strptime(str(date_planned)[:19], "%Y-%m-%d %H:%M:%S")
            vencida = "Sí" if datetime.now() > dp else "No"

        filas.append({
            "orden_compra":      val(l.get("order_id")),
            "proveedor":         val(cab.get("partner_id")),
            "responsable":       val(cab.get("user_id")),
            "estado_compra":     ESTADO_COMPRA.get(cab.get("state",""), cab.get("state","")),
            "estado_recepcion":  estado_recepcion,
            "producto":          val(l.get("product_id")),
            "cantidad":          round(float(l.get("product_qty") or 0), 3),
            "unidad_medida":     val(l.get("product_uom")),
            "precio_unitario":   round(float(l.get("price_unit") or 0), 4),
            "subtotal":          round(float(l.get("price_subtotal") or 0), 2),
            "fecha_orden":       utc_a_local(val(cab.get("date_order")), "%Y-%m-%d %H:%M"),
            "fecha_planificada": utc_a_local(date_planned, "%Y-%m-%d %H:%M"),
            "vencida":           vencida,
            "monto_total_orden": round(float(cab.get("amount_total") or 0), 2),
            "actualizado":       ahora(),
        })

    encabezados = ["orden_compra","proveedor","responsable","estado_compra","estado_recepcion",
                   "producto","cantidad","unidad_medida","precio_unitario","subtotal",
                   "fecha_orden","fecha_planificada","vencida","monto_total_orden","actualizado"]
    escribir_csv("compras_lineas.csv", filas, encabezados)

# ── TRASLADOS INTERNOS A ECLA (Emergen Cold) ──────────────────────────────────

ESTADO_TRASLADO = {
    "draft": "Borrador", "waiting": "Esperando", "confirmed": "Confirmado",
    "assigned": "Disponible", "done": "Hecho", "cancel": "Cancelado",
}

def extraer_traslados_ecla(models, uid):
    log.info("Extrayendo traslados internos a ECLA (stock.picking)...")

    # Inicio del día en Quito (UTC-5), expresado en UTC
    ahora_quito = datetime.now() - timedelta(hours=5)
    hoy_utc = (ahora_quito.replace(hour=0, minute=0, second=0, microsecond=0) +
               timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")

    pickings = odoo_get(models, uid, "stock.picking",
        [["location_dest_id.complete_name", "ilike", "ECLA"],
         ["state", "not in", ["cancel", "draft"]],
         "|",
           ["scheduled_date", ">=", hoy_utc],
           ["date_done", ">=", hoy_utc]],
        ["id", "name", "state", "scheduled_date", "date_done", "origin", "partner_id"]
    )

    filas = []
    for p in pickings:
        filas.append({
            "documento":        val(p.get("name")),
            "origen":           val(p.get("origin")),
            "cliente":          val(p.get("partner_id")),
            "estado":           ESTADO_TRASLADO.get(p.get("state",""), p.get("state","")),
            "fecha_programada": utc_a_local(val(p.get("scheduled_date")), "%Y-%m-%d %H:%M"),
            "fecha_efectiva":   utc_a_local(val(p.get("date_done")), "%Y-%m-%d %H:%M"),
            "actualizado":      ahora(),
        })

    encabezados = ["documento","origen","cliente","estado","fecha_programada","fecha_efectiva","actualizado"]
    escribir_csv("traslados_ecla.csv", filas, encabezados)

# ── PRODUCCIÓN: órdenes + órdenes de trabajo ──────────────────────────────────

ESTADO_MO = {
    "draft": "Borrador", "confirmed": "Confirmada", "progress": "En progreso",
    "to_close": "Por cerrar", "done": "Terminada", "cancel": "Cancelada",
}
ESTADO_WO = {
    "pending": "Pendiente", "ready": "Lista", "progress": "En progreso",
    "done": "Terminada", "cancel": "Cancelada",
}

def extraer_produccion(models, uid):
    log.info("Extrayendo producción (mrp.production + mrp.workorder)...")

    ordenes = odoo_get(models, uid, "mrp.production",
        [["state", "not in", ["cancel", "draft"]]],
        ["id", "name", "product_id", "product_qty", "qty_produced",
         "product_uom_id", "lot_producing_id",
         "state", "date_start", "date_finished", "production_date",
         "bom_id", "workorder_ids"]
    )

    # Órdenes de trabajo de todas las producciones
    wo_ids = [wid for o in ordenes for wid in (o.get("workorder_ids") or [])]
    workorders = odoo_get(models, uid, "mrp.workorder",
        [["id", "in", wo_ids]],
        ["id", "name", "production_id", "state", "workcenter_id",
         "duration_expected", "duration", "date_start", "date_finished"]
    ) if wo_ids else []

    wo_por_produccion = {}
    for wo in workorders:
        if wo.get("production_id"):
            wo_por_produccion.setdefault(wo["production_id"][0], []).append(wo)

    filas = []
    for o in ordenes:
        qty_plan = float(o.get("product_qty") or 0)
        qty_real = float(o.get("qty_produced") or 0)
        avance   = round((qty_real / qty_plan * 100), 1) if qty_plan else 0

        prod_date = val(o.get("production_date"))
        wos = wo_por_produccion.get(o["id"], [])

        # Avance real: % de órdenes de trabajo (procesos del taller) terminadas.
        # qty_produced suele quedar en 0 hasta el último paso, por lo que el
        # avance basado en cantidad se ve siempre en 0% o 100%.
        if wos:
            terminadas = sum(1 for wo in wos if wo.get("state") == "done")
            avance = round(terminadas / len(wos) * 100, 1)

        # Una fila por orden de trabajo (o una fila sola si no tiene)
        if wos:
            for wo in wos:
                dur_esperada = round(float(wo.get("duration_expected") or 0), 1)
                dur_real     = round(float(wo.get("duration") or 0), 1)
                filas.append({
                    "orden_produccion":   val(o["name"]),
                    "producto":           val(o["product_id"]),
                    "qty_planificada":    qty_plan,
                    "qty_producida":      qty_real,
                    "avance_pct":         avance,
                    "unidad":             val(o.get("product_uom_id")),
                    "lote":               val(o.get("lot_producing_id")),
                    "estado_produccion":  ESTADO_MO.get(o["state"], o["state"]),
                    "fecha_produccion":   str(prod_date)[:10] if prod_date else "",
                    "fecha_inicio":       utc_a_local(val(o.get("date_start")), "%Y-%m-%d %H:%M"),
                    "fecha_fin":          utc_a_local(val(o.get("date_finished")), "%Y-%m-%d %H:%M"),
                    "tiene_bom":          "Sí" if o.get("bom_id") else "No",
                    "orden_trabajo":      val(wo.get("name")),
                    "centro_trabajo":     val(wo.get("workcenter_id")),
                    "estado_ot":          ESTADO_WO.get(wo.get("state",""), wo.get("state","")),
                    "duracion_esperada_min": dur_esperada,
                    "duracion_real_min":     dur_real,
                    "ot_fecha_inicio":    utc_a_local(val(wo.get("date_start")), "%Y-%m-%d %H:%M"),
                    "ot_fecha_fin":       utc_a_local(val(wo.get("date_finished")), "%Y-%m-%d %H:%M"),
                    "actualizado":        ahora(),
                })
        else:
            filas.append({
                "orden_produccion":   val(o["name"]),
                "producto":           val(o["product_id"]),
                "qty_planificada":    qty_plan,
                "qty_producida":      qty_real,
                "avance_pct":         avance,
                "estado_produccion":  ESTADO_MO.get(o["state"], o["state"]),
                "fecha_produccion":   str(prod_date)[:10] if prod_date else "",
                "fecha_inicio":       utc_a_local(val(o.get("date_start")), "%Y-%m-%d %H:%M"),
                "fecha_fin":          utc_a_local(val(o.get("date_finished")), "%Y-%m-%d %H:%M"),
                "tiene_bom":          "Sí" if o.get("bom_id") else "No",
                "orden_trabajo":      "",
                "centro_trabajo":     "",
                "estado_ot":          "",
                "duracion_esperada_min": "",
                "duracion_real_min":     "",
                "ot_fecha_inicio":    "",
                "ot_fecha_fin":       "",
                "actualizado":        ahora(),
            })

    encabezados = ["orden_produccion","producto","unidad","lote","qty_planificada","qty_producida","avance_pct",
                   "estado_produccion","fecha_produccion","fecha_inicio","fecha_fin","tiene_bom",
                   "orden_trabajo","centro_trabajo","estado_ot",
                   "duracion_esperada_min","duracion_real_min","ot_fecha_inicio","ot_fecha_fin","actualizado"]
    escribir_csv("produccion.csv", filas, encabezados)

# ── TALLER: empleados por orden de trabajo ─────────────────────────────────────

def extraer_taller(models, uid):
    log.info("Extrayendo taller (mrp.workorder + productividad)...")

    # Fecha de "hoy" en hora de Quito (UTC-5), no la del runner (UTC)
    ahora_quito = datetime.now() - timedelta(hours=5)
    hoy = ahora_quito.strftime("%Y-%m-%d")
    # UTC equivalente de inicio del día en Quito (UTC-5)
    hoy_utc = (ahora_quito.replace(hour=0, minute=0, second=0, microsecond=0) +
               timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")

    # OTs activas (ready/progress) sin filtrar por fecha
    # + OTs terminadas hoy
    workorders = odoo_get(models, uid, "mrp.workorder",
        [["state", "in", ["ready", "progress", "done"]],
         ["production_id.state", "not in", ["cancel", "draft"]]],
        ["id", "name", "production_id", "workcenter_id", "state",
         "qty_production", "qty_produced",
         "duration_expected", "duration", "date_start", "date_finished"]
    )

    wo_ids = [wo["id"] for wo in workorders]

    # Toda la productividad de hoy (registros de tiempo con empleado)
    productividad = odoo_get(models, uid, "mrp.workcenter.productivity",
        [["workorder_id", "in", wo_ids],
         ["date_start", ">=", hoy_utc]],
        ["id", "workorder_id", "employee_id", "workcenter_id",
         "date_start", "date_end", "duration", "loss_id"]
    ) if wo_ids else []

    # Índice: workorder_id → lista de registros de productividad
    prod_por_wo = {}
    for p in productividad:
        if p.get("workorder_id"):
            prod_por_wo.setdefault(p["workorder_id"][0], []).append(p)

    # Empleados únicos referenciados
    emp_ids = list({p["employee_id"][0] for p in productividad
                    if p.get("employee_id") and p["employee_id"] is not False})
    empleados_raw = odoo_get(models, uid, "hr.employee",
        [["id", "in", emp_ids]],
        ["id", "name", "job_id", "department_id"]
    ) if emp_ids else []
    emp_idx = {e["id"]: e for e in empleados_raw}

    filas = []
    for wo in workorders:
        wo_id    = wo["id"]
        prods_wo = prod_por_wo.get(wo_id, [])

        qty_plan = float(wo.get("qty_production") or 0)
        qty_real = float(wo.get("qty_produced") or 0)
        avance   = round(qty_real / qty_plan * 100, 1) if qty_plan else 0

        # Fechas reales de la OT
        ot_inicio = utc_a_local(val(wo.get("date_start")), "%Y-%m-%d %H:%M")
        ot_fin    = utc_a_local(val(wo.get("date_finished")), "%Y-%m-%d %H:%M")

        base = {
            "fecha":                 hoy,
            "orden_trabajo":         f"{val(wo.get('production_id'))} - {val(wo.get('name'))}",
            "centro_trabajo":        val(wo.get("workcenter_id")),
            "estado_ot":             ESTADO_WO.get(wo.get("state",""), wo.get("state","")),
            "qty_planificada":       qty_plan,
            "qty_producida":         qty_real,
            "avance_pct":            avance,
            "duracion_esperada_min": round(float(wo.get("duration_expected") or 0), 1),
            "duracion_real_min":     round(float(wo.get("duration") or 0), 1),
            "ot_fecha_inicio":       ot_inicio,
            "ot_fecha_fin":          ot_fin,
            "actualizado":           ahora(),
        }

        # Agrupar registros de productividad por empleado
        emp_registros = {}
        for p in prods_wo:
            if p.get("employee_id") and p["employee_id"] is not False:
                eid = p["employee_id"][0]
                emp_registros.setdefault(eid, []).append(p)

        if emp_registros:
            for eid, registros in emp_registros.items():
                emp  = emp_idx.get(eid, {})
                mins = round(sum(float(r.get("duration") or 0) for r in registros), 1)
                # Primer inicio y último fin del empleado en esta OT hoy
                inicios = [r["date_start"] for r in registros if r.get("date_start")]
                fines   = [r["date_end"]   for r in registros if r.get("date_end") and r["date_end"] is not False]
                emp_inicio = utc_a_local(min(inicios), "%Y-%m-%d %H:%M") if inicios else ""
                emp_fin    = utc_a_local(max(fines),   "%Y-%m-%d %H:%M") if fines   else "En curso"

                fila = dict(base)
                fila.update({
                    "empleado":            emp.get("name", ""),
                    "puesto":              val(emp.get("job_id")),
                    "departamento":        val(emp.get("department_id")),
                    "minutos_empleado_hoy":mins,
                    "emp_fecha_inicio":    emp_inicio,
                    "emp_fecha_fin":       emp_fin,
                })
                filas.append(fila)
        else:
            # OT sin registros de empleado hoy
            fila = dict(base)
            fila.update({
                "empleado":            "Sin registro hoy",
                "puesto":              "",
                "departamento":        "",
                "minutos_empleado_hoy":0,
                "emp_fecha_inicio":    "",
                "emp_fecha_fin":       "",
            })
            filas.append(fila)

    encabezados = ["fecha","orden_trabajo","centro_trabajo","estado_ot",
                   "empleado","puesto","departamento",
                   "qty_planificada","qty_producida","avance_pct",
                   "duracion_esperada_min","duracion_real_min","minutos_empleado_hoy",
                   "ot_fecha_inicio","ot_fecha_fin","emp_fecha_inicio","emp_fecha_fin",
                   "actualizado"]
    escribir_csv("taller.csv", filas, encabezados)

# ── CALIDAD: checks del día ────────────────────────────────────────────────────

ESTADO_CHECK = {
    "none":        "Pendiente",
    "in_progress": "En proceso",
    "pass":        "Aprobado",
    "fail":        "Rechazado",
}

def extraer_calidad(models, uid):
    log.info("Extrayendo calidad (quality.check)...")

    ahora_quito = datetime.now() - timedelta(hours=5)
    hoy_utc = (ahora_quito.replace(hour=0, minute=0, second=0, microsecond=0) +
               timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")

    # Ventana amplia: últimos 7 días; filtro de estado se aplica en Python
    hace_7_dias = (ahora_quito - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    checks_raw = odoo_get(models, uid, "quality.check",
        [["create_date", ">=", hace_7_dias]],
        ["id", "name", "title", "point_id", "product_id", "picking_id",
         "production_id", "user_id", "team_id", "quality_state", "create_date"]
    )
    hoy_ec = ahora_quito.strftime("%Y-%m-%d")
    # Mantener: abiertos siempre + cerrados de hoy
    checks = [c for c in checks_raw if
              c.get("quality_state") in ("none", "in_progress") or
              str(c.get("create_date", ""))[:10] >= hoy_ec]

    # Plantilla de hoja de trabajo desde quality.point
    point_ids = list({c["point_id"][0] for c in checks
                      if c.get("point_id") and c["point_id"] is not False})
    puntos_raw = odoo_get(models, uid, "quality.point",
        [["id", "in", point_ids]],
        ["id", "name", "title", "worksheet_template_id"]
    ) if point_ids else []
    punto_idx = {p["id"]: p for p in puntos_raw}

    # Partner, origen (OC) y productos desde stock.picking + stock.move
    pick_ids = list({c["picking_id"][0] for c in checks
                     if c.get("picking_id") and c["picking_id"] is not False})
    pickings_raw = odoo_get(models, uid, "stock.picking",
        [["id", "in", pick_ids]],
        ["id", "partner_id", "origin", "move_ids", "scheduled_date"]
    ) if pick_ids else []
    picking_idx = {p["id"]: p for p in pickings_raw}

    # Productos por picking desde stock.move
    move_ids = [mid for p in pickings_raw for mid in (p.get("move_ids") or [])]
    moves_raw = odoo_get(models, uid, "stock.move",
        [["id", "in", move_ids]],
        ["id", "picking_id", "product_id"]
    ) if move_ids else []
    prods_por_picking = {}
    for m in moves_raw:
        if m.get("picking_id"):
            pk = m["picking_id"][0]
            nombre = val(m.get("product_id"))
            if nombre:
                prods_por_picking.setdefault(pk, []).append(nombre)

    filas = []
    for c in checks:
        pid   = c["point_id"][0]   if c.get("point_id")   and c["point_id"]   is not False else None
        pk_id = c["picking_id"][0] if c.get("picking_id") and c["picking_id"] is not False else None
        punto   = punto_idx.get(pid, {})
        picking = picking_idx.get(pk_id, {})
        # Deduplicar productos conservando orden
        prods = list(dict.fromkeys(prods_por_picking.get(pk_id, [])))
        filas.append({
            "check_name":       val(c.get("name")),
            "check_title":      val(c.get("title")),
            "quality_state":    ESTADO_CHECK.get(c.get("quality_state", "none"), "Pendiente"),
            "punto_control":    val(c.get("point_id")),
            "plantilla":        val(punto.get("worksheet_template_id", False)),
            "productos":        " | ".join(prods),
            "picking":          val(c.get("picking_id")),
            "origen_doc":       val(picking.get("origin", False)),
            "fecha_programada": utc_a_local(val(picking.get("scheduled_date", False)), "%Y-%m-%d"),
            "produccion":       val(c.get("production_id")),
            "partner":          val(picking.get("partner_id", False)),
            "responsable":      val(c.get("user_id")),
            "equipo":           val(c.get("team_id")),
            "fecha_asignacion": utc_a_local(val(c.get("create_date")), "%Y-%m-%d %H:%M"),
            "actualizado":      ahora(),
        })

    encabezados = ["check_name", "check_title", "quality_state", "punto_control", "plantilla",
                   "productos", "picking", "origen_doc", "fecha_programada", "produccion", "partner",
                   "responsable", "equipo", "fecha_asignacion", "actualizado"]
    escribir_csv("calidad.csv", filas, encabezados)

# ── SHAREPOINT: Recepciones + Liberaciones ────────────────────────────────────

def get_ms_token():
    import urllib.request, urllib.parse, json as _json
    tenant  = os.environ["AZURE_TENANT_ID"]
    payload = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     os.environ["AZURE_CLIENT_ID"],
        "client_secret": os.environ["AZURE_CLIENT_SECRET"],
        "scope":         "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return _json.loads(resp.read())["access_token"]

def graph_get(token, url, params=None):
    import urllib.request, json as _json
    if params:
        # NO usar urlencode: codifica $ como %24 y Graph no reconoce %24expand
        url = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return _json.loads(resp.read())

def extraer_recepciones_sp():
    log.info("Extrayendo SharePoint (Recepciones + Liberaciones)...")

    # Verificar que existen los secrets antes de intentar
    if not all(os.environ.get(k) for k in
               ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")):
        log.warning("  ⚠ Secrets de Azure no configurados — omitiendo SharePoint")
        return

    try:
        token = get_ms_token()
    except Exception as e:
        log.error(f"  ✗ Error de autenticación MS: {e}")
        return

    try:
        site_info = graph_get(token,
            "https://graph.microsoft.com/v1.0/sites/"
            "marcalman.sharepoint.com:/sites/EspacioColaborativo")
        site_id = site_info["id"]
    except Exception as e:
        log.error(f"  ✗ Error obteniendo site SharePoint: {e}")
        return

    ahora_quito = datetime.now() - timedelta(hours=5)
    hoy_utc_str = (ahora_quito.replace(hour=0, minute=0, second=0, microsecond=0)
                   + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    base = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists"

    # Obtener GUIDs de las listas por nombre (más fiable que usar el nombre en la URL)
    try:
        listas_meta = graph_get(token, base, {"$select": "id,name,displayName"})
        lista_ids = {l["name"]: l["id"] for l in listas_meta.get("value", [])}
        log.info(f"  GUIDs obtenidos: Recepciones1={lista_ids.get('Recepciones1','?')[:8]}... "
                 f"Liberaciones={lista_ids.get('Liberaciones','?')[:8]}...")
    except Exception as e:
        log.error(f"  ✗ Error listando listas: {e}")
        return

    def sp_items(list_guid):
        url = f"{base}/{list_guid}/items"
        data = graph_get(token, url, {"$expand": "fields", "$top": "500"})
        items = data.get("value", [])
        while data.get("@odata.nextLink"):
            data = graph_get(token, data["@odata.nextLink"])
            items += data.get("value", [])
        return items

    # Recepciones1
    rec_guid = lista_ids.get("Recepciones1")
    if not rec_guid:
        log.error("  ✗ Lista Recepciones1 no encontrada en el sitio")
        return
    try:
        todos = sp_items(rec_guid)
        hoy_ec = ahora_quito.strftime("%Y-%m-%d")
        recepciones = [r for r in todos
                       if (r.get("fields",{}).get("HoraLlegada","") or "")[:10] >= hoy_ec]
        log.info(f"  Recepciones hoy: {len(recepciones)} de {len(todos)} totales")
    except Exception as e:
        log.error(f"  ✗ Error leyendo Recepciones1: {e}")
        return

    # Liberaciones
    libera_idx = {}
    lib_guid = lista_ids.get("Liberaciones")
    if lib_guid:
        try:
            lib_todos = sp_items(lib_guid)
            ids_hoy = {str(r["fields"].get("ID_1","")) for r in recepciones
                       if r["fields"].get("ID_1")}
            for item in lib_todos:
                k = str(item["fields"].get("ID_1",""))
                if k in ids_hoy:
                    libera_idx[k] = item["fields"]
        except Exception as e:
            log.warning(f"  ⚠ Error leyendo Liberaciones: {e}")

    filas = []
    for r in recepciones:
        f   = r["fields"]
        id1 = str(f.get("ID_1",""))
        lib = libera_idx.get(id1, {})
        filas.append({
            "id_recepcion":  id1,
            "hora_llegada":  utc_a_local(f.get("HoraLlegada",""),  "%Y-%m-%d %H:%M"),
            "hora_cierre":   utc_a_local(f.get("HoraCierre",""),   "%Y-%m-%d %H:%M"),
            "fruta":         f.get("Fruta",""),
            "total_neto_kg": f.get("TotalNeto",""),
            "proveedor":     f.get("Proveedor",""),
            "observaciones": f.get("ObservacionesProveedor",""),
            "brix":          lib.get("_x00b0_Brix",""),
            "ph":            lib.get("PH",""),
            "acidez":        lib.get("Acidez",""),
            "obs_calidad":   lib.get("Observaciones",""),
            "actualizado":   ahora(),
        })

    encabezados = ["id_recepcion","hora_llegada","hora_cierre","fruta",
                   "total_neto_kg","proveedor","observaciones",
                   "brix","ph","acidez","obs_calidad","actualizado"]
    escribir_csv("recepciones_sp.csv", filas, encabezados)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("Extractor Odoo → CSV  |  Healthy Food")
    log.info(f"Inicio: {ahora()}")
    log.info(f"Destino: {OUT_DIR}")
    log.info("=" * 60)

    os.makedirs(OUT_DIR, exist_ok=True)

    try:
        uid, models = conectar()
        log.info(f"Conectado a Odoo (uid={uid})")
    except Exception as e:
        log.error(f"Error de conexión: {e}")
        return

    extraer_despachos(models, uid)
    extraer_despachos_lineas(models, uid)
    extraer_compras_lineas(models, uid)
    extraer_traslados_ecla(models, uid)
    extraer_produccion(models, uid)
    extraer_taller(models, uid)
    extraer_calidad(models, uid)
    extraer_recepciones_sp()

    log.info("=" * 60)
    log.info(f"✓ Extracción completa — {ahora()}")
    log.info("=" * 60)

if __name__ == "__main__":
    main()
