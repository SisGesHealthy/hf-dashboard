/*
 * directrices-banner.js — banner global + panel de detalle para el sistema
 * de Directrices por Teams. Se incluye igual en las 4 páginas del dashboard
 * (index.html, taller.html, calidad-sp.html, wcp.html). Autocontenido: no
 * depende de las variables REPO/BRANCH ni de Papa Parse de cada página.
 */
(function () {
  const REPO = 'SisGesHealthy/hf-dashboard';
  const BRANCH = 'data';
  const URL_ESTADO = `https://raw.githubusercontent.com/${REPO}/${BRANCH}/dashboard-data/directrices_estado.json`;

  // Qué área(s) enfatizar según la página actual. null = vista general (index).
  const AREA_POR_PAGINA = {
    'taller.html': ['Fabricación', 'Bodega'],
    'calidad-sp.html': ['Calidad'],
    'wcp.html': ['Producción'],
  };
  const pagina = (location.pathname.split('/').pop() || 'index.html');
  const areasEnfasis = AREA_POR_PAGINA[pagina] || null;

  const estilos = `
    #banner-directrices {
      display: none;
      flex-shrink: 0;
      background: #d63b3b;
      color: #fff;
      font-family: 'Segoe UI', Arial, sans-serif;
      font-size: .82rem;
      font-weight: 700;
      padding: 6px 18px;
      align-items: center;
      gap: 10px;
      cursor: pointer;
      animation: hf-dir-parpadeo 1.4s ease-in-out infinite;
      box-shadow: 0 2px 6px rgba(0,0,0,.25);
    }
    #banner-directrices:hover { animation-play-state: paused; }
    @keyframes hf-dir-parpadeo {
      0%, 100% { background: #d63b3b; }
      50%      { background: #a82424; }
    }
    #banner-directrices .dir-hint { margin-left: auto; font-weight: 400; opacity: .85; font-size: .72rem; }

    #modal-directrices {
      display: none;
      position: fixed; inset: 0;
      background: rgba(0,0,0,.45);
      z-index: 9999;
      align-items: center;
      justify-content: center;
    }
    #modal-directrices .panel {
      background: #fff;
      border-radius: 10px;
      width: min(760px, 92vw);
      max-height: 80vh;
      overflow: auto;
      padding: 16px 18px;
      font-family: 'Segoe UI', Arial, sans-serif;
    }
    #modal-directrices h2 { font-size: 1rem; margin-bottom: 10px; color: #2c2c2c; }
    #modal-directrices table { width: 100%; border-collapse: collapse; font-size: .78rem; }
    #modal-directrices th { text-align: left; padding: 5px 8px; background: #f5f5f5; position: sticky; top: 0; }
    #modal-directrices td { padding: 5px 8px; border-bottom: 1px solid #eee; vertical-align: top; }
    #modal-directrices .cerrar-btn {
      display: block; margin: 12px 0 0 auto;
      background: #6a8f2f; color: #fff; border: none;
      padding: 6px 14px; border-radius: 6px; cursor: pointer; font-weight: 700;
    }
    .dir-badge { display: inline-block; padding: 1px 7px; border-radius: 20px; font-size: .68rem; font-weight: 700; white-space: nowrap; }
    .dir-badge.escalada  { background: #f8d7da; color: #721c24; }
    .dir-badge.pendiente { background: #fff3cd; color: #856404; }

    .kpi.rojo { border-left-color: #d63b3b; }
    .kpi.rojo .kpi-num { color: #d63b3b; }

    #toast-directrices {
      position: fixed;
      top: 10px;
      left: 50%;
      transform: translateX(-50%) translateY(-16px) scale(.92);
      min-width: 320px;
      max-width: 90vw;
      background: #e07b2a;
      color: #fff;
      border-radius: 10px;
      border: 2px solid #ffcf99;
      padding: 12px 18px;
      font-family: 'Segoe UI', Arial, sans-serif;
      box-shadow: 0 8px 28px rgba(0,0,0,.45), 0 0 0 4px rgba(224,123,42,.25);
      z-index: 10000;
      opacity: 0;
      pointer-events: none;
      transition: opacity .35s ease, transform .35s cubic-bezier(.34,1.56,.64,1);
    }
    #toast-directrices.visible { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }
    #toast-directrices .toast-header { font-weight: 800; font-size: .95rem; margin-bottom: 6px; }
    #toast-directrices ul { list-style: none; padding: 0; margin: 0; }
    #toast-directrices li { font-size: .8rem; padding: 3px 0; border-bottom: 1px solid rgba(255,255,255,.25); }
    #toast-directrices li:last-child { border-bottom: none; }
    #toast-directrices .toast-tiempo { opacity: .85; font-size: .72rem; margin-left: 6px; }
    #toast-directrices .toast-extra { font-style: italic; opacity: .85; }
  `;
  const styleTag = document.createElement('style');
  styleTag.textContent = estilos;
  document.head.appendChild(styleTag);

  const banner = document.createElement('div');
  banner.id = 'banner-directrices';
  document.body.insertBefore(banner, document.body.firstChild);

  const modal = document.createElement('div');
  modal.id = 'modal-directrices';
  modal.innerHTML = `
    <div class="panel">
      <h2>📋 Directrices pendientes</h2>
      <table>
        <thead><tr><th>Área</th><th>Responsable</th><th>Directriz</th><th>Tiempo</th><th>Estado</th></tr></thead>
        <tbody id="tabla-directrices-modal"></tbody>
      </table>
      <button class="cerrar-btn" id="cerrar-modal-directrices">Cerrar</button>
    </div>`;
  document.body.appendChild(modal);

  const toast = document.createElement('div');
  toast.id = 'toast-directrices';
  document.body.appendChild(toast);
  let ultimosPendientes = [];

  function cerrarModal() { modal.style.display = 'none'; }
  function abrirModal() { modal.style.display = 'flex'; }

  banner.addEventListener('click', abrirModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) cerrarModal(); });
  modal.querySelector('#cerrar-modal-directrices').addEventListener('click', cerrarModal);

  const kpiCard = document.getElementById('kpi-directrices-card');
  if (kpiCard) kpiCard.addEventListener('click', abrirModal);

  function escaparHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function horasTexto(h) {
    if (h == null) return '';
    if (h < 1) return `${Math.round(h * 60)} min`;
    return `${h.toFixed(1)} h`;
  }

  function render(data) {
    const todas = (data && data.directrices) || [];
    const pendientes = todas.filter((d) => d.estado === 'pendiente');
    const escaladas = pendientes.filter((d) => d.escalado);

    if (escaladas.length === 0) {
      banner.style.display = 'none';
    } else {
      let texto = `⚠ ${escaladas.length} directriz${escaladas.length > 1 ? 'es' : ''} sin atender`;
      if (areasEnfasis) {
        const enEsteArea = escaladas.filter((d) => areasEnfasis.includes(d.area));
        if (enEsteArea.length > 0) {
          texto += ` · ${enEsteArea.length} para ${areasEnfasis.join('/')}`;
        }
      }
      banner.innerHTML = `<span>${texto}</span><span class="dir-hint">Ver detalle ▸</span>`;
      banner.style.display = 'flex';
    }

    const filas = pendientes
      .slice()
      .sort((a, b) => {
        if (a.escalado !== b.escalado) return a.escalado ? -1 : 1;
        return (b.horas_pendiente || 0) - (a.horas_pendiente || 0);
      })
      .map((d) => `
        <tr>
          <td>${escaparHtml(d.area)}</td>
          <td>${escaparHtml(d.responsable_nombre)}</td>
          <td>${escaparHtml(d.texto)}</td>
          <td>${horasTexto(d.horas_pendiente)}</td>
          <td><span class="dir-badge ${d.escalado ? 'escalada' : 'pendiente'}">${d.escalado ? 'Escalada' : 'Pendiente'}</span></td>
        </tr>`)
      .join('') || '<tr><td colspan="5" style="text-align:center;color:#888">Sin directrices pendientes 🎉</td></tr>';
    document.getElementById('tabla-directrices-modal').innerHTML = filas;
    ultimosPendientes = pendientes;
    actualizarToastPorVista();

    const kpiNum = document.getElementById('kpi-directrices');
    const kpiSub = document.getElementById('kpi-dir-sub');
    if (kpiNum) {
      kpiNum.textContent = pendientes.length;
      if (kpiCard) kpiCard.classList.toggle('rojo', escaladas.length > 0);
      if (kpiSub) {
        if (escaladas.length > 0) {
          kpiSub.innerHTML = `<span class="sub-pen">${escaladas.length} escaladas</span>`;
        } else if (pendientes.length > 0) {
          kpiSub.innerHTML = `<span class="sub-ok">a tiempo</span>`;
        } else {
          kpiSub.innerHTML = `<span class="sub-ok">todo al día ✓</span>`;
        }
      }
    }
  }

  async function actualizar() {
    try {
      const res = await fetch(URL_ESTADO + '?t=' + Date.now(), { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      render(data);
    } catch (e) {
      console.warn('directrices-banner: no se pudo leer el estado', e);
    }
  }

  // Qué área mostrar en el aviso emergente según la pantalla actual. En
  // index.html depende de si está activa la vista Agenda (Bodega) — la vista
  // Dashboard no tiene aviso propio, se queda con el banner/KPI genéricos.
  // wcp.html es una pantalla informativa/cultura, sin aviso de directrices.
  const AREA_TOAST_POR_PAGINA = {
    'taller.html': ['Producción'],
    'calidad-sp.html': ['Calidad'],
  };

  function areasParaToast() {
    if (pagina === 'index.html' || pagina === '') {
      const vistaAgenda = document.getElementById('vista-agenda');
      return (vistaAgenda && vistaAgenda.style.display === 'flex') ? ['Bodega'] : null;
    }
    return AREA_TOAST_POR_PAGINA[pagina] || null;
  }

  function actualizarToastPorVista() {
    const areas = areasParaToast();
    const relevantes = areas ? ultimosPendientes.filter((d) => areas.includes(d.area)) : [];

    if (relevantes.length === 0) {
      toast.classList.remove('visible');
      return;
    }

    const lista = relevantes.slice(0, 4);
    const extra = relevantes.length - lista.length;
    toast.innerHTML = `
      <div class="toast-header">🔔 ${relevantes.length} directriz${relevantes.length > 1 ? 'es' : ''} pendiente${relevantes.length > 1 ? 's' : ''} — ${areas.join('/')}</div>
      <ul>
        ${lista.map((d) => `
          <li><strong>${escaparHtml(d.area)}</strong> — ${escaparHtml(d.texto)}
            <span class="toast-tiempo">(${horasTexto(d.horas_pendiente)})</span></li>`).join('')}
        ${extra > 0 ? `<li class="toast-extra">y ${extra} más...</li>` : ''}
      </ul>`;
    toast.classList.add('visible');
  }

  actualizar();
  setInterval(actualizar, 60000);

  // Sin click para cerrarlo y sin duración fija: se muestra mientras esa
  // pantalla/vista siga activa y haya algo pendiente para su área; se oculta
  // solo si cambia la vista (dashboard↔agenda) o ya no hay nada pendiente.
  actualizarToastPorVista();
  setInterval(actualizarToastPorVista, 2000);
})();
