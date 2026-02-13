/**
 * API Discover - Content Script
 *
 * Captures UI context (clicks, inputs, form submissions, navigation)
 * and sends it to the background script for correlation with network traffic.
 *
 * Captures rich page context to help the LLM understand the business meaning
 * of API calls.
 */

// ============================================================================
// Configuration
// ============================================================================

const CONFIG = {
  // Debounce time for input events (ms)
  INPUT_DEBOUNCE_MS: 300,

  // Maximum text length for element text
  MAX_ELEMENT_TEXT: 100,

  // Maximum text length for main content
  MAX_MAIN_TEXT: 500,

  // Attributes to skip (framework noise)
  SKIP_ATTRIBUTES: [
    /^ng-/,
    /^_ngcontent/,
    /^_nghost/,
    /^data-reactid/,
    /^data-react-/,
    /^data-v-/,
    /^data-styled/,
    /^style$/,
    /^class$/,
  ],

  // Useful data attributes to keep
  KEEP_DATA_ATTRS: [
    'data-testid',
    'data-test',
    'data-cy',
    'data-id',
    'data-action',
    'data-tab',
    'data-page',
    'data-value',
  ],
};

// ============================================================================
// State
// ============================================================================

let inputDebounceTimer = null;
let lastInputElement = null;

// ============================================================================
// Utility functions
// ============================================================================

/**
 * Get current timestamp in milliseconds
 */
function now() {
  return Date.now();
}

/**
 * Truncate text to max length
 */
function truncate(text, maxLen) {
  if (!text) return '';
  text = text.trim().replace(/\s+/g, ' ');
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3) + '...';
}

/**
 * Check if an ID looks stable (not generated/hashed)
 */
function isStableId(id) {
  if (!id) return false;
  // Skip IDs that look like generated hashes or contain UUIDs
  if (/[0-9a-f]{8,}/i.test(id) && !/[a-z]{3,}/i.test(id)) return false;
  if (/^[a-z0-9]{20,}$/i.test(id)) return false;
  if (/ember\d+|react-/i.test(id)) return false;
  return true;
}

/**
 * Check if an attribute should be kept
 */
function shouldKeepAttribute(name) {
  // Check if explicitly kept
  if (CONFIG.KEEP_DATA_ATTRS.includes(name)) return true;

  // Check if matches skip pattern
  for (const pattern of CONFIG.SKIP_ATTRIBUTES) {
    if (pattern.test(name)) return false;
  }

  // Keep common useful attributes
  const keepList = ['id', 'name', 'type', 'href', 'src', 'value', 'placeholder', 'aria-label', 'role', 'title'];
  if (keepList.includes(name)) return true;

  // Keep data-* that aren't in skip list
  if (name.startsWith('data-')) return true;

  return false;
}

/**
 * Generate a CSS selector for an element
 */
function generateSelector(element) {
  if (!element || element === document.body || element === document.documentElement) {
    return 'body';
  }

  // Try ID if stable
  if (element.id && isStableId(element.id)) {
    return `#${CSS.escape(element.id)}`;
  }

  // Try data-testid
  const testId = element.getAttribute('data-testid') || element.getAttribute('data-test') || element.getAttribute('data-cy');
  if (testId) {
    return `[data-testid="${CSS.escape(testId)}"]`;
  }

  // Try name for form controls
  if (element.name && ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(element.tagName)) {
    return `${element.tagName.toLowerCase()}[name="${CSS.escape(element.name)}"]`;
  }

  // Build path with tag + class + nth-child
  const parts = [];
  let current = element;
  let depth = 0;

  while (current && current !== document.body && depth < 5) {
    let selector = current.tagName.toLowerCase();

    // Add meaningful classes (skip framework classes)
    const classes = Array.from(current.classList)
      .filter((c) => !/^(ng-|_ng|react-|styled-|css-|sc-|emotion-|chakra-)/.test(c))
      .filter((c) => !/^[a-z0-9]{8,}$/i.test(c))
      .slice(0, 2);

    if (classes.length > 0) {
      selector += '.' + classes.map((c) => CSS.escape(c)).join('.');
    }

    // Add nth-child if needed for uniqueness
    const parent = current.parentElement;
    if (parent) {
      const siblings = Array.from(parent.children).filter((c) => c.tagName === current.tagName);
      if (siblings.length > 1) {
        const index = siblings.indexOf(current) + 1;
        selector += `:nth-child(${index})`;
      }
    }

    parts.unshift(selector);
    current = parent;
    depth++;
  }

  return parts.join(' > ');
}

/**
 * Generate XPath for an element
 */
function generateXPath(element) {
  if (!element) return '';

  const parts = [];
  let current = element;

  while (current && current.nodeType === Node.ELEMENT_NODE) {
    let index = 1;
    let sibling = current.previousSibling;

    while (sibling) {
      if (sibling.nodeType === Node.ELEMENT_NODE && sibling.tagName === current.tagName) {
        index++;
      }
      sibling = sibling.previousSibling;
    }

    const tagName = current.tagName.toLowerCase();
    parts.unshift(`${tagName}[${index}]`);
    current = current.parentElement;
  }

  return '/' + parts.join('/');
}

/**
 * Extract element info
 */
function extractElementInfo(element) {
  if (!element) {
    return {
      selector: '',
      tag: '',
      text: '',
      attributes: {},
      xpath: '',
    };
  }

  // Get visible text content
  let text = '';
  if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') {
    text = element.placeholder || element.getAttribute('aria-label') || '';
  } else if (element.tagName === 'SELECT') {
    const selected = element.options[element.selectedIndex];
    text = selected?.text || '';
  } else {
    text = element.textContent || '';
  }

  // Extract filtered attributes
  const attributes = {};
  for (const attr of element.attributes) {
    if (shouldKeepAttribute(attr.name)) {
      // Don't capture actual input values for privacy
      if (attr.name === 'value' && ['INPUT', 'TEXTAREA'].includes(element.tagName)) {
        continue;
      }
      attributes[attr.name] = attr.value;
    }
  }

  return {
    selector: generateSelector(element),
    tag: element.tagName,
    text: truncate(text, CONFIG.MAX_ELEMENT_TEXT),
    attributes,
    xpath: generateXPath(element),
  };
}

/**
 * Extract page content for LLM context
 */
function extractPageContent() {
  const content = {
    headings: [],
    navigation: [],
    main_text: '',
    forms: [],
    tables: [],
    alerts: [],
  };

  try {
    // Extract visible headings (h1-h3)
    const headings = document.querySelectorAll('h1, h2, h3');
    const seenHeadings = new Set();
    for (const h of headings) {
      if (!isElementVisible(h)) continue;
      const text = truncate(h.textContent, 80);
      if (text && !seenHeadings.has(text)) {
        seenHeadings.add(text);
        content.headings.push(text);
      }
      if (content.headings.length >= 10) break;
    }

    // Extract navigation items
    const navElements = document.querySelectorAll('nav a, [role="navigation"] a, .nav a, .menu a, header a');
    const seenNav = new Set();
    for (const a of navElements) {
      if (!isElementVisible(a)) continue;
      const text = truncate(a.textContent, 40);
      if (text && !seenNav.has(text) && text.length > 1) {
        seenNav.add(text);
        content.navigation.push(text);
      }
      if (content.navigation.length >= 15) break;
    }

    // Extract main text content
    const mainSelectors = ['main', '[role="main"]', 'article', '.content', '.main-content', '#content'];
    let mainElement = null;
    for (const sel of mainSelectors) {
      mainElement = document.querySelector(sel);
      if (mainElement) break;
    }
    if (!mainElement) {
      mainElement = document.body;
    }

    // Get meaningful text from main content
    const walker = document.createTreeWalker(mainElement, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => {
        const parent = node.parentElement;
        if (!parent || !isElementVisible(parent)) return NodeFilter.FILTER_REJECT;
        if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG'].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
        const text = node.textContent.trim();
        if (text.length < 5) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    const textParts = [];
    let totalLen = 0;
    while (walker.nextNode() && totalLen < CONFIG.MAX_MAIN_TEXT) {
      const text = walker.currentNode.textContent.trim();
      if (text.length > 3) {
        textParts.push(text);
        totalLen += text.length;
      }
    }
    content.main_text = truncate(textParts.join(' '), CONFIG.MAX_MAIN_TEXT);

    // Extract form info
    const forms = document.querySelectorAll('form');
    for (const form of forms) {
      if (!isElementVisible(form)) continue;

      const formInfo = {
        id: form.id || form.name || null,
        fields: [],
        submitLabel: '',
      };

      // Get field names
      const inputs = form.querySelectorAll('input, select, textarea');
      for (const input of inputs) {
        const name = input.name || input.id || input.placeholder;
        if (name && !formInfo.fields.includes(name)) {
          formInfo.fields.push(name);
        }
        if (formInfo.fields.length >= 10) break;
      }

      // Get submit button text
      const submitBtn = form.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
      if (submitBtn) {
        formInfo.submitLabel = truncate(submitBtn.textContent || submitBtn.value || 'Submit', 30);
      }

      if (formInfo.fields.length > 0) {
        content.forms.push(formInfo);
      }
      if (content.forms.length >= 5) break;
    }

    // Extract table headers
    const tables = document.querySelectorAll('table');
    for (const table of tables) {
      if (!isElementVisible(table)) continue;

      const headerRow = table.querySelector('thead tr, tr:first-child');
      if (headerRow) {
        const headers = Array.from(headerRow.querySelectorAll('th, td'))
          .map((cell) => truncate(cell.textContent, 30))
          .filter((t) => t);

        if (headers.length > 0) {
          content.tables.push(headers.join(' | '));
        }
      }
      if (content.tables.length >= 5) break;
    }

    // Extract alerts/notifications
    const alertSelectors = [
      '[role="alert"]',
      '.alert',
      '.notification',
      '.toast',
      '.message',
      '.error',
      '.success',
      '.warning',
      '.info-message',
    ];
    for (const sel of alertSelectors) {
      const alerts = document.querySelectorAll(sel);
      for (const alert of alerts) {
        if (!isElementVisible(alert)) continue;
        const text = truncate(alert.textContent, 100);
        if (text && !content.alerts.includes(text)) {
          content.alerts.push(text);
        }
        if (content.alerts.length >= 5) break;
      }
    }
  } catch (e) {
    console.error('Error extracting page content:', e);
  }

  return content;
}

/**
 * Check if element is visible
 */
function isElementVisible(element) {
  if (!element) return false;

  const style = getComputedStyle(element);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
    return false;
  }

  const rect = element.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) {
    return false;
  }

  return true;
}

/**
 * Get viewport info
 */
function getViewportInfo() {
  return {
    width: window.innerWidth,
    height: window.innerHeight,
    scroll_x: window.scrollX,
    scroll_y: window.scrollY,
  };
}

/**
 * Get page info
 */
function getPageInfo() {
  return {
    url: window.location.href,
    title: document.title,
    content: extractPageContent(),
  };
}

/**
 * Send context to background script
 */
function sendContext(action, element = null) {
  const context = {
    timestamp: now(),
    action,
    element: extractElementInfo(element),
    page: getPageInfo(),
    viewport: getViewportInfo(),
  };

  chrome.runtime.sendMessage({
    type: 'ADD_CONTEXT',
    context,
  });
}

// ============================================================================
// Event handlers
// ============================================================================

/**
 * Handle click events
 */
function handleClick(event) {
  const target = event.target;

  // Skip if not a meaningful click target
  if (!target || target === document.body || target === document.documentElement) {
    return;
  }

  // Find the most meaningful ancestor (button, link, etc.)
  let meaningfulTarget = target;
  const meaningfulTags = ['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'LABEL'];
  const meaningfulRoles = ['button', 'link', 'tab', 'menuitem', 'checkbox', 'radio', 'option'];

  let current = target;
  while (current && current !== document.body) {
    if (meaningfulTags.includes(current.tagName) || meaningfulRoles.includes(current.getAttribute('role'))) {
      meaningfulTarget = current;
      break;
    }
    current = current.parentElement;
  }

  sendContext('click', meaningfulTarget);
}

/**
 * Handle input events (debounced)
 */
function handleInput(event) {
  const target = event.target;

  // Only track form inputs
  if (!['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) {
    return;
  }

  // Debounce to avoid spam
  lastInputElement = target;

  if (inputDebounceTimer) {
    clearTimeout(inputDebounceTimer);
  }

  inputDebounceTimer = setTimeout(() => {
    if (lastInputElement) {
      sendContext('input', lastInputElement);
      lastInputElement = null;
    }
  }, CONFIG.INPUT_DEBOUNCE_MS);
}

/**
 * Handle form submit
 */
function handleSubmit(event) {
  const form = event.target;
  sendContext('submit', form);
}

/**
 * Handle navigation (SPA and full page)
 */
let lastUrl = window.location.href;

function handleNavigation() {
  const currentUrl = window.location.href;
  if (currentUrl !== lastUrl) {
    lastUrl = currentUrl;
    // Small delay to let the page update
    setTimeout(() => {
      sendContext('navigate', null);
    }, 100);
  }
}

// ============================================================================
// Setup
// ============================================================================

// Click listener (capture phase to catch all clicks)
document.addEventListener('click', handleClick, true);

// Input listener
document.addEventListener('input', handleInput, true);

// Form submit listener
document.addEventListener('submit', handleSubmit, true);

// Navigation listeners
// pushState/replaceState interception
const originalPushState = history.pushState;
const originalReplaceState = history.replaceState;

history.pushState = function (...args) {
  originalPushState.apply(this, args);
  handleNavigation();
};

history.replaceState = function (...args) {
  originalReplaceState.apply(this, args);
  handleNavigation();
};

// popstate for back/forward
window.addEventListener('popstate', handleNavigation);

// Initial page context (if loaded mid-capture)
setTimeout(() => {
  sendContext('navigate', null);
}, 500);

console.log('API Discover content script loaded');
