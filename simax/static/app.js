/* SimaX local UI. All dynamic text is escaped; no sample production state is seeded. */
"use strict";
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const engines = {postgresql:"PostgreSQL",mysql:"MySQL",oracle:"Oracle Database",sqlserver:"SQL Server"};
const nav = [["overview","Overview"],["policies","Policies"],["sources","Sources"],["runs","Runs"],["artifacts","Artifacts"],["restore","Restore"],["audit","Audit log"],["settings","Settings"]];
const paths = {
  overview:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  policies:'<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  sources:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  runs:'<path d="m9 5 10 7-10 7z"/>',artifacts:'<path d="M4 8h16v13H4zM3 3h18v5H3zM9 12h6"/>',
  restore:'<path d="M3 10a9 9 0 1 1 1 8M3 4v6h6M12 8v5l3 2"/>',
  audit:'<path d="M9 5h12M9 12h12M9 19h12M3 5h1M3 12h1M3 19h1"/>',
  settings:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',check:'<path d="m5 12 4 4 10-10"/>'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.sources}</svg>`;
const button = (label, action, id="", primary=false, small=false) => `<button type="button" class="button ${primary?"primary":""} ${small?"small":""}" data-action="${action}" data-id="${esc(id)}">${esc(label)}</button>`;
const link = (label, href, primary=false) => `<a class="button ${primary?"primary":""}" href="${esc(href)}">${esc(label)}</a>`;
const chip = (label, tone="mute") => `<span class="chip ${tone}">${esc(label)}</span>`;
const env = source => `<span class="env ${source.environment === "PROD"?"prod":""}">${esc(source.environment)}</span>`;
const empty = (title, text, action="", symbol="artifacts") => `<div class="empty">${icon(symbol)}<h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
const table = (heads, rows) => `<div class="panel table-wrap"><table><thead><tr>${heads.map(h=>`<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
const row = cells => `<tr>${cells.map(c=>`<td>${c}</td>`).join("")}</tr>`;
const section = (title, content, extra="") => `<section class="section"><div class="section-heading"><h2>${esc(title)}</h2>${extra}</div>${content}</section>`;
const header = (title, text, actions="") => `<header class="page-header"><div><h1 tabindex="-1">${esc(title)}</h1><p>${esc(text)}</p></div><div class="actions">${actions}</div></header>`;
const field = (label, name, value="", type="text", extra="", help="") => `<label class="field">${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}>${help?`<small>${esc(help)}</small>`:""}</label>`;
const select = (label, name, options, current, extra="") => `<label class="field">${esc(label)}<select name="${name}" ${extra}>${options.map(([v,l])=>`<option value="${esc(v)}" ${String(v)===String(current)?"selected":""}>${esc(l)}</option>`).join("")}</select></label>`;
const notice = (title, text, kind="") => `<div class="notice ${kind}"><strong>${esc(title)}</strong>${esc(text)}</div>`;
let state, preview=null, toastTimer, loading=false;
let filters={artifactSource:"",artifactEvidence:"",runStatus:"",auditSearch:""};
const route = () => (location.hash.slice(1) || "overview").split("/");
const sourceById = id => state.sources.find(s=>s.id===id);
const policyById = id => state.policies.find(p=>p.id===id);
const formatDate = value => value ? new Intl.DateTimeFormat("en-GB", {timeZone:state?.settings.timezone||"Asia/Jakarta",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(value)) : "—";
const age = value => {if(!value)return "No recovery point";const hours=Math.max(0,(Date.now()-Date.parse(value))/36e5);return hours<1?"Less than 1 h old":hours<48?`${Math.floor(hours)} h old`:`${Math.floor(hours/24)} days old`;};
const bytes = n => n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KiB`:`${(n/1048576).toFixed(1)} MiB`;
function toast(message){$("#toast").textContent=message;$("#toast").hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("#toast").hidden=true,6000);}
async function api(path, method="GET", body){
  const response=await fetch(`/api${path}`,{method,headers:{"Content-Type":"application/json","X-SimaX-Request":"1"},...(body!==undefined?{body:JSON.stringify(body)}:{})});
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail || "The request could not be completed.");
  return data;
}
async function refresh(renderPage=true){
  state=await api("/state");
  const running=state.runtime==="running";
  $("#runtime").innerHTML=`<strong><span class="dot ${running?"":"off"}"></span>Runtime ${esc(state.runtime)}</strong><span class="sub">${running?"Jobs and schedules continue when this window is closed. Keep the runtime host awake.":esc(state.runtime_error||"Start the SimaX runtime to execute jobs.")}</span>`;
  if(renderPage)render();
}
function render(){
  const [page,id]=route();
  $("#navigation").innerHTML=nav.map(([key,label])=>`<a href="#${key}" class="${page===key?"active":""}" ${page===key?'aria-current="page"':""}>${icon(key)}${label}</a>`).join("");
  const views={overview,policies:()=>id?policyForm(id):policies(),sources,runs:()=>id?runDetail(id):runs(),artifacts,restore:()=>restorePage(id),audit,settings:()=>settings(id)};
  $("#main").innerHTML=(views[page]||overview)();
  if($("#policy-form"))updateScheduleVisibility($("#policy-form"));
  document.title=`${nav.find(n=>n[0]===page)?.[1]||"Overview"} · SimaX`;
}
function latestArtifact(id){return state.artifacts.filter(a=>a.source_id===id).sort((a,b)=>b.snapshot.localeCompare(a.snapshot))[0];}
function attention(){
  const items=[];
  for(const p of state.policies.filter(p=>p.enabled&&eventNames[p.trigger])){
    const evidence=(state.trigger_state||[]).find(s=>s.id===p.id&&s.revision===p.revision);
    if(evidence&&["degraded","rejected"].includes(evidence.status))items.push({title:"Trigger needs attention",name:p.name,text:evidence.message,href:`#policies/${p.id}`,action:"Review trigger",tone:"warn"});
  }
  for(const source of state.sources.filter(s=>s.role==="source")){
    const artifact=latestArtifact(source.id);
    const last=state.runs.find(r=>r.kind==="backup"&&r.source.id===source.id);
    if(last&&["failed","interrupted"].includes(last.status))items.push({title:"Backup needs attention",name:source.name,text:last.error||"The last run did not finish.",href:`#runs/${last.id}`,action:"Inspect run",tone:"bad"});
    else if(source.preflight&&!source.preflight.ok)items.push({title:"Connection check failed",name:source.name,text:source.preflight.message,href:"#sources",action:"Review connection",tone:"warn"});
    else if(!artifact)items.push({title:"No recovery point",name:source.name,text:"This source has no completed backup yet. Create a policy and run the first backup.",href:"#policies",action:"Review policies",tone:"warn"});
    else if((Date.now()-Date.parse(artifact.snapshot))/36e5>state.settings.recovery_limit_hours)items.push({title:"Recovery point overdue",name:source.name,text:`Latest recovery point is ${age(artifact.snapshot)}. The configured limit is ${state.settings.recovery_limit_hours} hours.`,href:"#policies",action:"Review policies",tone:"warn"});
    else if(!artifact.restore_test)items.push({title:"No restore evidence",name:source.name,text:"The backup has passed its integrity check. A recovery drill has not been recorded.",href:`#restore/${artifact.id}`,action:"Prepare a recovery drill",tone:"mute"});
    else if((Date.now()-Date.parse(artifact.restore_test.time))/864e5>state.settings.restore_test_limit_days)items.push({title:"Restore evidence is old",name:source.name,text:"The recorded table-inventory check is older than your configured limit. Data and behavior still need operator verification.",href:`#restore/${artifact.id}`,action:"Prepare another drill",tone:"warn"});
  }
  return items;
}
function overview(){
  let html=header("Protection overview","Latest usable recovery point per source. Backup, integrity and restore-test evidence are tracked separately: a finished backup is not proof of recovery.",link("Restore","#restore")+link("New backup policy","#policies/new",true));
  const alerts=attention();
  if(alerts.length)html+=section("Needs attention",`<div class="attention-grid">${alerts.slice(0,6).map(a=>`<article class="panel attention-card">${chip(a.title,a.tone)}<h3>${esc(a.name)}</h3><p>${esc(a.text)}</p><a href="${a.href}">${a.action} →</a></article>`).join("")}</div>`);
  else if(state.sources.length)html+=notice("No new protection alerts","Review restore evidence separately; successful backup jobs alone do not prove recoverability.");
  const sources=state.sources.filter(s=>s.role==="source");
  const body=sources.length?table(["Source","Latest recovery point","Backup","Integrity","Restore tested","Copies","Status"],sources.map(s=>{
    const a=latestArtifact(s.id),last=state.runs.find(r=>r.kind==="backup"&&r.source.id===s.id);
    const risk=last&&["failed","interrupted"].includes(last.status);
    return row([`<strong>${esc(s.name)}</strong><small>${engines[s.engine]}</small>${env(s)}`,a?`${formatDate(a.snapshot)}<small>${age(a.snapshot)}</small>`:"—",risk?"Last run failed":a?"Finalized":"Not run",a?chip("Verified","ok"):"Not checked",a?.restore_test?`${formatDate(a.restore_test.time)}<small>Table inventory only</small>`:"Never",a?"1 of 1":"0 of 1",risk?chip("At risk","bad"):a?chip("Review restore evidence","mute"):chip("Not protected","warn")]);
  })): `<div class="panel">${empty("Start with your first connection","Add a database source, define its backup policy, then verify your first recovery point.",button("Add connection","source-new","",true),"sources")}<div class="intro-grid"><div class="intro-step"><span>01 / CONNECT</span><strong>Know your source</strong><p>Keep production and test environments clearly separated.</p></div><div class="intro-step"><span>02 / PROTECT</span><strong>Define a policy</strong><p>Choose when to run and where your local SQL files go.</p></div><div class="intro-step"><span>03 / VERIFY</span><strong>Practice recovery</strong><p>Test a backup in a disposable database before you need it.</p></div></div></div>`;
  html+=section("Sources",body,`<span class="sub">Times in ${esc(state.settings.timezone)} · ${formatDate(state.time)}</span>`);
  html+=section("Recent runs",state.runs.length?runTable(state.runs.slice(0,5)):`<div class="panel">${empty("No runs yet","Accepted backup and restore jobs will appear here with their actual stages and results.","","runs")}</div>`,state.runs.length?'<a href="#runs" class="sub">View all runs →</a>':"");
  return html;
}
function sources(){
  let html=header("Sources","Database servers SimaX reads from or restores to. Check each connection before its first backup.",button("Add connection","source-new","",true));
  html+=state.sources.length?table(["Connection","Engine","Environment","Used as","Preflight","Actions"],state.sources.map(s=>row([
    `<strong>${esc(s.name)}</strong><small class="mono">${esc(s.host)}:${s.port} / ${esc(s.database)}</small>`,engines[s.engine],env(s),s.role==="target"?"Restore target":"Source",!s.preflight?chip("Not checked"):s.preflight.ok?chip("Ready","ok"):chip("Needs attention","warn"),`<div class="actions">${button("Check","source-check",s.id,false,true)}${button("Edit","source-edit",s.id,false,true)}</div>`
  ]))):`<div class="panel">${empty("No connections configured","Register a PostgreSQL or MySQL source to start. Oracle and SQL Server connections can be recorded for later integration.",button("Add connection","source-new","",true),"sources")}</div>`;
  const checked=state.sources.filter(s=>s.preflight);
  if(checked.length)html+=section("Connection evidence",`<div class="stack">${checked.map(s=>`<article class="panel padded stack"><div class="section-heading"><h3>${esc(s.name)} ${env(s)}</h3><span class="sub">Checked ${formatDate(s.preflight.checked)}</span></div>${notice(s.preflight.ok?"Connection and native tools available":"Preflight needs attention",s.preflight.message,s.preflight.ok?"":"warning")}${s.preflight.ok?`<p class="sub">${esc(s.preflight.version)} · ${s.preflight.tables.length} tables discovered</p>`:""}</article>`).join("")}</div>`);
  return html+notice("Credentials are encrypted locally","Database usernames and passwords are stored encrypted on this computer. Enter passwords directly in the connection editor; no environment file or restart is needed. Keep the local encryption key with your catalog recovery copy.");
}
function sourceDialog(id){
  const s=sourceById(id)||{name:"",engine:"postgresql",host:"localhost",port:5432,database:"",username:"",environment:"DEV",role:"source",tls:"verify-full"};
  $("#dialog-body").innerHTML=`<form id="source-form" data-id="${esc(id||"")}" class="dialog-content"><div class="dialog-header"><h2 id="dialog-title">${id?"Edit connection":"Add connection"}</h2><button type="button" class="close-button" data-action="close" aria-label="Close dialog">×</button></div><div class="fields">${field("Connection name","name",s.name,"text",'required maxlength="80" placeholder="orders-dev"')}${select("Database engine","engine",Object.entries(engines),s.engine)}${field("Host","host",s.host,"text","required")}${field("Port","port",s.port,"number",'required min="1" max="65535"')}${field("Database","database",s.database,"text","required")}${field("Backup user","username",s.username,"text","required")}${select("Environment","environment",["PROD","STAGING","DEV","DISPOSABLE"].map(x=>[x,x]),s.environment)}${select("Used as","role",[["source","Backup source"],["target","Restore target"]],s.role)}</div>${field("Database password","password","","password",'autocomplete="new-password" maxlength="4096"',s.password_saved?"Saved encrypted. Leave blank to keep the current password.":"Stored encrypted on this computer. No environment file or restart is needed.")}${select("Connection security","tls",[["verify-full","TLS — verify server identity"],["disable","No database TLS — trusted private network"]],s.tls)}<p class="sub">Restore targets must be empty, dedicated databases labeled DISPOSABLE. Oracle and SQL Server execution is planned.</p><p class="error-text form-error" role="alert"></p><div class="dialog-actions">${button("Cancel","close")}<button class="button primary" type="submit">Save connection</button></div></form>`;
  $("#dialog").showModal();
}
function policies(){
  let html=header("Backup policies","Define what is captured, when it runs, and where the recovery copy is stored. Every run records the policy revision it used.",link("New backup policy","#policies/new",true));
  html+=state.policies.length?table(["Policy","Source","Trigger","Destination","State","Actions"],state.policies.map(p=>row([
    `<a href="#policies/${p.id}"><strong>${esc(p.name)}</strong></a><small class="mono">Revision ${p.revision}</small>`,esc(sourceById(p.source_id)?.name||p.source_id),scheduleLabel(p),`Local / ${esc(p.destination)}<small>Single SQL file · whole database</small>`,chip(p.enabled?"Enabled":"Paused",p.enabled?"ok":"mute"),`<div class="actions">${button("Run now","policy-run",p.id,true,true)}${button(p.enabled?"Pause":"Enable","policy-toggle",p.id,false,true)}</div>`
  ]))):`<div class="panel">${empty("Give your backups a plan","A policy connects a database to its schedule and backup destination. Start with a manual run so you can inspect the result.",link("Create first policy","#policies/new",true),"policies")}</div>`;
  return html+notice("What this first release can execute","PostgreSQL/MySQL whole-database SQL exports to one local destination, triggered manually, by schedules, read-only change polling, signed webhooks or MQTT. Advanced object selection, other formats, Redis and remote destinations are planned.");
}
function formSection(number,title,body){return `<section class="panel form-section"><div class="form-heading"><span class="step">${number}</span><h2>${title}</h2></div>${body}</section>`;}
const eventNames={"table-change":"Table change","database-change":"Database change",webhook:"Webhook",mqtt:"MQTT"};
const eventKeys=["poll_seconds","change_tables","acknowledge_scan","debounce_seconds","cooldown_seconds","event_secret","mqtt_host","mqtt_port","mqtt_topic","mqtt_tls","mqtt_username","mqtt_password"];
function policyPayload(p){return Object.fromEntries(["name","source_id","destination","trigger","time","timezone","weekdays","cron","enabled",...eventKeys].map(k=>[k,p[k]]));}
function eventEvidence(p,compact=false){
  const evidence=(state.trigger_state||[]).find(s=>s.id===p.id&&s.revision===p.revision);
  if(!p.enabled)return chip("Paused");
  if(state.runtime!=="running")return chip("Runtime stopped","warn");
  if(!evidence)return chip("Waiting for observer","warn");
  const overdue=["table-change","database-change"].includes(p.trigger)&&evidence.last_poll&&Date.now()/1000>evidence.last_poll+p.poll_seconds+60;
  const status=overdue?"Scan overdue":evidence.status;
  return `${chip(status,["degraded","rejected","waiting","Scan overdue"].includes(status)?"warn":"ok")}${compact?"":`<small>${esc(evidence.message)}</small>`}${evidence.pending?`<small>${evidence.pending.count} events pending${compact?"":"; follow-up waits for active backup and cooldown"}.</small>`:""}<small>Checked ${formatDate(evidence.checked)}</small>${evidence.last_run?`<small><a href="#runs/${esc(evidence.last_run)}">Latest event backup →</a></small>`:""}`;
}
function eventFields(p){return `
  <div class="stack" data-schedule="table-change database-change">${notice("Read-only polling, not continuous change capture","Each poll scans and sorts hashes of table rows and reads column definitions. Inserts, updates, deletes, truncation and column changes are observable when their effects remain until a poll. Database mode also observes table creation/removal. Indexes, constraints beyond column metadata, routines, triggers, views and transient changes are not watched. This still backs up the whole database.","warning")}${field("Poll interval (seconds)","poll_seconds",p.poll_seconds??300,"number",'required min="60" max="86400"')}<label class="option"><input type="checkbox" name="acknowledge_scan" ${p.acknowledge_scan?"checked":""} required><span>I accept full-table scan cost and observation gaps. Use SELECT access to all watched rows. The first poll records a baseline without running a backup.</span></label></div>
  <div data-schedule="table-change"><label class="field">Tables to watch (one per line)<textarea name="change_tables" rows="4" required placeholder="public.orders">${esc((p.change_tables||[]).join("\n"))}</textarea><small>Use exact preflight table names: schema.table for PostgreSQL, table for MySQL. Up to 100. A missing watched table degrades observation.</small></label></div>
  <div class="fields" data-schedule="table-change database-change webhook mqtt">${field("Coalescing window (seconds)","debounce_seconds",p.debounce_seconds??10,"number",'required min="0" max="300"',"Starts at the first event; bursts cannot postpone it indefinitely.")}${field("Minimum time between event backups (seconds)","cooldown_seconds",p.cooldown_seconds??300,"number",'required min="60" max="86400"')}</div>
  <div class="stack" data-schedule="webhook mqtt">${field("Event signing secret","event_secret","","password",'autocomplete="new-password" maxlength="4096"',p.event_secret_saved?"Saved encrypted. Leave blank to keep the current signing secret.":"Enter a random shared secret of at least 32 bytes. Stored encrypted; use the same secret in your publisher.")}${notice("Authenticated events only","Signed events expire after five minutes. Event IDs are deduplicated for seven days. Accepted events survive restarts and coalesce into a bounded pending follow-up. Editing or pausing discards pending requests from the old revision; queued jobs remain.")}</div>
  <div class="stack" data-schedule="webhook"><p class="sub">${p.id?`POST ${esc(location.origin)}/api/triggers/webhook/${esc(p.id)}`:"Save the policy to obtain its webhook URL."}</p><p class="sub">Loopback endpoint for local integrations. Use the included scripts/send_event.py helper to sign requests; see docs/event-triggers.md. This does not expose the management app to the network.</p></div>
  <div class="stack" data-schedule="mqtt"><div class="fields">${field("MQTT broker host","mqtt_host",p.mqtt_host||"localhost","text","required")}${field("MQTT broker port","mqtt_port",p.mqtt_port??8883,"number",'required min="1" max="65535"')}${field("Exact MQTT topic","mqtt_topic",p.mqtt_topic||"simax/backup","text",'required maxlength="200"',"No + or # wildcards. Publishers must send QoS 1, non-retained signed JSON.")}${select("Broker transport","mqtt_tls",[["true","TLS — verify server identity"],["false","No TLS — trusted private network"]],String(p.mqtt_tls??true))}${field("Broker username (optional)","mqtt_username",p.mqtt_username||"","text",'maxlength="128"')}${field("Broker password","mqtt_password","","password",'autocomplete="new-password" maxlength="4096"',p.mqtt_password_saved?"Saved encrypted. Leave blank to keep it; clear the username to remove broker authentication.":"Required with a username. Stored encrypted, separately from the signing secret.")}</div>${notice("MQTT delivery boundary","MQTT 3.1.1 clean sessions reconnect and resubscribe. Offline messages are not replayed. Retained messages and QoS 0 are rejected. QoS 1 is acknowledged after durable acceptance; publishers must retry after gaps using the same event ID.")}</div>
  ${p.id&&eventNames[p.trigger]?`<div class="notice"><strong>Trigger evidence</strong>${eventEvidence(p)}</div>`:""}`;}
function eventPayload(form){
  const values=new FormData(form), result={};
  for(const key of eventKeys)if(values.has(key))result[key]=values.get(key);
  for(const key of ["poll_seconds","debounce_seconds","cooldown_seconds","mqtt_port"])if(key in result)result[key]=Number(result[key]);
  result.acknowledge_scan=values.get("acknowledge_scan")==="on";
  if("mqtt_tls" in result)result.mqtt_tls=result.mqtt_tls==="true";
  if("change_tables" in result)result.change_tables=result.change_tables.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
  for(const key of ["event_secret","mqtt_password"])if(result[key]==="")delete result[key];
  return result;
}
const weekdayNames=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
function scheduleLabel(p){
  if(p.trigger==="manual")return "Manual";
  if(eventNames[p.trigger])return `${esc(eventNames[p.trigger])}<div class="trigger-evidence">${eventEvidence(p,true)}</div>`;
  const label=p.trigger==="cron"?`Cron: ${p.cron}`:p.trigger==="weekly"?`${(p.weekdays||[0]).map(d=>weekdayNames[d]).join(", ")} at ${p.time}`:`Daily at ${p.time}`;
  return `${esc(label)}<small>${esc(p.timezone)}</small>`;
}
function scheduleFields(p){return `<div class="fields">${select("Trigger","trigger",[["manual","Manual only"],["daily","Daily schedule"],["weekly","Weekly schedule"],["cron","Cron schedule"],...Object.entries(eventNames)],p.trigger)}${select("Policy state","enabled",[["true","Enabled"],["false","Paused"]],String(p.enabled))}</div>
  <div data-schedule="daily weekly" ${["daily","weekly"].includes(p.trigger)?"":"hidden"}>${field("Local time","time",p.time,"time","required")}</div>
  <fieldset class="weekdays" data-schedule="weekly" ${p.trigger==="weekly"?"":"hidden"}><legend>Days of the week</legend>${weekdayNames.map((label,i)=>`<label><input type="checkbox" name="weekdays" value="${i}" ${(p.weekdays||[0]).includes(i)?"checked":""}>${label}</label>`).join("")}</fieldset>
  <div data-schedule="cron" ${p.trigger==="cron"?"":"hidden"}>${field("Cron expression","cron",p.cron||"0 3 * * *","text",'maxlength="256"',"Minute · hour · day of month · month · day of week (0 or 7 = Sunday). Numbers, *, lists, ranges and steps. Example: 0 */6 * * * runs every six hours.")}<p class="sub">When both day fields are restricted, either may match.</p></div>
  <div data-schedule="daily weekly cron" ${p.trigger==="manual"?"hidden":""}>${field("Time zone","timezone",p.timezone,"text","required","IANA zone, such as Asia/Jakarta or Europe/London.")}<div class="schedule-preview"><div class="actions">${button("Preview upcoming runs","schedule-preview")}<span class="sub">Preview does not save or start a backup.</span></div><div id="schedule-preview" role="status" aria-live="polite">Preview the next five occurrences before saving.</div></div></div>
  <p class="sub" data-schedule="daily weekly cron">After downtime, only the latest due occurrence from today in this time zone is queued. Earlier days are skipped. Repeated daylight-saving times run once at the first occurrence; nonexistent times are skipped. An occurrence during an active backup is coalesced. Edits take effect for future occurrences; pausing does not cancel queued jobs.</p>
  ${eventFields(p)}<p class="sub">Redis triggers are planned.</p>`;}
function schedulePayload(form){
  const values=new FormData(form);
  return {trigger:values.get("trigger"),time:values.get("time")??"03:00",timezone:values.get("timezone")??state.settings.timezone,cron:values.get("cron")??"0 3 * * *",weekdays:values.getAll("weekdays").map(Number)};
}
function updateScheduleVisibility(form){
  const trigger=form.elements.trigger.value;
  for(const area of form.querySelectorAll("[data-schedule]")){
    area.hidden=!area.dataset.schedule.split(" ").includes(trigger);
    for(const input of area.querySelectorAll("input,select,textarea"))input.disabled=area.hidden;
  }
}
function invalidateSchedule(form){
  form.dataset.scheduleVersion=String(Number(form.dataset.scheduleVersion||0)+1);
  updateScheduleVisibility(form);
  form.querySelector("#schedule-preview").textContent="Schedule changed. Preview upcoming runs again.";
}
async function previewSchedule(button){
  const form=button.closest("form"), version=form.dataset.scheduleVersion||"0", output=form.querySelector("#schedule-preview");
  button.disabled=true;output.textContent="Calculating upcoming runs…";
  try{
    const result=await api("/schedules/preview","POST",schedulePayload(form));
    if(!form.isConnected||(form.dataset.scheduleVersion||"0")!==version)return;
    output.innerHTML=`<p>Upcoming occurrences in ${esc(result.timezone)} (with UTC offset)${form.elements.enabled.value==="false"?". This policy is paused":""}:</p><ol>${result.occurrences.map(o=>`<li><time datetime="${esc(o.utc)}">${esc(o.local.replace("T"," "))}</time></li>`).join("")}</ol>${result.occurrences.length<5?`<p>Only ${result.occurrences.length} occurrences fall within the next ${result.horizon_years} years.</p>`:""}<p class="sub">Planned times; actual execution depends on runtime availability and the queue.</p>`;
  }catch(error){if(form.isConnected&&(form.dataset.scheduleVersion||"0")===version)output.textContent=error.message;}
  finally{button.disabled=false;}
}
function policyForm(id){
  const p=policyById(id)||{name:"",source_id:"",destination:"local",trigger:"manual",time:"03:00",timezone:state.settings.timezone,enabled:true};
  const eligible=state.sources.filter(s=>s.role==="source"&&["postgresql","mysql"].includes(s.engine));
  if(!eligible.length)return '<a class="breadcrumbs" href="#policies">← Policies</a>'+header("New backup policy","Connect a supported source before creating a policy.")+`<div class="panel">${empty("A database connection comes first","Add a PostgreSQL or MySQL source. You can test connectivity and tooling from Sources.",button("Add connection","source-new","",true),"sources")}</div>`;
  return '<a class="breadcrumbs" href="#policies">← Policies</a>'+header(id==="new"?"New backup policy":"Edit backup policy","A policy defines what is captured, what starts it and where the recovery copy goes. Changes create a new revision.")+`<form id="policy-form" data-id="${id==="new"?"":esc(id)}" class="form-layout"><div class="stack">`+
    formSection("01","Source",`<div class="fields">${field("Policy name","name",p.name,"text",'required maxlength="80" placeholder="nightly-orders"')}${select("Source connection","source_id",eligible.map(s=>[s.id,`${s.name} · ${engines[s.engine]}`]),p.source_id,"required")}</div>`)+
    formSection("02","What to capture",`<div class="option selected"><span>${icon("sources")}</span><span><strong>Whole database</strong><small>Schema and data, including database-local routines and triggers supported by the native export tool. Objects added later are included.</small></span></div>${notice("Review the scope","PostgreSQL ownership and grants, roles, tablespaces and other cluster objects are excluded. MySQL definers may require matching accounts. Schema changes must be quiesced during export.")}<p class="sub">Schema and individual object selection will be added after dependency handling is validated.</p>`)+
    formSection("03","What starts a backup",scheduleFields(p))+
    formSection("04","Output format",`<div class="option selected"><span><strong>Single SQL file</strong><small>One SQL payload with a companion JSON manifest recording source version, checksum, table inventory and recovery limitations.</small></span></div><div class="option-row"><div class="option disabled"><span>Multiple SQL files<small>Planned</small></span></div><div class="option disabled"><span>Encrypted SimaX binary<small>Planned</small></span></div></div>`)+
    formSection("05","Where the copy goes",`${field("Local destination folder","destination",p.destination,"text",'required pattern="[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}"',"Folder label inside the managed backup directory. Each run gets its own immutable directory.")}<p class="sub mono">${esc(state.data_directory)} / backups / &lt;folder&gt; / &lt;run&gt;</p>${notice("One required local copy","Complete means the SQL export and manifest are finalized, and the local file is integrity-checked. FTP, SFTP, AWS S3 and Google Cloud Storage are planned.")}`)+
    formSection("06","Retention",`<p>Backups are kept until you remove them manually outside SimaX. Automatic retention, deletion previews and pinning are planned.</p>${notice("No automatic deletion","Monitor free disk space. This first release never deletes completed backup files automatically.","warning")}`)+
    `</div><aside class="panel summary"><h2>Effective policy</h2><dl><div><dt>Captures</dt><dd>Whole database, schema and data.</dd></div><div><dt>Output</dt><dd>Single SQL file + manifest.</dd></div><div><dt>Complete when</dt><dd>The required local copy is finalized and integrity checked.</dd></div><div><dt>After the first backup</dt><dd>Run a recovery drill. File integrity alone does not prove recoverability.</dd></div></dl><p class="error-text form-error" role="alert"></p><button type="submit" name="intent" value="run" class="button primary">Save and run first backup</button><button type="submit" name="intent" value="save" class="button">Save without running</button><a href="#policies" class="sub">Cancel</a></aside></form>`;
}
function runTable(items){return table(["Run","Source / target","Started by","Policy revision","Stage reached","Result"],items.map(r=>row([
  `<a class="mono" href="#runs/${r.id}">${esc(r.id.slice(0,12))}</a><small>${formatDate(r.created)}</small>`,esc(r.source.name),esc(r.origin),r.policy?`${esc(r.policy.name)}<small class="mono">r${r.policy.revision}</small>`:"Recovery drill",esc(r.stage),chip(r.status,r.status==="succeeded"?"ok":["failed","interrupted"].includes(r.status)?"bad":"mute")
])));}
function runs(){
  const items=state.runs.filter(r=>!filters.runStatus||r.status===filters.runStatus);
  return header("Runs","Every accepted job, its immutable policy revision, stages and outcome. Backup and restore evidence are recorded separately.")+`<div class="filters">${select("Result","runStatus",[["","All results"],...["queued","running","succeeded","failed","interrupted","cancelled"].map(x=>[x,x])],filters.runStatus,'data-filter="runStatus"')}<span class="count">${items.length} runs</span></div>`+(items.length?runTable(items):`<div class="panel">${empty("No matching runs","Run a policy to see its actual export and verification stages here.",link("View policies","#policies"),"runs")}</div>`);
}
function runDetail(id){
  const r=state.runs.find(x=>x.id===id);if(!r)return header("Run not found","Choose a run from the history.",link("All runs","#runs"));
  const actions=r.status==="queued"?button("Cancel queued run","run-cancel",id):r.kind==="backup"&&["failed","interrupted"].includes(r.status)?button("Run a new backup","policy-run",r.policy.id,true):r.artifact_id?link("View artifacts","#artifacts"):"";
  let html='<a class="breadcrumbs" href="#runs">← All runs</a>'+header(r.id,`${r.source.name} · ${engines[r.source.engine]} · ${r.origin}`,actions);
  html+=`<div class="actions">${chip(r.status,["failed","interrupted"].includes(r.status)?"bad":r.status==="succeeded"?"ok":"mute")}${env(r.source)}<span class="sub">${r.kind==="backup"?"Backup":"Restore"} · ${formatDate(r.created)}</span></div>`;
  html+=`<div class="detail-grid"><section class="panel stack"><h2>${r.error?"What happened":"Execution details"}</h2>${r.error?notice("Operation did not complete",r.error,"error"):notice("Current stage",r.stage)}<dl class="detail-list"><dt>Scheduled for</dt><dd>${r.scheduled_for?esc(r.scheduled_for):r.trigger_event?`${esc(r.origin)} · ${r.trigger_event.count} coalesced events`:"Manual request"}</dd><dt>Started</dt><dd>${formatDate(r.started)}</dd><dt>Finished</dt><dd>${formatDate(r.finished)}</dd><dt>Database</dt><dd>${esc(r.source.database)}</dd><dt>Correlation</dt><dd class="mono">${esc(r.id)}</dd></dl><p class="sub">Raw native-tool output is withheld because it may contain credentials, SQL or database rows.</p></section><section class="panel stack"><h2>Recovery point impact</h2><p>${r.kind==="restore"?"A completed replay records table-inventory evidence only. Validate restored data and application behavior separately.":"Only finalized artifacts appear in the catalog. Failed exports never advance the latest recovery point."}</p>${r.policy?`<p class="sub">Policy snapshot: ${esc(r.policy.name)} r${r.policy.revision}. A new run uses the current policy revision.</p>`:""}</section></div>`;
  html+=section("Timeline",r.events.length?table(["Time","Stage"],r.events.map(e=>row([formatDate(e.time),esc(e.stage)]))):`<div class="panel">${empty("Waiting to start","The runtime processes one job at a time. You can cancel this job while it is queued.","","runs")}</div>`);
  return html;
}
function artifacts(){
  const items=state.artifacts.filter(a=>(!filters.artifactSource||a.source_id===filters.artifactSource)&&(!filters.artifactEvidence||(filters.artifactEvidence==="never"?!a.restore_test:!!a.restore_test)));
  return header("Artifacts","Every completed backup, where its copy lives, and what has actually been checked.")+`<div class="filters">${select("Source","artifactSource",[["","All sources"],...state.sources.filter(s=>s.role==="source").map(s=>[s.id,s.name])],filters.artifactSource,'data-filter="artifactSource"')}${select("Restore evidence","artifactEvidence",[["","All evidence"],["never","Never tested"],["tested","Table inventory checked"]],filters.artifactEvidence,'data-filter="artifactEvidence"')}<span class="count">${items.length} artifacts</span></div>`+
    (items.length?table(["Recovery point","Source","Format","Copy","Integrity","Restore evidence","Actions"],items.map(a=>row([
      `${formatDate(a.snapshot)}<small>${age(a.snapshot)}</small>`,esc(a.source_name),`Single SQL<small>${bytes(a.bytes)}</small>`,`Local<small>1 of 1 required</small>`,chip("Verified","ok"),a.restore_test?`${formatDate(a.restore_test.time)}<small>Table inventory only</small>`:chip("Never tested"),`<div class="stack">${link("Restore",`#restore/${a.id}`)}<a class="sub" href="/api/artifacts/${a.id}/manifest">Manifest ↓</a></div>`
    ]))):`<div class="panel">${empty("No matching artifacts","Only successfully finalized SQL exports appear here. Partial and failed files are never offered for restore.",link("View backup policies","#policies"),"artifacts")}</div>`)+
    notice("Preserve the SQL file and manifest together","Files are stored under the runtime's managed backup directory. Fresh-install catalog import is planned; the SQL payload remains usable with the matching native database client. Keep a separate copy of your recovery instructions and credentials.");
}
function restorePage(artifactId){
  const targets=state.sources.filter(s=>s.role==="target"&&s.environment==="DISPOSABLE");
  let html=header("Restore","Nothing on the target changes during preview. Review the artifact, target and checks before authorizing SQL replay.");
  if(!state.artifacts.length)return html+`<div class="panel">${empty("A recovery point comes first","Complete a backup before starting a restore. The artifact must pass its integrity check again before replay.",link("View policies","#policies"),"restore")}</div>`;
  if(!targets.length)return html+`<div class="panel">${empty("Add a disposable restore target","This first release restores only to an empty, separate database labeled DISPOSABLE. It never intentionally replaces an existing database.",button("Add connection","source-new","",true),"restore")}</div>`;
  const chosen=state.artifacts.find(a=>a.id===artifactId)||state.artifacts[0];
  if(preview&&preview.artifact_id!==chosen.id)preview=null;
  html+=`<div class="form-layout"><form id="restore-preview-form" class="stack">`+
    formSection("01","Artifact",select("Recovery point","artifact_id",state.artifacts.map(a=>[a.id,`${a.source_name} · ${formatDate(a.snapshot)}`]),chosen.id)+`<div class="actions">${chip("Local copy finalized","ok")}${chip("Integrity recorded","ok")}${chip(chosen.restore_test?"Inventory checked before":"Never restore-tested")}</div><p class="sub">Snapshot time is a conservative export-start lower bound. Integrity is rechecked during preflight.</p>`)+
    formSection("02","What to restore",`<div class="option selected"><span><strong>Everything in the SQL artifact</strong><small>Selected-object restore is planned. Owners, grants and external prerequisites follow the export limitations recorded in the manifest.</small></span></div><p class="sub">${chosen.tables.length} table names recorded. Data and behavior need separate verification.</p>`)+
    formSection("03","Restore target",select("Disposable target","target_id",targets.map(s=>[s.id,`${s.name} · ${engines[s.engine]} · ${s.database}`]),preview?.target_id||targets[0].id)+notice("Stop on conflict","The target must be empty and have no concurrent writers. The engine and major version must match. Target identity and emptiness are checked again immediately before replay.")+`<p class="error-text form-error" role="alert"></p><button type="submit" class="button">Run preflight checks</button>`)+
    formSection("04","Before you continue",notice("SQL can execute code","Restored functions and triggers can have effects outside the database. Use only trusted artifacts in an isolated, disposable environment. A failed MySQL restore may leave partial changes.","warning"))+`</form><aside class="panel summary"><h2>Ready to restore?</h2>`+
    (preview?`${chip("Preflight passed","ok")}<ul class="checklist">${preview.checks.map(c=>`<li><span class="checkmark">✓</span>${esc(c)}</li>`).join("")}</ul><p class="sub">Authorization expires at ${formatDate(preview.expires)}. The target is checked again at execution.</p><form id="restore-confirm-form" class="stack">${field(`Type target name: ${preview.target}`,"target_name","","text","required autocomplete=off")}<label class="option"><input type="checkbox" name="acknowledge_code" required><span>I trust this SQL and confirm the target is disposable, isolated and idle.</span></label><p class="error-text form-error" role="alert"></p><button class="button primary" type="submit">Authorize restore</button></form>`:`${chip("Preflight required","warn")}<p>Choose an artifact and a disposable target, then run the checks.</p>`)+`<p class="sub">After replay, SimaX compares table names and records the result. Row contents and application behavior are not automatically verified.</p></aside></div>`;
  return html;
}
function audit(){
  const items=state.audit.filter(a=>`${a.actor} ${a.action} ${a.scope} ${a.result}`.toLowerCase().includes(filters.auditSearch.toLowerCase()));
  return header("Audit log","Who changed protection, started a backup or authorized a restore, and what happened. Entries exclude credentials and database rows.",'<a class="button" href="/api/audit/export">Export log ↓</a>')+`<div class="filters">${field("Search activity","auditSearch",filters.auditSearch,"search",'data-filter="auditSearch" placeholder="Action, scope or result"')}<span class="count">${items.length} entries</span></div>`+(items.length?table(["Time","Who","Action","Scope","Result"],items.map(a=>row([formatDate(a.time),esc(a.actor),esc(a.action),`<span class="mono">${esc(a.scope)}</span>`,esc(a.result)]))):`<div class="panel">${empty("No matching activity","Connection changes, policy revisions and execution events are recorded here.","","audit")}</div>`)+`<p class="footer-note">This local preview has one operator identity. Audit entries are retained indefinitely and are not tamper-evident. Shared sign-in, roles and configurable retention are planned.</p>`;
}
function settings(tab="general"){
  let html=header("Settings","Workspace preferences, runtime capabilities and recovery boundaries.")+`<div class="tabs">${[["general","General"],["capabilities","Capabilities"],["keys","Encryption keys"],["roles","Alerts and roles"]].map(([id,label])=>`<a class="${tab===id?"active":""}" href="#settings/${id}">${label}</a>`).join("")}</div>`;
  if(tab==="general")return html+`<form id="settings-form" class="panel form-section settings-width"><h2>Time and freshness</h2><div class="fields">${field("Display time zone","timezone",state.settings.timezone,"text","required")}${field("Recovery point limit (hours)","recovery_limit_hours",state.settings.recovery_limit_hours,"number",'required min="1" max="8760"')}${field("Restore evidence limit (days)","restore_test_limit_days",state.settings.restore_test_limit_days,"number",'required min="1" max="3650"')}</div><p class="sub">Limits produce attention notices in the overview. Email and outgoing webhook delivery are not yet available.</p><p class="error-text form-error" role="alert"></p><div class="actions"><button type="submit" class="button primary">Save preferences</button>${button("Toggle light / dark","theme")}</div></form><section class="panel padded settings-width stack"><h2>Local runtime</h2><dl class="detail-list"><dt>Version</dt><dd>${esc(state.version)} · Development preview</dd><dt>Catalog</dt><dd>SQLite · schema version 2</dd><dt>Data directory</dt><dd class="mono">${esc(state.data_directory)}</dd><dt>Access</dt><dd>Loopback only · single local operator</dd></dl></section>`;
  if(tab==="capabilities")return html+section("Native tools",table(["Engine","Client","Exporter","Execution"],Object.entries(state.tools).map(([engine,tools])=>row([engines[engine],...Object.entries(tools).map(([name,found])=>`${chip(found?"Found":"Not installed",found?"ok":"warn")}<small class="mono">${esc(name)}</small>`),"Development adapter"])) ))+section("Delivery status",table(["Capability","This release"],[row(["Application storage","SQLite catalog; native databases remain the backup sources"]),row(["PostgreSQL / MySQL","Whole-database SQL export and guarded replay; PostgreSQL 17.11 / MySQL 8.4.11 verified on Windows"]),row(["Oracle / SQL Server","Connection records only; execution planned"]),row(["Triggers","Manual, daily, weekly, cron, table/database polling, signed webhook and MQTT; Redis planned"]),row(["Destinations","One required local copy; FTP/SFTP/S3/GCS planned"]),row(["Formats","Single SQL plus manifest; split SQL and encryption planned"]),row(["Restore","Empty disposable target; table inventory check; data/behavior checks remain manual"]),row(["Lifecycle","No automated retention, catalog import or active-run cancellation yet"])]));
  if(tab==="keys")return html+notice("Encrypted backup format is planned","This release writes plain SQL files. Store them on a protected volume with appropriate filesystem permissions. There are no encryption keys managed by this application yet.","warning")+`<section class="panel padded stack settings-width"><h2>Recovery requirements</h2><p>The future SimaX binary format will be authenticated and versioned. Key recovery, rotation and compatibility must be validated before encrypted output is enabled.</p><p class="sub">If the only valid key is lost, encrypted backups may be unrecoverable. A copy held only inside the application is not a recovery plan.</p></section>`;
  return html+notice("Single local operator","This release has no shared sign-in or role-based access. Keep the service on 127.0.0.1; do not publish it through a proxy or tunnel.","warning")+`<div class="two-columns"><section class="panel padded stack"><h2>Alerts</h2><p>Connection failures, missing backups and stale recovery evidence appear in the overview. Outgoing email and webhook notifications are planned.</p><a href="#settings/general">Configure freshness limits →</a></section><section class="panel padded stack"><h2>Roles</h2><p>Administrator, operator and read-only access are defined in the PRD. Authentication and server-enforced role permissions will be implemented before shared operation is supported.</p><p class="sub">This preview blocks restores to production and requires an empty disposable target.</p></section></div>`;
}
document.addEventListener("click",async event=>{
  if(event.target.closest(".skip")){event.preventDefault();$("#main").focus();return;}
  const b=event.target.closest("[data-action]");if(!b)return;
  const {action,id}=b.dataset;
  if(action==="close"){ $("#dialog").close();return; }
  if(action==="schedule-preview"){await previewSchedule(b);return;}
  if(action==="source-new"||action==="source-edit"){sourceDialog(id);return;}
  if(action==="theme"){document.documentElement.classList.toggle("dark");localStorage.setItem("simax-theme",document.documentElement.classList.contains("dark")?"dark":"light");return;}
  b.disabled=true;
  try{
    if(action==="source-check"){toast("Checking connection and native tools…");const result=await api(`/sources/${id}/preflight`,"POST");toast(result.ok?"Connection check complete.":result.message);}
    if(action==="policy-run"){const run=await api(`/policies/${id}/run`,"POST");await refresh(false);location.hash=`runs/${run.id}`;toast("Backup queued. Its progress is recorded here.");}
    if(action==="policy-toggle"){const p=policyById(id);await api(`/policies/${id}`,"PUT",{...policyPayload(p),enabled:!p.enabled});toast(p.enabled?"Policy paused.":"Policy enabled.");}
    if(action==="run-cancel"){await api(`/runs/${id}/cancel`,"POST");toast("Queued run cancelled.");}
    await refresh();
  }catch(error){toast(error.message);}finally{b.disabled=false;}
});
document.addEventListener("input",event=>{
  const form=event.target.closest("#policy-form");
  if(form&&["trigger","time","timezone","weekdays","cron","enabled"].includes(event.target.name))invalidateSchedule(form);
});
document.addEventListener("change",event=>{
  const el=event.target;
  if(el.dataset.filter){filters[el.dataset.filter]=el.value;render();}
  if(el.name==="engine"&&el.closest("#source-form"))$("#source-form [name=port]").value={postgresql:5432,mysql:3306,oracle:1521,sqlserver:1433}[el.value];
  if(el.closest("#restore-preview-form")&&["artifact_id","target_id"].includes(el.name)){
    preview=null;
    // Invalidate authorization immediately without resetting the chosen target.
    const summary=$(".summary");summary.innerHTML='<h2>Ready to restore?</h2>'+chip("Selection changed","warn")+'<p>Run preflight checks for this selection.</p>';
  }
});
document.addEventListener("submit",async event=>{
  const form=event.target;if(!form.id.endsWith("-form"))return;event.preventDefault();
  const data=Object.fromEntries(new FormData(form));
  const submitter=event.submitter;
  const errorBox=form.querySelector(".form-error");if(errorBox)errorBox.textContent="";
  for(const b of form.querySelectorAll('button[type="submit"]'))b.disabled=true;
  try{
    if(form.id==="source-form"){
      if(form.dataset.id&&data.password==="")delete data.password;
      data.port=Number(data.port);const id=form.dataset.id;
      await api(id?`/sources/${id}`:"/sources",id?"PUT":"POST",data);
      $("#dialog").close();await refresh();toast("Connection saved. Run preflight before the first backup.");
    }else if(form.id==="policy-form"){
      Object.assign(data,schedulePayload(form),eventPayload(form));for(const key of ["event_secret","mqtt_password"])if(data[key]==="")delete data[key];data.enabled=data.enabled==="true";delete data.intent;
      const id=form.dataset.id,p=await api(id?`/policies/${id}`:"/policies",id?"PUT":"POST",data);
      await refresh(false);
      if(submitter.value==="run"){
        try{const r=await api(`/policies/${p.id}/run`,"POST");await refresh(false);location.hash=`runs/${r.id}`;}
        catch(error){location.hash=`policies/${p.id}`;toast(`Policy saved, but no run was queued: ${error.message}`);return;}
      }else location.hash="policies";
      toast("Policy revision saved.");
    }else if(form.id==="settings-form"){
      data.recovery_limit_hours=Number(data.recovery_limit_hours);data.restore_test_limit_days=Number(data.restore_test_limit_days);
      await api("/settings","PUT",data);await refresh();toast("Preferences saved.");
    }else if(form.id==="restore-preview-form"){
      preview={...await api("/restore/preview","POST",data),...data};
      if(route()[1]!==data.artifact_id)location.hash=`restore/${data.artifact_id}`;else render();
    }else if(form.id==="restore-confirm-form"){
      const run=await api("/restore/confirm","POST",{token:preview.token,target_name:data.target_name,acknowledge_code:data.acknowledge_code==="on"});
      preview=null;await refresh(false);location.hash=`runs/${run.id}`;toast("Restore authorized and queued.");
    }
  }catch(error){if(errorBox)errorBox.textContent=error.message;else toast(error.message);}
  finally{for(const b of form.querySelectorAll('button[type="submit"]'))b.disabled=false;}
});
window.addEventListener("hashchange",()=>{if(state){render();$("main h1")?.focus({preventScroll:true});window.scrollTo(0,0);}});
if(localStorage.getItem("simax-theme")==="dark")document.documentElement.classList.add("dark");
refresh().catch(()=>{$("#main").innerHTML=header("Runtime unavailable","Start the SimaX server and reload this page. Your catalog remains on disk.");$("#runtime").textContent="Runtime unreachable";});
setInterval(async()=>{
  if(loading||document.hidden)return;loading=true;
  try{const [page,id]=route();const editing=$("main").contains(document.activeElement)&&document.activeElement.matches("input,select,textarea,button,a");const safe=(["overview","runs","artifacts","audit"].includes(page)||(page==="policies"&&!id))&&!$("#dialog").open&&!editing;await refresh(safe);}
  catch{$("#runtime").innerHTML='<strong><span class="dot off"></span>Runtime unreachable</strong><span class="sub">Displayed evidence may be stale. Check the server and reload.</span>';}
  finally{loading=false;}
},5000);
