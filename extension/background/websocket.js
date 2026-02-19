/**
 * WebSocket event handlers (DevTools Protocol Network domain).
 */

import { captureState } from './state.js';
import {
  padId,
  now,
  toEpochMs,
  base64ToBytes,
  stringToBytes,
  normalizeHeaders,
  findContextRefs,
} from './utils.js';

/**
 * Handle Network.webSocketCreated
 */
export function handleWebSocketCreated(params) {
  const { requestId, url } = params;

  captureState.wsConnectionCounter++;
  const wsId = padId('ws', captureState.wsConnectionCounter);

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

  captureState.wsConnections.set(requestId, connection);
  captureState.wsMessageCounters.set(wsId, 0);

  captureState.timeline.push({
    timestamp: connection.timestamp,
    type: 'ws_open',
    ref: wsId,
  });
}

/**
 * Handle Network.webSocketHandshakeResponseReceived
 */
export function handleWebSocketHandshake(params) {
  const { requestId, response } = params;

  const connection = captureState.wsConnections.get(requestId);
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
export function handleWebSocketFrameSent(params) {
  const { requestId, timestamp, response } = params;

  const connection = captureState.wsConnections.get(requestId);
  if (!connection) return;

  const wsId = connection.id;
  const counter = captureState.wsMessageCounters.get(wsId) + 1;
  captureState.wsMessageCounters.set(wsId, counter);

  const msgId = `${wsId}_m${String(counter).padStart(3, '0')}`;
  const ts = toEpochMs(timestamp);

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
  captureState.wsMessages.push(message);

  captureState.timeline.push({
    timestamp: ts,
    type: 'ws_message',
    ref: msgId,
  });
}

/**
 * Handle Network.webSocketFrameReceived
 */
export function handleWebSocketFrameReceived(params) {
  const { requestId, timestamp, response } = params;

  const connection = captureState.wsConnections.get(requestId);
  if (!connection) return;

  const wsId = connection.id;
  const counter = captureState.wsMessageCounters.get(wsId) + 1;
  captureState.wsMessageCounters.set(wsId, counter);

  const msgId = `${wsId}_m${String(counter).padStart(3, '0')}`;
  const ts = toEpochMs(timestamp);

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
  captureState.wsMessages.push(message);

  captureState.timeline.push({
    timestamp: ts,
    type: 'ws_message',
    ref: msgId,
  });
}

/**
 * Handle Network.webSocketClosed
 */
export function handleWebSocketClosed(_params) {
  // Connection is kept in wsConnections map - no action needed
}
