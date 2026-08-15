"""The single page: acceptance tab + bench tab. Self-contained (inline
CSS/JS, ES5, no external assets); the visual identity follows the
forgectrl control panel. State comes from GET /state on a 2 s poll; the
catalog and the bench listing are fetched once per tab and refreshed
after a run finishes."""

_HTML = r"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>ForgeFIRM acceptance</title>
<style>
:root{--navy:#2b2b5e;--red:#e8262a;--blue:#0088cc;--bg:#f0f1f4;--card:#fff;--line:#dde0e6;
--txt:#222;--dim:#767a82;--ok:#3d854d;--warn:#c7760a;--inh:#5b6ab0}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--txt);font-size:14px}
header{background:var(--navy);color:#fff;display:flex;align-items:center;padding:10px 16px;gap:14px}
header .app{font-size:19px;font-weight:600;letter-spacing:.3px}
header .sub{color:rgba(255,255,255,.65);font-size:13px}
header .ver{margin-left:auto;color:rgba(255,255,255,.7);font-size:13px;font-family:ui-monospace,Consolas,monospace}
nav{background:var(--card);border-bottom:1px solid var(--line);display:flex;padding:0 8px}
nav a{padding:10px 14px;color:var(--dim);text-decoration:none;border-bottom:2px solid transparent;cursor:pointer}
nav a.on{color:var(--navy);font-weight:600;border-color:var(--red)}
main{display:flex;gap:14px;padding:14px;align-items:flex-start}
#left{flex:1 1 640px;min-width:0}
#right{flex:0 0 420px;position:sticky;top:10px}
@media(max-width:1000px){main{flex-direction:column}#right{position:static;flex:1 1 auto;width:100%}}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:12px 14px;margin-bottom:12px}
.card h2{font-size:12.5px;margin:0 0 10px;color:var(--navy);text-transform:uppercase;letter-spacing:.5px}
.banner{display:flex;flex-wrap:wrap;gap:18px;align-items:center}
.auth{font-size:20px;font-weight:700;padding:6px 14px;border-radius:6px;color:#fff;background:var(--red)}
.auth.yes{background:var(--ok)}
.kv{color:var(--dim);font-size:12.5px;line-height:1.7}
.kv b{color:var(--txt);font-weight:600}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px}
table{width:100%;border-collapse:collapse}
th{font-size:11.5px;color:var(--dim);text-align:left;font-weight:600;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
.tid{color:var(--dim);font-size:11.5px;font-family:ui-monospace,Consolas,monospace}
.badge{display:inline-block;font-size:10.5px;padding:2px 6px;border-radius:9px;margin-right:4px;background:#e8e9ec;color:#444;font-weight:600;letter-spacing:.2px;text-transform:uppercase}
.badge.live{background:#fbe1e1;color:#a11}
.badge.operator{background:#fdf3e3;color:#8a5200}
.badge.takeover{background:#e6e8f5;color:#33407a}
.badge.core{background:var(--navy);color:#fff}
.st{font-weight:600}
.st.pass{color:var(--ok)}.st.inherited{color:var(--inh)}.st.fail,.st.error{color:var(--red)}
.st.stale,.st.aborted{color:var(--warn)}.st.none{color:var(--dim)}.st.running{color:var(--blue)}
.req{font-size:11.5px;color:var(--warn)}
button{background:#fff;color:var(--txt);border:1px solid #c9cdd4;border-radius:4px;padding:5px 11px;font-size:13px;cursor:pointer}
button:hover{border-color:var(--navy)}
button.pri{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
button.pri:hover{background:#0077b3}
button.danger{background:var(--red);border-color:var(--red);color:#fff}
button:disabled{opacity:.45;cursor:default}
input[type=text],input[type=number],select{background:#fff;border:1px solid #c9cdd4;border-radius:4px;padding:5px 7px;font-size:13px}
.actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.hint{color:var(--dim);font-size:12.5px;line-height:1.55;margin:8px 0 0}
pre#log{background:#1d1e26;color:#d7dae0;font-family:ui-monospace,Consolas,monospace;font-size:11.5px;padding:10px;border-radius:4px;height:380px;overflow:auto;margin:8px 0;white-space:pre-wrap;word-break:break-all}
#prompt{background:#fdf3e3;border:1px solid #eccb90;border-radius:6px;padding:10px 12px;margin:8px 0}
#prompt .q{font-weight:600;margin-bottom:8px}
.details{display:none;background:#f7f8fa;padding:8px 10px;border-radius:4px;font-size:12.5px;line-height:1.55;margin-top:6px}
.details.on{display:block}
.msg{color:var(--blue);font-size:13px;margin:6px 0}
.err{color:var(--red);font-size:13px;margin:6px 0}
.note{background:#fdf3e3;border:1px solid #eccb90;border-radius:6px;padding:8px 12px;margin:8px 0;font-size:13px}
.ack{display:block;margin:8px 0;font-size:12.5px}
.grp{margin-top:6px}
.tool .argrow{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}
.tool .argrow label{font-size:12px;color:var(--dim)}
</style></head><body>
<header><span class='app'>ForgeFIRM acceptance</span><span class='sub' id='hdrsub'></span><span class='ver' id='hdrver'></span></header>
<nav><a id='tab-acceptance' class='on' onclick='showTab("acceptance")'>Release acceptance</a><a id='tab-bench' onclick='showTab("bench")'>Bench diagnostics</a></nav>
<main>
<div id='left'>
 <div id='pane-acceptance'>
  <div class='card'><h2>Campaign</h2>
   <div class='banner'><div class='auth' id='auth'>?</div>
    <div class='kv' id='banner'></div></div>
   <div id='invnote'></div><div id='msgs'></div>
   <div class='actions' style='margin-top:10px'>
    <button class='pri' onclick='doExport()'>Export release artifact</button>
    <a id='dljson' href='/export/acceptance.json' style='display:none'><button>acceptance.json</button></a>
    <a id='dlmd' href='/export/acceptance.md' style='display:none'><button>acceptance.md</button></a>
    <a href='/log'><button>Raw log</button></a>
    <button onclick='toggleInv()'>Invalidate all&hellip;</button>
    <button onclick='doReset()'>Reset campaign</button>
   </div>
   <div id='invform' style='display:none;margin-top:8px'>
    <input type='text' id='invreason' size='60' placeholder='reason (required): what changed on the bench'>
    <button class='danger' onclick='doInvalidate()'>Invalidate all results</button>
   </div>
   <div id='actmsg'></div>
   <p class='hint'>A release is authorized when a campaign is open on this image and every catalog test is satisfied - by a PASS in the campaign, or (never for the core) by an earlier PASS whose domain fingerprint is unchanged. A FAIL ends the campaign. Invalidate-all forces a full campaign; give the reason.</p>
  </div>
  <div id='groups'></div>
 </div>
 <div id='pane-bench' style='display:none'>
  <div class='card'><h2>Bench diagnostics</h2>
   <p class='hint'>The bench tools (scripts/bench), run on the board with the output below. Runs here never enter a campaign. Tools not yet ported are listed for completeness; live tools need the operator acknowledgment; takeover tools stop forgectrl for the duration.</p>
   <div id='benchmsg'></div>
  </div>
  <div id='tools'></div>
 </div>
</div>
<div id='right'>
 <div class='card'><h2 id='runtitle'>Run</h2>
  <div id='runhead' class='kv'>idle</div>
  <div id='prompt' style='display:none'><div class='q' id='promptq'></div><div class='actions' id='promptb'></div></div>
  <pre id='log'></pre>
  <div class='actions'><button class='danger' id='abortbtn' onclick='doAbort()' disabled>Abort</button><span class='hint' id='runfoot'></span></div>
 </div>
</div>
</main>
<script>
var TOKEN='__TOKEN__';
var state=null, catalog=null, catalogHash=null, bench=null, tab='acceptance', openDetails={};
var lastRunKey=null;
function $(id){return document.getElementById(id)}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function api(method,path,body,cb){var x=new XMLHttpRequest();x.open(method,path,true);x.setRequestHeader('X-ForgeFIRM-Token',TOKEN);
 if(body!==undefined&&body!==null){x.setRequestHeader('Content-Type','application/json')}
 x.onreadystatechange=function(){if(x.readyState!==4)return;var d=null;try{d=JSON.parse(x.responseText)}catch(e){d={error:x.responseText}}cb(x.status,d)};
 x.send(body===undefined||body===null?null:JSON.stringify(body))}
function showTab(t){tab=t;$('tab-acceptance').className=t==='acceptance'?'on':'';$('tab-bench').className=t==='bench'?'on':'';
 $('pane-acceptance').style.display=t==='acceptance'?'':'none';$('pane-bench').style.display=t==='bench'?'':'none';
 if(t==='bench'&&!bench)loadBench()}
function setMsg(id,txt,err){var e=$(id);e.innerHTML=txt?"<div class='"+(err?'err':'msg')+"'>"+esc(txt)+"</div>":''}
function loadCatalog(cb){api('GET','/catalog',null,function(s,d){if(s===200){catalog=d.tests;catalogHash=d.catalog_hash;if(cb)cb()}})}
function loadBench(){api('GET','/bench',null,function(s,d){if(s===200){bench=d;renderBench()}})}
function poll(){api('GET','/state',null,function(s,d){if(s===200){state=d;if(!catalog||catalogHash!==d.catalog_hash){loadCatalog(render)}else{render()}}
 setTimeout(poll,2000)})}
function fmtTs(t){return t?t.replace('T',' ').replace('Z',' UTC'):'-'}
function render(){if(!state||!catalog)return;
 var m=state.manifest||{};$('hdrver').textContent=(m.version||'?');$('hdrsub').textContent=m.image||'';
 var a=$('auth');a.textContent='Release authorized: '+(state.authorized?'YES':'NO');a.className='auth'+(state.authorized?' yes':'');
 var c=state.campaign,cn=state.counts||{};var b='';
 b+='<b>'+cn.satisfied+'</b> of <b>'+cn.total+'</b> satisfied ('+cn.inherited+' inherited), <b>'+cn.required+'</b> required<br>';
 b+=c?('campaign <span class="mono">'+esc(c.id)+'</span> opened '+esc(fmtTs(c.ts))):('no open campaign'+(state.closed_by?(' (last one closed by '+esc(state.closed_by)+')'):'')+' - the first Start opens one');
 b+='<br>manifest identity <span class="mono">'+esc((m.sha||'').slice(0,16))+'</span> &middot; catalog <span class="mono">'+esc((state.catalog_hash||'').slice(0,12))+'</span>';
 if(state.log_corrupt)b+='<br><span style="color:var(--red)">'+state.log_corrupt+' corrupt log line(s) skipped</span>';
 $('banner').innerHTML=b;
 var inv=state.invalidate;$('invnote').innerHTML=inv?"<div class='note'>Full campaign required since "+esc(fmtTs(inv.ts))+": "+esc(inv.reason)+"</div>":'';
 var ms='';(state.messages||[]).forEach(function(x){ms+="<div class='note'>"+esc(x)+"</div>"});$('msgs').innerHTML=ms;
 renderGroups();renderRun()}
function renderGroups(){var groups={},order=[];catalog.forEach(function(t){if(!groups[t.subsystem]){groups[t.subsystem]=[];order.push(t.subsystem)}groups[t.subsystem].push(t)});
 var busy=!!state.running;var h='';
 order.forEach(function(g){h+="<div class='card grp'><h2>"+esc(g)+"</h2><table><tr><th>Test</th><th>Kind</th><th>Status</th><th>Last result</th><th></th></tr>";
  groups[g].forEach(function(t){var s=state.tests[t.id]||{};var badges='';
   if(t.always)badges+="<span class='badge core'>core</span>";badges+="<span class='badge "+esc(t.kind)+"'>"+esc(t.kind)+"</span>";
   if(t.hardware==='takeover')badges+="<span class='badge takeover'>takeover</span>";
   var st="<span class='st "+esc(s.status)+"'>"+esc(s.status||'none')+"</span>";
   if(s.required&&s.status!=='running')st+="<br><span class='req'>required: "+esc(s.reason)+"</span>";
   var last=s.last?(esc(s.last.result)+' '+esc(fmtTs(s.last.ts))):'-';
   if(s.status==='inherited'&&s.origin)last+="<br><span class='tid'>from "+esc(s.origin.campaign)+" on "+esc(s.origin.image)+"</span>";
   var canStart=!busy&&s.requires_met!==false;var why=busy?'a run is in progress':(!s.requires_met?('needs: '+(s.missing_requires||[]).join(', ')):'');
   var startBtn="<button class='pri' "+(canStart?'':'disabled')+" title='"+esc(why)+"' onclick='startTest(\""+esc(t.id)+"\")'>Start</button>";
   var det="<div class='details"+(openDetails[t.id]?' on':'')+"' id='det-"+esc(t.id)+"'>"+esc(t.description||'')+
     (t.steps&&t.steps.length?"<br><b>Operator steps:</b><ol>"+t.steps.map(function(x){return '<li>'+esc(x)+'</li>'}).join('')+"</ol>":'')+
     "<b>Requires:</b> "+esc((t.requires||[]).join(', ')||'-')+"<br><b>Covers:</b> "+esc((t.covers||[]).map(function(c){return c[0]+':'+c[1]}).join(', ')||'-')+
     "<br><b>Fingerprint:</b> <span class='mono'>"+esc((s.fingerprint||'').slice(0,16))+"</span> &middot; est. "+esc(t.est_min)+" min"+
     (s.last?"<br><a href='/result?test="+encodeURIComponent(t.id)+"&ts="+encodeURIComponent(s.last.ts)+"'>last result record</a>":'')+"</div>";
   h+="<tr><td><div>"+esc(t.title)+"</div><div class='tid'>"+esc(t.id)+" <a href='#' onclick='toggleDet(\""+esc(t.id)+"\");return false'>details</a></div>"+det+"</td><td>"+badges+"</td><td>"+st+"</td><td>"+last+"</td><td>"+startBtn+"</td></tr>"});
  h+="</table></div>"});
 $('groups').innerHTML=h}
function toggleDet(id){openDetails[id]=!openDetails[id];var e=$('det-'+id);if(e)e.className='details'+(openDetails[id]?' on':'')}
function renderRun(){var r=state.running||state.last_run;var key=r?(r.kind+':'+r.id+':'+r.started):null;
 if(!r){$('runhead').textContent='idle';$('log').textContent='';$('prompt').style.display='none';$('abortbtn').disabled=true;$('runtitle').textContent='Run';return}
 $('runtitle').textContent=(r.kind==='bench'?'Bench: ':'Test: ')+r.title;
 var hd=r.id+' &middot; started '+esc(fmtTs(r.started))+' &middot; '+r.elapsed_s+' s';
 if(r.finished){hd+=' &middot; <b class="st '+(r.finished.result==='PASS'||r.finished.result==='OK'?'pass':'fail')+'">'+esc(r.finished.result)+'</b>'+(r.finished.message?' - '+esc(r.finished.message):'')}
 else if(r.aborting){hd+=' &middot; <b class="st stale">aborting</b>'}
 $('runhead').innerHTML=hd;
 var lg=$('log');var atBottom=lg.scrollTop+lg.clientHeight>=lg.scrollHeight-20;lg.textContent=(r.dropped?('... '+r.dropped+' earlier lines dropped\n'):'')+r.log.join('\n');
 if(atBottom||key!==lastRunKey)lg.scrollTop=lg.scrollHeight;lastRunKey=key;
 if(r.prompt&&!r.finished){$('prompt').style.display='';$('promptq').textContent=r.prompt.question;var pb='';
  r.prompt.options.forEach(function(o){pb+="<button class='pri' onclick='answer(\""+esc(r.prompt.id)+"\",\""+esc(o)+"\")'>"+esc(o)+"</button>"});$('promptb').innerHTML=pb}
 else{$('prompt').style.display='none'}
 $('abortbtn').disabled=!!r.finished;
 if(r.finished&&tab==='bench'&&r.kind==='bench'&&benchNeedsRefresh){benchNeedsRefresh=false;loadBench()}}
var benchNeedsRefresh=false;
function findTest(id){for(var i=0;i<catalog.length;i++)if(catalog[i].id===id)return catalog[i];return null}
function startTest(id){var t=findTest(id);var body={test:id};
 if(t&&t.kind==='live'){if(!confirmLive())return;body.ack_live=true}
 api('POST','/start',body,function(s,d){setMsg('actmsg',d.message||d.error,s!==200)})}
function confirmLive(){return window.confirm('LIVE LASER TEST.\n\nConfirm before starting:\n - eye protection on, everyone in the room\n - fire watch present, extinguisher at hand\n - exhaust running, lid closed, scrap in place\n - you will press the physical button to arm when prompted\n\nStart the test?')}
function answer(pid,v){api('POST','/answer',{prompt_id:pid,value:v},function(s,d){if(s!==200)setMsg('actmsg',d.message||d.error,true)})}
function doAbort(){api('POST','/abort',{},function(s,d){setMsg('actmsg',d.message||d.error,s!==200)})}
function doExport(){api('POST','/export',{},function(s,d){if(s===200){setMsg('actmsg','exported: authorized='+d.authorized+', sha256 '+d.sha256.slice(0,16)+' - download below');$('dljson').style.display='';$('dlmd').style.display=''}else setMsg('actmsg',d.message||d.error,true)})}
function toggleInv(){var f=$('invform');f.style.display=f.style.display==='none'?'':'none'}
function doInvalidate(){var r=$('invreason').value;if(!r){setMsg('actmsg','a reason is required',true);return}
 api('POST','/invalidate',{reason:r},function(s,d){setMsg('actmsg',d.message||d.error,s!==200);if(s===200){$('invform').style.display='none';$('invreason').value=''}})}
function doReset(){api('POST','/reset',{reason:'operator reset from the page'},function(s,d){setMsg('actmsg',d.message||d.error,s!==200)})}
function renderBench(){if(!bench)return;var busy=!!(state&&state.running);var groups={dry:[],takeover:[],live:[],scope:[]};
 bench.tools.forEach(function(t){(groups[t.safety]||(groups[t.safety]=[])).push(t)});var h='';
 ['dry','takeover','scope','live'].forEach(function(g){if(!groups[g]||!groups[g].length)return;
  h+="<div class='card grp'><h2>"+esc(g)+"</h2>";
  groups[g].forEach(function(t){var can=t.ported&&t.installed&&!busy;var why=!t.ported?'not yet ported to the bench page':(!t.installed?'script not installed on this image':(busy?'a run is in progress':''));
   h+="<div class='tool' style='border-bottom:1px solid var(--line);padding:8px 0'><div><b>"+esc(t.title)+"</b> <span class='tid'>"+esc(t.script)+"</span> <span class='badge'>"+esc(t.where)+"</span>"+(t.ported?'':"<span class='badge'>unported</span>")+"</div>";
   h+="<div class='hint' style='margin:2px 0 4px'>"+esc(t.desc)+"</div>";
   if(t.args&&t.args.length){h+="<div class='argrow'>";t.args.forEach(function(a){var iid='arg-'+t.id+'-'+a.name;
     if(a.type==='choice'){h+="<label>"+esc(a.name)+" <select id='"+iid+"'>"+a.choices.map(function(c){return "<option"+(c===a.default?' selected':'')+">"+esc(c)+"</option>"}).join('')+"</select></label>"}
     else{h+="<label>"+esc(a.name)+" <input type='"+(a.type==='str'?'text':'number')+"' step='any' id='"+iid+"' value='"+esc(a.default==null?'':a.default)+"' title='"+esc(a.help)+"' style='width:90px'></label>"}});h+="</div>"}
   h+="<div class='actions'><button class='pri' "+(can?'':'disabled')+" title='"+esc(why)+"' onclick='startTool(\""+esc(t.id)+"\")'>Start</button>";
   if(t.last)h+="<span class='hint'>last: "+esc(t.last.result?t.last.result.result:'?')+" "+esc(fmtTs(t.last.ts))+"</span>";
   h+="</div></div>"});
  h+="</div>"});
 $('tools').innerHTML=h}
function startTool(id){var t=null;bench.tools.forEach(function(x){if(x.id===id)t=x});if(!t)return;var args={};
 (t.args||[]).forEach(function(a){var e=$('arg-'+id+'-'+a.name);if(e)args[a.name]=e.value});
 var body={tool:id,args:args};if(t.safety==='live'){if(!confirmLive())return;body.ack_live=true}
 api('POST','/bench/start',body,function(s,d){setMsg('benchmsg',d.message||d.error,s!==200);if(s===200)benchNeedsRefresh=true})}
poll();
</script></body></html>
"""


def render(token):
    return _HTML.replace("__TOKEN__", token)
