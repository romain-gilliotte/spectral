/**
 * Shared popup state, DOM helpers, and UI update logic.
 */

// Shared mutable state — imported by capture.js and auth.js
export const state = {
  currentTabId: null,
  lastStats: null,
  hostConnected: false,
};

/**
 * Format duration in seconds.
 */
export function formatDuration(ms) {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes}m ${secs}s`;
}

/**
 * Show error message (auto-hides after 5 s).
 */
export function showError(message) {
  const errorEl = document.getElementById('error');
  errorEl.textContent = message;
  errorEl.classList.remove('hidden');
  setTimeout(() => {
    errorEl.classList.add('hidden');
  }, 5000);
}

/**
 * Update UI based on state.
 */
export function updateUI(uiState, stats = null) {
  const statusEl = document.getElementById('status');
  const statusTextEl = statusEl.querySelector('.status-text');
  const statsEl = document.getElementById('stats');
  const btnStart = document.getElementById('btn-start');
  const btnStop = document.getElementById('btn-stop');
  const btnExport = document.getElementById('btn-export');
  const btnGrabAuth = document.getElementById('btn-grab-auth');
  const btnRow = btnStart.closest('.btn-row');
  const captureSettings = document.getElementById('capture-settings');

  // Reset all buttons
  btnRow.classList.add('hidden');
  btnStop.classList.add('hidden');
  btnExport.classList.add('hidden');
  btnGrabAuth.classList.add('hidden');
  captureSettings.classList.add('collapsed');

  switch (uiState) {
    case 'idle':
      statusEl.className = 'status status-idle';
      statusTextEl.textContent = 'Ready to capture';
      statsEl.classList.add('hidden');

      btnRow.classList.remove('hidden');
      if (!state.hostConnected) {
        statusTextEl.textContent = 'CLI not connected';
        btnStart.disabled = true;
      } else {
        btnGrabAuth.classList.remove('hidden');
      }

      if (state.lastStats && state.lastStats.trace_count > 0 && state.hostConnected) {
        btnExport.classList.remove('hidden');
        btnGrabAuth.classList.remove('hidden');
        statusEl.className = 'status status-stopped';
        statusTextEl.textContent = `Captured ${state.lastStats.trace_count} requests`;
      }
      break;

    case 'attaching':
      statusEl.className = 'status status-capturing';
      statusTextEl.textContent = 'Attaching debugger...';
      break;

    case 'capturing':
      statusEl.className = 'status status-capturing';
      statusTextEl.textContent = 'Capturing...';
      btnStop.classList.remove('hidden');
      statsEl.classList.remove('hidden');

      if (stats) {
        document.getElementById('stat-requests').textContent = stats.trace_count;
        document.getElementById('stat-ws').textContent = stats.ws_message_count;
        document.getElementById('stat-contexts').textContent = stats.context_count;
        document.getElementById('stat-duration').textContent = formatDuration(stats.duration_ms);
      }
      break;

    case 'sending':
      statusEl.className = 'status status-sending';
      statusTextEl.textContent = 'Sending to Spectral...';
      break;
  }
}
