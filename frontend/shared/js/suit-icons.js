// Flat suit glyphs (Round 1, unchanged) plus the Round 2 icon family in the
// same 24x24 line style, kept in this one module as the design doc asks.

const PATHS = {
  SPADE: 'M12 2C9 6 4 9.5 4 14a4 4 0 0 0 7 2.6c-.3 2.2-1.2 3.7-2.6 4.9a.6.6 0 0 0 .4 1h6.4a.6.6 0 0 0 .4-1c-1.4-1.2-2.3-2.7-2.6-4.9A4 4 0 0 0 20 14c0-4.5-5-8-8-12z',
  CLUB: 'M12 2a3.2 3.2 0 0 0-3.2 3.2c0 .5.1 1 .3 1.4A3.4 3.4 0 1 0 8.6 13c.9 0 1.7-.3 2.4-.9-.5 2.7-1.6 4.6-3.2 6.1a.6.6 0 0 0 .4 1h8a.6.6 0 0 0 .4-1c-1.6-1.5-2.7-3.4-3.2-6.1.7.6 1.5.9 2.4.9A3.4 3.4 0 1 0 14.9 6.6c.2-.4.3-.9.3-1.4A3.2 3.2 0 0 0 12 2z',
  DIAMOND: 'M12 2c2.5 4 5.5 7 8 10-2.5 3-5.5 6-8 10-2.5-4-5.5-7-8-10 2.5-3 5.5-6 8-10z',
  HEART: 'M12 21s-7.5-4.6-10.2-9.3C.3 9 1.4 5.4 4.7 4.4c2-.6 4 .2 5.3 2 .5.7 1 1.6 2 1.6s1.5-.9 2-1.6c1.3-1.8 3.3-2.6 5.3-2 3.3 1 4.4 4.6 2.9 7.3C19.5 16.4 12 21 12 21z',
};

export function suitIconSVG(code, opts = {}) {
  const size = opts.size || 24;
  const color = code === 'HEART' || code === 'DIAMOND' ? 'red' : 'black';
  const path = PATHS[code] || PATHS.SPADE;
  return `<svg class="suit-icon ${color}" viewBox="0 0 24 24" width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg"><path d="${path}"/></svg>`;
}

export const SUIT_CODES = ['SPADE', 'HEART', 'DIAMOND', 'CLUB'];
export const SUIT_PATHS = PATHS; // 24x24 shapes, reused by the picture puzzle's art

// Stroke icons (currentColor), same weight as Round 1's nav icons.
const GLYPHS = {
  home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
  trophy: '<path d="M8 21h8M12 17v4M6 4h12v4a6 6 0 0 1-12 0V4z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
  scan: '<path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3"/><rect x="7" y="7" width="4" height="4"/><rect x="13" y="13" width="4" height="4"/><path d="M13 7h4v2M7 15v2h2"/>',
  radar: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/><circle cx="12" cy="12" r="1.2"/>',
  route: '<circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M8 19h7a3.5 3.5 0 0 0 0-7H9a3.5 3.5 0 0 1 0-7h7"/>',
  puzzle: '<path d="M10 3h4v2.5a1.5 1.5 0 0 0 3 0V5h2a2 2 0 0 1 2 2v3h-1.5a1.5 1.5 0 0 0 0 3H21v4a2 2 0 0 1-2 2h-3.5v-1.5a1.5 1.5 0 0 0-3 0V19H5a2 2 0 0 1-2-2v-4h1.5a1.5 1.5 0 0 0 0-3H3V7a2 2 0 0 1 2-2h5z"/>',
  sentence: '<path d="M4 5h16M4 10h16M4 15h10"/><path d="M17 15l3 3-3 3"/>',
  powers: '<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/>',
  // Powers. One glyph per kind; families reuse the first of each.
  guide: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2"/>',
  freeze: '<path d="M12 2v20M2 12h20M4.9 4.9l14.2 14.2M19.1 4.9L4.9 19.1"/><path d="M9 3l3 3 3-3M9 21l3-3 3 3M3 9l3 3-3 3M21 9l-3 3 3 3"/>',
  jam: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/><path d="M3 21L21 3"/>',
  trap: '<path d="M3 12h4l2-5 4 10 2-5h6"/><path d="M4 20h16"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>',
  reflect: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 13l3-3 3 3"/><path d="M12 10v7"/>',
  ward: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><circle cx="12" cy="12" r="3"/><path d="M12 6v2M12 16v2M6.5 12h2M15.5 12h2"/>',
  attack: '<path d="M14.5 17.5L3 6V3h3l11.5 11.5"/><path d="M13 19l6-6M16 16l4 4M19 21l2-2"/><path d="M9.5 17.5L21 6V3h-3L6.5 14.5"/><path d="M11 19l-6-6M8 16l-4 4M5 21l-2-2"/>',
  map: '<path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/>',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  snow: '<path d="M12 2v20M2 12h20M4.9 4.9l14.2 14.2M19.1 4.9L4.9 19.1"/><path d="M9 3l3 3 3-3M9 21l3-3 3 3M3 9l3 3-3 3M21 9l-3 3 3 3"/>',
  joker: '<path d="M12 2l2.4 5 5.6.6-4.2 3.8 1.2 5.6L12 14.3 7 17l1.2-5.6L4 7.6 9.6 7z"/><path d="M8 21h8"/>',
  back: '<polyline points="15 18 9 12 15 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  visa: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18M7 15h4"/>',
};

export function glyphSVG(name, opts = {}) {
  const size = opts.size || 24;
  const width = opts.stroke || 2;
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${GLYPHS[name] || ''}</svg>`;
}

/** Radar needle: points "up" at 0deg; rotate the element to the bearing. */
export function needleSVG(size = 180) {
  return `<svg class="r2-needle" viewBox="0 0 100 100" width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <polygon points="50,6 60,50 50,44 40,50" class="r2-needle-tip"/>
    <polygon points="50,94 60,50 50,56 40,50" class="r2-needle-tail"/>
    <circle cx="50" cy="50" r="5" class="r2-needle-hub"/>
  </svg>`;
}
