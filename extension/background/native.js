/**
 * Native messaging: send capture data directly to the spectral CLI host.
 */

import { captureState, State } from './state.js';
import { uuid, now } from './utils.js';

/**
 * Encode a Uint8Array (or null) to base64 string (or null).
 */
function bytesToBase64(bytes) {
  if (!bytes || bytes.length === 0) return null;
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Slugify an app name: lowercase, replace non-alphanumeric with hyphens, trim.
 */
function slugify(name) {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    || 'app';
}

/**
 * Send captured data to the spectral CLI via Chrome Native Messaging.
 */
export async function sendCapture() {
  if (captureState.traces.length === 0 && captureState.contexts.length === 0) {
    throw new Error('No data to send');
  }

  captureState.state = State.SENDING;

  try {
    // Sort timeline by timestamp
    captureState.timeline.sort((a, b) => a.timestamp - b.timestamp);

    const appName = slugify(
      (captureState.appInfo && captureState.appInfo.name) || 'Unknown App'
    );

    const manifest = {
      format_version: '1.0.0',
      capture_id: uuid(),
      created_at: new Date().toISOString(),
      app: captureState.appInfo || {
        name: 'Unknown App',
        base_url: '',
        title: '',
      },
      browser: {
        name: 'Chrome',
        version: navigator.userAgent.match(/Chrome\/(\d+\.\d+)/)?.[1] || 'unknown',
      },
      extension_version: '0.1.0',
      duration_ms: captureState.captureStartTime ? now() - captureState.captureStartTime : 0,
      stats: {
        trace_count: captureState.traces.length,
        ws_connection_count: captureState.wsConnections.size,
        ws_message_count: captureState.wsMessages.length,
        context_count: captureState.contexts.length,
      },
    };

    // Build traces with base64-encoded bodies
    const traces = captureState.traces.map((trace) => ({
      id: trace.id,
      timestamp: trace.timestamp,
      type: trace.type,
      request: trace.request,
      response: trace.response,
      timing: trace.timing,
      initiator: trace.initiator,
      context_refs: trace.context_refs,
      request_body_b64: bytesToBase64(trace._requestBodyBytes),
      response_body_b64: bytesToBase64(trace._responseBodyBytes),
    }));

    // Build WebSocket connections with messages
    const wsConnections = [];
    for (const [, connection] of captureState.wsConnections) {
      const messages = connection.messages.map((msg) => ({
        id: msg.id,
        connection_ref: msg.connection_ref,
        timestamp: msg.timestamp,
        direction: msg.direction,
        opcode: msg.opcode,
        payload_file: msg.payload_file,
        payload_size: msg.payload_size,
        context_refs: msg.context_refs,
        payload_b64: bytesToBase64(msg._payloadBytes),
      }));

      wsConnections.push({
        id: connection.id,
        timestamp: connection.timestamp,
        url: connection.url,
        handshake_trace_ref: connection.handshake_trace_ref,
        protocols: connection.protocols,
        message_count: connection.message_count,
        context_refs: connection.context_refs,
        messages,
      });
    }

    const payload = {
      type: 'store_capture',
      app_name: appName,
      manifest,
      traces,
      ws_connections: wsConnections,
      contexts: captureState.contexts,
      timeline: { events: captureState.timeline },
    };

    const response = await chrome.runtime.sendNativeMessage(
      'com.spectral.capture_host',
      payload
    );

    captureState.state = State.IDLE;
    return response;
  } catch (error) {
    captureState.state = State.IDLE;
    throw error;
  }
}
