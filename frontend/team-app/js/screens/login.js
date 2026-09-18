// Round 1's login screen, unchanged in look and fields: team code + password.
import { api, setToken } from '../../../shared/js/api.js';
import { BUTTONS, FIELDS, HEADERS, tierLabelHTML, translateError } from '../../../shared/js/copy.js';
import { friendlyError, toast } from '../../../shared/js/ui.js';

export function renderLogin(root, navigate) {
  root.innerHTML = `
    <div class="bl-login-header-section">
      <div class="bl-login-logo-container">
        <img src="../shared/img/borderland_logo.png" alt="Borderland @ GCEE" class="bl-login-logo" />
      </div>
      <div class="bracket-header" style="padding-top: 6px; padding-bottom: 2px;">
        <span class="jp">${HEADERS.teamLogin.jp}</span>
        <span class="en">${HEADERS.teamLogin.en} · ROUND 2</span>
      </div>
    </div>

    <div class="scroll-area">
      <form id="login-form" autocomplete="on">
        <div class="field">
          <label class="tier-label">${tierLabelHTML(FIELDS.teamCode)}</label>
          <input name="team_code" type="text" autocomplete="username" autocapitalize="characters" spellcheck="false" placeholder="e.g. B@GCEE-1234#" required />
        </div>
        <div class="field">
          <label class="tier-label">${tierLabelHTML(FIELDS.password)}</label>
          <input name="password" type="password" autocomplete="current-password" inputmode="text" placeholder="First 4 digits of the leader's phone" required />
        </div>
        <div id="err" class="field-error" style="display:none;"></div>
      </form>
    </div>

    <div class="cta-dock">
      <button id="submit-btn" form="login-form" class="cta-btn" type="submit">
        ${BUTTONS.login.jp} / ${BUTTONS.login.en}
      </button>
    </div>
  `;

  const form = root.querySelector('#login-form');
  const errBox = root.querySelector('#err');
  const btn = root.querySelector('#submit-btn');
  const saved = localStorage.getItem('bl2_team_code');
  if (saved) form.team_code.value = saved;
  // The submit button lives outside the form (Round 1's bottom CTA dock), so
  // make Enter / the phone keyboard's "Go" key submit explicitly.
  form.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); btn.click(); }
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errBox.style.display = 'none';
    const fd = new FormData(form);
    const teamCode = String(fd.get('team_code') || '').trim();
    const password = String(fd.get('password') || '');
    btn.disabled = true;
    btn.textContent = '...';
    try {
      const res = await api.team.login(teamCode, password);
      setToken('team', res.access_token);
      localStorage.setItem('bl2_team_code', res.team_code || teamCode);
      const pending = sessionStorage.getItem('bl2_pending_scan');
      sessionStorage.removeItem('bl2_pending_scan');
      navigate(pending || '#/home');
    } catch (err) {
      errBox.textContent = friendlyError(err, translateError);
      errBox.style.display = 'block';
      toast(err.message, { error: true });
    } finally {
      btn.disabled = false;
      btn.textContent = `${BUTTONS.login.jp} / ${BUTTONS.login.en}`;
    }
  });
}
