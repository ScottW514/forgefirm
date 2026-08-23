"""The single page: acceptance tab + bench tab. Self-contained (inline
CSS/JS, ES5, no external assets); the visual identity follows the
forgectrl control panel. State comes from GET /state, polled every 2 s
when the machine is idle and every second during a run; the catalog and
the bench listing are fetched once per tab and refreshed after a run
finishes.

Rows, prompt buttons and tool entries are built once and thereafter only
updated in place. A poll that rebuilt them would swallow the click it
landed on: the button that took the mousedown would be gone before the
mouseup, so no click event would ever be raised. Every action also greys
its control out on the press and pulls the next poll forward, so the page
answers the operator rather than the timer."""

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
/* One grid for every subsystem. The groups are separate tables, so
   left to themselves each sizes its own columns from its own content
   and no two line up. Fixed widths put them all on the same rails. */
#groups .grp{overflow-x:auto}
#groups table{table-layout:fixed;min-width:700px}
#groups col.k{width:132px}
#groups col.s{width:250px}
#groups col.l{width:210px}
#groups col.a{width:96px}
/* Why a test stands where it does reads as one block under Status. It
   used to sit under the Start button, where a requires list of three
   test ids wrapped into a ragged stack and dragged that group's columns
   out of line with every other group's. */
#groups .req{overflow-wrap:break-word}
/* The details sit in a full-width row of their own: inside the Test
   cell they would have to be read through a column, and opening one
   would push that group's grid out of step with the rest. */
#groups td{border-bottom:0}
#groups tr.detrow td{padding:0 8px;border-bottom:1px solid var(--line)}
#groups tr.detrow:last-child td{border-bottom:0}
#groups .details{margin:2px 0 8px}
#groups .details .dsc{margin-bottom:6px}
.tid{color:var(--dim);font-size:11.5px;font-family:ui-monospace,Consolas,monospace}
.badge{display:inline-block;font-size:10.5px;padding:2px 6px;border-radius:9px;margin-right:4px;background:#e8e9ec;color:#444;font-weight:600;letter-spacing:.2px;text-transform:uppercase}
.badge.live{background:#fbe1e1;color:#a11}
.badge.operator{background:#fdf3e3;color:#8a5200}
.badge.takeover{background:#e6e8f5;color:#33407a}
.badge.mode{background:#e3f1e8;color:#1f5e3a}
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
#notice{background:#e8f1fb;border:1px solid #9dbde6;border-radius:6px;padding:10px 12px;margin:8px 0;font-weight:600}
#steps{background:#f7f8fa;border-radius:6px;padding:8px 12px;margin:8px 0;font-size:12.5px;line-height:1.5}
#steps .sh{font-weight:600;margin-bottom:4px}
#steps .sub{color:var(--dim);margin:6px 0 2px}
#steps ol{margin:2px 0 4px 20px}
#steps .auto{color:var(--dim);font-style:italic}
.tsel{cursor:pointer}.tsel:hover{text-decoration:underline}
#prompt .q{font-weight:600;margin-bottom:8px}
.details{display:none;background:#f7f8fa;padding:8px 10px;border-radius:4px;font-size:12.5px;line-height:1.55;margin-top:6px}
.details.on{display:block}
.msg{color:var(--blue);font-size:13px;margin:6px 0}
.err{color:var(--red);font-size:13px;margin:6px 0}
.note{background:#fdf3e3;border:1px solid #eccb90;border-radius:6px;padding:8px 12px;margin:8px 0;font-size:13px}
.ack{display:block;margin:8px 0;font-size:12.5px}
.switch{display:flex;align-items:center;gap:8px;margin:10px 0 0;font-size:13px}
.switch input{width:16px;height:16px;margin:0}
.switch .on{color:var(--warn);font-weight:600}
.req.over{color:var(--dim)}
.grp{margin-top:6px}
.queue{background:#f7f8fa;margin:10px 0 0;padding:10px 12px}
.queue h2{margin-bottom:8px}
.queue .hint{margin-top:8px}
.qline{font-size:12.5px;color:var(--dim);line-height:1.7;margin-top:8px}
.qline b{color:var(--txt)}
.qbar{display:flex;height:6px;border-radius:3px;overflow:hidden;background:#e2e4e9;margin:6px 0}
.qbar i{display:block}
.qbar i.ok{background:var(--ok)}.qbar i.bad{background:var(--red)}
.qbar i.skip{background:var(--warn)}.qbar i.now{background:var(--blue)}
.badge.queued{background:#dde7f5;color:#24507f}
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
   <div id='invnote'></div>
   <div class='card queue'><h2>Run what is left</h2>
    <div class='actions'>
     <button class='pri' id='q-unattended' onclick='startBatch("unattended")'>Unattended</button>
     <button class='pri' id='q-attended' onclick='startBatch("attended")'>Operator and live</button>
     <button class='danger' id='q-stop' onclick='stopBatch()' disabled>Stop the queue</button>
    </div>
    <div id='qstate'></div><div id='qmsg'></div><div id='fixture' class='hint'></div>
    <p class='hint'>Each queue takes every test of its kind that the campaign does not
     already count as satisfied, runs them one at a time in prerequisite order, and stops
     on the first result that is not a PASS. The unattended queue needs nobody in the room;
     with the bench fixture up, the operator tests it can perform by itself run there too.
     The other one does: it prompts, and it fires the laser. Stop-the-queue cancels what is
     still waiting and lets the run in progress finish; Abort ends that one too.</p>
   </div>
   <div class='actions' style='margin-top:10px'>
    <button class='pri' id='exportbtn' onclick='doExport()'>Export release artifact</button>
    <a id='dljson' href='/export/acceptance.json' style='display:none'><button>acceptance.json</button></a>
    <a id='dlmd' href='/export/acceptance.md' style='display:none'><button>acceptance.md</button></a>
    <a href='/log'><button>Raw log</button></a>
    <a href='/journal'><button>Runner journal</button></a>
    <button onclick='toggleInv()'>Invalidate all&hellip;</button>
    <button onclick='doReset()'>Reset campaign</button>
   </div>
   <div id='invform' style='display:none;margin-top:8px'>
    <input type='text' id='invreason' size='60' placeholder='reason (required): what changed on the bench'>
    <button class='danger' onclick='doInvalidate()'>Invalidate all results</button>
   </div>
   <div id='actmsg'></div>
   <label class='switch'><input type='checkbox' id='ignreq' onchange='setIgnoreReq(this.checked)'>
    <span>Ignore prerequisites - Start any test on its own, whatever its <i>requires</i> list says</span>
    <span id='ignreqon'></span></label>
   <p class='hint'>A release is authorized when a campaign is open on this image and every catalog test is satisfied - by a PASS in the campaign, or (never for the core) by an earlier PASS whose domain fingerprint is unchanged. A FAIL ends the campaign. Invalidate-all forces a full campaign; give the reason. A test's <i>requires</i> list only orders the runs: with the switch above on, any test starts alone and its record notes which prerequisites were unmet - the release still needs every test satisfied.</p>
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
  <div id='steps' style='display:none'></div>
  <div id='notice' style='display:none'></div>
  <div id='prompt' style='display:none'><div class='q' id='promptq'></div><div class='actions' id='promptb'></div></div>
  <pre id='log'></pre>
  <div class='actions'><button class='danger' id='abortbtn' onclick='doAbort()' disabled>Abort</button><span class='hint' id='runfoot'></span></div>
 </div>
</div>
</main>
<script>
var TOKEN='__TOKEN__';
var state=null, catalog=null, catalogHash=null, bench=null, tab='acceptance', openDetails={};
var lastRunKey=null, stateEtag=null, curPrompt=null, promptKey=null, abortSent=false;
var pollTimer=null, polling=false, pending=0, pendingId=null, rowMsg={};
var rowEls=null, groupsKey=null, benchEls=null, benchKey=null, benchNeedsRefresh=false;
var PENDING_MS=6000;
/* A poll that never answers must not wedge the loop: it times out
   and the next one is scheduled as usual. Actions carry no timeout,
   because a POST the server did act on must not read as a failure. */
var POLL_TIMEOUT_MS=20000;
var ignoreReq=false;try{ignoreReq=window.localStorage.getItem('forgetest.ignoreReq')==='1'}catch(e){}
function $(id){return document.getElementById(id)}
function nowMs(){return (new Date()).getTime()}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
/* Touch the DOM only where the value really changed. Replacing a node
   under the operator's finger loses the click: the button that took the
   mousedown is gone before the mouseup, so no click event is ever
   raised, and the press does nothing. Nothing on a poll may rebuild a
   control that is only sitting there unchanged. */
function setHtml(e,h){if(e&&e.__h!==h){e.__h=h;e.innerHTML=h}}
function setText(e,t){if(e&&e.__t!==t){e.__t=t;e.textContent=t}}
function setDis(e,d){if(e&&e.disabled!==d)e.disabled=d}
function setProp(e,k,v){if(e&&e[k]!==v)e[k]=v}
function api(method,path,body,cb,hdrs,timeoutMs){var x=new XMLHttpRequest();x.open(method,path,true);
 if(timeoutMs)x.timeout=timeoutMs;
 x.setRequestHeader('X-ForgeFIRM-Token',TOKEN);
 if(hdrs){for(var k in hdrs){if(hdrs.hasOwnProperty(k))x.setRequestHeader(k,hdrs[k])}}
 if(body!==undefined&&body!==null){x.setRequestHeader('Content-Type','application/json')}
 x.onreadystatechange=function(){if(x.readyState!==4)return;var d=null;try{d=JSON.parse(x.responseText)}catch(e){d={error:x.responseText}}cb(x.status,d,x)};
 x.send(body===undefined||body===null?null:JSON.stringify(body))}
/* The state poll. It carries the last ETag, so an unchanged state costs
   a 304 and no re-render; a run gets a faster tick, and every action
   pulls the next poll forward instead of waiting out the interval. */
function pollDelay(){return (state&&(state.running||batchActive()))?1000:2000}
function schedule(ms){if(pollTimer)window.clearTimeout(pollTimer);pollTimer=window.setTimeout(poll,ms)}
function kick(){schedule(120)}
function poll(){if(polling){schedule(150);return}polling=true;
 /* While an action is still in flight the state is asked for in full:
    a 304 would skip the render that releases the greyed-out buttons. */
 var h=(stateEtag&&!pending)?{'If-None-Match':stateEtag}:null;
 api('GET','/state',null,function(s,d,x){polling=false;
  if(s===200){stateEtag=x.getResponseHeader('ETag');state=d;
   if(!catalog||catalogHash!==d.catalog_hash){loadCatalog(render)}else{render()}}
  schedule(pollDelay())},h,POLL_TIMEOUT_MS)}
function showTab(t){tab=t;$('tab-acceptance').className=t==='acceptance'?'on':'';$('tab-bench').className=t==='bench'?'on':'';
 $('pane-acceptance').style.display=t==='acceptance'?'':'none';$('pane-bench').style.display=t==='bench'?'':'none';
 if(t==='bench'&&!bench)loadBench()}
function setMsg(id,txt,err){setHtml($(id),txt?"<div class='"+(err?'err':'msg')+"'>"+esc(txt)+"</div>":'')}
function loadCatalog(cb){api('GET','/catalog',null,function(s,d){if(s===200){catalog=d.tests;catalogHash=d.catalog_hash;if(cb)cb()}})}
function loadBench(){api('GET','/bench',null,function(s,d){if(s===200){bench=d;benchKey=null;renderBench()}})}
function setIgnoreReq(on){ignoreReq=!!on;try{window.localStorage.setItem('forgetest.ignoreReq',ignoreReq?'1':'0')}catch(e){}
 $('ignreq').checked=ignoreReq;setHtml($('ignreqon'),ignoreReq?"<span class='on'>ON - prerequisites are not enforced</span>":'');
 if(state&&catalog)renderGroups()}
/* A start already sent but not yet seen in the state counts as busy, so
   the buttons grey out on the click rather than on the next poll. The
   window is capped in case the answer never arrives. A queue holds the
   machine between its tests as well as during them. */
function batchActive(){return !!(state&&state.batch&&!state.batch.finished)}
function isBusy(){if(state&&(state.running||batchActive()))return true;
 return !!(pending&&(nowMs()-pending)<PENDING_MS)}
function fmtTs(t){return t?t.replace('T',' ').replace('Z',' UTC'):'-'}
function render(){if(!state||!catalog)return;
 if(state.running||batchActive()){pending=0;pendingId=null}
 var m=state.manifest||{};setText($('hdrver'),(m.version||'?'));setText($('hdrsub'),m.image||'');
 var a=$('auth');setText(a,'Release authorized: '+(state.authorized?'YES':'NO'));setProp(a,'className','auth'+(state.authorized?' yes':''));
 var c=state.campaign,cn=state.counts||{};var b='';
 b+='<b>'+cn.satisfied+'</b> of <b>'+cn.total+'</b> satisfied ('+cn.inherited+' inherited), <b>'+cn.required+'</b> required<br>';
 b+=c?('campaign <span class="mono">'+esc(c.id)+'</span> opened '+esc(fmtTs(c.ts))):('no open campaign'+(state.closed_by?(' (last one closed by '+esc(state.closed_by)+')'):'')+' - the first Start opens one');
 b+='<br>manifest identity <span class="mono">'+esc((m.sha||'').slice(0,16))+'</span> &middot; catalog <span class="mono">'+esc((state.catalog_hash||'').slice(0,12))+'</span>';
 if(state.log_corrupt)b+='<br><span style="color:var(--red)">'+state.log_corrupt+' corrupt log line(s) skipped</span>';
 setHtml($('banner'),b);
 var inv=state.invalidate;setHtml($('invnote'),inv?"<div class='note'>Full campaign required since "+esc(fmtTs(inv.ts))+": "+esc(inv.reason)+"</div>":'');
 renderQueue();renderGroups();renderRun();renderSteps();if(bench)renderBench()}
/* The two queues: what each would run now, and how the running one is
   getting on. Built from the state, so a reload picks the queue back up
   exactly where it is - the queue lives in the runner, not in this tab. */
var QUEUES=[['unattended','Unattended'],['attended','Operator and live']];
function renderFixture(){var f=state.fixture,e=$('fixture');if(!e)return;
 if(!f){setHtml(e,'');return}
 var ch=(f.channels||[]).filter(function(c){return c!=='button'||f.button_enabled});
 setHtml(e,'Bench fixture <b>'+esc(f.hostname)+'</b> at '+esc(f.ip||'?')+' (v'+esc(f.version||'?')+') covers <b>'+
  (ch.length?esc(ch.join(', ')):'nothing')+'</b>'+
  ((f.channels||[]).indexOf('button')>=0&&!f.button_enabled?' (button disabled: enable jumper out)':'')+
  '; arm press: '+(f.arm_press?'<b>the fixture</b>':'the operator'))}
function renderQueue(){var av=state.batch_available||{},b=state.batch,busy=isBusy();
 renderFixture();
 QUEUES.forEach(function(p){var e=$('q-'+p[0]);if(!e)return;
  var ids=av[p[0]]||[];
  setText(e,ids.length?(p[1]+' ('+ids.length+')'):(p[1]+' (none left)'));
  setDis(e,busy||!ids.length);
  setProp(e,'title',!ids.length?('nothing left: every '+p[0]+' test is satisfied')
   :(busy?'a run is in progress':('in order: '+ids.join(', '))))});
 setDis($('q-stop'),!batchActive()||!!(b&&b.stopping));
 if(!b){setHtml($('qstate'),'');return}
 var total=b.order.length||1,ok=0,bad=0;
 b.done.forEach(function(x){if(x.result==='PASS')ok++;else bad++});
 function seg(cls,n){return n?("<i class='"+cls+"' style='width:"+(100*n/total)+"%'></i>"):''}
 var h="<div class='qbar'>"+seg('ok',ok)+seg('bad',bad)+seg('skip',b.skipped.length)+
   (b.current?seg('now',1):'')+"</div><div class='qline'><b>"+esc(b.group)+"</b> queue, opened "+
   esc(fmtTs(b.ts))+" &middot; ";
 h+=b.finished?('finished '+esc(fmtTs(b.finished))):(b.current?('running <b>'+esc(b.current)+'</b>'):
   (b.stopping?'stopping':'starting'));
 h+=" &middot; <b>"+ok+"</b> passed, <b>"+bad+"</b> not, <b>"+b.skipped.length+
   "</b> skipped, <b>"+b.pending.length+"</b> waiting";
 if(b.stopped)h+="<br><span class='req'>stopped: "+esc(b.stopped)+"</span>";
 if(b.skipped.length)h+="<br>skipped: "+esc(b.skipped.map(function(x){return x.test+' ('+x.reason+')'}).join('; '));
 if(b.pending.length)h+="<br>waiting: <span class='tid'>"+esc(b.pending.join(', '))+"</span>";
 setHtml($('qstate'),h+"</div>")}
/* The rows are built once for a given catalog and then only updated in
   place: a poll never rewrites the table, so a Start button survives the
   press that is landing on it. */
function renderGroups(){var ids=[];catalog.forEach(function(t){ids.push(t.id)});
 var sig=catalogHash+'|'+ids.join(',');
 if(sig!==groupsKey){groupsKey=sig;buildGroups()}
 updateGroups()}
var COLS="<colgroup><col><col class='k'><col class='s'><col class='l'><col class='a'></colgroup>";
function buildGroups(){var groups={},order=[];
 catalog.forEach(function(t){if(!groups[t.subsystem]){groups[t.subsystem]=[];order.push(t.subsystem)}groups[t.subsystem].push(t)});
 var h='';
 order.forEach(function(g){h+="<div class='card grp'><h2>"+esc(g)+"</h2><table>"+COLS+"<tr><th>Test</th><th>Kind</th><th>Status</th><th>Last result</th><th></th></tr>";
  groups[g].forEach(function(t){var d=esc(t.id);var badges='';
   if(t.always)badges+="<span class='badge core'>core</span>";badges+="<span class='badge "+esc(t.kind)+"'>"+esc(t.kind)+"</span>";
   if(t.hardware==='takeover')badges+="<span class='badge takeover'>takeover</span>";
   if(t.mode)badges+="<span class='badge mode'>"+esc(t.mode)+"</span>";
   var det="<div class='details"+(openDetails[t.id]?' on':'')+"' id='det-"+d+"'>"+
     (t.description?("<div class='dsc'>"+esc(t.description)+"</div>"):'')+
     (t.steps&&t.steps.length?"<b>Operator steps:</b><ol>"+t.steps.map(function(x){return '<li>'+esc(x)+'</li>'}).join('')+"</ol>":'')+
     (t.actions&&t.actions.length?"<b>Machine actions:</b> "+esc(t.actions.join(', '))+"<br>":'')+
     "<b>Requires:</b> "+esc((t.requires||[]).join(', ')||'-')+"<br><b>Covers:</b> "+esc((t.covers||[]).map(function(c){return c[0]+':'+c[1]}).join(', ')||'-')+
     "<br><span id='detdyn-"+d+"'></span></div>";
   h+="<tr><td><div class='tsel' title='show what this test asks of you' onclick='selectTest(\""+d+"\")'>"+esc(t.title)+"</div><div class='tid'>"+d+" <a href='#' onclick='toggleDet(\""+d+"\");return false'>details</a></div>"+
     "</td><td>"+badges+"</td>"+
     "<td><div id='st-"+d+"'></div><div id='unmet-"+d+"'></div><div id='note-"+d+"'></div></td>"+
     "<td id='last-"+d+"'></td>"+
     "<td><button class='pri' id='btn-"+d+"' onclick='startTest(\""+d+"\")'>Start</button></td></tr>"+
     "<tr class='detrow'><td colspan='5'>"+det+"</td></tr>"});
  h+="</table></div>"});
 $('groups').innerHTML=h;rowEls={};
 catalog.forEach(function(t){rowEls[t.id]={st:$('st-'+t.id),last:$('last-'+t.id),btn:$('btn-'+t.id),
  unmet:$('unmet-'+t.id),note:$('note-'+t.id),detdyn:$('detdyn-'+t.id)}})}
function updateGroups(){if(!rowEls||!state)return;var busy=isBusy();
 var queued={};if(batchActive()){(state.batch.pending||[]).forEach(function(x){queued[x]=1})}
 catalog.forEach(function(t){var e=rowEls[t.id];if(!e)return;var s=state.tests[t.id]||{};
  var st;
  if(pendingId===t.id&&isBusy()&&!state.running){st="<span class='st running'>starting&hellip;</span>"}
  else{st="<span class='st "+esc(s.status)+"'>"+esc(s.status||'none')+"</span>";
   if(s.required&&s.status!=='running')st+="<br><span class='req'>required: "+esc(s.reason)+"</span>"}
  if(queued[t.id])st+="<br><span class='badge queued'>queued</span>";
  setHtml(e.st,st);
  var last=s.last?(esc(s.last.result)+' '+esc(fmtTs(s.last.ts))):'-';
  if(s.status==='inherited'&&s.origin)last+="<br><span class='tid'>from "+esc(s.origin.campaign)+" on "+esc(s.origin.image)+"</span>";
  setHtml(e.last,last);
  var unmet=s.requires_met===false;var can=!busy&&(!unmet||ignoreReq);
  setDis(e.btn,!can);
  setProp(e.btn,'title',busy?'a run is in progress':(unmet?((ignoreReq?'prerequisites overridden - needs: ':'needs: ')+(s.missing_requires||[]).join(', ')):''));
  setProp(e.unmet,'className','req'+(ignoreReq?' over':''));
  setHtml(e.unmet,unmet?((ignoreReq?'unmet: ':'needs: ')+esc((s.missing_requires||[]).join(', '))):'');
  setHtml(e.note,rowMsg[t.id]?"<div class='err'>"+esc(rowMsg[t.id])+"</div>":'');
  setHtml(e.detdyn,"<b>Fingerprint:</b> <span class='mono'>"+esc((s.fingerprint||'').slice(0,16))+"</span> &middot; est. "+esc(t.est_min)+" min"+
   (s.last?"<br><a href='/result?test="+encodeURIComponent(t.id)+"&ts="+encodeURIComponent(s.last.ts)+"'>last result record</a>":''))})}
function toggleDet(id){openDetails[id]=!openDetails[id];var e=$('det-'+id);if(e)e.className='details'+(openDetails[id]?' on':'')}
function renderRun(){var r=state.running||state.last_run;var key=r?(r.kind+':'+r.id+':'+r.started):null;
 if(key!==lastRunKey)abortSent=false;
 if(!r){setText($('runhead'),'idle');setText($('log'),'');$('prompt').style.display='none';$('notice').style.display='none';
  curPrompt=null;promptKey=null;setDis($('abortbtn'),true);setText($('runtitle'),'Run');lastRunKey=null;return}
 setText($('runtitle'),(r.kind==='bench'?'Bench: ':'Test: ')+r.title);
 var hd=esc(r.id)+' &middot; started '+esc(fmtTs(r.started))+' &middot; '+r.elapsed_s+' s';
 if(r.finished){hd+=' &middot; <b class="st '+(r.finished.result==='PASS'||r.finished.result==='OK'?'pass':'fail')+'">'+esc(r.finished.result)+'</b>'+(r.finished.message?' - '+esc(r.finished.message):'')}
 else if(r.aborting){hd+=' &middot; <b class="st stale">aborting</b>'}
 setHtml($('runhead'),hd);
 var lg=$('log');var txt=(r.dropped?('... '+r.dropped+' earlier lines dropped\n'):'')+r.log.join('\n');
 if(lg.__t!==txt){var atBottom=lg.scrollTop+lg.clientHeight>=lg.scrollHeight-20;
  lg.__t=txt;lg.textContent=txt;if(atBottom||key!==lastRunKey)lg.scrollTop=lg.scrollHeight}
 lastRunKey=key;
 var nt=(r.notice&&!r.finished)?r.notice.text:'';
 setText($('notice'),nt);$('notice').style.display=nt?'':'none';
 /* The prompt buttons are rebuilt only when the prompt itself changes -
    they are the ones the operator stares at before pressing. */
 if(r.prompt&&!r.finished){var pk=r.prompt.id+'|'+r.prompt.question+'|'+r.prompt.options.length+':'+r.prompt.options.join(',');
  if(pk!==promptKey){promptKey=pk;curPrompt=r.prompt;
   $('promptq').textContent=r.prompt.question;var pb='';
   r.prompt.options.forEach(function(o,i){pb+="<button class='pri' onclick='answerIdx("+i+")'>"+esc(o)+"</button>"});
   $('promptb').innerHTML=pb;$('promptb').__h=pb;$('prompt').style.display=''}}
 else if(promptKey!==null){promptKey=null;curPrompt=null;$('prompt').style.display='none'}
 setDis($('abortbtn'),!!r.finished||abortSent||!!r.aborting);
 if(r.finished&&tab==='bench'&&r.kind==='bench'&&benchNeedsRefresh){benchNeedsRefresh=false;loadBench()}}
function findTest(id){for(var i=0;i<catalog.length;i++)if(catalog[i].id===id)return catalog[i];return null}
/* What the operator will be asked to do, shown before it is asked: the
   running test's steps for the whole run, the queue's attended tests
   before the first one starts, or the test the operator clicked on. The
   prompts and notices that follow are these steps, taken in turn. */
var selected=null;
function selectTest(id){selected=(selected===id)?null:id;renderSteps()}
function stepsOf(t,head){var h='';
 var acts=(t.actions||[]);
 if(head)h+="<div class='sub'>"+head+"</div>";
 if(t.kind==='live')h+="<div>This test fires the laser: eye protection, fire watch, exhaust, scrap under the head.</div>";
 if(acts.length)h+="<div>Machine actions: <b>"+esc(acts.join(', '))+"</b> (a standing instruction tells you when; the test watches the machine for it)</div>";
 if(t.steps&&t.steps.length)h+="<ol>"+t.steps.map(function(x){return '<li>'+esc(x)+'</li>'}).join('')+"</ol>";
 return h}
function renderSteps(){var e=$('steps');if(!e||!catalog)return;var h='',r=state.running;
 if(r&&r.kind==='test'){var t=findTest(r.id);
  if(t&&((t.steps&&t.steps.length)||(t.actions&&t.actions.length)||t.kind==='live'))h="<div class='sh'>What you will do</div>"+stepsOf(t,null)}
 else if(batchActive()&&state.batch.pending&&state.batch.pending.length){var parts=[];
  state.batch.pending.forEach(function(id){var t=findTest(id);if(t&&t.kind!=='auto')parts.push(stepsOf(t,esc(id)))});
  if(parts.length)h="<div class='sh'>Coming up in this queue</div>"+parts.join('')}
 else if(selected&&!r){var t=findTest(selected);
  if(t)h="<div class='sh'>Before you start "+esc(t.id)+"</div>"+(t.kind==='auto'?"<div class='auto'>Nothing: this test needs nobody at the machine.</div>":stepsOf(t,null))}
 setHtml(e,h);e.style.display=h?'':'none'}
function startTest(id){if(isBusy())return;var t=findTest(id);var body={test:id};
 if(ignoreReq)body.ignore_requires=true;
 if(t&&t.kind==='live'){if(!confirmLive())return;body.ack_live=true}
 pending=nowMs();pendingId=id;rowMsg={};updateGroups();
 setMsg('actmsg','starting '+id+'...');
 api('POST','/start',body,function(s,d){
  if(s!==200){pending=0;pendingId=null;rowMsg[id]=d.message||d.error;updateGroups()}
  setMsg('actmsg',d.message||d.error,s!==200);kick()})}
function confirmLive(live){return window.confirm(
 (live?('LIVE LASER QUEUE.\n\nThese fire the laser:\n - '+live.join('\n - ')+'\n'):'LIVE LASER TEST.\n')+
 '\nConfirm before starting:\n - eye protection on, everyone in the room\n - fire watch present, extinguisher at hand\n - exhaust running, lid closed, scrap in place\n - you will press the physical button to arm when prompted\n\n'+
 (live?'Start the queue?':'Start the test?'))}
/* A queue takes the machine for a long stretch, so both what it will run
   and the acknowledgment it needs are put in front of the operator once,
   before anything starts. */
function startBatch(group){if(isBusy())return;
 var ids=(state&&state.batch_available&&state.batch_available[group])||[];
 if(!ids.length)return;
 var body={group:group};if(ignoreReq)body.ignore_requires=true;
 var live=[];catalog.forEach(function(t){if(t.kind==='live'&&ids.indexOf(t.id)>=0)live.push(t.id)});
 if(live.length){if(!confirmLive(live))return;body.ack_live=true}
 else if(!window.confirm('Run these '+ids.length+' test(s), in this order?\n\n - '+ids.join('\n - ')))return;
 pending=nowMs();pendingId=null;rowMsg={};updateGroups();renderQueue();
 setMsg('qmsg','starting the '+group+' queue...');
 api('POST','/batch',body,function(s,d){
  if(s!==200){pending=0;updateGroups();renderQueue()}
  setMsg('qmsg',d.message||d.error,s!==200);kick()})}
function stopBatch(){var e=$('q-stop');if(e.disabled)return;setDis(e,true);
 setMsg('qmsg','stopping the queue...');
 api('POST','/batch/stop',{},function(s,d){setMsg('qmsg',d.message||d.error,s!==200);kick()})}
function promptBusy(on){var b=$('promptb').getElementsByTagName('button');for(var i=0;i<b.length;i++)setDis(b[i],on)}
function answerIdx(i){if(!curPrompt)return;var p=curPrompt,v=p.options[i];
 promptBusy(true);setMsg('actmsg','answer sent: '+v);
 api('POST','/answer',{prompt_id:p.id,value:v},function(s,d){
  if(s!==200){promptBusy(false);setMsg('actmsg',d.message||d.error,true)}kick()})}
function doAbort(){var b=$('abortbtn');if(b.disabled)return;abortSent=true;setDis(b,true);
 setMsg('actmsg','aborting...');
 api('POST','/abort',{},function(s,d){if(s!==200)abortSent=false;setMsg('actmsg',d.message||d.error,s!==200);kick()})}
function doExport(){var b=$('exportbtn');if(b.disabled)return;setDis(b,true);setMsg('actmsg','exporting...');
 api('POST','/export',{},function(s,d){setDis(b,false);
  if(s===200){setMsg('actmsg','exported: authorized='+d.authorized+', sha256 '+d.sha256.slice(0,16)+' - download below');$('dljson').style.display='';$('dlmd').style.display=''}
  else setMsg('actmsg',d.message||d.error,true)})}
function toggleInv(){var f=$('invform');f.style.display=f.style.display==='none'?'':'none'}
function doInvalidate(){var r=$('invreason').value;if(!r){setMsg('actmsg','a reason is required',true);return}
 api('POST','/invalidate',{reason:r},function(s,d){setMsg('actmsg',d.message||d.error,s!==200);
  if(s===200){$('invform').style.display='none';$('invreason').value=''}kick()})}
function doReset(){api('POST','/reset',{reason:'operator reset from the page'},function(s,d){setMsg('actmsg',d.message||d.error,s!==200);kick()})}
/* Same rule as the acceptance rows: the tool list is built once and then
   only updated, so a run starting never rewrites the arg fields the
   operator has typed into or the button being pressed. */
function renderBench(){if(!bench)return;var ids=[];
 bench.tools.forEach(function(t){ids.push(t.id+':'+(t.ported?1:0)+(t.installed?1:0))});
 var sig=ids.join(',');
 if(sig!==benchKey){benchKey=sig;buildBench()}
 updateBench()}
function buildBench(){var groups={dry:[],takeover:[],live:[],scope:[]};
 bench.tools.forEach(function(t){(groups[t.safety]||(groups[t.safety]=[])).push(t)});var h='';
 ['dry','takeover','scope','live'].forEach(function(g){if(!groups[g]||!groups[g].length)return;
  h+="<div class='card grp'><h2>"+esc(g)+"</h2>";
  groups[g].forEach(function(t){var d=esc(t.id);
   h+="<div class='tool' style='border-bottom:1px solid var(--line);padding:8px 0'><div><b>"+esc(t.title)+"</b> <span class='tid'>"+esc(t.script)+"</span> <span class='badge'>"+esc(t.where)+"</span>"+(t.ported?'':"<span class='badge'>unported</span>")+"</div>";
   h+="<div class='hint' style='margin:2px 0 4px'>"+esc(t.desc)+"</div>";
   if(t.args&&t.args.length){h+="<div class='argrow'>";t.args.forEach(function(a){var iid='arg-'+t.id+'-'+a.name;
     if(a.type==='choice'){h+="<label>"+esc(a.name)+" <select id='"+iid+"'>"+a.choices.map(function(c){return "<option"+(c===a.default?' selected':'')+">"+esc(c)+"</option>"}).join('')+"</select></label>"}
     else{h+="<label>"+esc(a.name)+" <input type='"+(a.type==='str'?'text':'number')+"' step='any' id='"+iid+"' value='"+esc(a.default==null?'':a.default)+"' title='"+esc(a.help)+"' style='width:90px'></label>"}});h+="</div>"}
   h+="<div class='actions'><button class='pri' id='tbtn-"+d+"' onclick='startTool(\""+d+"\")'>Start</button>";
   h+="<span class='hint' id='tlast-"+d+"'></span></div></div>"});
  h+="</div>"});
 $('tools').innerHTML=h;benchEls={};
 bench.tools.forEach(function(t){benchEls[t.id]={btn:$('tbtn-'+t.id),last:$('tlast-'+t.id)}})}
function updateBench(){if(!benchEls)return;var busy=isBusy();
 bench.tools.forEach(function(t){var e=benchEls[t.id];if(!e)return;
  var can=t.ported&&t.installed&&!busy;
  setDis(e.btn,!can);
  setProp(e.btn,'title',!t.ported?'not yet ported to the bench page':(!t.installed?'script not installed on this image':(busy?'a run is in progress':'')));
  setHtml(e.last,t.last?("last: "+esc(t.last.result?t.last.result.result:'?')+" "+esc(fmtTs(t.last.ts))):'')})}
function startTool(id){if(isBusy())return;var t=null;bench.tools.forEach(function(x){if(x.id===id)t=x});if(!t)return;var args={};
 (t.args||[]).forEach(function(a){var e=$('arg-'+id+'-'+a.name);if(e)args[a.name]=e.value});
 var body={tool:id,args:args};if(t.safety==='live'){if(!confirmLive())return;body.ack_live=true}
 pending=nowMs();pendingId=null;updateBench();updateGroups();
 setMsg('benchmsg','starting '+id+'...');
 api('POST','/bench/start',body,function(s,d){
  if(s!==200){pending=0;updateBench();updateGroups()}
  setMsg('benchmsg',d.message||d.error,s!==200);if(s===200)benchNeedsRefresh=true;kick()})}
setIgnoreReq(ignoreReq);
poll();
</script></body></html>
"""


def render(token):
    return _HTML.replace("__TOKEN__", token)
