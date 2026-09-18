// Round 1's admin login screen (username + password).
import { api, setToken } from '../../../shared/js/api.js';
import { HEADERS } from '../../../shared/js/copy.js';
import { toast } from '../../../shared/js/ui.js';

export function renderLogin(root, navigate) {
  root.innerHTML = `
    <div class="bracket-header"><span class="jp">${HEADERS.adminLogin.jp}</span><span class="en">${HEADERS.adminLogin.en} · ROUND 2</span></div>
    <form id="admin-login-form" style="margin-top:var(--gap-md);">
      <div class="field">
        <label class="tier-label"><span class="primary">ユーザー名</span><span class="secondary">Username</span></label>
        <input id="username" type="text" required autocomplete="username" />
      </div>
      <div class="field">
        <label class="tier-label"><span class="primary">パスワード</span><span class="secondary">Password</span></label>
        <input id="password" type="password" required autocomplete="current-password" />
      </div>
      <div id="err" class="field-error" style="display:none;"></div>
      <button class="cta-btn" id="login-btn" type="submit">ログイン / Log In</button>
    </form>
  `;
  const errBox = root.querySelector('#err');
  root.querySelector('#admin-login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    errBox.style.display = 'none';
    try {
      const res = await api.admin.login(root.querySelector('#username').value.trim(), root.querySelector('#password').value);
      setToken('admin', res.access_token);
      navigate('#/dashboard');
    } catch (err) {
      errBox.textContent = err.message;
      errBox.style.display = 'block';
      toast(err.message, { error: true });
    }
  });
}
