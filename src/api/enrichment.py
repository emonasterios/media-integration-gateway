"""Endpoints para enriquecimiento automático del catálogo con UI web."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from src.models.catalog import MediaType
from src.services.enrichment import CatalogEnricher

router = APIRouter(tags=["enrichment"])

logger = logging.getLogger(__name__)

# Global enricher instance (wired in main.py)
_enricher = CatalogEnricher()


def get_enricher() -> CatalogEnricher:
    return _enricher


@router.post("/api/enrich/start")
async def start_enrichment(
    provider: Optional[str] = Query(None, description="Proveedor específico"),
    media_type: Optional[str] = Query("movie", description="movie, series, o all"),
    concurrency: int = Query(3, ge=1, le=10),
    delay: float = Query(0.5, ge=0.1, le=5.0),
    force: bool = Query(False),
):
    """Inicia el proceso de enriquecimiento del catálogo."""
    enricher = get_enricher()
    mt = None if media_type == "all" else MediaType(media_type)
    
    # Normalizar provider: None o "" = todos
    if not provider:
        provider = None
    
    result = await enricher.run(
        provider=provider,
        media_type=mt,
        concurrency=concurrency,
        delay=delay,
        force=force,
    )
    return result


@router.get("/api/enrich/status")
async def enrichment_status():
    """Obtiene el estado actual del enriquecimiento."""
    enricher = get_enricher()
    stats = enricher.stats
    if stats is None:
        return {"running": False, "message": "No hay proceso activo"}
    return stats


@router.get("/enrich", response_class=HTMLResponse)
async def enrichment_ui():
    """Interfaz web para monitorear y controlar el enriquecimiento."""
    return HTMLResponse(content=_UI_HTML)


_UI_HTML = """\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Enriquecimiento del Catálogo</title>
<style>
  :root { --bg: #0f1117; --card: #1a1d27; --accent: #6c5ce7; --ok: #00b894; --warn: #fdcb6e; --err: #e17055; --text: #dfe6e9; --muted: #636e72; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
  h1 { font-size: 1.5rem; margin-bottom: 20px; color: var(--accent); }
  .card { background: var(--card); border-radius: 12px; padding: 20px; margin-bottom: 16px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
  .stat { text-align: center; padding: 12px; background: rgba(255,255,255,0.03); border-radius: 8px; }
  .stat .value { font-size: 1.8rem; font-weight: 700; }
  .stat .label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; margin-top: 4px; }
  .stat.total .value { color: var(--accent); }
  .stat.enriched .value { color: var(--ok); }
  .stat.failed .value { color: var(--err); }
  .stat.skipped .value { color: var(--warn); }
  .progress-bar { height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; margin: 16px 0; overflow: hidden; }
  .progress-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--ok)); border-radius: 4px; transition: width 0.5s ease; }
  .controls { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
  select, input, button { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15); color: var(--text); padding: 8px 14px; border-radius: 6px; font-size: 0.9rem; }
  button { background: var(--accent); border: none; cursor: pointer; font-weight: 600; }
  button:hover { opacity: 0.9; }
  button:disabled { opacity: 0.4; cursor: not-allowed; }
  .errors { max-height: 200px; overflow-y: auto; font-size: 0.8rem; color: var(--err); }
  .errors div { padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
  .current { color: var(--warn); font-style: italic; margin: 8px 0; }
  .eta { color: var(--muted); font-size: 0.85rem; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
  .badge.running { background: var(--accent); }
  .badge.idle { background: var(--muted); }
  .badge.done { background: var(--ok); }
</style>
</head>
<body>
<h1>🎬 Enriquecimiento del Catálogo</h1>

<div class="card">
  <div class="controls">
    <select id="provider">
      <option value="">Todos los proveedores</option>
      <option value="cuevana3">Cuevana3</option>
      <option value="cuevan_net">CuevanNet</option>
    </select>
    <select id="mediaType">
      <option value="movie">Películas</option>
      <option value="series">Series</option>
      <option value="all">Todos</option>
    </select>
    <label>Concurrencia: <input type="number" id="concurrency" value="3" min="1" max="10" style="width:60px"></label>
    <label>Delay(s): <input type="number" id="delay" value="0.5" min="0.1" max="5" step="0.1" style="width:60px"></label>
    <label><input type="checkbox" id="force"> Forzar re-enriquecimiento</label>
    <button id="startBtn" onclick="startEnrich()">▶ Iniciar</button>
  </div>
</div>

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <span id="statusBadge" class="badge idle">Inactivo</span>
    <span class="eta" id="etaText"></span>
  </div>
  <div class="progress-bar"><div class="progress-fill" id="progressFill" style="width:0%"></div></div>
  <div class="stats">
    <div class="stat total"><div class="value" id="statTotal">0</div><div class="label">Total</div></div>
    <div class="stat"><div class="value" id="statProcessed">0</div><div class="label">Procesados</div></div>
    <div class="stat enriched"><div class="value" id="statEnriched">0</div><div class="label">Enriquecidos</div></div>
    <div class="stat skipped"><div class="value" id="statSkipped">0</div><div class="label">Saltados</div></div>
    <div class="stat failed"><div class="value" id="statFailed">0</div><div class="label">Fallos</div></div>
  </div>
  <div class="current" id="currentItem"></div>
</div>

<div class="card" id="errorsCard" style="display:none">
  <h3 style="margin-bottom:8px;color:var(--err)">Errores recientes</h3>
  <div class="errors" id="errorsList"></div>
</div>

<script>
let polling = false;

async function startEnrich() {
  const params = new URLSearchParams({
    provider: document.getElementById('provider').value,
    media_type: document.getElementById('mediaType').value,
    concurrency: document.getElementById('concurrency').value,
    delay: document.getElementById('delay').value,
    force: document.getElementById('force').checked,
  });
  document.getElementById('startBtn').disabled = true;
  const res = await fetch('/api/enrich/start?' + params, { method: 'POST' });
  const data = await res.json();
  if (data.error) { alert(data.error); document.getElementById('startBtn').disabled = false; return; }
  polling = true;
  pollStatus();
}

async function pollStatus() {
  const res = await fetch('/api/enrich/status');
  const s = await res.json();
  if (!s.running && !s.total) {
    document.getElementById('statusBadge').className = 'badge idle';
    document.getElementById('statusBadge').textContent = 'Inactivo';
    document.getElementById('startBtn').disabled = false;
    polling = false;
    return;
  }
  document.getElementById('statTotal').textContent = s.total || 0;
  document.getElementById('statProcessed').textContent = s.processed || 0;
  document.getElementById('statEnriched').textContent = s.enriched || 0;
  document.getElementById('statSkipped').textContent = s.skipped || 0;
  document.getElementById('statFailed').textContent = s.failed || 0;
  document.getElementById('progressFill').style.width = (s.progress_pct || 0) + '%';
  document.getElementById('currentItem').textContent = s.current_item ? 'Procesando: ' + s.current_item : '';
  document.getElementById('etaText').textContent = s.eta_s ? 'ETA: ' + Math.round(s.eta_s) + 's' : '';

  if (s.running) {
    document.getElementById('statusBadge').className = 'badge running';
    document.getElementById('statusBadge').textContent = 'En curso';
  } else {
    document.getElementById('statusBadge').className = 'badge done';
    document.getElementById('statusBadge').textContent = 'Completado';
    document.getElementById('startBtn').disabled = false;
    polling = false;
  }

  if (s.errors && s.errors.length) {
    document.getElementById('errorsCard').style.display = 'block';
    document.getElementById('errorsList').innerHTML = s.errors.map(e => '<div>' + e + '</div>').join('');
  }

  if (polling) setTimeout(pollStatus, 2000);
}

// Poll on load if something is running
pollStatus();
</script>
</body>
</html>
"""
