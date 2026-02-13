/**
 * API Discover - Background Service Worker
 *
 * Captures network traffic via Chrome DevTools Protocol (chrome.debugger)
 * and coordinates with content.js for UI context capture.
 *
 * State machine: IDLE → ATTACHING → CAPTURING → EXPORTING → IDLE
 */

// Import JSZip for bundle export
importScripts('lib/jszip.min.js');

// ============================================================================
// State
// ============================================================================

const State = {
  IDLE: 'idle',
  ATTACHING: 'attaching',
  CAPTURING: 'capturing',
  EXPORTING: 'exporting',
};

let state = State.IDLE;
let captureTabId = null;
let captureStartTime = null;

// Captured data
let traces = [];
let contexts = [];
let wsConnections = new Map(); // ws_id -> connection data
let wsMessages = []; // All WebSocket messages
let timeline = [];

// Pending requests (requestId -> partial trace data)
let pendingRequests = new Map();

// Counters for ID generation
let traceCounter = 0;
let contextCounter = 0;
let wsConnectionCounter = 0;
let wsMessageCounters = new Map(); // ws_id -> message counter

// Tab info captured at start
let appInfo = null;

// ============================================================================
// Utility functions
// ============================================================================

/**
 * Generate zero-padded ID
 */
function padId(prefix, num) {
  return `${prefix}_${String(num).padStart(4, '0')}`;
}

/**
 * Get current timestamp in milliseconds
 */
function now() {
  return Date.now();
}

/**
 * Generate a UUID v4
 */
function uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Decode base64 to Uint8Array
 */
function base64ToBytes(base64) {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

/**
 * Convert string to Uint8Array (UTF-8)
 */
function stringToBytes(str) {
  return new TextEncoder().encode(str);
}

/**
 * Convert headers from Chrome format to our format
 * Chrome: { "Name": "value" } or { name: { name, value } }
 * Ours: [{ name, value }]
 */
function normalizeHeaders(headers) {
  if (!headers) return [];
  if (Array.isArray(headers)) return headers;

  return Object.entries(headers).map(([name, value]) => ({
    name,
    value: typeof value === 'object' ? value.value : String(value),
  }));
}

/**
 * Find contexts within the correlation window (2 seconds before timestamp)
 */
function findContextRefs(timestamp, windowMs = 2000) {
  const refs = [];
  for (const ctx of contexts) {
    if (ctx.timestamp >= timestamp - windowMs && ctx.timestamp <= timestamp) {
      refs.push(ctx.id);
    }
  }
  return refs;
}

// ============================================================================
// DevTools Protocol handlers
// ============================================================================

/**
 * Handle Network.requestWillBeSent
 */
function handleRequestWillBeSent(params) {
  const { requestId, request, timestamp, initiator, type } = params;

  // Skip WebSocket upgrade requests - handled separately
  if (type === 'WebSocket') return;

  // Store partial trace data
  pendingRequests.set(requestId, {
    requestId,
    timestamp: Math.floor(timestamp * 1000), // Chrome uses seconds, we use ms
    request: {
      method: request.method,
      url: request.url,
      headers: normalizeHeaders(request.headers),
      postData: request.postData || null,
    },
    initiator: {
      type: initiator?.type || 'other',
      url: initiator?.url || null,
      line: initiator?.lineNumber || null,
    },
  });
}

/**
 * Handle Network.responseReceived
 */
function handleResponseReceived(params) {
  const { requestId, response, timestamp } = params;

  const pending = pendingRequests.get(requestId);
  if (!pending) return;

  // Compute timing
  const timing = response.timing || {};
  const timingInfo = {
    dns_ms: timing.dnsEnd - timing.dnsStart || 0,
    connect_ms: timing.connectEnd - timing.connectStart || 0,
    tls_ms: timing.sslEnd - timing.sslStart || 0,
    send_ms: timing.sendEnd - timing.sendStart || 0,
    wait_ms: timing.receiveHeadersEnd - timing.sendEnd || 0,
    receive_ms: 0, // Computed at loadingFinished
    total_ms: 0,
  };

  pending.response = {
    status: response.status,
    statusText: response.statusText || '',
    headers: normalizeHeaders(response.headers),
    mimeType: response.mimeType,
  };
  pending.timing = timingInfo;
  pending.responseTimestamp = Math.floor(timestamp * 1000);
}

/**
 * Handle Network.loadingFinished - fetch response body and finalize trace
 */
async function handleLoadingFinished(params, debuggeeId) {
  const { requestId, timestamp, encodedDataLength } = params;

  const pending = pendingRequests.get(requestId);
  if (!pending || !pending.response) {
    pendingRequests.delete(requestId);
    return;
  }

  // Try to get response body
  let responseBody = null;
  let responseBase64 = false;
  try {
    const result = await chrome.debugger.sendCommand(debuggeeId, 'Network.getResponseBody', {
      requestId,
    });
    responseBody = result.body;
    responseBase64 = result.base64Encoded;
  } catch (e) {
    // Body might not be available (e.g., redirects, 204 responses)
  }

  // Compute total timing
  if (pending.timing) {
    const receiveMs = timestamp * 1000 - pending.responseTimestamp;
    pending.timing.receive_ms = Math.max(0, receiveMs);
    pending.timing.total_ms =
      pending.timing.dns_ms +
      pending.timing.connect_ms +
      pending.timing.tls_ms +
      pending.timing.send_ms +
      pending.timing.wait_ms +
      pending.timing.receive_ms;
  }

  // Create the trace
  traceCounter++;
  const traceId = padId('t', traceCounter);

  // Process request body
  let requestBodyBytes = null;
  if (pending.request.postData) {
    requestBodyBytes = stringToBytes(pending.request.postData);
  }

  // Process response body
  let responseBodyBytes = null;
  if (responseBody) {
    if (responseBase64) {
      responseBodyBytes = base64ToBytes(responseBody);
    } else {
      responseBodyBytes = stringToBytes(responseBody);
    }
  }

  const trace = {
    id: traceId,
    timestamp: pending.timestamp,
    type: 'http',
    request: {
      method: pending.request.method,
      url: pending.request.url,
      headers: pending.request.headers,
      body_file: requestBodyBytes?.length ? `${traceId}_request.bin` : null,
      body_size: requestBodyBytes?.length || 0,
      body_encoding: null,
    },
    response: {
      status: pending.response.status,
      status_text: pending.response.statusText,
      headers: pending.response.headers,
      body_file: responseBodyBytes?.length ? `${traceId}_response.bin` : null,
      body_size: responseBodyBytes?.length || 0,
      body_encoding: null,
    },
    timing: pending.timing || {
      dns_ms: 0,
      connect_ms: 0,
      tls_ms: 0,
      send_ms: 0,
      wait_ms: 0,
      receive_ms: 0,
      total_ms: 0,
    },
    initiator: pending.initiator,
    context_refs: findContextRefs(pending.timestamp),
    // Store body bytes for ZIP export
    _requestBodyBytes: requestBodyBytes,
    _responseBodyBytes: responseBodyBytes,
  };

  traces.push(trace);
  timeline.push({
    timestamp: pending.timestamp,
    type: 'trace',
    ref: traceId,
  });

  pendingRequests.delete(requestId);
}

/**
 * Handle Network.loadingFailed
 */
function handleLoadingFailed(params) {
  const { requestId } = params;
  pendingRequests.delete(requestId);
}

/**
 * Handle Network.webSocketCreated
 */
function handleWebSocketCreated(params) {
  const { requestId, url } = params;

  wsConnectionCounter++;
  const wsId = padId('ws', wsConnectionCounter);

  const connection = {
    id: wsId,
    timestamp: now(),
    url,
    handshake_trace_ref: null,
    protocols: [],
    message_count: 0,
    context_refs: findContextRefs(now()),
    requestId, // Chrome's requestId for this WS
    messages: [],
  };

  wsConnections.set(requestId, connection);
  wsMessageCounters.set(wsId, 0);

  timeline.push({
    timestamp: connection.timestamp,
    type: 'ws_open',
    ref: wsId,
  });
}

/**
 * Handle Network.webSocketHandshakeResponseReceived
 */
function handleWebSocketHandshake(params) {
  const { requestId, response } = params;

  const connection = wsConnections.get(requestId);
  if (!connection) return;

  // Extract protocols from headers
  const headers = normalizeHeaders(response.headers);
  const protocolHeader = headers.find(
    (h) => h.name.toLowerCase() === 'sec-websocket-protocol'
  );
  if (protocolHeader) {
    connection.protocols = protocolHeader.value.split(',').map((p) => p.trim());
  }
}

/**
 * Handle Network.webSocketFrameSent
 */
function handleWebSocketFrameSent(params) {
  const { requestId, timestamp, response } = params;

  const connection = wsConnections.get(requestId);
  if (!connection) return;

  const wsId = connection.id;
  const counter = wsMessageCounters.get(wsId) + 1;
  wsMessageCounters.set(wsId, counter);

  const msgId = `${wsId}_m${String(counter).padStart(3, '0')}`;
  const ts = Math.floor(timestamp * 1000);

  // Determine opcode and payload
  const opcode = response.opcode === 1 ? 'text' : response.opcode === 2 ? 'binary' : 'text';
  let payloadBytes = null;

  if (response.payloadData) {
    if (opcode === 'binary') {
      payloadBytes = base64ToBytes(response.payloadData);
    } else {
      payloadBytes = stringToBytes(response.payloadData);
    }
  }

  const message = {
    id: msgId,
    connection_ref: wsId,
    timestamp: ts,
    direction: 'send',
    opcode,
    payload_file: payloadBytes?.length ? `${msgId}.bin` : null,
    payload_size: payloadBytes?.length || 0,
    context_refs: findContextRefs(ts),
    _payloadBytes: payloadBytes,
  };

  connection.messages.push(message);
  connection.message_count++;
  wsMessages.push(message);

  timeline.push({
    timestamp: ts,
    type: 'ws_message',
    ref: msgId,
  });
}

/**
 * Handle Network.webSocketFrameReceived
 */
function handleWebSocketFrameReceived(params) {
  const { requestId, timestamp, response } = params;

  const connection = wsConnections.get(requestId);
  if (!connection) return;

  const wsId = connection.id;
  const counter = wsMessageCounters.get(wsId) + 1;
  wsMessageCounters.set(wsId, counter);

  const msgId = `${wsId}_m${String(counter).padStart(3, '0')}`;
  const ts = Math.floor(timestamp * 1000);

  const opcode = response.opcode === 1 ? 'text' : response.opcode === 2 ? 'binary' : 'text';
  let payloadBytes = null;

  if (response.payloadData) {
    if (opcode === 'binary') {
      payloadBytes = base64ToBytes(response.payloadData);
    } else {
      payloadBytes = stringToBytes(response.payloadData);
    }
  }

  const message = {
    id: msgId,
    connection_ref: wsId,
    timestamp: ts,
    direction: 'receive',
    opcode,
    payload_file: payloadBytes?.length ? `${msgId}.bin` : null,
    payload_size: payloadBytes?.length || 0,
    context_refs: findContextRefs(ts),
    _payloadBytes: payloadBytes,
  };

  connection.messages.push(message);
  connection.message_count++;
  wsMessages.push(message);

  timeline.push({
    timestamp: ts,
    type: 'ws_message',
    ref: msgId,
  });
}

/**
 * Handle Network.webSocketClosed
 */
function handleWebSocketClosed(params) {
  // Connection is kept in wsConnections map - no action needed
}

// ============================================================================
// Debugger event handler
// ============================================================================

function onDebuggerEvent(debuggeeId, method, params) {
  if (state !== State.CAPTURING) return;
  if (debuggeeId.tabId !== captureTabId) return;

  switch (method) {
    case 'Network.requestWillBeSent':
      handleRequestWillBeSent(params);
      break;
    case 'Network.responseReceived':
      handleResponseReceived(params);
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
  }
}

/**
 * Handle debugger detach
 */
function onDebuggerDetach(debuggeeId, reason) {
  if (debuggeeId.tabId === captureTabId) {
    console.log('Debugger detached:', reason);
    deactivateContentScript(captureTabId);
    resetState();
  }
}

// ============================================================================
// Capture control
// ============================================================================

/**
 * Tell the content script to stop/start capturing
 */
function deactivateContentScript(tabId) {
  chrome.tabs.sendMessage(tabId, { type: 'SET_CAPTURE_ACTIVE', active: false }).catch(() => {});
}

function activateContentScript(tabId) {
  chrome.tabs.sendMessage(tabId, { type: 'SET_CAPTURE_ACTIVE', active: true }).catch(() => {});
}

/**
 * Reset all capture state
 */
function resetState() {
  state = State.IDLE;
  captureTabId = null;
  captureStartTime = null;
  traces = [];
  contexts = [];
  wsConnections = new Map();
  wsMessages = [];
  timeline = [];
  pendingRequests = new Map();
  traceCounter = 0;
  contextCounter = 0;
  wsConnectionCounter = 0;
  wsMessageCounters = new Map();
  appInfo = null;
}

/**
 * Start capture on a tab
 */
async function startCapture(tabId) {
  if (state !== State.IDLE) {
    throw new Error(`Cannot start capture in state: ${state}`);
  }

  state = State.ATTACHING;
  captureTabId = tabId;

  try {
    // Get tab info
    const tab = await chrome.tabs.get(tabId);
    const url = new URL(tab.url);

    appInfo = {
      name: tab.title || 'Unknown App',
      base_url: url.origin,
      title: tab.title || '',
    };

    // Inject content script for UI context capture (IIFE guards against double-init)
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: ['content.js'],
    });
    // Re-activate if already injected from a previous capture
    activateContentScript(tabId);

    // Attach debugger
    await chrome.debugger.attach({ tabId }, '1.3');

    // Enable network domain
    await chrome.debugger.sendCommand({ tabId }, 'Network.enable', {
      maxPostDataSize: 65536, // 64KB max POST data
    });

    // Set up event listener
    chrome.debugger.onEvent.addListener(onDebuggerEvent);
    chrome.debugger.onDetach.addListener(onDebuggerDetach);

    captureStartTime = now();
    state = State.CAPTURING;

    return { success: true };
  } catch (error) {
    resetState();
    throw error;
  }
}

/**
 * Stop capture
 */
async function stopCapture() {
  if (state !== State.CAPTURING) {
    throw new Error(`Cannot stop capture in state: ${state}`);
  }

  deactivateContentScript(captureTabId);

  try {
    // Detach debugger
    await chrome.debugger.detach({ tabId: captureTabId });
  } catch (e) {
    // Ignore detach errors
  }

  chrome.debugger.onEvent.removeListener(onDebuggerEvent);
  chrome.debugger.onDetach.removeListener(onDebuggerDetach);

  state = State.IDLE;

  return {
    success: true,
    stats: getStats(),
  };
}

/**
 * Get current capture stats
 */
function getStats() {
  return {
    trace_count: traces.length,
    ws_connection_count: wsConnections.size,
    ws_message_count: wsMessages.length,
    context_count: contexts.length,
    duration_ms: captureStartTime ? now() - captureStartTime : 0,
  };
}

/**
 * Add a UI context from content script
 */
function addContext(contextData) {
  if (state !== State.CAPTURING) return;

  contextCounter++;
  const contextId = padId('c', contextCounter);
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

  contexts.push(context);
  timeline.push({
    timestamp,
    type: 'context',
    ref: contextId,
  });
}

// ============================================================================
// Export
// ============================================================================

/**
 * Export capture data as a ZIP bundle
 */
async function exportCapture() {
  if (traces.length === 0 && contexts.length === 0) {
    throw new Error('No data to export');
  }

  state = State.EXPORTING;

  try {
    const zip = new JSZip();

    // Sort timeline by timestamp
    timeline.sort((a, b) => a.timestamp - b.timestamp);

    // Create manifest
    const manifest = {
      format_version: '1.0.0',
      capture_id: uuid(),
      created_at: new Date().toISOString(),
      app: appInfo || {
        name: 'Unknown App',
        base_url: '',
        title: '',
      },
      browser: {
        name: 'Chrome',
        version: navigator.userAgent.match(/Chrome\/(\d+\.\d+)/)?.[1] || 'unknown',
      },
      extension_version: '0.1.0',
      duration_ms: captureStartTime ? now() - captureStartTime : 0,
      stats: {
        trace_count: traces.length,
        ws_connection_count: wsConnections.size,
        ws_message_count: wsMessages.length,
        context_count: contexts.length,
      },
    };

    zip.file('manifest.json', JSON.stringify(manifest, null, 2));

    // Add traces
    const tracesFolder = zip.folder('traces');
    for (const trace of traces) {
      // Clone trace metadata without internal _*Bytes fields
      const traceMeta = {
        id: trace.id,
        timestamp: trace.timestamp,
        type: trace.type,
        request: trace.request,
        response: trace.response,
        timing: trace.timing,
        initiator: trace.initiator,
        context_refs: trace.context_refs,
      };

      tracesFolder.file(`${trace.id}.json`, JSON.stringify(traceMeta, null, 2));

      if (trace._requestBodyBytes?.length) {
        tracesFolder.file(`${trace.id}_request.bin`, trace._requestBodyBytes);
      }
      if (trace._responseBodyBytes?.length) {
        tracesFolder.file(`${trace.id}_response.bin`, trace._responseBodyBytes);
      }
    }

    // Add WebSocket connections and messages
    const wsFolder = zip.folder('ws');
    for (const [, connection] of wsConnections) {
      const connMeta = {
        id: connection.id,
        timestamp: connection.timestamp,
        url: connection.url,
        handshake_trace_ref: connection.handshake_trace_ref,
        protocols: connection.protocols,
        message_count: connection.message_count,
        context_refs: connection.context_refs,
      };

      wsFolder.file(`${connection.id}.json`, JSON.stringify(connMeta, null, 2));

      for (const msg of connection.messages) {
        const msgMeta = {
          id: msg.id,
          connection_ref: msg.connection_ref,
          timestamp: msg.timestamp,
          direction: msg.direction,
          opcode: msg.opcode,
          payload_file: msg.payload_file,
          payload_size: msg.payload_size,
          context_refs: msg.context_refs,
        };

        wsFolder.file(`${msg.id}.json`, JSON.stringify(msgMeta, null, 2));

        if (msg._payloadBytes?.length) {
          wsFolder.file(`${msg.id}.bin`, msg._payloadBytes);
        }
      }
    }

    // Add contexts
    const contextsFolder = zip.folder('contexts');
    for (const ctx of contexts) {
      contextsFolder.file(`${ctx.id}.json`, JSON.stringify(ctx, null, 2));
    }

    // Add timeline
    zip.file('timeline.json', JSON.stringify({ events: timeline }, null, 2));

    // Generate ZIP as base64 (URL.createObjectURL not available in service workers)
    const base64 = await zip.generateAsync({ type: 'base64' });

    // Create filename with timestamp
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const domain = appInfo?.base_url ? new URL(appInfo.base_url).hostname.replace(/\./g, '_') : 'unknown';
    const filename = `capture_${domain}_${timestamp}.zip`;

    // Trigger download via data URL
    await chrome.downloads.download({
      url: `data:application/zip;base64,${base64}`,
      filename,
      saveAs: true,
    });

    state = State.IDLE;
    return { success: true, filename };
  } catch (error) {
    state = State.IDLE;
    throw error;
  }
}

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
            state,
            tabId: captureTabId,
            stats: state === State.CAPTURING ? getStats() : null,
          });
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

// Log startup
console.log('API Discover background service worker started');
