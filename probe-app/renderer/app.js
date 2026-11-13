document.addEventListener('DOMContentLoaded', async () => {
  const $ = (id) => document.getElementById(id);
  const pageMeta = {
    dashboard:['Workspace overview','Your secure AI workspace, at a glance.'],
    shares:['Workspace shares','Manage folders and AI client access.'],
    permissions:['Access & permissions','Review and manage capability boundaries.'],
    network:['Network','Connectivity, gateway and reachability status.'],
    sandbox:['Sandbox & CLI','Isolated command execution and file exchange.'],
    ide:['IDE integrations','Connect supported development environments.'],
    'computer-use':['Computer use','Manage the optional computer-use provider.'],
    monitor:['AI Realtime Monitor','Live AI client sessions, capabilities and activity.'],
    downloads:['Desktop installers','Download SF2AiS desktop applications for supported platforms.'],
    activity:['Activity & logs','Review local probe events and diagnostics.'],
    settings:['System settings','Configure the local desktop agent.']
  };
  function toast(message, error=false) {
    const el=document.createElement('div');el.className='toast'+(error?' err':'');el.textContent=message;
    $('toast-region').appendChild(el);setTimeout(()=>el.remove(),3200);
  }
  function setPage(name) {
    if(!pageMeta[name]) name='dashboard';
    document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='page-'+name));
    document.querySelectorAll('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.page===name));
    $('page-title').textContent=pageMeta[name][0];
    const subtitle=window.api.runtime==='web'&&name==='settings'?'Configure server network, routing and remote access.':window.api.runtime==='web'&&name==='activity'?'Review server-side audit events and diagnostics.':pageMeta[name][1];
    $('page-subtitle').textContent=subtitle;$('breadcrumb').textContent=name.toUpperCase().replace('-',' ');
    history.replaceState(null,'','#'+name);
    if(name==='activity') refreshLogs();
    if(name==='monitor') document.dispatchEvent(new CustomEvent('sf2ais:monitor-visible'));
    else document.dispatchEvent(new CustomEvent('sf2ais:monitor-hidden'));
  }
  $('window-minimize')?.addEventListener('click',()=>window.api.minimizeWindow());
  $('window-maximize')?.addEventListener('click',()=>window.api.toggleMaximizeWindow());
  $('window-close')?.addEventListener('click',()=>window.api.closeWindow());
  document.querySelectorAll('.nav-item').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.page)));
  document.querySelectorAll('[data-open-page]').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.openPage)));
  document.querySelectorAll('[data-open-page]').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.openPage)));
  const hash=location.hash.replace('#','');if(pageMeta[hash])setPage(hash);
  const cfgEls={gatewayUrl:$('gateway-url'),probeToken:$('probe-token'),duckdnsSubdomain:$('duckdns-subdomain'),duckdnsToken:$('duckdns-token'),interval:$('interval'),startWithWindows:$('start-with-windows')};
  const appearanceDefaults={backgroundOpacity:0,cardOpacity:78,windowBorderStart:'#a07eff',windowBorderEnd:'#398fff',cardBorderStart:'#a897ff',cardBorderEnd:'#398fff',cardFrostStart:'#191f43',cardFrostEnd:'#26376b'};
  const appearanceIds={backgroundOpacity:'background-opacity',cardOpacity:'card-opacity',windowBorderStart:'window-border-start',windowBorderEnd:'window-border-end',cardBorderStart:'card-border-start',cardBorderEnd:'card-border-end',cardFrostStart:'card-frost-start',cardFrostEnd:'card-frost-end'};
  let appearanceSaveTimer=null;
  function hexToRgb(value){
    const match=/^#([0-9a-f]{6})$/i.exec(String(value||''));if(!match)return '160, 126, 255';
    const hex=match[1];return [0,2,4].map(i=>parseInt(hex.slice(i,i+2),16)).join(', ');
  }
  function readAppearance(){
    const result={};
    for(const [key,id] of Object.entries(appearanceIds)){
      const el=$(id);if(!el)continue;
      result[key]=key.toLowerCase().includes('opacity')?Math.min(100,Math.max(key==='cardOpacity'?25:0,Number(el.value)||0)):el.value;
    }
    return result;
  }
  function applyAppearance(values={}){
    const settings={...appearanceDefaults,...values};
    const root=document.documentElement;
    root.style.setProperty('--background-opacity',String(Math.min(1,Math.max(0,Number(settings.backgroundOpacity)||0)/100)));
    root.style.setProperty('--card-opacity',String(Math.min(1,Math.max(.25,Number(settings.cardOpacity??78)/100))));
    root.style.setProperty('--window-border-rgb',hexToRgb(settings.windowBorderStart));
    root.style.setProperty('--window-glow-rgb',hexToRgb(settings.windowBorderEnd));
    root.style.setProperty('--card-border-rgb',hexToRgb(settings.cardBorderStart));
    root.style.setProperty('--card-glow-rgb',hexToRgb(settings.cardBorderEnd));
    root.style.setProperty('--card-frost-start-rgb',hexToRgb(settings.cardFrostStart));
    root.style.setProperty('--card-frost-end-rgb',hexToRgb(settings.cardFrostEnd));
    for(const [key,id] of Object.entries(appearanceIds)){
      const el=$(id);if(!el)continue;
      el.value=settings[key];
      if(key==='backgroundOpacity'||key==='cardOpacity')$(id+'-value').textContent=String(settings[key])+'%';
    }
  }
  function persistAppearance(){
    clearTimeout(appearanceSaveTimer);
    appearanceSaveTimer=setTimeout(async()=>{try{await window.api.saveConfig(readAppearance());}catch(error){toast('Could not save appearance: '+error.message,true);}},180);
  }
  Object.values(appearanceIds).forEach(id=>{
    const el=$(id);if(!el)return;
    el.addEventListener('input',()=>applyAppearance(readAppearance()));
    el.addEventListener('change',persistAppearance);
  });
  $('btn-reset-appearance')?.addEventListener('click',()=>{applyAppearance(appearanceDefaults);persistAppearance();toast('Default appearance restored.');});
  function updateUI(status={}) {
    const set=(id,v)=>{const e=$(id);if(e)e.textContent=v;};
    if(window.api.runtime==='web'){
      const healthy=status.backendHealthy===true;
      const checked=status.lastCheckAt?new Date(status.lastCheckAt).toLocaleString():'Not checked';
      const stateLabel=healthy?'Backend API responding':status.error||'Backend health check failed';
      set('status-text',healthy?'Backend healthy':'Backend unavailable');
      set('dash-probe-status','Not running in browser');
      set('system-health',healthy?'Authenticated backend API':'Backend unavailable');
      set('dash-health-title',healthy?'Backend API verified':'Backend unavailable');
      set('dash-health-subtitle',healthy?'Authenticated request to /api/desktop/state succeeded':stateLabel);
      set('dash-public-state','Not verified');
      set('dash-connection-method',location.protocol==='https:'?'Authenticated HTTPS':'Local HTTP development');
      set('dash-network-report','Backend API health does not prove public inbound reachability.');
      set('current-ip','Not reported by web session');
      set('last-check',checked);
      set('report-state','External reachability not verified');
      set('network-page-ip','Not provided');
      set('network-page-gateway',location.origin);
      set('network-page-report','Backend API health and external reachability are separate checks.');
      set('network-health',healthy?'Backend API responding':'Backend unavailable');
      set('network-state-title',healthy?'Backend API responding':'Backend health check failed');
      set('network-state-detail',healthy?'Authenticated API request succeeded. Public internet reachability remains unverified.':stateLabel);
      set('sidebar-status-text',healthy?'Backend healthy':'Backend unavailable');
      set('sidebar-status-ip',location.host);
      set('sidebar-status-last','API check: '+checked);
      ['sidebar-dot','top-dot','dash-health-dot'].forEach(id=>{const d=$(id);if(d){const color=healthy?'var(--green)':'var(--yellow)';d.style.background=color;d.style.boxShadow='0 0 12px '+color;}});
      return;
    }
    const running=!!status.running, checked=status.lastCheckAt?new Date(status.lastCheckAt).toLocaleString():'Never';
    set('status-text',running?'Probe running':'Probe stopped');set('dash-probe-status',running?'Running':'Stopped');set('system-health',running?'Probe process active':'Probe service stopped');
    set('dash-health-title',running?'Probe service running':'Probe service stopped');set('dash-health-subtitle',running?'Local IP-reporting process is active; backend and inbound access are separate checks.':'Local probe is not running');
    set('dash-public-state',status.lastReportOk===true?'Verified':'Not verified');set('dash-sandbox-state','Ready · isolated');set('dash-connection-method',status.gatewayUrl?'Gateway configured':'Not configured');set('dash-network-report',status.lastReportOk===true?'Public IP report successful':status.lastReportOk===false?'Last IP report failed':'Waiting for a report.');
    set('metric-probe',running?'Running':'Stopped');set('metric-probe-detail',running?'IP reporting active':'IP reporting service');
    set('ip-display',status.gatewayUrl||'Not configured');set('current-ip',status.currentIp||'Waiting…');set('last-check',checked);
    set('sidebar-status-text',running?'Probe running':'Service stopped');set('sidebar-status-ip',status.currentIp||'Waiting for IP check');set('sidebar-status-last','Last check: '+checked);
    set('network-ip',status.currentIp||'—');set('network-page-ip',status.currentIp||'Not detected');set('network-page-gateway',status.gatewayUrl||'Not configured');
    set('network-page-report',status.lastReportOk===true?'Last IP report succeeded.':status.lastReportOk===false?'Last IP report failed.':'Waiting for a report.');
    set('report-state',status.lastReportOk===true?'Report successful':status.lastReportOk===false?'Report failed':'Awaiting first report');
    set('network-health',status.lastReportOk===true?'IP report successful':status.lastReportOk===false?'IP report failed':'Awaiting check');
    set('network-state-title',status.lastReportOk===true?'Public IP report successful':'Reachability not verified');
    set('network-state-detail',status.lastReportOk===true?'The probe reported its public IP. This does not independently verify inbound access.':'A successful IP report does not independently verify inbound access. Test from a separate network.');
    ['sidebar-dot','top-dot'].forEach(id=>{const d=$(id);if(d){const color='var(--yellow)';d.style.background=color;d.style.boxShadow='0 0 12px '+color;}});
    if($('network-page-ip'))$('network-page-ip').title=status.currentIp||'';
  }
  async function loadConfig() {
    const cfg=await window.api.getConfig();
    cfgEls.gatewayUrl.value=cfg.gatewayUrl||'';cfgEls.probeToken.value=cfg.probeToken||'';
    cfgEls.duckdnsSubdomain.value=cfg.duckdnsSubdomain||'';cfgEls.duckdnsToken.value=cfg.duckdnsToken||'';
    cfgEls.interval.value=cfg.intervalMinutes||5;cfgEls.startWithWindows.checked=!!cfg.startWithWindows;applyAppearance(cfg);updateUI(cfg);
  }
  async function refreshLogs() {
    const logs=await window.api.getLogs();const value=logs&&logs.trim()?logs:'No local probe activity has been recorded yet.';
    if($('log-box'))$('log-box').textContent=value;
    if($('dashboard-log'))$('dashboard-log').textContent=value.split('\n').slice(-5).join('\n');
  }
  async function checkNow() {
    toast('Checking public IP…');
    try {const result=await window.api.checkNow();if(result.error)toast('Check failed: '+result.error,true);else if(result.skipped)toast('Configure gateway and probe token first',true);else if(result.ok)toast('IP reported successfully');else toast('IP check completed; no change or report pending');await refreshLogs();}
    catch(e){toast('IP check failed: '+e.message,true);}
  }
  $('btn-check-now')?.addEventListener('click',checkNow);$('btn-dash-check-now')?.addEventListener('click',checkNow);$('btn-top-check')?.addEventListener('click',checkNow);
  $('btn-notifications')?.addEventListener('click',()=>toast('No new workspace notifications.'));
  ['btn-top-notifications','btn-dashboard-settings','btn-top-settings','btn-top-workspace','btn-dashboard-workspace'].forEach(id=>{const el=document.getElementById(id);el?.addEventListener('click',()=>{if(id.includes('notifications'))toast('No new workspace notifications.');else setPage(id.includes('workspace')?'dashboard':'settings');});});
  $('btn-hero-dashboard')?.addEventListener('click',()=>window.api.openDashboard('dashboard'));
  $('btn-save')?.addEventListener('click',async()=>{
    const cfg={gatewayUrl:cfgEls.gatewayUrl.value.trim(),probeToken:cfgEls.probeToken.value.trim(),duckdnsSubdomain:cfgEls.duckdnsSubdomain.value.trim(),duckdnsToken:cfgEls.duckdnsToken.value.trim(),intervalMinutes:Math.min(1440,Math.max(1,parseInt(cfgEls.interval.value,10)||5)),startWithWindows:cfgEls.startWithWindows.checked,...readAppearance()};
    try{await window.api.saveConfig(cfg);const ok=await window.api.toggleStartup(cfg.startWithWindows);if(ok===false)throw new Error('Could not update Windows startup registration');toast('Settings saved');}
    catch(e){toast('Could not save settings: '+e.message,true);}
  });
  $('btn-start-probe')?.addEventListener('click',async()=>{await window.api.startProbe();toast('Probe started');});
  $('btn-stop-probe')?.addEventListener('click',async()=>{await window.api.stopProbe();toast('Probe stopped');});
  $('btn-refresh-logs')?.addEventListener('click',refreshLogs);
  $('btn-clear-logs')?.addEventListener('click',async()=>{await window.api.clearLogs();await refreshLogs();toast('Local log cleared');});
  $('btn-ide-guide')?.addEventListener('click',()=>window.api.openIdeGuide());
  $('btn-open-duckdns')?.addEventListener('click',()=>window.api.openExternal('https://www.duckdns.org/'));
  $('btn-scheduler')?.addEventListener('click',async()=>{toast('Creating Windows task…');const r=await window.api.createScheduledTask();toast(r.ok?'Scheduled task created':'Task creation failed: '+(r.error||'unknown'),!r.ok);});

  let desktopState=null, activeShareId='', activeProjectClientId='', projectPathRules=[], projectPickerPath='';
  const apiCall=(method,path,body)=>window.api.desktopApi({method,path,body});
  const escHtml=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const activeShare=()=>desktopState?.shares?.find(s=>s.id===activeShareId)||null;
  const activeProjectClient=()=>activeShare()?.clients?.find(c=>c.id===activeProjectClientId)||null;
  function renderNativeShares(){
    const el=$('native-share-list');if(!el)return;
    const rows=desktopState?.shares||[];
    if(!rows.length){el.innerHTML='<p class="muted">No shares configured. Create one above.</p>';return;}
    el.innerHTML=rows.map(s=>'<div class="native-list-row"><div class="native-list-main"><b>'+escHtml(s.username)+'</b><small>'+escHtml(s.folder)+'</small><small>'+(s.clients||[]).length+' AI clients ? last access '+escHtml(s.last_seen||'never')+'</small></div><div class="native-list-actions"><button class="btn ghost" data-manage-share="'+escHtml(s.id)+'">Permissions / clients</button><button class="btn danger" data-delete-share="'+escHtml(s.id)+'">Delete</button></div></div>').join('');
    $('dash-share-count') && ($('dash-share-count').textContent=String(rows.length));
    $('dash-client-count') && ($('dash-client-count').textContent=String(rows.reduce((n,s)=>n+(s.clients||[]).length,0)));
  }
  function renderProjectAccess(){
    const share=activeShare(), select=$('project-client-select');
    if(!select)return;
    select.innerHTML='<option value="">Select a connected identity</option>'+(share?.clients||[]).map(c=>'<option value="'+escHtml(c.id)+'">'+escHtml(c.name)+'</option>').join('');
    if(!(share?.clients||[]).some(c=>c.id===activeProjectClientId)){activeProjectClientId=share?.clients?.[0]?.id||'';renderProjectAccess.lastClientId='';}
    select.value=activeProjectClientId;
    const client=activeProjectClient();
    if(client&&client.id!==renderProjectAccess.lastClientId){
      projectPathRules=Array.isArray(client.project_access?.rules)?client.project_access.rules.map(rule=>({...rule})):[];
      renderProjectAccess.lastClientId=client.id;
    }
    const access=client?.project_access||{read:false,write:false,deny:false,upload:false,download:false,rules:[]};
    document.querySelectorAll('[data-project-root-perm]').forEach(i=>{i.checked=!!access[i.dataset.projectRootPerm];i.disabled=!client||(['write','upload'].includes(i.dataset.projectRootPerm)&&!share?.workspace_write_enabled);});
    document.querySelectorAll('[data-project-rule-perm]').forEach(i=>{i.checked=false;i.disabled=!client||(['write','upload'].includes(i.dataset.projectRulePerm)&&!share?.workspace_write_enabled);});
    ['btn-save-project-access','btn-add-project-rule','btn-pick-project-path'].forEach(id=>{if($(id))$(id).disabled=!client;});
    const rules=$('project-access-rules');
    if(rules)rules.innerHTML=client&&projectPathRules.length?projectPathRules.map((rule,index)=>'<div class="native-list-row"><div class="native-list-main"><b>'+escHtml(rule.path)+'</b><small>'+['read','write','deny','upload','download'].filter(key=>rule[key]).map(key=>key==='deny'?'DENY':key.toUpperCase()).join(' ? ')||'Explicitly no permissions (overrides inherited grants)'+'</small></div><button class="btn danger" data-remove-project-rule="'+index+'">Remove</button></div>').join(''):'<p class="muted">'+(client?'No path overrides. Project folder defaults apply.':'Select a connected identity to manage its project access.')+'</p>';
  }
  renderProjectAccess.lastClientId='';
  function renderNativePermissions(){
    const select=$('permission-share-select');if(!select)return;
    select.innerHTML='<option value="">Select a workspace share</option>'+(desktopState?.shares||[]).map(s=>'<option value="'+escHtml(s.id)+'">'+escHtml(s.username)+'</option>').join('');
    select.value=activeShareId;
    const share=activeShare();
    document.querySelectorAll('[data-share-cap]').forEach(i=>{i.checked=!!share?.[i.dataset.shareCap];i.disabled=!share;});
    const clients=$('native-client-list');if(!clients)return;
    if(!share){clients.innerHTML='<p class="muted">Select a share to manage its clients.</p>';activeProjectClientId='';renderProjectAccess();return;}
    clients.innerHTML=(share.clients||[]).length?share.clients.map(c=>'<div class="native-list-row"><div class="native-list-main"><b>'+escHtml(c.name)+'</b><small>Last seen '+escHtml(c.last_seen||'never')+'</small><small>'+Object.entries(c.permissions||{}).filter(x=>x[1]===true&&x[0]!=='project_access').map(x=>escHtml(x[0])).join(' ? ')+'</small></div><button class="btn danger" data-revoke-client="'+escHtml(c.id)+'">Revoke</button></div>').join(''):'<p class="muted">No AI clients issued for this share.</p>';
    document.querySelectorAll('[data-client-perm]').forEach(i=>{const dep={write:'workspace_write_enabled',cli:'cli_enabled',ide:'ide_enabled',tunnel:'tunnel_enabled'}[i.dataset.clientPerm];i.disabled=!share||(dep&&!share[dep]);});
    renderProjectAccess();
  }
  function renderNetworkAdmin(){
    const n=desktopState?.network||{};
    const set=(id,value)=>{const el=$(id);if(el)el.textContent=value;};
    const connected=!!desktopState;
    ['btn-router-discover','btn-save-network-port','btn-create-external-test','btn-create-router-mapping'].forEach(id=>{if($(id))$(id).disabled=!connected;});
    const ddnsSubmit=$('ddns-form')?.querySelector('button[type=submit]');if(ddnsSubmit)ddnsSubmit.disabled=!connected;
    if($('network-https-port'))$('network-https-port').value=String(n.port||443);
    if($('network-page-gateway'))$('network-page-gateway').textContent=n.public_host||'Public host not configured';
    set('network-lan-ip',n.local_lan_ip?'LAN address: '+n.local_lan_ip:'LAN address unavailable');
    if($('ddns-domain'))$('ddns-domain').value=n.ddns_domain||'';
    set('ddns-token-status',n.ddns_configured?'A DDNS token is stored securely. Leave the field blank to retain it.':'No DDNS token is configured.');
    const discovery=n.router_discovery||{};
    set('router-discovery-status',discovery.available?'Router discovered: '+(discovery.router_address||'address unavailable'):(discovery.reason||'Router discovery has not been run.'));
    const protocols=n.mapping_protocols||{};
    set('https-listener-status',n.https_listener_ready?'HTTPS listener ready: '+(n.https_listener_status||'TLS handshake succeeded.'):(n.https_listener_status||'HTTPS reverse proxy is not responding on the LAN. Automatic router mapping is blocked until TLS is ready.'));
    const routerAddress=discovery.router_address||protocols.gateway||'';
    const routerButton=$('btn-open-router-admin');
    const octets=routerAddress.split('.').map(Number);
    const validPrivateRouter=octets.length===4&&octets.every(x=>Number.isInteger(x)&&x>=0&&x<=255)&&((octets[0]===10)||(octets[0]===172&&octets[1]>=16&&octets[1]<=31)||(octets[0]===192&&octets[1]===168));
    if(routerButton)routerButton.disabled=!validPrivateRouter||!connected;
    set('router-admin-status',validPrivateRouter?'Router administration page detected at http://'+routerAddress+'/ . Sign in directly in your browser; SF2AiS will not collect the router password.':'No private router administration address is available yet. Run router discovery.');
    set('router-manual-local-ip',n.local_lan_ip||'not detected');
    set('router-manual-local-ip-copy',n.local_lan_ip||'not detected');
    set('router-manual-internal-port',String(n.port||443));
    set('router-manual-external-port',String(n.port||443));
    set('router-upnp-status',protocols.upnp_igd?'Detected':'Not detected');
    set('router-natpmp-status',protocols.nat_pmp?'Detected':'Not detected');
    set('router-pcp-status',protocols.pcp?'Detected':'Not detected');
    set('router-gateway-status',protocols.gateway||discovery.router_address||'Unknown');
    const diagnostics=n.nat_diagnostics||{};
    const diagText=diagnostics.explanation||diagnostics.reason||diagnostics.external_reachability||'No NAT diagnostics available.';
    set('nat-diagnostics-status',typeof diagText==='string'?diagText:JSON.stringify(diagText));
    const mapping=n.router_mapping;
    set('router-mapping-status',mapping?'Active '+(mapping.method||'router')+' mapping · external port '+mapping.external_port+' · expires '+(mapping.expires_at||'lease expiry unknown'):(!n.https_listener_ready?'No rule created: the configured LAN HTTPS port is not completing a TLS handshake. Start the reverse proxy first.':'No router mapping is recorded.'));
    const methodSelect=$('router-mapping-method');
    if(methodSelect){for(const option of methodSelect.options){option.disabled=option.value==='upnp-igd'?!protocols.upnp_igd:option.value==='nat-pmp'?!protocols.nat_pmp:option.value==='pcp'?!protocols.pcp:false;}if(methodSelect.selectedOptions[0]?.disabled){const first=[...methodSelect.options].find(o=>!o.disabled);if(first)methodSelect.value=first.value;}}
    if($('btn-create-router-mapping'))$('btn-create-router-mapping').disabled=!connected||!n.https_listener_ready||!protocols[$('router-mapping-method')?.value?.replace('-','_')];
    if($('btn-remove-router-mapping'))$('btn-remove-router-mapping').disabled=!connected||!mapping;
    const reach=n.external_reachability||{};
    set('external-reachability-status',reach.status==='verified'?'Verified at '+(reach.verified_at||'unknown time')+' from '+(reach.remote_ip||'an external network'):'External reachability is not verified.');
    const relay=n.relay||{};
    set('relay-status',relay.available?(relay.enabled?'Relay enabled · ':'Relay disabled · ')+(relay.state||'status available'):(relay.state||'Relay provider unavailable or not configured.'));
  }
  async function refreshDesktopState(){
    const status=await window.api.connectionStatus();
    if(!status.connected){desktopState=null;renderNativeShares();renderNativePermissions();renderNetworkAdmin();return null;}
    desktopState=await apiCall('GET','/api/desktop/state');
    if(!activeShareId||!desktopState.shares.some(s=>s.id===activeShareId))activeShareId=desktopState.shares[0]?.id||'';
    renderNativeShares();renderNativePermissions();renderNetworkAdmin();
    const selected=activeShare();
    if(selected){
      $('dash-share-name')&&($('dash-share-name').textContent=selected.username||'Active share');
      $('dash-share-path')&&($('dash-share-path').textContent=selected.folder||'Server-managed share');
      $('dash-share-access')&&($('dash-share-access').textContent=selected.workspace_write_enabled?'Read / write scoped':'Read-only scoped');
    } else {
      $('dash-share-name')&&($('dash-share-name').textContent='No active share selected');
      $('dash-share-path')&&($('dash-share-path').textContent='Create or select a workspace share to begin.');
      $('dash-share-access')&&($('dash-share-access').textContent='Awaiting configuration');
    }
    $('dash-sandbox-state')&&($('dash-sandbox-state').textContent=desktopState.capabilities?.sandbox?'Docker detected':'Docker unavailable');
    $('cua-provider-status')&&($('cua-provider-status').textContent=(desktopState.capabilities?.computer_use_provider?.available?'Installed':'Not installed')+(desktopState.capabilities?.computer_use_provider?.running?' ? running':' ? stopped'));
    return desktopState;
  }
  let monitorTimer=null;
  let monitorBusy=false;
  function formatMonitorTime(value){
    if(!value)return 'Unknown';
    const date=new Date(value);
    return Number.isNaN(date.getTime())?String(value):date.toLocaleString();
  }
  function renderMonitorSessions(sessions){
    const list=$('monitor-session-list');if(!list)return;
    const rows=Array.isArray(sessions)?sessions:[];
    $('monitor-session-count').textContent=String(rows.length);
    $('monitor-active-count').textContent=String(rows.filter(s=>['active','connected','authorized'].includes(String(s.status||'').toLowerCase())).length);
    const select=$('monitor-session-filter');
    const previous=select.value;
    select.innerHTML='<option value="">All sessions</option>'+rows.map(s=>'<option value="'+escHtml(s.session_id)+'">'+escHtml(s.identity||s.client_type||s.client_id||s.session_id)+'</option>').join('');
    if(rows.some(s=>s.session_id===previous))select.value=previous;
    if(!rows.length){list.innerHTML='<p class="muted">No AI client sessions are currently registered. Sessions will appear when an authorized client connects.</p>';return;}
    list.innerHTML=rows.map(s=>{
      const status=String(s.status||'unknown');
      const caps=Array.isArray(s.capabilities)?s.capabilities:[];
      return '<div class="monitor-session-row"><div class="monitor-session-main"><div class="monitor-session-title"><b>'+escHtml(s.identity||s.client_type||'AI client')+'</b><span class="status-tag '+(['active','connected','authorized'].includes(status.toLowerCase())?'success':'neutral')+'">'+escHtml(status)+'</span></div><small>Client '+escHtml(s.client_id||'—')+' · Session '+escHtml(s.session_id||'—')+'</small><small>Share '+escHtml(s.share_id||'—')+' · Last seen '+escHtml(formatMonitorTime(s.last_seen))+'</small><small>Workspace '+escHtml(s.workspace_path||'Not supplied')+'</small><div class="monitor-capabilities">'+(caps.length?caps.map(c=>'<span>'+escHtml(c)+'</span>').join(''):'<span>No capabilities reported</span>')+'</div></div><div class="monitor-session-meta"><small>Expires</small><b>'+escHtml(formatMonitorTime(s.expires_at))+'</b></div></div>';
    }).join('');
  }
  function renderMonitorEvents(events){
    const list=$('monitor-event-list');if(!list)return;
    const rows=Array.isArray(events)?events:[];
    $('monitor-event-count').textContent=String(rows.length);
    if(!rows.length){list.innerHTML='<p class="muted">No activity has been recorded for the selected session yet.</p>';return;}
    list.innerHTML=rows.slice().reverse().map(e=>'<div class="monitor-event-row"><span class="monitor-event-dot"></span><div><b>'+escHtml(e.action||'Activity')+'</b><small>'+escHtml(formatMonitorTime(e.at))+' · Session '+escHtml(e.session_id||'—')+'</small><p>'+escHtml(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail||{}))+'</p></div></div>').join('');
  }
  async function refreshMonitor(){
    if(monitorBusy||!$('page-monitor')?.classList.contains('active'))return;
    monitorBusy=true;
    const state=$('monitor-connection-state');
    try{
      const [sessionResult,eventResult]=await Promise.all([
        apiCall('GET','/api/monitor/sessions'),
        apiCall('GET','/api/monitor/events?limit=100'+($('monitor-session-filter')?.value?'&session_id='+encodeURIComponent($('monitor-session-filter').value):''))
      ]);
      renderMonitorSessions(sessionResult?.sessions||[]);
      renderMonitorEvents(eventResult?.events||[]);
      state.textContent='Connected · updating';
      $('monitor-updated-at').textContent='Updated '+new Date().toLocaleTimeString();
    }catch(error){
      state.textContent='Connection error';
      $('monitor-session-list').innerHTML='<p class="muted">Could not load AI sessions: '+escHtml(error.message)+'</p>';
      $('monitor-event-list').innerHTML='<p class="muted">The activity stream is unavailable until the authenticated server connection is restored.</p>';
    }finally{monitorBusy=false;}
  }
  function configureMonitorPolling(){
    if(monitorTimer){clearInterval(monitorTimer);monitorTimer=null;}
    if($('page-monitor')?.classList.contains('active')&&$('monitor-auto-refresh')?.checked){
      monitorTimer=setInterval(()=>refreshMonitor(),5000);
    }
  }
  document.addEventListener('sf2ais:monitor-visible',()=>{refreshMonitor();configureMonitorPolling();});
  document.addEventListener('sf2ais:monitor-hidden',()=>{if(monitorTimer){clearInterval(monitorTimer);monitorTimer=null;}});
  $('btn-monitor-refresh')?.addEventListener('click',()=>refreshMonitor());
  document.querySelectorAll('[data-installer-platform]').forEach(button=>button.addEventListener('click',async()=>{
    const platform=button.dataset.installerPlatform,arch=button.dataset.installerArch;
    const status=$('installer-download-status');button.disabled=true;status.textContent='Preparing '+platform+' '+arch+' installer…';
    try{const result=await window.api.downloadInstaller(platform,arch);status.textContent=result?.canceled?'Download cancelled.':'Saved '+(result?.filename||platform+' '+arch+' installer')+'.';toast(result?.canceled?'Download cancelled.':'Installer downloaded successfully.');}
    catch(error){status.textContent='Download unavailable: '+error.message;toast('Installer download failed: '+error.message,true);}
    finally{button.disabled=false;}
  }));
  $('monitor-auto-refresh')?.addEventListener('change',configureMonitorPolling);
  $('monitor-session-filter')?.addEventListener('change',()=>refreshMonitor());
  if($('page-monitor')?.classList.contains('active')){refreshMonitor();configureMonitorPolling();}

  function applyNetworkResponse(result){
    if(!result?.network)return;
    if(!desktopState)desktopState={shares:[],capabilities:{}};
    desktopState.network=result.network;
    renderNetworkAdmin();
  }
  $('btn-open-router-admin')?.addEventListener('click',async()=>{
    const n=desktopState?.network||{};const address=n.router_discovery?.router_address||n.mapping_protocols?.gateway||'';
    const parts=address.split('.').map(Number);
    const safe=parts.length===4&&parts.every(x=>Number.isInteger(x)&&x>=0&&x<=255)&&((parts[0]===10)||(parts[0]===172&&parts[1]>=16&&parts[1]<=31)||(parts[0]===192&&parts[1]===168));
    if(!safe){toast('No safe private router address is available. Run discovery first.',true);return;}
    try{await window.api.openExternal('http://'+address+'/');}catch(e){toast('Could not open router login page: '+e.message,true);}
  });
  $('btn-router-discover')?.addEventListener('click',async()=>{
    const b=$('btn-router-discover');b.disabled=true;b.textContent='Discovering…';
    try{const r=await apiCall('POST','/api/desktop/network/discover');applyNetworkResponse(r);toast('Router discovery completed.');}
    catch(e){toast('Router discovery failed: '+e.message,true);}
    finally{b.disabled=false;b.textContent='Discover router';}
  });
  $('btn-save-network-port')?.addEventListener('click',async()=>{
    const port=parseInt($('network-https-port').value,10);
    if(!Number.isInteger(port)||port<1||port>65535){toast('Enter a valid HTTPS port from 1 to 65535.',true);return;}
    try{const r=await apiCall('PATCH','/api/desktop/network',{port});applyNetworkResponse(r);toast('HTTPS gateway port saved. No router mapping was created.');}
    catch(e){toast('Could not save network settings: '+e.message,true);}
  });
  $('ddns-form')?.addEventListener('submit',async e=>{
    e.preventDefault();
    try{const r=await apiCall('PATCH','/api/desktop/network/ddns',{domain:$('ddns-domain').value.trim(),token:$('ddns-token').value});$('ddns-token').value='';applyNetworkResponse(r);toast('DuckDNS settings saved securely.');}
    catch(x){toast('Could not save DuckDNS settings: '+x.message,true);}
  });
  $('router-mapping-form')?.addEventListener('submit',async e=>{
    e.preventDefault();
    if($('router-mapping-confirm').value.trim()!=='CREATE'||!$('router-mapping-approve').checked){toast('Tick the router approval box and type CREATE to authorize a temporary mapping.',true);return;}
    const port=parseInt($('network-https-port').value,10),external=parseInt($('router-external-port').value,10);
    if(!Number.isInteger(port)||!Number.isInteger(external)){toast('Enter valid internal and external HTTPS ports.',true);return;}
    if(!confirm('This will create a temporary TCP forwarding rule on your router to the configured HTTPS reverse proxy. It will NOT forward port 8000. Continue?'))return;
    const b=$('btn-create-router-mapping');b.disabled=true;
    try{const r=await apiCall('POST','/api/desktop/network/mapping',{method:$('router-mapping-method').value,internal_port:port,external_port:external,approve:true,confirm:'CREATE'});applyNetworkResponse(r);$('router-mapping-confirm').value='';$('router-mapping-approve').checked=false;toast('Temporary HTTPS router mapping created.');}
    catch(x){toast('Router mapping was not created: '+x.message,true);}
    finally{b.disabled=false;}
  });
  $('btn-remove-router-mapping')?.addEventListener('click',async()=>{
    if(!confirm('Remove the recorded temporary HTTPS router mapping now?'))return;
    const b=$('btn-remove-router-mapping');b.disabled=true;
    try{const r=await apiCall('DELETE','/api/desktop/network/mapping');applyNetworkResponse(r);toast(r.removed?'Router mapping removed.':'No router mapping was recorded.');}
    catch(e){toast('Could not remove router mapping: '+e.message,true);}
    finally{b.disabled=false;}
  });
  $('btn-create-external-test')?.addEventListener('click',async()=>{
    const b=$('btn-create-external-test');b.disabled=true;
    try{const r=await apiCall('POST','/api/desktop/network/verification');const box=$('external-verification-result');box.hidden=false;box.innerHTML='<b>One-time link · expires in 10 minutes</b><code>'+escHtml(r.url)+'</code><button class="btn ghost" id="copy-external-verification" type="button">Copy link</button>';$('copy-external-verification').addEventListener('click',()=>navigator.clipboard.writeText(r.url).then(()=>toast('External test link copied.')).catch(()=>toast('Clipboard access failed.',true)));toast('One-time external verification link generated. Open it from mobile data with Wi-Fi off.');}
    catch(e){toast('Could not generate external test link: '+e.message,true);}
    finally{b.disabled=false;}
  });
  $('create-share-form')?.addEventListener('submit',async e=>{
    e.preventDefault();
    try{const r=await apiCall('POST','/api/desktop/shares',{folder:$('new-share-folder').value.trim(),workspace_write_enabled:$('new-share-write').checked,cli_enabled:$('new-share-cli').checked,ide_enabled:$('new-share-ide').checked,tunnel_enabled:$('new-share-tunnel').checked});activeShareId=r.share.id;e.target.reset();await refreshDesktopState();toast('Project folder added. Issue individual AI identities to grant access.');}
    catch(err){toast(err.message,true);}
  });
  $('native-share-list')?.addEventListener('click',async e=>{
    const m=e.target.closest('[data-manage-share]'),d=e.target.closest('[data-delete-share]');
    if(m){activeShareId=m.dataset.manageShare;setPage('permissions');refreshDesktopState().catch(x=>toast(x.message,true));return;}
    if(d){const s=desktopState?.shares?.find(x=>x.id===d.dataset.deleteShare);if(!s||!confirm('Delete share '+s.username+'? Its folder contents will not be deleted.'))return;try{await apiCall('DELETE','/api/desktop/shares/'+s.id);if(activeShareId===s.id)activeShareId='';await refreshDesktopState();toast('Share deleted; folder contents retained.');}catch(x){toast(x.message,true);}}
  });
  $('btn-refresh-server')?.addEventListener('click',()=>refreshDesktopState().then(()=>toast('Server state refreshed')).catch(e=>toast(e.message,true)));
  $('permission-share-select')?.addEventListener('change',e=>{activeShareId=e.target.value;renderNativePermissions();});
  $('btn-save-share-permissions')?.addEventListener('click',async()=>{
    const s=activeShare();if(!s){toast('Select a share first.',true);return;}
    const body={};document.querySelectorAll('[data-share-cap]').forEach(i=>body[i.dataset.shareCap]=i.checked);
    try{await apiCall('PATCH','/api/desktop/shares/'+s.id,body);await refreshDesktopState();toast('Share capabilities saved.');}catch(e){toast(e.message,true);}
  });
  $('project-client-select')?.addEventListener('change',e=>{activeProjectClientId=e.target.value;renderProjectAccess.lastClientId='';renderProjectAccess();});
  $('project-access-rules')?.addEventListener('click',e=>{
    const b=e.target.closest('[data-remove-project-rule]');if(!b)return;
    projectPathRules.splice(Number(b.dataset.removeProjectRule),1);renderProjectAccess();
  });
  $('btn-add-project-rule')?.addEventListener('click',()=>{
    const path=$('project-path-value').value.trim();if(!path){toast('Choose a project file or folder first.',true);return;}
    const rule={path};document.querySelectorAll('[data-project-rule-perm]').forEach(i=>rule[i.dataset.projectRulePerm]=i.checked);
    projectPathRules=projectPathRules.filter(item=>item.path!==path);projectPathRules.push(rule);
    projectPathRules.sort((a,b)=>a.path.split('/').length-b.path.split('/').length||a.path.localeCompare(b.path));
    $('project-path-value').value='';renderProjectAccess();toast('Path permission added. Save to apply it on the server.');
  });
  $('btn-save-project-access')?.addEventListener('click',async()=>{
    const s=activeShare(),c=activeProjectClient();if(!s||!c){toast('Select a project and connected identity first.',true);return;}
    const project_access={};document.querySelectorAll('[data-project-root-perm]').forEach(i=>project_access[i.dataset.projectRootPerm]=i.checked);
    project_access.rules=projectPathRules.map(rule=>({...rule}));
    try{await apiCall('PATCH','/api/desktop/shares/'+s.id+'/clients/'+c.id+'/project-access',{project_access});await refreshDesktopState();toast('Per-identity project permissions saved and enforced by the server.');}
    catch(e){toast(e.message,true);}
  });
  async function loadProjectPicker(path=''){
    const s=activeShare();if(!s)throw new Error('Select a project folder first.');
    projectPickerPath=path;
    $('project-picker-current').textContent='/'+path;
    $('btn-project-picker-up').disabled=!path;
    const result=await apiCall('GET','/api/desktop/shares/'+s.id+'/tree?path='+encodeURIComponent(path));
    const rows=result.entries||[];
    $('project-picker-list').innerHTML=rows.length?rows.map(item=>'<div class="native-list-row"><div class="native-list-main"><b>'+(item.type==='directory'?'📁 ':'📄 ')+escHtml(item.name)+'</b><small>'+escHtml(item.path)+'</small></div><div class="native-list-actions">'+(item.type==='directory'?'<button class="btn ghost" data-browse-project-path="'+escHtml(item.path)+'">Open</button>':'')+'<button class="btn ghost" data-use-project-path="'+escHtml(item.path)+'">Use</button></div></div>').join(''):'<p class="muted">This folder is empty.</p>';
  }
  $('btn-pick-project-path')?.addEventListener('click',async()=>{try{await loadProjectPicker('');$('project-path-dialog').showModal();}catch(e){toast('Could not browse project paths: '+e.message,true);}});
  $('btn-close-project-picker')?.addEventListener('click',()=>$('project-path-dialog').close());
  $('btn-project-picker-up')?.addEventListener('click',async()=>{const parent=projectPickerPath.includes('/')?projectPickerPath.slice(0,projectPickerPath.lastIndexOf('/')):'';try{await loadProjectPicker(parent);}catch(e){toast(e.message,true);}});
  $('btn-project-picker-use-folder')?.addEventListener('click',()=>{if(!projectPickerPath){toast('Choose a subfolder or file; project root permissions are set above.',true);return;}$('project-path-value').value=projectPickerPath;$('project-path-dialog').close();});
  $('project-picker-list')?.addEventListener('click',async e=>{
    const browse=e.target.closest('[data-browse-project-path]'),use=e.target.closest('[data-use-project-path]');
    if(browse){try{await loadProjectPicker(browse.dataset.browseProjectPath);}catch(x){toast(x.message,true);}return;}
    if(use){$('project-path-value').value=use.dataset.useProjectPath;$('project-path-dialog').close();}
  });
  $('create-client-form')?.addEventListener('submit',async e=>{
    e.preventDefault();const s=activeShare();if(!s){toast('Select a share first.',true);return;}
    const permissions={};document.querySelectorAll('[data-client-perm]').forEach(i=>permissions[i.dataset.clientPerm]=i.checked);
    try{const r=await apiCall('POST','/api/desktop/shares/'+s.id+'/clients',{name:$('new-client-name').value.trim(),permissions});$('new-client-name').value='';activeProjectClientId=r.client.id;renderProjectAccess.lastClientId='';const box=$('new-client-token');box.hidden=false;box.innerHTML='<b>Copy this token now. It will not be shown again. This identity has no project access until you grant it.</b><code>'+escHtml(r.token)+'</code><button class="btn ghost" id="copy-client-token" type="button">Copy token</button>';$('copy-client-token').addEventListener('click',()=>navigator.clipboard.writeText(r.token).then(()=>toast('Token copied')).catch(()=>toast('Clipboard access failed',true)));await refreshDesktopState();toast('AI identity registered with no project access.');}catch(e){toast(e.message,true);}
  });
  $('native-client-list')?.addEventListener('click',async e=>{const b=e.target.closest('[data-revoke-client]'),s=activeShare();if(!b||!s)return;if(!confirm('Revoke this AI client immediately?'))return;try{await apiCall('DELETE','/api/desktop/shares/'+s.id+'/clients/'+b.dataset.revokeClient);await refreshDesktopState();toast('Client revoked.');}catch(x){toast(x.message,true);}});
  $('server-connection-form')?.addEventListener('submit',async e=>{
    e.preventDefault();const b=e.target.querySelector('button[type=submit]');b.disabled=true;b.textContent='Connecting?';
    try{const r=await window.api.connectServer({serverUrl:$('server-url').value.trim(),username:$('server-admin-username').value.trim(),password:$('server-admin-password').value});$('server-admin-password').value='';$('server-connection-status').textContent='Connected';$('server-connection-detail').textContent='Authenticated to '+r.serverUrl+' as '+r.username+'.';desktopState=r.state;activeShareId=desktopState.shares[0]?.id||'';renderNativeShares();renderNativePermissions();renderNetworkAdmin();toast('SF2AiS server connected.');}
    catch(x){$('server-connection-status').textContent='Connection failed';$('server-connection-detail').textContent=x.message;toast(x.message,true);}
    finally{b.disabled=false;b.textContent='Connect and verify';}
  });
  $('btn-disconnect-server')?.addEventListener('click',async()=>{try{await window.api.disconnectServer();desktopState=null;activeShareId='';$('server-connection-status').textContent='Not connected';$('server-connection-detail').textContent='Encrypted administrator credentials removed.';renderNativeShares();renderNativePermissions();renderNetworkAdmin();toast('Disconnected.');}catch(e){toast(e.message,true);}});
  $('btn-refresh-server-audit')?.addEventListener('click',async()=>{try{const r=await apiCall('GET','/api/desktop/activity');$('log-box').textContent=(r.events||[]).map(x=>JSON.stringify(x)).join('\n')||'No server audit events.';}catch(e){toast(e.message,true);}});
  async function loadNativeConnection(){
    const s=await window.api.connectionStatus();$('server-url').value=s.serverUrl||'';$('server-admin-username').value=s.username||'';
    if(s.connected){$('server-connection-status').textContent='Saved connection';try{await refreshDesktopState();$('server-connection-status').textContent='Connected';$('server-connection-detail').textContent='Authenticated connection to '+s.serverUrl+'.';}catch(e){$('server-connection-status').textContent='Offline';$('server-connection-detail').textContent=e.message;}}
  }
  loadNativeConnection().catch(e=>toast('Could not load server connection: '+e.message,true));

  window.api.onStatus(updateUI);
  try{await loadConfig();await refreshLogs();}catch(e){toast('Could not load local settings: '+e.message,true);}
});
