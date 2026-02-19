/**
 * GraphQL __typename injection for the Chrome extension.
 *
 * Injects __typename into selection sets so that response objects carry their
 * type names, enabling accurate type inference during analysis.
 */

/**
 * Inject __typename into all selection sets of a GraphQL query string.
 * Uses a lightweight brace-tracking approach (no full parser needed).
 * Skips injection if __typename is already present in a selection set.
 */
export function injectTypename(query) {
  const result = [];
  let i = 0;
  // Stack tracks brace depth; each entry is true if we already saw __typename
  // at that depth level.
  const stack = [];

  while (i < query.length) {
    const ch = query[i];

    // Skip string literals
    if (ch === '"') {
      result.push(ch);
      i++;
      while (i < query.length && query[i] !== '"') {
        if (query[i] === '\\') { result.push(query[i]); i++; }
        if (i < query.length) { result.push(query[i]); i++; }
      }
      if (i < query.length) { result.push(query[i]); i++; }
      continue;
    }

    // Skip comments
    if (ch === '#') {
      while (i < query.length && query[i] !== '\n') {
        result.push(query[i]);
        i++;
      }
      continue;
    }

    if (ch === '{') {
      result.push(ch);
      stack.push(false);
      i++;
      continue;
    }

    if (ch === '}') {
      // Before closing, inject __typename if not already present
      if (stack.length > 0 && !stack[stack.length - 1]) {
        result.push(' __typename ');
      }
      stack.pop();
      result.push(ch);
      i++;
      continue;
    }

    // Detect __typename already present — scan for the word
    if (ch === '_' && query.slice(i, i + 10) === '__typename') {
      // Check it's a standalone word (not part of a larger identifier)
      const before = i > 0 ? query[i - 1] : ' ';
      const after = i + 10 < query.length ? query[i + 10] : ' ';
      if (!/[a-zA-Z0-9_]/.test(before) && !/[a-zA-Z0-9_]/.test(after)) {
        if (stack.length > 0) {
          stack[stack.length - 1] = true;
        }
      }
    }

    result.push(ch);
    i++;
  }

  return result.join('');
}

/**
 * Check if a GraphQL request item is a persisted query (has extensions.persistedQuery
 * but no query string). These are sent by Apollo clients using Automatic Persisted
 * Queries (APQ) — the client sends a hash instead of the full query.
 */
function isPersistedQuery(item) {
  return item
    && typeof item.query !== 'string'
    && item.extensions
    && item.extensions.persistedQuery;
}

/** Build a PersistedQueryNotFound error response for a single operation. */
function persistedQueryNotFoundError() {
  return {
    errors: [{
      message: 'PersistedQueryNotFound',
      extensions: { code: 'PERSISTED_QUERY_NOT_FOUND' },
    }],
  };
}

/**
 * Respond to a paused Fetch request with a synthetic JSON response body,
 * bypassing the actual server.
 */
async function fulfillWithJson(debuggeeId, requestId, responseBody) {
  const json = JSON.stringify(responseBody);
  const body = btoa(unescape(encodeURIComponent(json)));
  await chrome.debugger.sendCommand(debuggeeId, 'Fetch.fulfillRequest', {
    requestId,
    responseCode: 200,
    responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
    body,
  });
}

/**
 * Handle Fetch.requestPaused — intercept GraphQL requests.
 *
 * Two interception modes:
 * 1. Persisted query rejection — if the request uses a persisted query hash
 *    (no query string), respond immediately with PersistedQueryNotFound so
 *    the client retries with the full query text.
 * 2. __typename injection — inject __typename into selection sets so response
 *    objects carry type information for analysis.
 */
export async function handleFetchRequestPaused(params, debuggeeId) {
  const { requestId, request } = params;

  try {
    // Only process POST requests with a body
    if (request.method !== 'POST' || !request.postData) {
      await chrome.debugger.sendCommand(debuggeeId, 'Fetch.continueRequest', { requestId });
      return;
    }

    let body;
    try {
      body = JSON.parse(request.postData);
    } catch {
      await chrome.debugger.sendCommand(debuggeeId, 'Fetch.continueRequest', { requestId });
      return;
    }

    // --- Persisted query detection ---
    // Must run before __typename injection: if the request has no query string,
    // we reject it so the client retries with the full query text.
    if (Array.isArray(body)) {
      const hasPersistedItem = body.some(item => isPersistedQuery(item));
      if (hasPersistedItem) {
        // Respond with errors for the entire batch — Fetch.fulfillRequest applies
        // to the whole HTTP response, so we can't selectively pass through some
        // items. The client will retry the full batch with query strings.
        const responseBody = body.map(() => persistedQueryNotFoundError());
        await fulfillWithJson(debuggeeId, requestId, responseBody);
        return;
      }
    } else if (isPersistedQuery(body)) {
      await fulfillWithJson(debuggeeId, requestId, persistedQueryNotFoundError());
      return;
    }

    // --- __typename injection ---
    let modified = false;

    if (Array.isArray(body)) {
      // Batch GraphQL
      for (const item of body) {
        if (item && typeof item.query === 'string') {
          const injected = injectTypename(item.query);
          if (injected !== item.query) {
            item.query = injected;
            modified = true;
          }
        }
      }
    } else if (body && typeof body.query === 'string') {
      const injected = injectTypename(body.query);
      if (injected !== body.query) {
        body.query = injected;
        modified = true;
      }
    }

    if (modified) {
      const newPostData = JSON.stringify(body);
      await chrome.debugger.sendCommand(debuggeeId, 'Fetch.continueRequest', {
        requestId,
        postData: btoa(unescape(encodeURIComponent(newPostData))),
      });
    } else {
      await chrome.debugger.sendCommand(debuggeeId, 'Fetch.continueRequest', { requestId });
    }
  } catch {
    // On any error, let the request through unmodified
    try {
      await chrome.debugger.sendCommand(debuggeeId, 'Fetch.continueRequest', { requestId });
    } catch {
      // Debugger may have been detached
    }
  }
}
