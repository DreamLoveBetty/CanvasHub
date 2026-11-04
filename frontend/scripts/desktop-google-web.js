// Independent Web account UI. Cookie input is transient; scheduling belongs to server.
(function () {
  function create({request, escapeHtml, onRender}) {
    let status = null, busy = false, message = '', profiles = [], hasError = false;
    const esc = escapeHtml;
    const names = {available:'可用', unchecked:'待检查', busy:'使用中', cooldown:'冷却中', requires_relogin:'需更新登录态', disabled:'已停用'};
    const button = (action, label, attrs='') => `<button type="button" data-google-web-action="${action}" ${attrs}${busy?' disabled':''}>${label}</button>`;
    function render() {
      const items = status?.items || [];
      const accounts = items.map(account => {
        const attrs = `data-google-web-id="${esc(account.id)}"`;
        const cooldown = account.state === 'cooldown' ? ` · ${Math.max(0,Math.ceil((account.cooldown_until*1000-Date.now())/1000))} 秒` : '';
        const name=account.display_name||account.email||account.label||'Web 账号';
        const identity=[account.display_name&&account.email, (account.display_name||account.email)&&account.label].filter(Boolean);
        if(Number.isInteger(account.authuser))identity.push(`Google 账号 ${account.authuser+1}`);
        return `<div class="desk-google-web-account">
          <div class="desk-google-web-account__head"><strong>${esc(name)}</strong><span>${esc(names[account.state] || '未知')}${cooldown}</span></div>
          ${identity.length?`<p>${identity.map(esc).join(' · ')}</p>`:''}
          <div class="desk-google-web-account__actions"><small>成功 ${Number(account.success_count||0)} · 额度未知</small>
            ${button('account-check','检查登录态',attrs)}
            ${button('account-expand','识别同会话账号',attrs)}
            ${button('account-update',account.enabled?'停用':'启用',attrs+` data-google-web-enabled="${!account.enabled}"`)}
            ${button('account-delete','删除',attrs)}
          </div>
          ${account.last_error?`<p class="desk-google-web-error">${esc(account.last_error)}</p>`:''}
        </div>`;
      }).join('');
      return `<section class="desk-google-web" data-google-web-panel aria-busy="${busy}">
        <div class="desk-google-web-toolbar"><div><h3>Gemini Web</h3><p>${status?`${status.enabled?'已启用':'已关闭'} · ${items.length} 个账号 · 可用 ${Number(status.stats?.available||0)} · 使用中 ${Number(status.stats?.inflight||0)}`:'未连接'}</p></div>
          <div class="desk-google-web-actions">${button('config',status?.enabled?'关闭':'启用',status?'':'disabled ')}${button('status','刷新')}</div></div>
        <p>在模型节点的「线路」选择 Gemini Web。账号由服务端自动调度，不影响 Google OAuth。点击「检查登录态」可识别实际名称和邮箱，不消耗生图额度。</p>
        ${status?.capabilities?.backend_available===false?'<p class="desk-google-web-error">Web 运行依赖未安装，请在服务端安装 Web 依赖并重启账号服务。</p>':''}
        ${busy||message?`<p class="desk-google-web-feedback${hasError?' desk-google-web-error':''}" role="${hasError?'alert':'status'}">${esc(message||(busy?'处理中…':''))}</p>`:''}
        <section class="desk-google-web-import"><strong>添加 Web 账号 · 导入 Cookie JSON</strong><div class="desk-google-web-import__body">
          <label>账号名称（可选）<input type="text" maxlength="120" data-google-web-label autocomplete="off"></label>
          <textarea rows="4" data-google-web-cookies autocomplete="off" spellcheck="false" aria-label="Web Cookie JSON" placeholder="粘贴浏览器导出的 Cookie JSON，保存后不回显"></textarea>
          <div class="desk-google-web-actions">${button('accounts-import','导入 Cookie')}<label class="desk-google-web-file">选择 JSON 文件<input type="file" accept=".json,application/json" data-google-web-file${busy?' disabled':''}></label></div>
          <p>Cookie 仅保存在服务端；不写入浏览器设置或工作流。支持单账号 Cookie 导出，或 accounts 多账号列表。</p>
        </div></section>
        ${status?.capabilities?.browser_import?`<div class="desk-google-web-browser">${button('browser-profiles','从服务端本机 Chrome 导入')}
          ${profiles.length?`<select class="desk-select" data-google-web-profile aria-label="服务端 Chrome Profile">${profiles.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('')}</select>${button('browser-import','导入所选 Profile')}`:''}
          <p>Profile 是 Chrome 用户目录，不是 Google 账号。导入会分别识别该用户内已登录的 Google 账号；已有会话也可点击「识别同会话账号」，无需重读 Chrome。如出现系统授权，请在服务端本机完成。</p></div>`:''}
        <div class="desk-google-web-accounts">${accounts||'<p>暂无 Web 账号，请先导入 Cookie。</p>'}</div>
      </section>`;
    }
    async function run(action, body) {
      if (busy) return;
      busy = true; hasError = false;
      message = action==='browser-profiles'?'正在读取服务端 Chrome Profile 列表…'
        :action==='browser-import'?'正在读取 Chrome 并识别其中的 Google 账号，如出现 macOS 授权弹窗，请在服务端电脑完成。'
        :action==='account-expand'?'正在识别该会话中的 Google 账号，不消耗生图额度…':'';
      if(action==='browser-profiles')profiles=[];
      onRender();
      try {
        const result = await request(action,body);
        if (action==='browser-profiles') {
          profiles=result.items||[];
          message=profiles.length?`找到 ${profiles.length} 个 Chrome Profile，请选择一个 Profile，再点击「导入所选 Profile」。`:'服务端未找到可导入的 Chrome Profile。';
        }
        else {status=result;message=action==='status'?'':Number.isInteger(result.imported)?`已导入 ${result.imported} 个 Google 账号；可分别检查登录态。`:'已完成';}
      } catch(error) {hasError=true;message=error.message||'Web 账号操作失败';}
      finally {busy=false;onRender();}
    }
    function importBody(raw, label) {
      return {accounts:Array.isArray(raw?.accounts)?raw.accounts:[{label,cookies:raw}]};
    }
    function handleClick(event) {
      const control=event.target.closest('[data-google-web-action]');
      if(!control)return false;
      event.preventDefault();if(busy||control.disabled)return true;
      const action=control.dataset.googleWebAction, panel=control.closest('[data-google-web-panel]');
      let body=action==='status'?undefined:{};
      if(action==='config')body.enabled=!status?.enabled;
      if(action==='accounts-import') {
        const input=panel.querySelector('[data-google-web-cookies]');
        try {body=importBody(JSON.parse(input.value),panel.querySelector('[data-google-web-label]')?.value||'');}
        catch(_){hasError=true;message='请输入有效的 Cookie JSON。';onRender();return true;}
        input.value='';
      }
      if(action==='browser-import')body.profile=panel.querySelector('[data-google-web-profile]')?.value;
      if(action.startsWith('account-')){
        body.account_id=control.dataset.googleWebId;
        if(action==='account-update')body.enabled=control.dataset.googleWebEnabled==='true';
        if(action==='account-delete'&&!window.confirm('仅删除此 Web 账号的本地 Cookie？不会删除 OAuth 或 GPT 授权。'))return true;
      }
      void run(action,body);return true;
    }
    function handleChange(event) {
      const input=event.target.closest('[data-google-web-file]');if(!input)return false;
      const file=input.files?.[0], panel=input.closest('[data-google-web-panel]');
      if(file&&!busy)void (async()=>{
        try {if(file.size>2*1024*1024)throw Error();const raw=JSON.parse(await file.text());
          await run('accounts-import',importBody(raw,panel.querySelector('[data-google-web-label]')?.value||''));
        }catch(_){hasError=true;message='请选择不超过 2 MB 的有效 Cookie JSON。';onRender();}
        finally{input.value='';}
      })();
      return true;
    }
    return {render,handleClick,handleChange,refresh:()=>run('status')};
  }
  window.DesktopGoogleWeb={create};
})();
