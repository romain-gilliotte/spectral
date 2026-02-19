/**
 * Capture lifecycle: start, stop, stats, context, content script control.
 */

import { captureState, State, resetState } from './state.js';
import { padId, now } from './utils.js';

/**
 * Tell the content script to stop capturing.
 */
export function deactivateContentScript(tabId) {
  chrome.tabs.sendMessage(tabId, { type: 'SET_CAPTURE_ACTIVE', active: false }).catch(() => {});
}

/**
 * Tell the content script to start capturing.
 */
export function activateContentScript(tabId) {
  chrome.tabs.sendMessage(tabId, { type: 'SET_CAPTURE_ACTIVE', active: true }).catch(() => {});
}

/**
 * Get current capture stats.
 */
export function getStats() {
  return {
    trace_count: captureState.traces.length,
    ws_connection_count: captureState.wsConnections.size,
    ws_message_count: captureState.wsMessages.length,
    context_count: captureState.contexts.length,
    duration_ms: captureState.captureStartTime ? now() - captureState.captureStartTime : 0,
  };
}

/**
 * Add a UI context from content script.
 */
export function addContext(contextData) {
  if (captureState.state !== State.CAPTURING) return;

  captureState.contextCounter++;
  const contextId = padId('c', captureState.contextCounter);
  const timestamp = contextData.timestamp || now();

  const context = {
    id: contextId,
    timestamp,
    action: contextData.action,
    element: contextData.element || {
      selector: '',
      tag: '',
      text: '',
      attributes: {},
      xpath: '',
    },
    page: {
      url: contextData.page?.url || '',
      title: contextData.page?.title || '',
      content: contextData.page?.content || null,
    },
    viewport: contextData.viewport || {
      width: 0,
      height: 0,
      scroll_x: 0,
      scroll_y: 0,
    },
  };

  captureState.contexts.push(context);
  captureState.timeline.push({
    timestamp,
    type: 'context',
    ref: contextId,
  });
}

/**
 * Start capture on a tab.
 */
export async function startCapture(tabId) {
  if (captureState.state !== State.IDLE) {
    throw new Error(`Cannot start capture in state: ${captureState.state}`);
  }

  captureState.state = State.ATTACHING;
  captureState.captureTabId = tabId;

  try {
    // Get tab info
    const tab = await chrome.tabs.get(tabId);
    const url = new URL(tab.url);

    captureState.appInfo = {
      name: tab.title || 'Unknown App',
      base_url: url.origin,
      title: tab.title || '',
    };

    // Inject content script for UI context capture (IIFE guards against double-init)
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: ['content/content.js'],
    });
    // Re-activate if already injected from a previous capture
    activateContentScript(tabId);

    // Attach debugger
    await chrome.debugger.attach({ tabId }, '1.3');

    // Enable network domain
    await chrome.debugger.sendCommand({ tabId }, 'Network.enable', {
      maxPostDataSize: 65536, // 64KB max POST data
    });

    // Enable Fetch domain to intercept and modify GraphQL requests
    // (inject __typename into selection sets for accurate type inference)
    await chrome.debugger.sendCommand({ tabId }, 'Fetch.enable', {
      patterns: [{ urlPattern: '*graphql*', requestStage: 'Request' }],
    });

    captureState.captureStartTime = now();
    captureState.state = State.CAPTURING;

    return { success: true };
  } catch (error) {
    resetState();
    throw error;
  }
}

/**
 * Stop capture.
 */
export async function stopCapture() {
  if (captureState.state !== State.CAPTURING) {
    throw new Error(`Cannot stop capture in state: ${captureState.state}`);
  }

  deactivateContentScript(captureState.captureTabId);

  try {
    // Detach debugger
    await chrome.debugger.detach({ tabId: captureState.captureTabId });
  } catch (e) {
    // Ignore detach errors
  }

  captureState.state = State.IDLE;

  return {
    success: true,
    stats: getStats(),
  };
}
