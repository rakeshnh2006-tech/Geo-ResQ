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
const _incidentMap = new Map();   // id → incident object — safe lookup from onclick

// ── Teardrop SVG Pin Path for Incidents ───────────────────────────────────
const PIN_SVG_PATH = 'M 12 0 C 5.37 0 0 5.37 0 12 c 0 9 12 24 12 24 s 12 -15 12 -24 C 24 5.37 18.63 0 12 0 Z';

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

// ── Auto-fit map to encompass all markers ─────────────────────────────────
function fitMapToMarkers() {
  if (!map) return;
  const bounds = new google.maps.LatLngBounds();
  let count = 0;
  incidentMarkers.forEach(m => {
    if (m.getPosition()) { bounds.extend(m.getPosition()); count++; }
  });
  villageMarkers.forEach(m => {
    if (m.getPosition()) { bounds.extend(m.getPosition()); count++; }
  });
  if (count > 0) {
    map.fitBounds(bounds, { top: 60, bottom: 60, left: 60, right: 60 });
    google.maps.event.addListenerOnce(map, 'idle', () => {
      if (map.getZoom() > 14) map.setZoom(14);
    });
  }
}

// ── Focus map on specific incident ────────────────────────────────────────
function focusIncidentOnMap(id) {
  const inc = _incidentMap.get(id);
  if (!inc || !inc.lat || !inc.lng || !map) return;
  map.panTo({ lat: inc.lat, lng: inc.lng });
  map.setZoom(15);
  const marker = incidentMarkers.find(m => m.incidentId === id);
  if (marker) {
    google.maps.event.trigger(marker, 'click');
  }
}

// ── Load everything ───────────────────────────────────────────────────────
async function loadAll() {
  await Promise.all([loadIncidents(), loadRoads(), loadAccessibility(), loadLiveLocations()]);
  refreshStats();
  fitMapToMarkers();
}

// ── Incidents ─────────────────────────────────────────────────────────────
async function loadIncidents() {
  const res = await fetch('/api/incidents');
  if (!res.ok) return;
  const { incidents } = await res.json();
  _incidents = incidents;
  _incidentMap.clear();
  incidents.forEach(i => _incidentMap.set(i.id, i));
  renderIncidentList(incidents);
  renderIncidentMarkers(incidents);
  loadImagesGallery(incidents);
}

function renderIncidentMarkers(incidents) {
  incidents.forEach(inc => {
    if (!inc.lat || !inc.lng) return;
    const reporterName = inc.reporter_name || (inc.reporter ? inc.reporter.full_name : 'Anonymous Citizen');
    const typeName = (inc.incident_type || 'Incident').replace('_', ' ').toUpperCase();

    const marker = new google.maps.Marker({
      position: { lat: inc.lat, lng: inc.lng },
      map,
      title: `${typeName} #${inc.id} — ${inc.location_name || 'Location'} (Reporter: ${reporterName})`,
      icon: {
        path: PIN_SVG_PATH,
        fillColor: severityColour(inc.severity),
        fillOpacity: 1.0,
        strokeColor: '#FFFFFF',
        strokeWeight: 2,
        scale: 1.3,
        anchor: new google.maps.Point(12, 36),
        labelOrigin: new google.maps.Point(12, 12),
      },
      label: {
        text: `${inc.severity || '!'}`,
        color: '#FFFFFF',
        fontSize: '11px',
        fontWeight: '700',
      },
      zIndex: 10 + (inc.severity || 1),
    });

    marker.incidentId = inc.id;

    marker.addListener('click', () => {
      infoWindow.setContent(`
        <div style="font-family:inherit;min-width:240px;max-width:300px;padding:4px 2px">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:6px">
            <span style="font-weight:700;font-size:0.95rem;color:${severityColour(inc.severity)}">
              🚨 ${typeName} #${inc.id}
            </span>
            <span class="badge badge-${inc.status}">${inc.status}</span>
          </div>
          <div style="font-size:0.85rem;font-weight:600;margin-bottom:4px;color:#111827">
            📍 ${inc.location_name || 'Location'}
            <span style="font-size:0.75rem;font-weight:normal;color:#6b7280">(${inc.lat.toFixed(4)}, ${inc.lng.toFixed(4)})</span>
          </div>
          <div style="font-size:0.82rem;color:#374151;margin-bottom:4px">
            👤 <b>Reporter:</b> ${_esc(reporterName)}
          </div>
          <div style="font-size:0.78rem;color:#6b7280;margin-bottom:6px">
            ⏱️ ${inc.created_at ? inc.created_at.slice(0, 19).replace('T', ' ') : '—'} &bull; Severity: ${inc.severity || 1}/5
          </div>
          ${inc.raw_text ? `
            <div style="font-size:0.8rem;background:#f9fafb;border-left:3px solid ${severityColour(inc.severity)};padding:6px 8px;border-radius:4px;margin-bottom:8px;color:#374151">
              &ldquo;${_esc(inc.raw_text.slice(0, 110))}${inc.raw_text.length > 110 ? '…' : ''}&rdquo;
            </div>` : ''}
          <div style="display:flex;gap:6px;margin-top:6px">
            <button class="btn btn-sm btn-primary" style="padding:4px 8px;font-size:0.75rem" onclick="openIncidentById(${inc.id})">Full Details</button>
            ${inc.status === 'pending' ? `<button class="btn btn-sm btn-secondary" style="padding:4px 8px;font-size:0.75rem" onclick="verifyIncident(${inc.id})">Verify</button>` : ''}
          </div>
        </div>
      `);
      infoWindow.open(map, marker);
    });

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
         style="cursor:pointer" onclick="openIncidentById(${inc.id})">
      <div class="panel-item-title">
        <span class="severity-dot sev-${inc.severity || 1}"></span>
        ${_esc(inc.location_name) || '<em style="opacity:.6">Extracting location…</em>'}
        <span class="badge badge-${inc.status}">${inc.status}</span>
      </div>
      ${inc.raw_text ? `
      <div class="panel-item-meta" style="font-style:italic;color:var(--text-secondary);
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%">
        &ldquo;${_esc(inc.raw_text.slice(0,90))}${inc.raw_text.length > 90 ? '…' : ''}&rdquo;
      </div>` : ''}
      <div class="panel-item-meta">
        <span>👤 ${_esc(inc.reporter_name || 'Anonymous')}</span>
        <span>${inc.incident_type || '—'}</span>
        <span>Sev ${inc.severity || '—'}</span>
        ${inc.photo_count ? `<span>&#128247; ${inc.photo_count} photo${inc.photo_count > 1 ? 's' : ''}</span>` : ''}
        ${inc.lat ? `<span style="color:var(--accent,#f97316);font-weight:600">&#128204; ${inc.lat.toFixed(4)}, ${inc.lng.toFixed(4)}</span>` : ''}
      </div>
      <div class="panel-item-actions" onclick="event.stopPropagation()">
        ${inc.lat ? `<button class="btn btn-sm btn-secondary" onclick="focusIncidentOnMap(${inc.id})">&#128204; Map</button>` : ''}
        <button class="btn btn-sm btn-secondary" onclick="verifyIncident(${inc.id})">Verify</button>
        <button class="btn btn-sm btn-danger"    onclick="rejectIncident(${inc.id})">Reject</button>
        <button class="btn btn-sm btn-secondary" onclick="openIncidentById(${inc.id})">&#128247; Detail</button>
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
    <div class="gallery-item" onclick="openIncidentById(${p.incident.id})">
      <img src="${p.url}" alt="Photo for incident #${p.incident.id}" loading="lazy">
      <div class="gallery-label">
        #${p.incident.id} ${_esc(p.incident.location_name) || ''}
      </div>
    </div>`).join('');
}

// ── HTML escape helper (prevents XSS and broken onclick attrs) ────────────
function _esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Open modal by ID (safe — avoids inline JSON in onclick) ───────────────
function openIncidentById(id) {
  const inc = _incidentMap.get(id);
  if (inc) openIncidentModal(inc);
}

// ── Incident detail modal ─────────────────────────────────────────────────
async function openIncidentModal(inc) {

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
  const reporterName = inc.reporter_name || (inc.reporter ? inc.reporter.full_name : 'Anonymous Citizen');
  metaEl.innerHTML = `
    <dt>Reporter</dt>   <dd>${_esc(reporterName)}</dd>
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
    ${inc.lat ? `<button class="btn btn-primary btn-sm" onclick="focusIncidentOnMap(${inc.id});closeModalDirect()">📍 Focus on Map</button>` : ''}
    <button class="btn btn-secondary btn-sm" onclick="verifyIncident(${inc.id});closeModalDirect()">Verify</button>
    <button class="btn btn-danger btn-sm"    onclick="rejectIncident(${inc.id});closeModalDirect()">Reject</button>
    ${inc.lat ? `<a class="btn btn-secondary btn-sm"
      href="https://maps.google.com/?q=${inc.lat},${inc.lng}" target="_blank">
      &#128204; Google Maps ↗</a>` : ''}`;

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
let _roadsCache = [];

async function loadRoads() {
  const res = await fetch('/api/roads');
  if (!res.ok) return;
  const { roads } = await res.json();
  _roadsCache = roads;
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
      strokeColor: road.blocked ? '#dc2626' : '#2563eb',
      strokeWeight: road.blocked ? 6 : 3,
      strokeOpacity: road.blocked ? 1.0 : 0.65,
    });
    poly.roadId = road.id;

    poly.addListener('click', () => {
      infoWindow.setContent(
        `<div style="font-family:inherit;min-width:220px;padding:4px">
           <div style="font-weight:700;font-size:0.95rem;margin-bottom:4px;color:#1e3a8a">
             ${_esc(road.name || 'Road #' + road.id)}
           </div>
           <div style="font-size:0.85rem;color:#4b5563;margin-bottom:4px">
             Type: <b>${road.highway_type || 'primary'}</b>
           </div>
           <div style="font-size:0.85rem;margin-bottom:8px">
             Status: ${road.blocked ? '<b style="color:#dc2626">⛔ BLOCKED</b>' : '<b style="color:#16a34a">✓ OPEN</b>'}
           </div>
           <button class="btn btn-sm ${road.blocked ? 'btn-secondary' : 'btn-danger'}"
                   onclick="toggleRoad(${road.id}, ${road.blocked})">
             ${road.blocked ? '✓ Unblock Road' : '⛔ Block Road'}
           </button>
         </div>`
      );
      infoWindow.open(map, poly);
    });
    roadPolylines.push(poly);
  });
}

function focusRoadOnMap(id) {
  const road = _roadsCache.find(r => r.id === id);
  if (!road || !road.start || !map) return;
  const midLat = (road.start.lat + road.end.lat) / 2;
  const midLng = (road.start.lng + road.end.lng) / 2;
  map.panTo({ lat: midLat, lng: midLng });
  map.setZoom(12);
  const poly = roadPolylines.find(p => p.roadId === id);
  if (poly) {
    google.maps.event.trigger(poly, 'click');
  }
}

function renderRoadList(roads) {
  // 1. Blocked roads section
  const container = document.getElementById('road-list');
  if (container) {
    const blocked = roads.filter(r => r.blocked);
    if (!blocked.length) {
      container.innerHTML = '<div class="empty-state" style="padding:10px 0;font-size:0.85rem">All road segments are currently open.</div>';
    } else {
      container.innerHTML = blocked.map(r => `
        <div class="panel-item" style="border-left:3px solid #dc2626">
          <div class="panel-item-title">
            ${_esc(r.name || 'Road #' + r.id)}
            <span class="badge badge-incomplete">BLOCKED</span>
          </div>
          <div class="panel-item-meta"><span>Type: ${r.highway_type || '—'}</span></div>
          <div class="panel-item-actions">
            <button class="btn btn-sm btn-secondary" onclick="toggleRoad(${r.id}, true)">✓ Unblock</button>
            <button class="btn btn-sm btn-secondary" onclick="focusRoadOnMap(${r.id})">&#128204; Map</button>
          </div>
        </div>`).join('');
    }
  }

  // 2. All road network segments (to manage/block any segment)
  const allContainer = document.getElementById('all-roads-list');
  if (allContainer) {
    allContainer.innerHTML = roads.map(r => `
      <div class="panel-item" style="padding:8px 10px">
        <div class="panel-item-title" style="font-size:0.85rem">
          <span>${_esc(r.name || 'Road #' + r.id)}</span>
          <span class="badge ${r.blocked ? 'badge-incomplete' : 'badge-verified'}" style="font-size:0.7rem">
            ${r.blocked ? 'BLOCKED' : 'OPEN'}
          </span>
        </div>
        <div class="panel-item-meta" style="font-size:0.75rem">
          <span>${r.highway_type || 'primary'}</span>
          <span>${r.length_m ? (r.length_m / 1000).toFixed(1) + ' km' : ''}</span>
        </div>
        <div class="panel-item-actions" style="margin-top:4px">
          <button class="btn btn-sm ${r.blocked ? 'btn-secondary' : 'btn-danger'}"
                  style="font-size:0.75rem;padding:3px 8px"
                  onclick="toggleRoad(${r.id}, ${r.blocked})">
            ${r.blocked ? '✓ Unblock' : '⛔ Block'}
          </button>
          <button class="btn btn-sm btn-secondary"
                  style="font-size:0.75rem;padding:3px 8px"
                  onclick="focusRoadOnMap(${r.id})">&#128204; Map</button>
        </div>
      </div>`).join('');
  }
}

async function runAccessibilityAnalysis() {
  const btn = document.getElementById('btn-re-analysis');
  if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }
  try {
    await fetch('/api/accessibility/run', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrfToken() }
    });
    clearMap();
    await loadAll();
  } catch (e) {
    console.error('Accessibility analysis failed:', e);
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Re-run Analysis'; }
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
        `<div style="font-family:inherit;min-width:200px;padding:4px">
           <b style="color:#ea580c;font-size:0.95rem">${_esc(v.village_name || 'Village #' + v.village_id)}</b><br>
           <span style="color:#ea580c;font-weight:600">⚠ CUT OFF / ISOLATED</span><br>
           <span style="font-size:0.8rem;color:#4b5563">Population: ${v.population || 'Unknown'}</span>
         </div>`
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
    container.innerHTML = '<div class="empty-state" style="padding:10px 0;font-size:0.85rem">All villages accessible.</div>';
    return;
  }
  container.innerHTML = villages.map(v => `
    <div class="panel-item" style="border-left:3px solid #ea580c">
      <div class="panel-item-title">
        ${_esc(v.village_name || 'Village #' + v.village_id)}
        <span class="badge badge-incomplete">ISOLATED</span>
      </div>
      <div class="panel-item-meta">
        <span>Pop: ${v.population || '—'}</span>
        ${v.lat ? `<button class="btn btn-sm btn-secondary" onclick="map.panTo({lat:${v.lat},lng:${v.lng}});map.setZoom(13)">&#128204; Map</button>` : ''}
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
    const locationStr = rr.location_name || rr.incident_location || 'Malenadu Region';
    const latLng = (rr.incident_lat && rr.incident_lng)
      ? `<span style="color:var(--accent,#f97316);font-weight:600">&#128204; ${parseFloat(rr.incident_lat).toFixed(4)}, ${parseFloat(rr.incident_lng).toFixed(4)}</span>`
      : '';
    const category = (rr.need_category || 'relief').replace('_', ' ').toUpperCase();
    return `
    <div class="panel-item" style="padding:10px 12px;margin-bottom:8px">
      <div class="panel-item-title" style="display:flex;align-items:center;justify-content:space-between">
        <div>
          <span class="badge badge-orange">#${i+1}</span>
          <b>${category}</b>
        </div>
        <span class="badge badge-secondary" style="font-weight:700">Score: ${p.composite_score?.toFixed(3)}</span>
      </div>
      ${rr.raw_text ? `
        <div class="panel-item-meta" style="font-style:italic;color:#374151;margin:4px 0;font-size:0.83rem">
          &ldquo;${_esc(rr.raw_text)}&rdquo;
        </div>` : ''}
      <div class="panel-item-meta" style="font-size:0.8rem">
        <span>📍 ${_esc(locationStr)}</span>
        ${latLng}
        ${rr.incident_id ? `<span style="font-weight:600">Incident #${rr.incident_id}</span>` : ''}
      </div>
      ${p.rationale ? `
        <div class="panel-item-meta" style="font-size:0.78rem;background:#fef3c7;border-left:3px solid #f59e0b;padding:6px 8px;border-radius:4px;color:#92400e;margin-top:4px">
          <b>Rationale:</b> ${_esc(p.rationale)}
        </div>` : ''}
      <div class="panel-item-actions" style="margin-top:8px">
        ${rr.incident_id ? `<button class="btn btn-sm btn-secondary" onclick="openIncidentById(${rr.incident_id})">View Incident</button>` : ''}
        ${(rr.incident_lat && rr.incident_lng) ? `<button class="btn btn-sm btn-secondary" onclick="focusIncidentOnMap(${rr.incident_id})">&#128204; Map</button>` : ''}
      </div>
    </div>`;
  }).join('');
}

// ── Briefings ─────────────────────────────────────────────────────────────
async function loadBriefings() {
  const res = await fetch('/api/briefings');
  if (!res.ok) return;
  const { briefings } = await res.json();
  const container = document.getElementById('briefing-list');
  const selBar = document.getElementById('briefings-selection-bar');
  if (!container) return;

  if (!briefings.length) {
    if (selBar) selBar.style.display = 'none';
    container.innerHTML = '<div class="empty-state">No briefings yet. Click Generate to create one.</div>';
    return;
  }

  if (selBar) selBar.style.display = 'flex';
  const selectAllCb = document.getElementById('briefing-select-all');
  if (selectAllCb) {
    selectAllCb.checked = false;
    selectAllCb.indeterminate = false;
  }
  updateBriefingBatchBar();

  container.innerHTML = briefings.map(b => `
    <div class="panel-item" id="briefing-card-${b.id}" style="padding:10px 12px;margin-bottom:8px">
      <div class="panel-item-title" style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin:0">
          <input type="checkbox" class="briefing-checkbox" value="${b.id}" onchange="onBriefingCheckboxChange()" style="cursor:pointer;width:15px;height:15px">
          <b>📄 Briefing #${b.id}</b>
        </label>
        <span class="badge badge-secondary" style="font-size:0.75rem">${b.created_at?.slice(0,19).replace('T',' ')}</span>
      </div>
      <div class="panel-item-meta" style="margin:4px 0">
        <span>By: <b>${_esc(b.generated_by || 'Coordinator')}</b></span>
      </div>
      ${b.summary_text ? `
        <div class="panel-item-meta" style="font-size:0.8rem;color:#4b5563;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;margin-bottom:8px">
          ${_esc(b.summary_text.slice(0, 110))}…
        </div>` : ''}
      <div class="panel-item-actions" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <a class="btn btn-sm btn-secondary" href="/api/briefings/${b.id}/view" target="_blank">👁️ View Briefing</a>
        <a class="btn btn-sm btn-primary" href="/api/briefings/${b.id}/pdf">📥 Download PDF</a>
        <button class="btn btn-sm btn-danger" onclick="deleteSingleBriefing(${b.id})" style="font-size:0.75rem;padding:3px 8px" title="Delete this briefing">🗑️ Delete</button>
      </div>
    </div>`).join('');
}

function onBriefingCheckboxChange() {
  updateBriefingBatchBar();
}

function updateBriefingBatchBar() {
  const checkboxes = document.querySelectorAll('.briefing-checkbox');
  const checked = document.querySelectorAll('.briefing-checkbox:checked');
  const deleteBtn = document.getElementById('btn-delete-selected-briefings');
  const countSpan = document.getElementById('briefings-selected-num');
  const selectAll = document.getElementById('briefing-select-all');

  if (deleteBtn) {
    if (checked.length > 0) {
      deleteBtn.style.display = 'inline-block';
      if (countSpan) countSpan.textContent = checked.length;
    } else {
      deleteBtn.style.display = 'none';
    }
  }

  if (selectAll && checkboxes.length > 0) {
    selectAll.checked = checked.length === checkboxes.length;
    selectAll.indeterminate = checked.length > 0 && checked.length < checkboxes.length;
  }
}

function toggleSelectAllBriefings(checked) {
  const checkboxes = document.querySelectorAll('.briefing-checkbox');
  checkboxes.forEach(cb => { cb.checked = checked; });
  updateBriefingBatchBar();
}

async function deleteSingleBriefing(id) {
  if (!confirm(`Are you sure you want to delete Briefing #${id}? This cannot be undone.`)) {
    return;
  }
  try {
    const res = await fetch(`/api/briefings/${id}`, {
      method: 'DELETE',
      headers: { 'X-CSRFToken': getCsrfToken() }
    });
    if (res.ok) {
      await loadBriefings();
    } else {
      const err = await res.json().catch(() => ({}));
      alert(err.message || err.error?.message || 'Failed to delete briefing.');
    }
  } catch (err) {
    console.error('Delete briefing error:', err);
    alert('An error occurred while deleting the briefing.');
  }
}

async function deleteSelectedBriefings() {
  const checked = Array.from(document.querySelectorAll('.briefing-checkbox:checked')).map(cb => parseInt(cb.value, 10));
  if (!checked.length) return;

  if (!confirm(`Are you sure you want to delete ${checked.length} selected briefing(s)? This cannot be undone.`)) {
    return;
  }

  const deleteBtn = document.getElementById('btn-delete-selected-briefings');
  if (deleteBtn) {
    deleteBtn.disabled = true;
    deleteBtn.textContent = 'Deleting…';
  }

  try {
    const res = await fetch('/api/briefings/batch-delete', {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfToken(),
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ briefing_ids: checked })
    });
    if (res.ok) {
      await loadBriefings();
    } else {
      const err = await res.json().catch(() => ({}));
      alert(err.message || err.error?.message || 'Failed to delete selected briefings.');
    }
  } catch (err) {
    console.error('Batch delete error:', err);
    alert('An error occurred while deleting briefings.');
  } finally {
    if (deleteBtn) {
      deleteBtn.disabled = false;
      deleteBtn.innerHTML = '🗑️ Delete Selected (<span id="briefings-selected-num">0</span>)';
    }
  }
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
  await loadAll();
}

async function runPrioritization() {
  const btn = document.getElementById('btn-run-prio');
  if (btn) { btn.disabled = true; btn.textContent = 'Re-scoring…'; }
  try {
    await fetch('/api/prioritization/run', { method: 'POST',
      headers: { 'X-CSRFToken': getCsrfToken() } });
    await loadPrioritization();
  } catch (e) {
    console.error('Prioritization error:', e);
  }
  if (btn) { btn.disabled = false; btn.textContent = 'Re-score'; }
}

async function generateBriefing() {
  const btn = document.getElementById('btn-briefing');
  if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
  try {
    await fetch('/api/briefings', { method: 'POST',
      headers: { 'X-CSRFToken': getCsrfToken() } });
    await loadBriefings();
  } catch (e) {
    console.error('Briefing error:', e);
  }
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
