/**
 * Shared mutable state for the capture session.
 *
 * Every module that needs capture data imports `captureState` from here
 * and reads/writes its properties directly.
 */

export const State = {
  IDLE: 'idle',
  ATTACHING: 'attaching',
  CAPTURING: 'capturing',
  EXPORTING: 'exporting',
};

export const captureState = {
  state: State.IDLE,
  captureTabId: null,
  captureStartTime: null,

  // Settings (persisted across sessions via chrome.storage.local)
  settings: {
    injectTypename: true,
    injectApqError: true,
  },

  // Captured data
  traces: [],
  contexts: [],
  wsConnections: new Map(),
  wsMessages: [],
  timeline: [],

  // Pending requests (requestId -> partial trace data)
  pendingRequests: new Map(),

  // ExtraInfo events can arrive before or after their base events.
  // Buffer them keyed by requestId for merging.
  pendingExtraInfo: new Map(),

  // Counters for ID generation
  traceCounter: 0,
  contextCounter: 0,
  wsConnectionCounter: 0,
  wsMessageCounters: new Map(),

  // Tab info captured at start
  appInfo: null,

  // Offset to convert Chrome monotonic timestamps to epoch ms.
  // Computed from the first requestWillBeSent event's wallTime.
  timeOffset: null,
};

/**
 * Reset all capture state to initial values.
 */
export function resetState() {
  captureState.state = State.IDLE;
  captureState.captureTabId = null;
  captureState.captureStartTime = null;
  captureState.traces = [];
  captureState.contexts = [];
  captureState.wsConnections = new Map();
  captureState.wsMessages = [];
  captureState.timeline = [];
  captureState.pendingRequests = new Map();
  captureState.pendingExtraInfo = new Map();
  captureState.traceCounter = 0;
  captureState.contextCounter = 0;
  captureState.wsConnectionCounter = 0;
  captureState.wsMessageCounters = new Map();
  captureState.appInfo = null;
  captureState.timeOffset = null;
}

/**
 * Load settings from chrome.storage.local into captureState.settings.
 * Missing keys fall back to the defaults already in captureState.
 */
export async function loadSettings() {
  try {
    const result = await chrome.storage.local.get('settings');
    if (result.settings) {
      Object.assign(captureState.settings, result.settings);
    }
  } catch {
    // Storage unavailable — keep defaults
  }
}

/**
 * Persist the current settings to chrome.storage.local.
 */
export async function saveSettings() {
  try {
    await chrome.storage.local.set({ settings: { ...captureState.settings } });
  } catch {
    // Storage unavailable — ignore
  }
}
