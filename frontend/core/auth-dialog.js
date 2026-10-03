(() => {
  const dialog = document.createElement('dialog');
  dialog.className = 'auth-dialog';
  dialog.setAttribute('aria-labelledby', 'auth-dialog-title');
  dialog.innerHTML = `
    <div class="auth-dialog__head">
      <div><div class="auth-dialog__eyebrow">Mythic Analyzer</div><h2 id="auth-dialog-title">欢迎回来</h2></div>
      <button class="auth-dialog__close" type="button" aria-label="关闭登录窗口">×</button>
    </div>
    <div class="auth-dialog__body">
      <div class="auth-dialog__tabs" role="tablist" aria-label="账号操作">
        <button type="button" data-auth-mode="login" role="tab" aria-selected="true">登录</button>
        <button type="button" data-auth-mode="register" role="tab" aria-selected="false">注册</button>
      </div>
      <form data-auth-form="login">
        <label>用户名<input name="username" autocomplete="username" minlength="3" maxlength="32" required></label>
        <label>密码<input name="password" type="password" autocomplete="current-password" required></label>
        <button class="auth-dialog__submit" type="submit">登录并继续</button>
      </form>
      <form data-auth-form="register" hidden>
        <label>用户名<input name="username" autocomplete="username" minlength="3" maxlength="32" required></label>
        <label>密码<input name="password" type="password" autocomplete="new-password" required></label>
        <label data-auth-invite hidden>邀请码<input name="inviteCode" autocomplete="off"></label>
        <p class="auth-dialog__hint">普通账户可以绑定自己的 WCL 凭据并运行分析。</p>
        <button class="auth-dialog__submit" type="submit">创建普通账户</button>
      </form>
      <div class="auth-dialog__message" role="alert" aria-live="polite"></div>
    </div>`;
  document.body.append(dialog);

  const title = dialog.querySelector('#auth-dialog-title');
  const message = dialog.querySelector('.auth-dialog__message');
  const invite = dialog.querySelector('[data-auth-invite]');
  let nextPath = '/';
  let loggedIn = false;
  const sessionReady = fetch('/api/auth/me', {cache:'no-store', credentials:'same-origin'})
    .then(response => { loggedIn = response.ok; return loggedIn; })
    .catch(() => false);

  function safePath(value) {
    return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && !value.includes('\\')
      ? value : '/';
  }

  function setMode(mode) {
    const selected = mode === 'register' ? 'register' : 'login';
    dialog.querySelectorAll('[data-auth-mode]').forEach(button =>
      button.setAttribute('aria-selected', String(button.dataset.authMode === selected)));
    dialog.querySelectorAll('[data-auth-form]').forEach(form =>
      form.hidden = form.dataset.authForm !== selected);
    title.textContent = selected === 'register' ? '创建账户' : '欢迎回来';
    message.textContent = '';
    dialog.querySelector(`[data-auth-form="${selected}"] input`)?.focus();
  }

  async function open({mode='login', next='/'} = {}) {
    nextPath = safePath(next);
    setMode(mode);
    if (!dialog.open) dialog.showModal();
    dialog.querySelector(`[data-auth-form="${mode === 'register' ? 'register' : 'login'}"] input`)?.focus();
    document.body.classList.add('auth-dialog-open');
    try {
      const response = await fetch('/api/auth/config', {cache:'no-store'});
      if (!response.ok) return;
      const config = await response.json();
      invite.hidden = !config.registrationRequiresInvite;
      invite.querySelector('input').required = Boolean(config.registrationRequiresInvite);
    } catch (_) { /* The server validates invitations on submit. */ }
  }

  dialog.querySelector('.auth-dialog__close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => {
    document.body.classList.remove('auth-dialog-open');
    const url = new URL(location.href);
    if (url.searchParams.has('auth')) {
      url.searchParams.delete('auth');
      url.searchParams.delete('mode');
      url.searchParams.delete('next');
      history.replaceState(null, '', url.pathname + url.search + url.hash);
    }
  });
  dialog.querySelectorAll('[data-auth-mode]').forEach(button =>
    button.addEventListener('click', () => setMode(button.dataset.authMode)));

  dialog.querySelectorAll('[data-auth-form]').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('.auth-dialog__submit');
    button.disabled = true;
    message.textContent = '';
    try {
      const endpoint = form.dataset.authForm === 'register' ? '/api/auth/register' : '/api/auth/login';
      const payload = {...Object.fromEntries(new FormData(form)), next: nextPath};
      const response = await fetch(endpoint, {
        method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || '操作失败，请稍后重试。');
      loggedIn = true;
      dialog.close();
      location.assign(safePath(result.redirectTo || nextPath));
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }));

  document.addEventListener('click', async event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin) return;
    const publicPaths = new Set(['/', '/index.html', '/raid-guide', '/frontend/tools/raid-guide/index.html']);
    if (publicPaths.has(url.pathname)) return;
    event.preventDefault();
    if (loggedIn || await sessionReady) {
      location.assign(url.pathname + url.search + url.hash);
    } else {
      open({mode: url.searchParams.get('mode') || 'login', next: url.pathname === '/login' ? (url.searchParams.get('next') || '/') : url.pathname + url.search + url.hash});
    }
  });

  window.MythicAuthDialog = {
    open,
    setAuthenticated(value) { loggedIn = Boolean(value); },
  };
  const query = new URLSearchParams(location.search);
  if (query.get('auth') === '1') open({mode:query.get('mode') || 'login', next:query.get('next') || '/'});
})();
