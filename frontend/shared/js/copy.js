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

export const POWERS = {
  HELP: { jp: '救援', en: 'Help', desc: 'Call a volunteer to your team.' },
  ATTACK: { jp: '攻撃', en: 'Attack', desc: 'Freeze a rival team unless they defend.' },
  DEFENCE: { jp: '防御', en: 'Defence', desc: 'Cancel an attack on your team.' },
};

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
  { en: '<strong>Attack</strong> freezes a rival for a while unless they use <strong>Defence</strong> in time. <strong>Help</strong> calls a volunteer.', jp: '攻撃・防御・救援の特殊能力を使いこなせ。' },
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
