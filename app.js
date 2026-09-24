
const STATUS_ORDER = ["ACTIVATE","PREPARE","WATCH","CLEAR"];
let DATA = null;

function fmtTime(value){
  if(!value) return "Awaiting first refresh";
  const d = new Date(value);
  return new Intl.DateTimeFormat(undefined,{dateStyle:"medium",timeStyle:"short"}).format(d);
}
function safe(v,fallback="—"){ return v === null || v === undefined || v === "" ? fallback : v; }
function esc(s){ return String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c])); }

async function loadData(){
  const res = await fetch(`data/weather.json?t=${Date.now()}`,{cache:"no-store"});
  DATA = await res.json();
  document.getElementById("last-updated").textContent = fmtTime(DATA.updatedAt);
  document.getElementById("seed-banner").classList.toggle("hidden",DATA.dataState !== "seed");
  buildStateFilter();
  render();
}

function buildStateFilter(){
  const sel = document.getElementById("state-filter");
  if(sel.options.length > 1) return;
  [...new Set(DATA.markets.map(m=>m.state))].sort().forEach(st=>{
    const o=document.createElement("option"); o.value=st; o.textContent=st; sel.appendChild(o);
  });
}
function setCount(status){
  document.getElementById(`count-${status.toLowerCase()}`).textContent =
    DATA.markets.filter(m=>m.status===status).length;
}
function renderChanges(){
  const panel=document.getElementById("changes-panel");
  const list=document.getElementById("changes-list");
  list.innerHTML="";
  if(!DATA.changes || DATA.changes.length===0){ panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  DATA.changes.forEach(c=>{
    const div=document.createElement("div"); div.className="change";
    const up = STATUS_ORDER.indexOf(c.to) < STATUS_ORDER.indexOf(c.from);
    div.innerHTML=`<span class="arrow">${up?"↑":"↓"}</span><strong>${esc(c.name)}, ${esc(c.state)}</strong><span>${esc(c.from)} → ${esc(c.to)}</span>`;
    list.appendChild(div);
  });
}
function card(m){
  const corridorText=(m.corridors||[]).slice(0,3).map(c=>`${c.name}${c.routes?` (${c.routes})`:""}`).join(" · ");
  const weatherLink=m.weatherUrl?`<a href="${esc(m.weatherUrl)}" target="_blank" rel="noopener">NWS</a>`:"";
  const roadLinks=(m.roadSources||[]).slice(0,2).map((u,i)=>`<a href="${esc(u)}" target="_blank" rel="noopener">DOT / 511${i?` ${i+1}`:""}</a>`).join("");
  const storeLink=(m.lesSchwabSources||[])[0]?`<a href="${esc(m.lesSchwabSources[0])}" target="_blank" rel="noopener">Stores</a>`:"";
  return `<article class="market-card ${esc(m.status)}">
    <div class="card-top"><div><h3 class="market-name">${esc(m.name)}</h3><div class="state">${esc(m.state)} · baseline ${esc(m.priority)}</div></div><span class="badge">${esc(m.status)}</span></div>
    <p class="reason">${esc(m.reason)}</p>
    <p class="forecast">${esc(safe(m.forecast,"No meaningful winter-weather signal."))}</p>
    <div class="facts">
      <div class="fact"><span>Timing</span><strong>${esc(safe(m.timing))}</strong></div>
      <div class="fact"><span>Low temp</span><strong>${m.temperatureMin==null?"—":`${Math.round(m.temperatureMin)}°F`}</strong></div>
      <div class="fact"><span>Max precip</span><strong>${m.maxPrecipProbability==null?"—":`${Math.round(m.maxPrecipProbability)}%`}</strong></div>
    </div>
    ${corridorText?`<p class="corridors"><strong>Nearby:</strong> ${esc(corridorText)}</p>`:""}
    <p class="corridors"><strong>Recommended action:</strong> ${esc(safe(m.prAction, m.status==="CLEAR"?"No action. Keep in the broad market screen.":"Verify conditions and assess local activation."))}</p>
    <div class="links">${weatherLink}${roadLinks}${storeLink}</div>
  </article>`;
}
function render(){
  STATUS_ORDER.forEach(setCount); renderChanges();
  const q=document.getElementById("search").value.trim().toLowerCase();
  const st=document.getElementById("state-filter").value;
  const sf=document.getElementById("status-filter").value;
  const filtered=DATA.markets.filter(m=>{
    const hay=[m.name,m.state,...(m.mediaMarkets||[]),...(m.corridors||[]).map(c=>`${c.name} ${c.routes}`)].join(" ").toLowerCase();
    return (!q||hay.includes(q)) && (!st||m.state===st) && (!sf||m.status===sf);
  });
  const root=document.getElementById("market-sections"); root.innerHTML="";
  STATUS_ORDER.forEach(status=>{
    const items=filtered.filter(m=>m.status===status);
    if(!items.length) return;
    const section=document.createElement("section");
    section.innerHTML=`<div class="section-heading"><div><p class="eyebrow">${status}</p><h2>${status==="CLEAR"?"Below threshold":status[0]+status.slice(1).toLowerCase()}</h2></div><span>${items.length} market${items.length===1?"":"s"}</span></div><div class="market-grid">${items.map(card).join("")}</div>`;
    root.appendChild(section);
  });
  if(!root.children.length) root.innerHTML='<div class="empty">No markets match the current filters.</div>';
}
document.getElementById("search").addEventListener("input",render);
document.getElementById("state-filter").addEventListener("change",render);
document.getElementById("status-filter").addEventListener("change",render);
document.getElementById("refresh-btn").addEventListener("click",loadData);
document.querySelectorAll(".summary-card").forEach(b=>b.addEventListener("click",()=>{
  document.getElementById("status-filter").value=b.dataset.filter; render();
  document.querySelector(".controls").scrollIntoView({behavior:"smooth"});
}));
loadData().catch(err=>{
  console.error(err); document.getElementById("last-updated").textContent="Data load failed";
});
setInterval(loadData,5*60*1000);
