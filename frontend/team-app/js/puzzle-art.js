// Pictures for the scrambled-picture puzzle, drawn as SVG (no image files to
// load on a weak connection): Borderland-style face cards. The diagonal
// colour sweep plus marks in every ninth make all nine tiles look different.
import { SUIT_PATHS } from '../../shared/js/suit-icons.js';

const CARDS = {
  king: { rank: 'K', word: 'KING', suit: 'HEART', from: '#6b0f14', to: '#f97316', ink: '#fff7ed' },
  queen: { rank: 'Q', word: 'QUEEN', suit: 'SPADE', from: '#1e1b4b', to: '#0ea5e9', ink: '#f0f9ff' },
  jack: { rank: 'J', word: 'JACK', suit: 'DIAMOND', from: '#064e3b', to: '#eab308', ink: '#fefce8' },
  joker: { rank: '★', word: 'JOKER', suit: 'CLUB', from: '#3b0764', to: '#ec4899', ink: '#fdf4ff' },
};

function pictureSVG(id) {
  const c = CARDS[id] || CARDS.king;
  const suit = (x, y, scale, rotate = 0, opacity = 1) =>
    `<path d="${SUIT_PATHS[c.suit]}" fill="${c.ink}" opacity="${opacity}" transform="translate(${x} ${y}) rotate(${rotate}) scale(${scale}) translate(-12 -12)"/>`;
  const index = `<text x="78" y="118" font-family="Georgia, 'Times New Roman', serif" font-size="92" font-weight="700" fill="${c.ink}" text-anchor="middle">${c.rank}</text>${suit(78, 168, 2.4)}`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600">
    <defs>
      <linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c.from}"/><stop offset="1" stop-color="${c.to}"/></linearGradient>
      <radialGradient id="r" cx=".5" cy=".48" r=".5"><stop offset="0" stop-color="#ffffff" stop-opacity=".38"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/></radialGradient>
    </defs>
    <rect width="600" height="600" fill="url(#g)"/>
    <circle cx="300" cy="290" r="250" fill="url(#r)"/>
    <rect x="20" y="20" width="560" height="560" rx="38" fill="none" stroke="${c.ink}" stroke-width="7" opacity=".85"/>
    <circle cx="300" cy="290" r="165" fill="none" stroke="${c.ink}" stroke-width="4" stroke-dasharray="4 14" stroke-linecap="round" opacity=".7"/>
    ${index}
    <g transform="rotate(180 300 300)">${index}</g>
    ${suit(300, 288, 9.5)}
    ${suit(522, 82, 2, 25, 0.75)}
    ${suit(82, 522, 2, -25, 0.75)}
    <text x="300" y="528" font-family="Georgia, 'Times New Roman', serif" font-size="58" font-weight="700" letter-spacing="10" fill="${c.ink}" text-anchor="middle">${c.word}</text>
  </svg>`;
}

/** A CSS-safe data URL for the picture (quotes and brackets escaped). */
export function pictureURL(id) {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(pictureSVG(id)).replace(/'/g, '%27').replace(/\(/g, '%28').replace(/\)/g, '%29')}`;
}
