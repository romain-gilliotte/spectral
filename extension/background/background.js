/**
 * API Discover - Background Service Worker (entry point)
 *
 * Captures network traffic via Chrome DevTools Protocol (chrome.debugger)
 * and coordinates with content.js for UI context capture.
 *
 * State machine: IDLE → ATTACHING → CAPTURING → EXPORTING → IDLE
 */

import { captureState, State, resetState, loadSettings, saveSettings } from './state.js';
import {
  handleRequestWillBeSent,
  handleResponseReceived,
  handleLoadingFinished,
  handleLoadingFailed,
  handleRequestWillBeSentExtraInfo,
  handleResponseReceivedExtraInfo,
} from './network.js';
import {
  handleWebSocketCreated,
  handleWebSocketHandshake,
  handleWebSocketFrameSent,
  handleWebSocketFrameReceived,
  handleWebSocketClosed,
} from './websocket.js';
import { handleFetchRequestPaused } from './graphql.js';
import {
  startCapture,
  stopCapture,
  getStats,
  addContext,
  activateContentScript,
  deactivateContentScript,
} from './capture.js';
import { exportCapture } from './export.js';

// ============================================================================
// Debugger event handler
// ============================================================================

function onDebuggerEvent(debuggeeId, method, params) {
  if (captureState.state !== State.CAPTURING) return;
  if (debuggeeId.tabId !== captureState.captureTabId) return;

  switch (method) {
    case 'Network.requestWillBeSent':
      handleRequestWillBeSent(params);
      break;
    case 'Network.responseReceived':
      handleResponseReceived(params);
      break;
    case 'Network.requestWillBeSentExtraInfo':
      handleRequestWillBeSentExtraInfo(params);
      break;
    case 'Network.responseReceivedExtraInfo':
      handleResponseReceivedExtraInfo(params);
      break;
    case 'Network.loadingFinished':
      handleLoadingFinished(params, debuggeeId);
      break;
    case 'Network.loadingFailed':
      handleLoadingFailed(params);
      break;
    case 'Network.webSocketCreated':
      handleWebSocketCreated(params);
      break;
    case 'Network.webSocketHandshakeResponseReceived':
      handleWebSocketHandshake(params);
      break;
    case 'Network.webSocketFrameSent':
      handleWebSocketFrameSent(params);
      break;
    case 'Network.webSocketFrameReceived':
      handleWebSocketFrameReceived(params);
      break;
    case 'Network.webSocketClosed':
      handleWebSocketClosed(params);
      break;
    case 'Fetch.requestPaused':
      handleFetchRequestPaused(params, debuggeeId);
      break;
  }
}

/**
 * Re-inject content script when the captured tab completes a navigation.
 * Full (non-SPA) navigations destroy the JS context, so the content script
 * must be re-injected to keep capturing UI events.
 */
function onTabUpdated(tabId, changeInfo) {
  if (tabId !== captureState.captureTabId || captureState.state !== State.CAPTURING) return;
  if (changeInfo.status === 'complete') {
    chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: ['content/content.js'],
    }).then(() => activateContentScript(tabId))
      .catch((e) => console.warn('Content script re-injection failed:', e));
  }
}

/**
 * Handle debugger detach.
 */
function onDebuggerDetach(debuggeeId, reason) {
  if (debuggeeId.tabId === captureState.captureTabId) {
    console.log('Debugger detached:', reason);
    deactivateContentScript(captureState.captureTabId);
    resetState();
  }
}

// ============================================================================
// Event listener registration
// ============================================================================

chrome.debugger.onEvent.addListener(onDebuggerEvent);
chrome.debugger.onDetach.addListener(onDebuggerDetach);
chrome.tabs.onUpdated.addListener(onTabUpdated);

// ============================================================================
// Message handling
// ============================================================================

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      switch (message.type) {
        case 'START_CAPTURE': {
          const result = await startCapture(message.tabId);
          sendResponse(result);
          break;
        }

        case 'STOP_CAPTURE': {
          const result = await stopCapture();
          sendResponse(result);
          break;
        }

        case 'GET_STATUS': {
          sendResponse({
            state: captureState.state,
            tabId: captureState.captureTabId,
            stats: captureState.state === State.CAPTURING ? getStats() : null,
            settings: { ...captureState.settings },
          });
          break;
        }

        case 'UPDATE_SETTINGS': {
          Object.assign(captureState.settings, message.settings);
          await saveSettings();
          sendResponse({ success: true });
          break;
        }

        case 'EXPORT_CAPTURE': {
          const result = await exportCapture();
          sendResponse(result);
          break;
        }

        case 'ADD_CONTEXT': {
          addContext(message.context);
          sendResponse({ success: true });
          break;
        }

        default:
          sendResponse({ error: `Unknown message type: ${message.type}` });
      }
    } catch (error) {
      sendResponse({ error: error.message });
    }
  })();

  // Return true to indicate async response
  return true;
});

// Load persisted settings and log startup
loadSettings().then(() => {
  console.log('API Discover background service worker started');
});
