/**
 * API Discover - Popup Script
 *
 * Handles the extension popup UI: start/stop capture, display stats, export.
 */

// ============================================================================
// DOM Elements
// ============================================================================

const statusEl = document.getElementById('status');
const statusTextEl = statusEl.querySelector('.status-text');
const statsEl = document.getElementById('stats');
const errorEl = document.getElementById('error');

const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const btnExport = document.getElementById('btn-export');

const statRequests = document.getElementById('stat-requests');
const statWs = document.getElementById('stat-ws');
const statContexts = document.getElementById('stat-contexts');
const statDuration = document.getElementById('stat-duration');

const settingTypename = document.getElementById('setting-typename');
const settingApq = document.getElementById('setting-apq');

// ============================================================================
// State
// ============================================================================

let currentTabId = null;
let statusPollInterval = null;
let lastStats = null;
let hostConnected = false;

// ============================================================================
// Utility functions
// ============================================================================

/**
 * Format duration in seconds
 */
function formatDuration(ms) {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes}m ${secs}s`;
}

/**
 * Show error message
 */
function showError(message) {
  errorEl.textContent = message;
  errorEl.classList.remove('hidden');
  setTimeout(() => {
    errorEl.classList.add('hidden');
  }, 5000);
}

/**
 * Update UI based on state
 */
function updateUI(state, stats = null) {
  // Reset all buttons
  btnStart.classList.add('hidden');
  btnStop.classList.add('hidden');
  btnExport.classList.add('hidden');

  // Update status and buttons based on state
  switch (state) {
    case 'idle':
      statusEl.className = 'status status-idle';
      statusTextEl.textContent = 'Ready to capture';
      statsEl.classList.add('hidden');

      if (!hostConnected) {
        statusTextEl.textContent = 'CLI not connected';
        btnStart.disabled = true;
      } else {
        btnStart.classList.remove('hidden');
      }

      // Show send button if we have data from last capture
      if (lastStats && lastStats.trace_count > 0 && hostConnected) {
        btnExport.classList.remove('hidden');
        statusEl.className = 'status status-stopped';
        statusTextEl.textContent = `Captured ${lastStats.trace_count} requests`;
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
        statRequests.textContent = stats.trace_count;
        statWs.textContent = stats.ws_message_count;
        statContexts.textContent = stats.context_count;
        statDuration.textContent = formatDuration(stats.duration_ms);
      }
      break;

    case 'sending':
      statusEl.className = 'status status-sending';
      statusTextEl.textContent = 'Sending to Spectral...';
      break;
  }
}

// ============================================================================
// Actions
// ============================================================================

/**
 * Start capture on current tab
 */
async function startCapture() {
  try {
    btnStart.disabled = true;
    lastStats = null;

    const response = await chrome.runtime.sendMessage({
      type: 'START_CAPTURE',
      tabId: currentTabId,
    });

    if (response.error) {
      throw new Error(response.error);
    }

    // Start polling for status
    startStatusPolling();
    updateUI('capturing');
  } catch (error) {
    showError(`Failed to start: ${error.message}`);
    updateUI('idle');
  } finally {
    btnStart.disabled = false;
  }
}

/**
 * Stop capture
 */
async function stopCapture() {
  try {
    btnStop.disabled = true;
    stopStatusPolling();

    const response = await chrome.runtime.sendMessage({
      type: 'STOP_CAPTURE',
    });

    if (response.error) {
      throw new Error(response.error);
    }

    lastStats = response.stats;
    updateUI('idle');
  } catch (error) {
    showError(`Failed to stop: ${error.message}`);
  } finally {
    btnStop.disabled = false;
  }
}

/**
 * Send capture to spectral CLI via native messaging
 */
async function sendCapture() {
  try {
    btnExport.disabled = true;
    updateUI('sending');

    const response = await chrome.runtime.sendMessage({
      type: 'SEND_CAPTURE',
    });

    if (response.error) {
      // Detect native messaging host not installed
      if (chrome.runtime.lastError &&
          chrome.runtime.lastError.message &&
          chrome.runtime.lastError.message.includes('native messaging host not found')) {
        throw new Error(`Native host not found. Run: spectral extension install --extension-id ${chrome.runtime.id}`);
      }
      throw new Error(response.error);
    }

    // Reset state after send
    lastStats = null;
    updateUI('idle');
  } catch (error) {
    // Also check lastError at this level
    if (error.message && error.message.includes('native messaging host not found')) {
      showError(`Native host not found. Run: spectral extension install --extension-id ${chrome.runtime.id}`);
    } else {
      showError(`Failed to send: ${error.message}`);
    }
    updateUI('idle');
  } finally {
    btnExport.disabled = false;
  }
}

// ============================================================================
// Status polling
// ============================================================================

/**
 * Start polling for capture status
 */
function startStatusPolling() {
  stopStatusPolling();
  statusPollInterval = setInterval(pollStatus, 1000);
}

/**
 * Stop polling
 */
function stopStatusPolling() {
  if (statusPollInterval) {
    clearInterval(statusPollInterval);
    statusPollInterval = null;
  }
}

/**
 * Poll current status
 */
async function pollStatus() {
  try {
    const response = await chrome.runtime.sendMessage({
      type: 'GET_STATUS',
    });

    if (response.state === 'capturing' && response.stats) {
      updateUI('capturing', response.stats);
    } else if (response.state === 'idle') {
      stopStatusPolling();
      if (response.stats) {
        lastStats = response.stats;
      }
      updateUI('idle');
    }
  } catch (error) {
    // Ignore polling errors
  }
}

// ============================================================================
// Initialize
// ============================================================================

/**
 * Check if the native messaging host is reachable.
 */
async function checkHostConnection() {
  const connEl = document.getElementById('connection-status');
  try {
    const response = await chrome.runtime.sendNativeMessage(
      'com.spectral.capture_host',
      { type: 'ping' }
    );
    if (response && response.type === 'pong') {
      hostConnected = true;
      connEl.innerHTML = 'Connected to <code>spectral</code> CLI';
      return true;
    }
  } catch {
    // Host not found or errored
  }
  hostConnected = false;
  const installCmd = `spectral extension install --extension-id ${chrome.runtime.id}`;
  connEl.innerHTML = `<code>spectral</code> CLI not connected. Run:<br><span class="install-cmd"><code>${installCmd}</code><button class="btn-copy" title="&#128461; command">&#128461;</button></span>`;
  connEl.classList.add('connection-error');
  connEl.querySelector('.btn-copy').addEventListener('click', () => {
    navigator.clipboard.writeText(installCmd).then(() => {
      const btn = connEl.querySelector('.btn-copy');
      btn.textContent = '\u2713';
      setTimeout(() => { btn.innerHTML = '&#128461;'; }, 1500);
    });
  });
  btnStart.disabled = true;
  return false;
}

async function initialize() {
  try {
    // Check host connection first
    await checkHostConnection();

    // Get current tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab) {
      showError('No active tab found');
      return;
    }

    // Check if we can attach to this tab
    if (tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
      showError('Cannot capture Chrome internal pages');
      btnStart.disabled = true;
      return;
    }

    currentTabId = tab.id;

    // Get current status from background
    const response = await chrome.runtime.sendMessage({
      type: 'GET_STATUS',
    });

    // Apply persisted settings to checkboxes
    if (response.settings) {
      settingTypename.checked = response.settings.injectTypename;
      settingApq.checked = response.settings.injectApqError;
    }

    if (response.state === 'capturing') {
      // Already capturing
      startStatusPolling();
      updateUI('capturing', response.stats);
    } else {
      // Check if we have data from a previous capture
      if (response.stats && response.stats.trace_count > 0) {
        lastStats = response.stats;
      }
      updateUI('idle');
    }
  } catch (error) {
    showError(`Initialization error: ${error.message}`);
  }
}

// ============================================================================
// Event listeners
// ============================================================================

btnStart.addEventListener('click', startCapture);
btnStop.addEventListener('click', stopCapture);
btnExport.addEventListener('click', sendCapture);

settingTypename.addEventListener('change', () => {
  chrome.runtime.sendMessage({
    type: 'UPDATE_SETTINGS',
    settings: { injectTypename: settingTypename.checked },
  });
});

settingApq.addEventListener('change', () => {
  chrome.runtime.sendMessage({
    type: 'UPDATE_SETTINGS',
    settings: { injectApqError: settingApq.checked },
  });
});

// Initialize on popup open
initialize();
