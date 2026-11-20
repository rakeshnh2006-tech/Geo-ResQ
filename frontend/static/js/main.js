/**
 * GeoResQ — main.js
 * Shared JS: tab switching, flash auto-dismiss, CSRF helper, live location.
 */

// ── CSRF token helper ─────────────────────────────────────────────────────
function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : '';
}

// ── Tab switching ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

  // Support both old .tabs class and new .tab-nav class
  document.querySelectorAll('.tabs, .tab-nav').forEach(tabGroup => {
    tabGroup.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.tab;
        // Find the nearest scoping ancestor; fall back to document
        const scope = tabGroup.closest('[data-tabs-container]')
                   || tabGroup.closest('.sidebar-panel')
                   || tabGroup.closest('.card')
                   || document;
        // Deactivate all in this group
        tabGroup.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        scope.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        // Activate selected
        btn.classList.add('active');
        const panel = scope.querySelector(`#${target}`) || document.getElementById(target);
        if (panel) panel.classList.add('active');
      });
    });
  });

  // Auto-dismiss flash messages after 6s
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity .4s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 400);
    }, 6000);
  });

});

// ── Password Visibility Toggle ────────────────────────────────────────────
/**
 * Toggle the visibility of a password input between 'password' and 'text'.
 *
 * @param {string} inputId - id of the input element
 * @param {HTMLElement} btn - button element containing the toggle icon
 */
function togglePasswordVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const isPassword = input.type === 'password';
  input.type = isPassword ? 'text' : 'password';

  const eyeIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
  const eyeOffIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>';

  btn.innerHTML = isPassword ? eyeOffIcon : eyeIcon;
  btn.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password');
  btn.setAttribute('title', isPassword ? 'Hide password' : 'Show password');
}

// ── Live location (browser Geolocation API) ───────────────────────────────
/**
 * Request the user's GPS position and populate hidden form fields.
 *
 * @param {string} latFieldId  - id of the hidden <input> for latitude
 * @param {string} lngFieldId  - id of the hidden <input> for longitude
 * @param {string} statusId    - id of the <span> that shows status text
 */
function shareLocation(latFieldId, lngFieldId, statusId) {
  const statusEl = document.getElementById(statusId);
  const latEl    = document.getElementById(latFieldId);
  const lngEl    = document.getElementById(lngFieldId);

  if (!navigator.geolocation) {
    if (statusEl) statusEl.textContent = 'Geolocation is not supported by your browser.';
    return;
  }

  if (statusEl) {
    statusEl.textContent = 'Requesting location…';
    statusEl.style.color = 'var(--text-muted)';
  }

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const lat = pos.coords.latitude.toFixed(6);
      const lng = pos.coords.longitude.toFixed(6);
      if (latEl) latEl.value = lat;
      if (lngEl) lngEl.value = lng;
      if (statusEl) {
        statusEl.textContent = `📍 Location captured: ${lat}, ${lng}`;
        statusEl.style.color = 'var(--color-success)';
      }
    },
    (err) => {
      const messages = {
        1: 'Location access denied. Please allow location in your browser settings.',
        2: 'Location unavailable. Try again or enter your location manually.',
        3: 'Location request timed out. Please try again.',
      };
      if (statusEl) {
        statusEl.textContent = messages[err.code] || 'Could not get location.';
        statusEl.style.color = 'var(--color-danger)';
      }
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
  );
}
