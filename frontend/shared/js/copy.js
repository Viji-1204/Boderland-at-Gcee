// Bilingual copy (Round 1's dictionary + Round 2 additions).
// Values sent to the API are never translated - only the labels beside them.

export const HEADERS = {
  teamLogin: { jp: '【ログイン】', en: 'Login' },
  adminLogin: { jp: '【管理者ログイン】', en: 'Admin Login' },
  leaderboard: { jp: '【順位表】', en: 'Leaderboard' },
  hub: { jp: '【ゲーム】', en: 'Game' },
  account: { jp: '【アカウント】', en: 'Account' },
  scanner: { jp: '【スキャン】', en: 'QR Scanner' },
  radar: { jp: '【レーダー】', en: 'Radar' },
  route: { jp: '【ルート】', en: 'My Route' },
  powers: { jp: '【特殊能力】', en: 'Powers' },
  sentence: { jp: '【暗号文】', en: 'Secret Sentence' },
  puzzle: { jp: '【パズル】', en: 'Checkpoint Puzzle' },
  results: { jp: '【結果】', en: 'Final Results' },
  rules: { jp: '【ルール】', en: 'How to Play' },
  final: { jp: '【ジョーカー】', en: 'Find the Joker' },
};

export const FIELDS = {
  teamCode: { jp: 'チームコード', en: 'Team Code' },
  teamName: { jp: 'チーム名', en: 'Team Name' },
  password: { jp: 'パスワード', en: 'Password' },
  adminUser: { jp: 'ユーザー名', en: 'Username' },
  answer: { jp: '回答', en: 'Your Answer' },
  qrCode: { jp: 'QRコード', en: 'QR Code' },
};

export const BUTTONS = {
  login: { jp: 'ログイン', en: 'Log In' },
  submit: { jp: '送信', en: 'Submit' },
  confirm: { jp: '確認', en: 'Confirm' },
  scan: { jp: 'スキャン', en: 'Scan' },
};

export const TEAM_STATUS = {
  NOT_STARTED: { jp: '準備中', en: 'Getting ready' },
  WAITING: { jp: '開始待ち', en: 'Waiting for the start' },
  ACTIVE: { jp: '探索中', en: 'Hunting' },
  PUZZLE_LOCKED: { jp: 'パズル', en: 'Solve the puzzle' },
  FROZEN: { jp: '凍結', en: 'Frozen' },
  FINAL: { jp: 'ジョーカーへ', en: 'Find the Joker' },
  COMPLETED: { jp: 'クリア', en: 'Completed' },
  DISQUALIFIED: { jp: '失格', en: 'Disqualified' },
};

export const EVENT_STATUS = {
  DRAFT: { jp: '準備中', en: 'Setting up' },
  CONFIGURED: { jp: '開始待ち', en: 'Ready - waiting to start' },
  LIVE: { jp: '進行中', en: 'Live' },
  PAUSED: { jp: '一時停止中', en: 'Paused by the coordinators' },
  ENDED: { jp: '終了', en: 'Game over' },
};

// Power families and the powers in each. `desc` may use {freeze_duration_s},
// {jam_duration_s}, {ward_duration_s}, {guide_duration_s} - filled from the
// event's settings by powerDesc().
export const POWER_FAMILIES = {
  HELP: { jp: '救援', en: 'Help', blurb: 'For you. Used from here.' },
  ATTACK: { jp: '攻撃', en: 'Attack', blurb: 'Pick a rival. They get a few seconds to block it.' },
  DEFENCE: { jp: '防御', en: 'Defence', blurb: 'Shield and Reflect answer an attack; a Ward is raised in advance.' },
};

export const POWERS = {
  GUIDE: { jp: '道しるべ', en: 'Guide', family: 'HELP', desc: 'Reveals your next checkpoint for {guide_duration_min} min: its name, the exact distance and a Google Maps route.' },
  FREEZE: { jp: '凍結', en: 'Freeze', family: 'ATTACK', desc: 'Freezes a rival for {freeze_duration_s}s: no radar, scanner or puzzle.' },
  JAM: { jp: '妨害', en: 'Jam', family: 'ATTACK', desc: "Scrambles a rival's radar for {jam_duration_s}s. They can still scan and solve." },
  TRAP: { jp: '罠', en: 'Trap', family: 'ATTACK', desc: 'Plants a foul on a rival (+1). Fouls decide ties.' },
  SHIELD: { jp: '盾', en: 'Shield', family: 'DEFENCE', desc: 'Blocks one incoming attack.' },
  REFLECT: { jp: '反射', en: 'Reflect', family: 'DEFENCE', desc: 'Blocks an attack and bounces its effect back onto the attacker.' },
  WARD: { jp: '結界', en: 'Ward', family: 'DEFENCE', desc: 'Raise it in advance: every attack is blocked automatically for {ward_duration_min} min.' },
};

/** A power's description with the event's durations filled in. */
export function powerDesc(kind, settings = {}) {
  const s = { ...settings, guide_duration_min: Math.round((settings.guide_duration_s || 180) / 60), ward_duration_min: Math.round((settings.ward_duration_s || 300) / 60) };
  return (POWERS[kind] ? POWERS[kind].desc : '').replace(/\{(\w+)\}/g, (_, k) => (s[k] != null ? s[k] : '?'));
}

export const FACES = {
  JACK: { jp: 'ジャック', en: 'Jack', short: 'J' },
  QUEEN: { jp: 'クイーン', en: 'Queen', short: 'Q' },
  KING: { jp: 'キング', en: 'King', short: 'K' },
};

export const RULES = [
  { en: 'Your team follows its own secret route through the campus checkpoints. Start at the checkpoint the volunteers give you.', jp: '各チームは独自のルートでチェックポイントを巡ります。' },
  { en: '<strong>Scan the QR</strong> at your checkpoint. The right one reveals a <strong>puzzle</strong> and a fragment of your secret sentence.', jp: '正しいQRをスキャンするとパズルと暗号文の断片が現れます。' },
  { en: 'Solve the puzzle to unlock the <strong>radar</strong>. It points to your next checkpoint - but never names it.', jp: 'パズルを解くとレーダーが次の目的地を示します。' },
  { en: 'Scanning <strong>someone else\'s checkpoint</strong> is a foul. Fouls are private, but they decide ties.', jp: '他チームのQRをスキャンするとファウルになります。' },
  { en: 'Meet the <strong>Jack, Queen and King</strong> on the way. After your last checkpoint, the radar leads to the coordinators - <strong>find the Joker</strong>.', jp: 'J・Q・Kを集め、最後にジョーカーを見つけよう。' },
  { en: '<strong>Attacks</strong> - Freeze, Jam or Trap - hit a rival unless they <strong>Shield</strong>, <strong>Reflect</strong> or have a <strong>Ward</strong> up. Lost? A <strong>Guide</strong> shows the exact way to your next checkpoint.', jp: '攻撃・防御・道しるべの特殊能力を使いこなせ。' },
];

export const ERROR_JP = {
  'Invalid team code or password': 'チームコードまたはパスワードが違います',
  'The game is paused by the coordinators. Hold tight!': 'ゲームは一時停止中です',
  'You are frozen! Wait for the timer to run out.': '凍結中です',
};

export function translateError(detail) {
  return ERROR_JP[detail] || null;
}

export function tierLabelHTML(entry) {
  return `<span class="primary">${entry.jp}</span><span class="secondary">${entry.en}</span>`;
}

export function bracketHeaderHTML(entry) {
  return `<div class="bracket-header"><span class="jp">${entry.jp}</span><span class="en">${entry.en}</span></div>`;
}
