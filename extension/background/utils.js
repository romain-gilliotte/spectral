/**
 * Pure utility functions shared across modules.
 */

import { captureState } from './state.js';

/**
 * Generate zero-padded ID (e.g. padId('t', 1) → "t_0001")
 */
export function padId(prefix, num) {
  return `${prefix}_${String(num).padStart(4, '0')}`;
}

/**
 * Get current timestamp in milliseconds.
 */
export function now() {
  return Date.now();
}

/**
 * Convert a Chrome DevTools Protocol monotonic timestamp (seconds) to epoch ms.
 * Uses the offset computed from the first requestWillBeSent wallTime.
 * Falls back to Date.now() if no offset has been computed yet.
 */
export function toEpochMs(chromeTimestamp) {
  if (captureState.timeOffset !== null) {
    return Math.floor(chromeTimestamp * 1000 + captureState.timeOffset);
  }
  return Date.now();
}

/**
 * Generate a UUID v4.
 */
export function uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Decode base64 to Uint8Array.
 */
export function base64ToBytes(base64) {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

/**
 * Convert string to Uint8Array (UTF-8).
 */
export function stringToBytes(str) {
  return new TextEncoder().encode(str);
}

/**
 * Convert headers from Chrome format to our format.
 * Chrome: { "Name": "value" } or { name: { name, value } }
 * Ours: [{ name, value }]
 */
export function normalizeHeaders(headers) {
  if (!headers) return [];
  if (Array.isArray(headers)) return headers;

  return Object.entries(headers).map(([name, value]) => ({
    name,
    value: typeof value === 'object' ? value.value : String(value),
  }));
}

/**
 * Find contexts within the correlation window (2 seconds before timestamp).
 */
export function findContextRefs(timestamp, windowMs = 2000) {
  const refs = [];
  for (const ctx of captureState.contexts) {
    if (ctx.timestamp >= timestamp - windowMs && ctx.timestamp <= timestamp) {
      refs.push(ctx.id);
    }
  }
  return refs;
}
