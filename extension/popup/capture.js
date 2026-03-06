/**
 * Capture flow: start, stop+send, and status polling.
 */

import { state, showError, updateUI, formatDuration } from './ui.js';

let statusPollInterval = null;

/**
 * Start capture on current tab.
 */
export async function startCapture() {
  const btnStart = document.getElementById('btn-start');
  try {
    btnStart.disabled = true;
    state.lastStats = null;

    const response = await chrome.runtime.sendMessage({
      type: 'START_CAPTURE',
      tabId: state.currentTabId,
    });

    if (response.error) {
      throw new Error(response.error);
    }

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
 * Stop capture and automatically send to CLI via native messaging.
 */
export async function stopCapture() {
  const btnStop = document.getElementById('btn-stop');
  try {
    btnStop.disabled = true;
    stopStatusPolling();

    const stopResponse = await chrome.runtime.sendMessage({
      type: 'STOP_CAPTURE',
    });

    if (stopResponse.error) {
      throw new Error(stopResponse.error);
    }

    const stats = stopResponse.stats;

    if (!stats || stats.trace_count === 0) {
      state.lastStats = null;
      updateUI('idle');
      showError('Nothing captured');
      return;
    }

    state.lastStats = stats;
    updateUI('sending');

    const sendResponse = await chrome.runtime.sendMessage({
      type: 'SEND_CAPTURE',
    });

    if (sendResponse.error) {
      throw new Error(sendResponse.error);
    }

    state.sentCount = stats.trace_count;
    state.lastStats = null;
    updateUI('idle');
  } catch (error) {
    showError(`Failed: ${error.message}`);
    updateUI('idle');
  } finally {
    btnStop.disabled = false;
  }
}

// -- Status polling ----------------------------------------------------------

export function startStatusPolling() {
  stopStatusPolling();
  statusPollInterval = setInterval(pollStatus, 1000);
}

export function stopStatusPolling() {
  if (statusPollInterval) {
    clearInterval(statusPollInterval);
    statusPollInterval = null;
  }
}

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
        state.lastStats = response.stats;
      }
      updateUI('idle');
    }
  } catch (error) {
    // Ignore polling errors
  }
}
