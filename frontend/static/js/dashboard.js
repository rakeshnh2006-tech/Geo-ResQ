/**
 * GeoResQ — dashboard.js
 * Coordinator Dashboard: Google Maps layers + API polling + actions.
 */

const POLL_INTERVAL_MS = 60_000;
let map, infoWindow;
const incidentMarkers  = [];
const roadPolylines    = [];
const villageMarkers   = [];
const liveLocMarkers   = [];   // user-submitted GPS pins (blue)

// Cache of all incidents loaded (used by gallery + modal)
let _incidents = [];

// ── Map initialisation (called by Google Maps callback) ──────────────────
function initMap() {
  map = new google.maps.Map(document.getElementById('map'), {
    center: { lat: 13.75, lng: 75.5 },   // Malenadu centroid
    zoom: 9,
    mapTypeId: 'terrain',
  });
  infoWindow = new google.maps.InfoWindow();
  loadAll();
}

// ── Severity → marker colour ─────────────────────────────────────────────
function severityColour(sev) {
  return ['#16a34a','#65a30d','#ca8a04','#ea580c','#dc2626'][Math.min((sev||1)-1,4)];
}

// ── Clear existing map objects ────────────────────────────────────────────
function clearMap() {
  incidentMarkers.forEach(m => m.setMap(null));  incidentMarkers.length = 0;
  roadPolylines.forEach(p => p.setMap(null));    roadPolylines.length = 0;
  villageMarkers.forEach(m => m.setMap(null));   villageMarkers.length = 0;
  liveLocMarkers.forEach(m => m.setMap(null));   liveLocMarkers.length = 0;
}

// ── Load everything ───────────────────────────────────────────────────────
async function loadAll() {
  await Promise.all([loadIncidents(), loadRoads(), loadAccessibility(), loadLiveLocations()]);
  refreshStats();
}

// ── Incidents ─────────────────────────────────────────────────────────────
async function loadIncidents() {
  const res = await fetch('/api/incidents');
  if (!res.ok) return;
  const { incidents } = await res.json();
  _incidents = incidents;
  renderIncidentList(incidents);
  renderIncidentMarkers(incidents);
  loadImagesGallery(incidents);
}

function renderIncidentMarkers(incidents) {
  incidents.forEach(inc => {
    if (!inc.lat || !inc.lng) return;
    const marker = new google.maps.Marker({
      position: { lat: inc.lat, lng: inc.lng },
      map,
      title: inc.location_name || 'Incident',
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 8 + (inc.severity || 1),
        fillColor: severityColour(inc.severity),
        fillOpacity: 0.9,
        strokeColor: '#fff',
        strokeWeight: 1.5,
      },
    });
    marker.addListener('click', () => openIncidentModal(inc));
    incidentMarkers.push(marker);
  });
}

function renderIncidentList(incidents) {
  const container = document.getElementById('incident-list');
  if (!container) return;
  if (!incidents.length) {
    container.innerHTML = '<div class="empty-state">No incidents yet.</div>';
    return;
  }
  container.innerHTML = incidents.map(inc => `
    <div class="panel-item" data-id="${inc.id}" id="incident-card-${inc.id}"
         style="cursor:pointer" onclick="openIncidentModal(${JSON.stringify(inc).replace(/"/g,'&quot;')})">
      <div class="panel-item-title">
        <span class="severity-dot sev-${inc.severity || 1}"></span>
        ${inc.location_name || '<em style="opacity:.6">Extracting location…</em>'}
        <span class="badge badge-${inc.status}">${inc.status}</span>
      </div>
      ${inc.raw_text ? `
      <div class="panel-item-meta" style="font-style:italic;color:var(--text-secondary);
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%">
        "${inc.raw_text.slice(0,90)}${inc.raw_text.length > 90 ? '…' : ''}"
      </div>` : ''}
      <div class="panel-item-meta">
        <span>${inc.incident_type || '—'}</span>
        <span>Sev ${inc.severity || '—'}</span>
        <span>${inc.affected_households ?? '—'} hh</span>
        ${inc.photo_count ? `<span>&#128247; ${inc.photo_count} photo${inc.photo_count > 1 ? 's' : ''}</span>` : ''}
        ${inc.lat ? `<span>&#128204; ${inc.lat.toFixed(4)}, ${inc.lng.toFixed(4)}</span>` : ''}
      </div>
      <div class="panel-item-actions" onclick="event.stopPropagation()">
        <button class="btn btn-sm btn-secondary" onclick="verifyIncident(${inc.id})">Verify</button>
        <button class="btn btn-sm btn-danger"    onclick="rejectIncident(${inc.id})">Reject</button>
        <button class="btn btn-sm btn-secondary" onclick="openIncidentModal(${JSON.stringify(inc).replace(/"/g,'&quot;')})">&#128247; Detail</button>
      </div>
    </div>`).join('');
}

// ── Images gallery tab ────────────────────────────────────────────────────
async function loadImagesGallery(incidents) {
  const gallery = document.getElementById('images-gallery');
  if (!gallery) return;

  // Fetch photos for all incidents that have them
  const withPhotos = incidents.filter(i => i.photo_count > 0);
  if (!withPhotos.length) {
    gallery.innerHTML = '<div class="empty-state" style="grid-column:1/-1">No photos submitted yet.</div>';
    return;
  }

  gallery.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><span class="spinner"></span></div>';

  const allPhotos = [];
  await Promise.all(withPhotos.map(async inc => {
    const r = await fetch(`/api/incidents/${inc.id}/photos`);
    if (!r.ok) return;
    const { photos } = await r.json();
    photos.forEach(p => allPhotos.push({ ...p, incident: inc }));
  }));

  if (!allPhotos.length) {
    gallery.innerHTML = '<div class="empty-state" style="grid-column:1/-1">No photos found.</div>';
    return;
  }

  gallery.innerHTML = allPhotos.map(p => `
    <div class="gallery-item" onclick="openIncidentModal(${JSON.stringify(p.incident).replace(/"/g,'&quot;')})">
      <img src="${p.url}" alt="Photo for incident #${p.incident.id}" loading="lazy">
      <div class="gallery-label">
        #${p.incident.id} ${p.incident.location_name || ''}
      </div>
    </div>`).join('');
}

// ── Incident detail modal ─────────────────────────────────────────────────
async function openIncidentModal(inc) {
  if (typeof inc === 'string') { try { inc = JSON.parse(inc); } catch(_) { return; } }

  // Set header
  document.getElementById('modal-title').textContent =
    `Incident #${inc.id} — ${inc.location_name || 'Unknown Location'}`;

  // Raw text quote
  const rawEl = document.getElementById('modal-raw-text');
  rawEl.textContent = inc.raw_text || '—';

  // Meta grid
  const metaEl = document.getElementById('modal-meta');
  const statusColour = { verified:'#16a34a', pending:'#ca8a04', incomplete:'#dc2626',
                         duplicate:'#6b7280', rejected:'#9f1239' };
  metaEl.innerHTML = `
    <dt>Type</dt>       <dd>${(inc.incident_type||'—').replace('_',' ')}</dd>
    <dt>Severity</dt>   <dd>${inc.severity ? '⬛'.repeat(inc.severity) + ' ' + inc.severity + '/5' : '—'}</dd>
    <dt>Status</dt>     <dd style="color:${statusColour[inc.status]||'inherit'}">${inc.status}</dd>
    <dt>Households</dt> <dd>${inc.affected_households ?? '—'}</dd>
    <dt>Reported</dt>   <dd>${inc.created_at ? inc.created_at.slice(0,19).replace('T',' ') : '—'}</dd>
    <dt>Photos</dt>     <dd>${inc.photo_count || 0}</dd>`;

  // Location
  const locEl = document.getElementById('modal-location');
  if (inc.lat && inc.lng) {
    locEl.innerHTML = `${inc.location_name || 'GPS coordinates'} &nbsp;
      <a href="https://maps.google.com/?q=${inc.lat},${inc.lng}" target="_blank"
         style="color:var(--accent,#f97316);font-size:.8rem">
        ${inc.lat.toFixed(5)}, ${inc.lng.toFixed(5)} ↗
      </a>`;
  } else {
    locEl.textContent = inc.location_name || 'No location data';
  }

  // Actions
  const actionsEl = document.getElementById('modal-actions');
  actionsEl.innerHTML = `
    <button class="btn btn-secondary btn-sm" onclick="verifyIncident(${inc.id});closeModalDirect()">Verify</button>
    <button class="btn btn-danger btn-sm"    onclick="rejectIncident(${inc.id});closeModalDirect()">Reject</button>
    ${inc.lat ? `<a class="btn btn-secondary btn-sm"
      href="https://maps.google.com/?q=${inc.lat},${inc.lng}" target="_blank">
      &#128204; View on Maps</a>` : ''}`;

  // Photos — load fresh
  const photosEl = document.getElementById('modal-photos');
  photosEl.innerHTML = '<p class="photo-empty">Loading…</p>';

  document.getElementById('incident-modal').classList.add('open');
  document.body.style.overflow = 'hidden';

  // Async load photos
  if (inc.photo_count > 0) {
    const r = await fetch(`/api/incidents/${inc.id}/photos`);
    if (r.ok) {
      const { photos } = await r.json();
      if (photos.length) {
        photosEl.innerHTML = photos.map(p => `
          <a href="${p.url}" target="_blank">
            <img src="${p.url}" alt="Evidence photo" loading="lazy">
          </a>`).join('');
      } else {
        photosEl.innerHTML = '<p class="photo-empty">No photos stored.</p>';
      }
    } else {
      photosEl.innerHTML = '<p class="photo-empty">Could not load photos.</p>';
    }
  } else {
    photosEl.innerHTML = '<p class="photo-empty">No photos submitted with this incident.</p>';
  }
}

function closeModal(event) {
  // Only close when clicking the backdrop (not the modal box itself)
  if (event.target === document.getElementById('incident-modal')) closeModalDirect();
}

function closeModalDirect() {
  document.getElementById('incident-modal').classList.remove('open');
  document.body.style.overflow = '';
}

// Close on Escape key
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModalDirect(); });

// ── Roads ─────────────────────────────────────────────────────────────────
async function loadRoads() {
  const res = await fetch('/api/roads');
  if (!res.ok) return;
  const { roads } = await res.json();
  renderRoadList(roads);
  renderRoadPolylines(roads);
}

function renderRoadPolylines(roads) {
  roads.forEach(road => {
    if (!road.start || !road.end) return;
    const poly = new google.maps.Polyline({
      path: [
        { lat: road.start.lat, lng: road.start.lng },
        { lat: road.end.lat,   lng: road.end.lng   },
      ],
      map,
      strokeColor: road.blocked ? '#dc2626' : '#6b7280',
      strokeWeight: road.blocked ? 4 : 2,
      strokeOpacity: road.blocked ? 1.0 : 0.5,
    });
    poly.addListener('click', () => {
      infoWindow.setContent(
        `<b>${road.name || 'Road ' + road.id}</b><br>
         Type: ${road.highway_type || '—'}<br>
         Status: ${road.blocked ? '<b style="color:#dc2626">BLOCKED</b>' : 'Open'}<br>
         <button onclick="toggleRoad(${road.id}, ${road.blocked})">
           ${road.blocked ? 'Unblock' : 'Block'}
         </button>`
      );
      infoWindow.open(map, poly);
    });
    roadPolylines.push(poly);
  });
}

function renderRoadList(roads) {
  const container = document.getElementById('road-list');
  if (!container) return;
  const blocked = roads.filter(r => r.blocked);
  if (!blocked.length) {
    container.innerHTML = '<div class="empty-state">No blocked roads.</div>';
    return;
  }
  container.innerHTML = blocked.map(r => `
    <div class="panel-item">
      <div class="panel-item-title">
        ${r.name || 'Road #' + r.id}
        <span class="badge badge-incomplete">BLOCKED</span>
      </div>
      <div class="panel-item-meta"><span>${r.highway_type || '—'}</span></div>
      <div class="panel-item-actions">
        <button class="btn btn-sm btn-secondary" onclick="toggleRoad(${r.id}, true)">Unblock</button>
      </div>
    </div>`).join('');
}

// ── Accessibility ─────────────────────────────────────────────────────────
async function loadAccessibility() {
  const res = await fetch('/api/accessibility');
  if (!res.ok) return;
  const { isolated_villages } = await res.json();
  renderAccessibilityList(isolated_villages);
  renderVillageMarkers(isolated_villages);
}

function renderVillageMarkers(villages) {
  villages.forEach(v => {
    if (!v.lat || !v.lng) return;
    const marker = new google.maps.Marker({
      position: { lat: v.lat, lng: v.lng },
      map,
      title: v.village_name || 'Isolated village',
      icon: {
        path: google.maps.SymbolPath.BACKWARD_CLOSED_ARROW,
        scale: 7,
        fillColor: '#f97316',
        fillOpacity: 1,
        strokeColor: '#fff',
        strokeWeight: 1.5,
      },
    });
    marker.addListener('click', () => {
      infoWindow.setContent(
        `<b>${v.village_name || 'Village #' + v.village_id}</b><br>
         <span style="color:#ea580c;font-weight:600">⚠ ISOLATED</span>`
      );
      infoWindow.open(map, marker);
    });
    villageMarkers.push(marker);
  });
}

function renderAccessibilityList(villages) {
  const container = document.getElementById('accessibility-list');
  if (!container) return;
  setChip('stat-isolated', villages.length);
  if (!villages.length) {
    container.innerHTML = '<div class="empty-state">All villages accessible.</div>';
    return;
  }
  container.innerHTML = villages.map(v => `
    <div class="panel-item">
      <div class="panel-item-title">
        ${v.village_name || 'Village #' + v.village_id}
        <span class="badge badge-incomplete">ISOLATED</span>
      </div>
    </div>`).join('');
}

// ── Live Locations (user-submitted GPS) ───────────────────────────────────
async function loadLiveLocations() {
  if (!map) return;
  const res = await fetch('/api/locations');
  if (!res.ok) return;
  const { locations } = await res.json();
  locations.forEach(loc => {
    if (!loc.lat || !loc.lng) return;
    const marker = new google.maps.Marker({
      position: { lat: loc.lat, lng: loc.lng },
      map,
      title: `Live: ${loc.location_name || 'User location'}`,
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 7,
        fillColor: '#3B82F6',
        fillOpacity: 0.9,
        strokeColor: '#fff',
        strokeWeight: 2,
      },
      zIndex: 5,
    });
    marker.addListener('click', () => {
      // Find the full incident from cache and open modal
      const inc = _incidents.find(i => i.id === loc.id);
      if (inc) { openIncidentModal(inc); return; }
      infoWindow.setContent(
        `<b>&#128204; User-reported location</b><br>
         ${loc.location_name || 'Unknown'}<br>
         Type: ${loc.incident_type || '—'} | Sev: ${loc.severity || '—'}<br>
         <span style="color:#3B82F6;font-size:0.8rem">
           ${loc.lat.toFixed(5)}, ${loc.lng.toFixed(5)}
         </span>`
      );
      infoWindow.open(map, marker);
    });
    liveLocMarkers.push(marker);
  });
}

// ── Relief + Prioritization ───────────────────────────────────────────────
async function loadPrioritization() {
  const res = await fetch('/api/prioritization');
  if (!res.ok) return;
  const { prioritization } = await res.json();
  const container = document.getElementById('priority-list');
  if (!container) return;
  if (!prioritization.length) {
    container.innerHTML = '<div class="empty-state">No scored relief requests yet.</div>';
    return;
  }
  container.innerHTML = prioritization.map((p, i) => {
    const rr = p.relief_request || {};
    const locationStr = rr.incident_location || rr.location_name || '—';
    const latLng = (rr.incident_lat && rr.incident_lng)
      ? `<span>&#128204; ${parseFloat(rr.incident_lat).toFixed(4)}, ${parseFloat(rr.incident_lng).toFixed(4)}</span>`
      : '';
    return `
    <div class="panel-item">
      <div class="panel-item-title">
        <span class="badge badge-orange">#${i+1}</span>
        ${(rr.need_category||'—').replace('_',' ')}
        <span class="text-muted text-xs">${p.composite_score?.toFixed(3)}</span>
      </div>
      <div class="panel-item-meta">
        <span>&#128205; ${locationStr}</span>
        ${latLng}
        ${rr.incident_id ? `<span>Incident #${rr.incident_id}</span>` : ''}
      </div>
      ${p.rationale ? `<div class="panel-item-meta" style="font-style:italic">${p.rationale.slice(0,100)}…</div>` : ''}
    </div>`;
  }).join('');
}

// ── Briefings ─────────────────────────────────────────────────────────────
async function loadBriefings() {
  const res = await fetch('/api/briefings');
  if (!res.ok) return;
  const { briefings } = await res.json();
  const container = document.getElementById('briefing-list');
  if (!container) return;
  if (!briefings.length) {
    container.innerHTML = '<div class="empty-state">No briefings yet.</div>';
    return;
  }
  container.innerHTML = briefings.map(b => `
    <div class="panel-item">
      <div class="panel-item-title">${b.created_at?.slice(0,19).replace('T',' ')}</div>
      <div class="panel-item-meta"><span>By: ${b.generated_by || 'System'}</span></div>
      ${b.pdf_path
        ? `<div class="panel-item-actions">
             <a class="btn btn-sm btn-secondary" href="/api/briefings/${b.id}/pdf">Download PDF</a>
           </div>`
        : ''}
    </div>`).join('');
}

// ── Actions ───────────────────────────────────────────────────────────────
async function verifyIncident(id) {
  await fetch(`/api/incidents/${id}/verify`, { method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' } });
  loadIncidents();
}

async function rejectIncident(id) {
  if (!confirm('Reject this incident?')) return;
  await fetch(`/api/incidents/${id}/reject`, { method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' } });
  loadIncidents();
}

async function toggleRoad(id, currentlyBlocked) {
  const action = currentlyBlocked ? 'unblock' : 'block';
  await fetch(`/api/roads/${id}/${action}`, { method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() } });
  clearMap();
  loadAll();
}

async function runPrioritization() {
  const btn = document.getElementById('btn-run-prio');
  if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }
  await fetch('/api/prioritization/run', { method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() } });
  await loadPrioritization();
  if (btn) { btn.disabled = false; btn.textContent = 'Re-score'; }
}

async function generateBriefing() {
  const btn = document.getElementById('btn-briefing');
  if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
  await fetch('/api/briefings', { method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() } });
  await loadBriefings();
  if (btn) { btn.disabled = false; btn.textContent = 'Generate'; }
}

// ── Stats summary ─────────────────────────────────────────────────────────
function refreshStats() {
  if (!_incidents.length) return;
  setChip('stat-total',     _incidents.length);
  setChip('stat-verified',  _incidents.filter(i => i.status === 'verified').length);
  setChip('stat-pending',   _incidents.filter(i => i.status === 'pending').length);
  setChip('stat-incomplete',_incidents.filter(i => i.status === 'incomplete').length);
}
function setChip(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── Auto-poll ─────────────────────────────────────────────────────────────
setInterval(() => { clearMap(); loadAll(); }, POLL_INTERVAL_MS);
