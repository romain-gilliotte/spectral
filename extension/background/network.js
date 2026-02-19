/**
 * HTTP network event handlers (DevTools Protocol Network domain).
 */

import { captureState } from './state.js';
import {
  padId,
  toEpochMs,
  stringToBytes,
  base64ToBytes,
  normalizeHeaders,
  findContextRefs,
} from './utils.js';

/**
 * Static asset extensions to skip during capture.
 */
const STATIC_EXTENSIONS = new Set([
  '.js', '.css', '.woff', '.woff2', '.ttf', '.png', '.jpg', '.jpeg',
  '.gif', '.svg', '.ico', '.map',
]);

/**
 * Response content-type prefixes to skip during capture.
 */
const SKIP_CONTENT_TYPES = [
  'font/', 'image/', 'text/css', 'application/javascript', 'text/javascript',
];

/**
 * Check if a URL points to a static asset by extension.
 */
function isStaticAsset(url) {
  try {
    const pathname = new URL(url).pathname;
    const ext = pathname.slice(pathname.lastIndexOf('.')).toLowerCase();
    return STATIC_EXTENSIONS.has(ext);
  } catch {
    return false;
  }
}

/**
 * Check if a content-type is non-API (font, image, css, js).
 */
function isSkippableContentType(mimeType) {
  if (!mimeType) return false;
  const lower = mimeType.toLowerCase();
  return SKIP_CONTENT_TYPES.some((prefix) => lower.startsWith(prefix));
}

/**
 * Handle Network.requestWillBeSent
 */
export function handleRequestWillBeSent(params) {
  const { requestId, request, timestamp, wallTime, initiator, type } = params;

  // Skip WebSocket upgrade requests - handled separately
  if (type === 'WebSocket') return;

  // Skip chrome-extension:// URLs
  if (request.url.startsWith('chrome-extension://')) return;

  // Compute time offset on the first event (wallTime = epoch seconds)
  if (captureState.timeOffset === null && wallTime) {
    captureState.timeOffset = wallTime * 1000 - timestamp * 1000;
  }

  // Store partial trace data
  captureState.pendingRequests.set(requestId, {
    requestId,
    timestamp: toEpochMs(timestamp),
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

  // Check if ExtraInfo arrived first (wire-level headers)
  const extra = captureState.pendingExtraInfo.get(requestId);
  if (extra?.requestHeaders) {
    captureState.pendingRequests.get(requestId).request.headers = extra.requestHeaders;
    delete extra.requestHeaders;
    if (!extra.responseHeaders) captureState.pendingExtraInfo.delete(requestId);
  }
}

/**
 * Handle Network.responseReceived
 */
export function handleResponseReceived(params) {
  const { requestId, response, timestamp } = params;

  const pending = captureState.pendingRequests.get(requestId);
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
  pending.responseTimestamp = toEpochMs(timestamp);

  // Check if ExtraInfo arrived first (wire-level headers)
  const extra = captureState.pendingExtraInfo.get(requestId);
  if (extra?.responseHeaders) {
    pending.response.headers = extra.responseHeaders;
    delete extra.responseHeaders;
    if (!extra.requestHeaders) captureState.pendingExtraInfo.delete(requestId);
  }
}

/**
 * Handle Network.loadingFinished - fetch response body and finalize trace.
 */
export async function handleLoadingFinished(params, debuggeeId) {
  const { requestId, timestamp } = params;

  const pending = captureState.pendingRequests.get(requestId);
  if (!pending || !pending.response) {
    captureState.pendingRequests.delete(requestId);
    return;
  }

  // Skip static assets by URL extension
  if (isStaticAsset(pending.request.url)) {
    captureState.pendingRequests.delete(requestId);
    return;
  }

  // Skip non-API content types
  if (isSkippableContentType(pending.response.mimeType)) {
    captureState.pendingRequests.delete(requestId);
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
    const receiveMs = toEpochMs(timestamp) - pending.responseTimestamp;
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
  captureState.traceCounter++;
  const traceId = padId('t', captureState.traceCounter);

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

  captureState.traces.push(trace);
  captureState.timeline.push({
    timestamp: pending.timestamp,
    type: 'trace',
    ref: traceId,
  });

  captureState.pendingRequests.delete(requestId);
  captureState.pendingExtraInfo.delete(requestId);
}

/**
 * Handle Network.loadingFailed
 */
export function handleLoadingFailed(params) {
  const { requestId } = params;
  captureState.pendingRequests.delete(requestId);
  captureState.pendingExtraInfo.delete(requestId);
}

/**
 * Handle Network.requestWillBeSentExtraInfo — wire-level request headers
 * (includes Cookie, browser-managed Authorization, etc.)
 */
export function handleRequestWillBeSentExtraInfo(params) {
  const { requestId, headers } = params;

  const pending = captureState.pendingRequests.get(requestId);
  if (pending) {
    // Base event already arrived — merge directly
    pending.request.headers = normalizeHeaders(headers);
  } else {
    // Base event not yet arrived — buffer
    const extra = captureState.pendingExtraInfo.get(requestId) || {};
    extra.requestHeaders = normalizeHeaders(headers);
    captureState.pendingExtraInfo.set(requestId, extra);
  }
}

/**
 * Handle Network.responseReceivedExtraInfo — wire-level response headers
 * (includes Set-Cookie, cross-origin headers, etc.)
 */
export function handleResponseReceivedExtraInfo(params) {
  const { requestId, headers } = params;

  const pending = captureState.pendingRequests.get(requestId);
  if (pending && pending.response) {
    // Response already arrived — merge directly
    pending.response.headers = normalizeHeaders(headers);
  } else {
    // Response not yet arrived — buffer
    const extra = captureState.pendingExtraInfo.get(requestId) || {};
    extra.responseHeaders = normalizeHeaders(headers);
    captureState.pendingExtraInfo.set(requestId, extra);
  }
}
