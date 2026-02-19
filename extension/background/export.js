/**
 * Bundle export: assembles captured data into a ZIP and triggers download.
 */

import { captureState, State } from './state.js';
import { uuid, now } from './utils.js';
import JSZip from '../lib/jszip.js';

/**
 * Export capture data as a ZIP bundle.
 */
export async function exportCapture() {
  if (captureState.traces.length === 0 && captureState.contexts.length === 0) {
    throw new Error('No data to export');
  }

  captureState.state = State.EXPORTING;

  try {
    const zip = new JSZip();

    // Sort timeline by timestamp
    captureState.timeline.sort((a, b) => a.timestamp - b.timestamp);

    // Create manifest
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

    zip.file('manifest.json', JSON.stringify(manifest, null, 2));

    // Add traces
    const tracesFolder = zip.folder('traces');
    for (const trace of captureState.traces) {
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
    for (const [, connection] of captureState.wsConnections) {
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
    for (const ctx of captureState.contexts) {
      contextsFolder.file(`${ctx.id}.json`, JSON.stringify(ctx, null, 2));
    }

    // Add timeline
    zip.file('timeline.json', JSON.stringify({ events: captureState.timeline }, null, 2));

    // Generate ZIP as base64 (URL.createObjectURL not available in service workers)
    const base64 = await zip.generateAsync({ type: 'base64' });

    // Create filename with timestamp
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const domain = captureState.appInfo?.base_url
      ? new URL(captureState.appInfo.base_url).hostname.replace(/\./g, '_')
      : 'unknown';
    const filename = `capture_${domain}_${timestamp}.zip`;

    // Trigger download via data URL
    await chrome.downloads.download({
      url: `data:application/zip;base64,${base64}`,
      filename,
      saveAs: true,
    });

    captureState.state = State.IDLE;
    return { success: true, filename };
  } catch (error) {
    captureState.state = State.IDLE;
    throw error;
  }
}
