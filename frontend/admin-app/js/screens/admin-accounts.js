// Round 1's admin-accounts screen (SUPER_ADMIN only), with Round 2 roles.
import { api } from '../../../shared/js/api.js';
import { esc } from '../../../shared/js/ui.js';
import { confirmModal, guarded, openModal, passwordModal } from '../common.js';

export function renderAdminAccounts(main) {
  main.innerHTML = `
    <div class="admin-topline">
      <h1 class="admin-h1">Admin Accounts</h1>
      <button id="new-admin" class="btn primary"><span class="mi">person_add</span> New Admin</button>
    </div>
    <div class="r2-banner-note info">SUPER_ADMIN: everything. COORDINATOR: run events (setup, live controls, results) but not accounts, event creation or team import/deletion.</div>
    <div id="admins-body"><div class="spinner"></div></div>`;
  const body = main.querySelector('#admins-body');

  async function load() {
    try {
      const admins = await api.admin.admins.list();
      body.innerHTML = `
        <div class="dash-card"><table class="dtable">
          <thead><tr><th>Username</th><th>Role</th><th>Status</th><th></th></tr></thead>
          <tbody>${admins.map((a) => `
            <tr>
              <td class="mono">${esc(a.username)}</td>
              <td><span class="pill NOT_STARTED">${esc(a.role)}</span></td>
              <td>${a.is_active ? '<span class="pill LIVE">active</span>' : '<span class="pill DISQUALIFIED">deactivated</span>'}</td>
              <td><div class="btn-row">
                <button class="btn" data-pw="${a.admin_id}"><span class="mi">key</span> Reset Password</button>
                ${a.is_active
                  ? `<button class="btn danger" data-del="${a.admin_id}"><span class="mi">block</span> Deactivate</button>`
                  : `<button class="btn" data-act="${a.admin_id}"><span class="mi">check</span> Activate</button>`}
              </div></td>
            </tr>`).join('')}</tbody>
        </table></div>`;
      body.querySelectorAll('[data-pw]').forEach((b) => b.addEventListener('click', async () => {
        const pw = await passwordModal('Reset admin password', 6);
        if (pw) await guarded(() => api.admin.admins.setPassword(b.dataset.pw, pw), 'Password updated');
      }));
      body.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
        if (!(await confirmModal('Deactivate this admin account? Their current session stops working immediately.', { okLabel: 'Deactivate', danger: true }))) return;
        if (await guarded(() => api.admin.admins.remove(b.dataset.del), 'Deactivated')) load();
      }));
      body.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', async () => {
        if (await guarded(() => api.admin.admins.activate(b.dataset.act), 'Activated')) load();
      }));
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${esc(err.message)}</p>`;
    }
  }

  main.querySelector('#new-admin').addEventListener('click', () => openModal('New admin', `
    <div class="field"><label class="tier-label"><span class="primary">ユーザー名</span><span class="secondary">Username</span></label><input name="username" required pattern="[A-Za-z0-9_.@-]{3,80}" /></div>
    <div class="field"><label class="tier-label"><span class="primary">パスワード</span><span class="secondary">Password (6+ characters)</span></label><input name="password" type="password" required minlength="6" /></div>
    <div class="field"><label class="tier-label"><span class="primary">役割</span><span class="secondary">Role</span></label>
      <select name="role"><option value="COORDINATOR">COORDINATOR</option><option value="SUPER_ADMIN">SUPER_ADMIN</option></select></div>`, {
    submitLabel: 'Create',
    onSubmit: async (fd) => {
      const ok = await guarded(() => api.admin.admins.create(fd.get('username'), fd.get('password'), fd.get('role')), 'Admin created');
      if (!ok) return false;
      load();
      return true;
    },
  }));

  load();
}
