/* Chokepoint 投研系统 V2 — Frontend */
(function(){
'use strict';

let dashData = null;
let priceChart = null, signalChart = null;
let currentTicker = null;

function $(sel,ctx){ return (ctx||document).querySelector(sel); }
function $$(sel,ctx){ return [...(ctx||document).querySelectorAll(sel)]; }
function fmt(n,d=2){ return n==null?'—':Number(n).toFixed(d); }
function fmtK(n){ return n==null?'—':n>=1e9?(n/1e9).toFixed(1)+'B':n>=1e6?(n/1e6).toFixed(0)+'M':n>=1e3?(n/1e3).toFixed(0)+'K':n.toFixed(0); }
function fmtM(n){ return n==null?'—':Math.abs(n)>=1e9?'$'+(n/1e9).toFixed(1)+'B':Math.abs(n)>=1e6?'$'+(n/1e6).toFixed(0)+'M':'$'+fmtK(n); }
function fmtB(n){ return n==null?'—':n>=1e9?'$'+(n/1e9).toFixed(1)+'B':n>=1e6?'$'+(n/1e6).toFixed(0)+'M':'$'+(n/1e3).toFixed(0)+'K'; }
function toast(msg,type='success'){
  const t=$('#toast'); t.textContent=msg; t.className='toast '+type;
  t.classList.remove('hidden'); setTimeout(()=>t.classList.add('hidden'),3000);
}
async function api(path,opts){ return (await fetch(path,opts)).json(); }

// ---- Tabs ----
$$('.tab').forEach(btn=>{
  btn.addEventListener('click',()=>{
    $$('.tab').forEach(b=>b.classList.remove('active'));
    $$('.tab-content').forEach(s=>s.classList.remove('active'));
    btn.classList.add('active');
    $(`#tab-${btn.dataset.tab}`).classList.add('active');
    if(btn.dataset.tab==='dashboard') loadDashboard();
    else if(btn.dataset.tab==='research'){
      if(currentTicker) openResearch(currentTicker);
      else showTickerSelector('research');
    }
    else if(btn.dataset.tab==='trading'){
      if(currentTicker) openTrading(currentTicker);
      else showTickerSelector('trading');
    }
    else if(btn.dataset.tab==='supplymap') loadSupplyMap();
    else if(btn.dataset.tab==='demand') loadDemand();
    else if(btn.dataset.tab==='watchlist') loadWatchlist();
  });
});

// ---- Dashboard ----
async function loadDashboard(){
  dashData = await api('/api/dashboard');
  renderFreshness();
  renderHealthWarnings();
  renderMacro(dashData.macro);
  renderStats(dashData.stats);
  renderCards(dashData.watchlist);
}

async function renderFreshness(){
  try{
    const f=await api('/api/freshness');
    const bar=$('#freshness-bar');
    if(!bar)return;
    const now=Date.now();
    const items=Object.entries(f).map(([k,v])=>{
      if(!v) return `<span class="fresh-item fresh-stale">${k}: 无数据</span>`;
      const d=new Date(v);
      const days=Math.floor((now-d.getTime())/(1000*60*60*24));
      const cls=days>7?'fresh-stale':days>3?'fresh-warn':'fresh-ok';
      const label=days===0?'今天':days===1?'昨天':`${days}天前`;
      return `<span class="fresh-item ${cls}">${k}: ${label}</span>`;
    });
    bar.innerHTML='<span class="fresh-label">数据新鲜度:</span>'+items.join('');
  }catch(e){}
}

async function renderHealthWarnings(){
  try{
    const warnings=await api('/api/health');
    const el=$('#health-warnings');
    if(!el)return;
    if(!warnings||!warnings.length){el.innerHTML='';el.classList.add('hidden');return;}
    const high=warnings.filter(w=>w.severity==='high');
    el.classList.remove('hidden');
    el.innerHTML=`
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <span style="font-weight:700;color:var(--red)">⚠ ${warnings.length}个预警</span>
        ${high.length?`<span style="color:var(--red);font-size:12px">(${high.length}个高危)</span>`:''}
        ${warnings.slice(0,5).map(w=>`
          <span style="font-size:12px;padding:2px 8px;border-radius:4px;background:${w.severity==='high'?'var(--red-bg)':'var(--yellow-bg)'}">
            ${w.ticker}: ${w.message}
            <span onclick="dismissWarning(${w.id})" style="cursor:pointer;margin-left:4px;color:var(--text2)">✕</span>
          </span>
        `).join('')}
      </div>`;
  }catch(e){}
}
window.dismissWarning=async function(id){
  await api('/api/health/dismiss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
  renderHealthWarnings();
};

function renderMacro(m){
  const bar=$('#macro-bar');
  if(!m){bar.innerHTML='<span class="macro-item"><span class="macro-label">宏观数据待采集</span></span>';return;}
  const items=[
    {label:'SOX',val:fmt(m.sox,0),chg:m.sox_chg},
    {label:'VXX',val:fmt(m.vxx,1),chg:m.vxx_chg},
    {label:'USD/JPY',val:fmt(m.usdjpy,1)},
    {label:'恐慌',val:m.fear_level||'—'},
    {label:'入场条件',val:`${m.conditions_met||0}/4`},
    {label:'入场',val:m.entry_ready?'✅':'❌'},
  ];
  bar.innerHTML=items.map(i=>{
    let cls=i.chg>0?'up':i.chg<0?'down':'';
    let chg=i.chg!=null?` (${i.chg>0?'+':''}${fmt(i.chg,1)}%)`:'';
    return `<span class="macro-item"><span class="macro-label">${i.label}</span><span class="macro-val ${cls}">${i.val}${chg}</span></span>`;
  }).join('');
}

function renderStats(s){
  $('#stats-row').innerHTML=[
    {num:s.total,label:'标的总数'},
    {num:s.buy_signals,label:'买入信号',cls:s.buy_signals>0?'color:var(--green)':''},
    {num:s.positions,label:'持仓'},
  ].map(c=>`<div class="stat-card"><div class="stat-num" style="${c.cls||''}">${c.num}</div><div class="stat-label">${c.label}</div></div>`).join('');
}

function renderCards(wl){
  const groups={core:[],observe:[],downgrade:[]};
  wl.forEach(w=>{
    const cat=w.category||'observe';
    (groups[cat]||groups.observe).push(w);
  });
  for(const cat of Object.keys(groups)){
    groups[cat].sort((a,b)=>(b.signal?.total_score||0)-(a.signal?.total_score||0));
  }
  $('#cards-core').innerHTML=groups.core.map(cardHtml).join('');
  $('#cards-observe').innerHTML=groups.observe.map(cardHtml).join('');
  $('#cards-downgrade').innerHTML=groups.downgrade.map(cardHtml).join('');
  $$('.ticker-card').forEach(c=>{
    c.addEventListener('click',()=> openResearch(c.dataset.ticker));
  });
}

function cardHtml(w){
  const sig=w.signal||{};
  const signal=sig.signal||'HOLD';
  const score=sig.total_score!=null?sig.total_score:'—';
  const price=sig.price!=null?fmt(sig.price,2):'—';
  const thesis=w.thesis||{};
  const val=w.valuation||{};
  const vm=w.valuation_model||{};
  const verdict=thesis.verdict||'HOLD';

  let thesisLine=thesis.thesis||'';
  if(thesisLine.length>80) thesisLine=thesisLine.substring(0,80)+'...';

  let valChips='';
  if(val.pe_ttm) valChips+=`<span class="val-chip">PE ${fmt(val.pe_ttm,1)}</span>`;
  if(val.ps_ttm) valChips+=`<span class="val-chip">PS ${fmt(val.ps_ttm,1)}</span>`;
  if(val.pct_from_high!=null){
    const cls=val.pct_from_high<-30?'cheap':val.pct_from_high>-10?'expensive':'fair';
    valChips+=`<span class="val-chip ${cls}">${fmt(val.pct_from_high,0)}%高点</span>`;
  }

  let vmLine='';
  if(vm.current_tier){
    const tierIcon={Mega:'🏛️',Large:'🔵',Mid:'🟢',Small:'🟡',Micro:'🔴'}[vm.current_tier]||'⚪';
    const curB=vm.current_mcap?fmtB(vm.current_mcap):'—';
    const baseB=vm.base_mcap?fmtB(vm.base_mcap):'—';
    const bullB=vm.bull_mcap?fmtB(vm.bull_mcap):'—';
    const baseUp=vm.base_upside!=null?`${vm.base_upside>0?'+':''}${fmt(vm.base_upside,0)}%`:'';
    let flags='';
    if(vm.has_100b_path) flags+='<span class="vm-flag vm-flag-path">$100B路径</span>';
    if(vm.micro_warning) flags+='<span class="vm-flag vm-flag-micro">微盘</span>';
    if(vm.is_sweet_spot) flags+='<span class="vm-flag vm-flag-sweet">甜区</span>';
    vmLine=`<div class="card-vm-row">${tierIcon} <span class="vm-tier">${vm.current_tier}</span> ${curB} → Base ${baseB} <span class="vm-upside">${baseUp}</span> | Bull ${bullB} ${flags}</div>`;
  }

  return `<div class="ticker-card" data-ticker="${w.ticker}">
    <div class="card-top">
      <div><span class="card-ticker">${w.ticker}</span> <span class="card-name">${w.name||''}</span></div>
      <span class="card-layer">${w.layer||''}</span>
    </div>
    <div class="card-thesis">${thesisLine}</div>
    <div class="card-val-row">${valChips}</div>
    ${vmLine}
    <div class="card-signal-row">
      <div>
        <span class="signal-badge verdict-${verdict}">${verdict}</span>
        <span class="signal-badge signal-${signal}">${signal} ${score}</span>
      </div>
      <span style="font-size:15px;font-weight:600">$${price}</span>
    </div>
  </div>`;
}

async function showTickerSelector(tab){
  if(!dashData) dashData = await api('/api/dashboard');
  const wl = (dashData.watchlist||[]).sort((a,b)=>(a.ticker||'').localeCompare(b.ticker||''));
  const options = wl.map(w=>{
    const v = (w.thesis||{}).verdict||'HOLD';
    return `<option value="${w.ticker}">${w.ticker} — ${w.name||''} [${v}]</option>`;
  }).join('');
  const isResearch = tab==='research';
  const header = $(isResearch ? '#research-header' : '#trading-header');
  header.innerHTML=`
    <h2>${isResearch?'研究详情':'交易策略'}</h2>
    <span class="meta">选择标的查看${isResearch?'深度研究':'交易信号'}</span>
    <select id="ticker-select" style="font-size:14px;padding:6px 12px;background:var(--bg3);border:1px solid var(--border);color:var(--text);border-radius:6px">
      <option value="">— 请选择标的 —</option>
      ${options}
    </select>
  `;
  if(isResearch){
    $('#thesis-panel').innerHTML='';
    $('#company-profile-panel').innerHTML='';
    $('#valuation-panel').innerHTML='';
    $('#supply-panel').innerHTML='';
    const rc=$('#rev-canvas'); if(rc)rc.getContext('2d').clearRect(0,0,rc.width,rc.height);
    const mc=$('#margin-canvas'); if(mc)mc.getContext('2d').clearRect(0,0,mc.width,mc.height);
  } else {
    $('#price-chart').innerHTML='';
    $('#signal-chart').innerHTML='';
    $('#indicators-panel').innerHTML='';
    $('#trade-advice').innerHTML='';
  }
  $('#ticker-select').addEventListener('change',e=>{
    if(e.target.value){
      if(isResearch) openResearch(e.target.value);
      else openTrading(e.target.value);
    }
  });
}

// ---- Research Detail ----
async function openResearch(ticker){
  currentTicker=ticker;
  $$('.tab').forEach(b=>b.classList.remove('active'));
  $$('.tab-content').forEach(s=>s.classList.remove('active'));
  $$('.tab').find(b=>b.dataset.tab==='research').classList.add('active');
  $('#tab-research').classList.add('active');

  const d=await api(`/api/ticker/${ticker}`);
  renderResearchHeader(d.info,d.valuation,d.thesis);
  renderThesis(d.thesis,d.supply_chain,d.bear_thesis);
  renderCompanyProfile(d.company_profile);
  renderValuationModelPanel(d.valuation_model);
  renderFundamentalsCharts(d.fundamentals);
  renderValuationPanel(d.valuation,d.fundamentals);
  renderFilings(d.filings);
  renderSupplyChainPanel(d.supply_chain);
}

function tickerSwitcher(current,handler){
  if(!dashData||!dashData.watchlist) return '';
  const opts=dashData.watchlist.slice().sort((a,b)=>(a.ticker||'').localeCompare(b.ticker||'')).map(w=>
    `<option value="${w.ticker}"${w.ticker===current?' selected':''}>${w.ticker}</option>`
  ).join('');
  return `<select onchange="${handler}(this.value)" style="font-size:13px;padding:4px 8px;background:var(--bg3);border:1px solid var(--border);color:var(--text);border-radius:4px">${opts}</select>`;
}

function renderResearchHeader(info,val,thesis){
  const v=thesis||{};
  const verdict=v.verdict||'HOLD';
  const price=val?`$${fmt(val.price)}`:'—';
  $('#research-header').innerHTML=`
    ${tickerSwitcher(info.ticker,'openResearch')}
    <h2>${info.ticker} — ${info.name||''}</h2>
    <span class="card-layer">${info.layer||''}</span>
    <span class="signal-badge verdict-${verdict}">${verdict}</span>
    <span class="meta">${price} | 入场: $${fmt(info.entry_low,0)}–$${fmt(info.entry_high,0)}</span>
    <button class="btn" onclick="openTrading('${info.ticker}')">查看交易策略 →</button>
  `;
}

function renderThesis(thesis,supply,bear){
  const p=$('#thesis-panel');
  if(!thesis){p.innerHTML='<p style="color:var(--text2)">暂无研究论点</p>';return;}
  let catalysts='';
  try{
    const cats=typeof thesis.catalysts==='string'?JSON.parse(thesis.catalysts):thesis.catalysts;
    if(cats&&cats.length) catalysts=`<ul class="catalyst-list">${cats.map(c=>`<li>${c}</li>`).join('')}</ul>`;
  }catch(e){}

  let supplyHtml='';
  if(supply&&supply.length){
    supplyHtml=`<div class="thesis-section"><div class="thesis-label">10-K供应链扫描</div><div class="thesis-text">${supply.map(s=>`${s.mention_type}: ${s.mention_count}次`).join(' | ')}</div></div>`;
  }

  let bearHtml='';
  if(bear&&bear.bear_case){
    let triggers='';
    const dt=bear.downgrade_triggers;
    if(dt&&dt.length){
      const ts=bear.trigger_status;
      let parsed=null;
      try{parsed=typeof ts==='string'?JSON.parse(ts):ts;}catch(e){}
      triggers=`<div style="margin-top:8px"><b style="font-size:12px">降级触发条件:</b><ul style="list-style:none;padding:0;margin:4px 0">${dt.map((t,i)=>{
        const fired=parsed&&parsed[i];
        const icon=fired?'🔴':'🟢';
        return `<li style="font-size:12px;padding:2px 0">${icon} ${t}</li>`;
      }).join('')}</ul></div>`;
    }
    bearHtml=`
    <div style="margin-top:16px;padding:14px;background:rgba(248,81,73,0.06);border:1px solid rgba(248,81,73,0.25);border-radius:8px">
      <div style="font-size:13px;font-weight:700;color:var(--red);margin-bottom:8px">魔鬼代言人 — Bear Case</div>
      <div class="thesis-text" style="color:var(--text)">${bear.bear_case}</div>
      ${bear.competitive_threats?`<div style="margin-top:8px"><b style="font-size:12px;color:var(--orange)">竞争威胁:</b><div class="thesis-text" style="font-size:12px">${bear.competitive_threats}</div></div>`:''}
      ${bear.valuation_risk?`<div style="margin-top:8px"><b style="font-size:12px;color:var(--yellow)">估值风险:</b><div class="thesis-text" style="font-size:12px">${bear.valuation_risk}</div></div>`:''}
      ${triggers}
      <div style="font-size:10px;color:var(--text2);margin-top:6px">更新: ${bear.updated_at||'—'}</div>
    </div>`;
  } else {
    bearHtml=`<div style="margin-top:12px;padding:8px 12px;background:var(--bg3);border-radius:6px;font-size:12px;color:var(--text2)">⚠ 无看空分析 — 运行"采集:公司研究"生成 Bear Case</div>`;
  }

  p.innerHTML=`
    <div class="thesis-section"><div class="thesis-label">投资逻辑</div><div class="thesis-text">${thesis.thesis||'—'}</div></div>
    <div class="thesis-section"><div class="thesis-label">护城河</div><div class="thesis-text">${thesis.moat||'—'}</div></div>
    <div class="thesis-section"><div class="thesis-label">催化剂</div>${catalysts||'<div class="thesis-text">—</div>'}</div>
    <div class="thesis-section"><div class="thesis-label">风险</div><div class="thesis-text risk-text">${thesis.risks||'—'}</div></div>
    ${supplyHtml}
    ${bearHtml}
  `;
}

function renderFundamentalsCharts(funds){
  const qFunds = (funds||[]).filter(f=>f.period && f.period.includes('Q'));
  renderBarChart($('#rev-chart'),qFunds,'revenue','季度Revenue','blue');
  renderBarChart($('#margin-chart'),qFunds,'gross_margin','毛利率%','green',true);
}

function renderBarChart(container,funds,field,title,color,isPct=false){
  let canvas=container.querySelector('canvas');
  if(!canvas){canvas=document.createElement('canvas');container.appendChild(canvas);}
  const h4=container.querySelector('h4');
  if(h4)h4.textContent=title;

  if(!funds||!funds.length){container.innerHTML=`<h4>${title}</h4><p style="padding:20px;color:var(--text2)">无数据</p>`;return;}

  const data=funds.filter(f=>f[field]!=null);
  if(!data.length){container.innerHTML=`<h4>${title}</h4><p style="padding:20px;color:var(--text2)">无数据</p>`;return;}

  const vals=data.map(d=>d[field]);
  const maxVal=Math.max(...vals.map(Math.abs));
  const barHtml=data.map(d=>{
    const v=d[field];
    const h=maxVal>0?Math.abs(v)/maxVal*180:0;
    const label=d.period.replace('CY','').replace('20','');
    const display=isPct?fmt(v,1)+'%':fmtM(v);
    const barColor=v<0?'red':color;
    return `<div class="bar-group"><div class="bar-val">${display}</div><div class="bar ${barColor}" style="height:${h}px"></div><div class="bar-label">${label}</div></div>`;
  }).join('');

  container.innerHTML=`<h4>${title}</h4><div class="bar-chart">${barHtml}</div>`;
}

function renderValuationPanel(val,funds){
  const p=$('#valuation-panel');
  if(!val){p.innerHTML='';return;}

  const qFunds = (funds||[]).filter(f=>f.period && f.period.includes('Q'));
  const latestFund=qFunds.length?qFunds[qFunds.length-1]:{};
  const items=[
    {label:'价格',val:'$'+fmt(val.price)},
    {label:'市值',val:fmtM(val.market_cap)},
    {label:'P/E(TTM)',val:val.pe_ttm?fmt(val.pe_ttm,1):'—',cls:val.pe_ttm>50?'color:var(--red)':val.pe_ttm<15?'color:var(--green)':''},
    {label:'P/S(TTM)',val:val.ps_ttm?fmt(val.ps_ttm,1)+'x':'—',cls:val.ps_ttm>30?'color:var(--red)':val.ps_ttm<5?'color:var(--green)':''},
    {label:'距52周高点',val:fmt(val.pct_from_high,0)+'%',cls:val.pct_from_high<-30?'color:var(--green)':val.pct_from_high>-10?'color:var(--red)':''},
    {label:'距52周低点',val:'+'+fmt(val.pct_from_low,0)+'%'},
    {label:'毛利率',val:latestFund.gross_margin?fmt(latestFund.gross_margin,1)+'%':'—'},
    {label:'Revenue YoY',val:latestFund.revenue_yoy?fmt(latestFund.revenue_yoy,0)+'%':'—',cls:latestFund.revenue_yoy>20?'color:var(--green)':latestFund.revenue_yoy<0?'color:var(--red)':''},
  ];
  p.innerHTML=items.map(i=>`<div class="val-item"><div class="val-label">${i.label}</div><div class="val-value" style="${i.cls||''}">${i.val}</div></div>`).join('');
}

function renderCompanyProfile(profile){
  const p=$('#company-profile-panel');
  if(!profile){p.innerHTML='<p style="color:var(--text2);padding:12px">暂无公司研究档案 — 请在管理Tab点击"采集:公司研究"</p>';return;}

  function jsonList(val){
    if(!val) return [];
    try{ const parsed=typeof val==='string'?JSON.parse(val):val; return Array.isArray(parsed)?parsed:[parsed]; }catch(e){ return val?[val]:[]; }
  }

  const products=jsonList(profile.products_services);
  const customers=jsonList(profile.customers);
  const suppliers=jsonList(profile.suppliers);

  function listHtml(arr,empty){
    if(!arr.length) return `<span class="cp-text">${empty||'—'}</span>`;
    return `<ul class="cp-list">${arr.map(i=>`<li>${i}</li>`).join('')}</ul>`;
  }

  const srcLabel = profile.analysis_source==='llm'?'LLM深度分析':'10-K关键词提取';

  p.innerHTML=`<h3 style="font-size:15px;margin-bottom:10px">公司深度研究
    <span class="cp-source">数据来源: ${srcLabel} | 最近Filing: ${profile.last_filing||'—'}</span></h3>

    <div class="cp-section">
      <div class="cp-label">一、公司做什么</div>
      <div class="cp-text">${profile.business_overview||'—'}</div>
    </div>

    <div class="cp-grid">
      <div class="cp-section">
        <div class="cp-label">二、产品/服务线</div>
        ${listHtml(products,'待分析')}
      </div>
      <div class="cp-section">
        <div class="cp-label">三、主要客户</div>
        ${listHtml(customers,'待分析')}
      </div>
    </div>

    <div class="cp-grid">
      <div class="cp-section">
        <div class="cp-label">四、供应商/上游依赖</div>
        ${listHtml(suppliers,'待分析')}
      </div>
      <div class="cp-section">
        <div class="cp-label">五、市场空间</div>
        <div class="cp-text">${profile.market_size||'—'}</div>
      </div>
    </div>

    ${profile.competitive_position?`<div class="cp-section"><div class="cp-label">六、竞争格局</div><div class="cp-text">${profile.competitive_position}</div></div>`:''}
    ${profile.technology_moat?`<div class="cp-section"><div class="cp-label">七、技术壁垒/护城河</div><div class="cp-text">${profile.technology_moat}</div></div>`:''}
    ${profile.risk_factors?`<div class="cp-section"><div class="cp-label">八、核心风险</div><div class="cp-text risk-text" style="font-size:12px">${profile.risk_factors}</div></div>`:''}

    ${profile.analysis_source!=='llm'?'<div class="cp-source" style="margin-top:12px;padding:8px;background:var(--bg3);border-radius:4px">提示：当前为关键词提取模式，内容为英文原文摘取。配置LLM API后可获得中文结构化深度分析。</div>':''}
  `;
}

function renderValuationModelPanel(vm){
  const container=$('#vm-panel');
  if(!container) return;
  if(!vm||!vm.current_tier){
    container.innerHTML='<p style="color:var(--text2);padding:12px">暂无估值模型数据 — 请在管理Tab点击"估值模型"</p>';
    return;
  }
  const tierIcon={Mega:'🏛️',Large:'🔵',Mid:'🟢',Small:'🟡',Micro:'🔴'}[vm.current_tier]||'⚪';
  const cd=vm.calc_details||{};
  const cagrPct=vm.revenue_cagr!=null?(vm.revenue_cagr*100).toFixed(1):'—';
  const gmPct=vm.gross_margin!=null?(vm.gross_margin*100).toFixed(1):'—';
  const gmSource=cd.margin_source==='override'?' (非GAAP override)':cd.margin_source==='default'?' (默认)':'';
  const updatedAt=vm.updated_at?`<span class="vm-updated">更新: ${vm.updated_at.substring(0,10)}</span>`:'';

  let flags='';
  if(vm.is_sweet_spot) flags+='<span class="vm-flag vm-flag-sweet">甜区$5-50B</span>';
  if(vm.has_100b_path) flags+='<span class="vm-flag vm-flag-path">$100B路径</span>';
  if(vm.micro_warning) flags+='<span class="vm-flag vm-flag-micro">微盘风险</span>';

  const scenarios=[
    {name:'Bear',rev:vm.bear_rev_y3,ps:vm.bear_ps,mcap:vm.bear_mcap,upside:vm.bear_upside,cls:'vm-bear'},
    {name:'Base',rev:vm.base_rev_y3,ps:vm.base_ps,mcap:vm.base_mcap,upside:vm.base_upside,cls:'vm-base'},
    {name:'Bull',rev:vm.bull_rev_y3,ps:vm.bull_ps,mcap:vm.bull_mcap,upside:vm.bull_upside,cls:'vm-bull'},
  ];

  const proj=cd.base_projection||{};
  const decayPct=proj.decay!=null?(proj.decay*100).toFixed(0):'—';

  container.innerHTML=`
    <h3>估值模型 — 3年Revenue Forward ${updatedAt}</h3>
    <div class="vm-inputs">
      <div class="vm-input-item"><span class="vm-input-label">当前市值</span><span class="vm-input-val">${tierIcon} ${vm.current_tier} ${fmtB(vm.current_mcap)}</span></div>
      <div class="vm-input-item"><span class="vm-input-label">TTM Revenue</span><span class="vm-input-val">${fmtB(vm.ttm_revenue)}</span></div>
      <div class="vm-input-item"><span class="vm-input-label">Revenue CAGR</span><span class="vm-input-val" style="color:${vm.revenue_cagr>0?'var(--green)':'var(--red)'}">${cagrPct}%</span></div>
      <div class="vm-input-item"><span class="vm-input-label">毛利率${gmSource}</span><span class="vm-input-val">${gmPct}%</span></div>
      <div class="vm-input-item"><span class="vm-input-label">增长衰减</span><span class="vm-input-val">${decayPct}%/年</span></div>
    </div>
    ${flags?`<div style="margin:8px 0">${flags}</div>`:''}
    <div class="vm-scenarios">
      ${scenarios.map(s=>`<div class="vm-scenario ${s.cls}">
        <div class="vm-scenario-name">${s.name}</div>
        <div class="vm-scenario-mcap">${fmtB(s.mcap)}</div>
        <div class="vm-scenario-upside" style="color:${s.upside>0?'var(--green)':'var(--red)'}">${s.upside!=null?(s.upside>0?'+':'')+fmt(s.upside,0)+'%':'—'}</div>
        <div class="vm-scenario-detail">Y3 Rev ${fmtB(s.rev)} × ${fmt(s.ps,1)}x PS</div>
      </div>`).join('')}
    </div>
    <details style="margin-top:8px">
      <summary style="font-size:11px;color:var(--text2);cursor:pointer">计算过程</summary>
      <pre style="font-size:11px;color:var(--text2);margin-top:4px;white-space:pre-wrap;max-height:200px;overflow:auto">${JSON.stringify(cd,null,2)}</pre>
    </details>
  `;
}

// ---- Trading ----
window.openTrading=async function(ticker){
  currentTicker=ticker;
  $$('.tab').forEach(b=>b.classList.remove('active'));
  $$('.tab-content').forEach(s=>s.classList.remove('active'));
  $$('.tab').find(b=>b.dataset.tab==='trading').classList.add('active');
  $('#tab-trading').classList.add('active');

  const d=await api(`/api/ticker/${ticker}`);
  renderTradingHeader(d.info,d.signals[0],d.valuation);
  requestAnimationFrame(()=>{
    renderPriceChart(d.bars);
    renderSignalChart(d.signals);
    renderIndicators(d.bars);
    renderTradeAdvice(d.info,d.signals[0],d.valuation,d.bars);
  });
};

function renderTradingHeader(info,sig,val){
  const s=sig||{};
  const price=val?`$${fmt(val.price)}`:'—';
  $('#trading-header').innerHTML=`
    ${tickerSwitcher(info.ticker,'openTrading')}
    <h2>${info.ticker} — ${info.name||''}</h2>
    <span class="signal-badge signal-${s.signal||'HOLD'}">${s.signal||'—'} ${s.total_score!=null?s.total_score:'—'}</span>
    <span class="meta">${price} | 入场: $${fmt(info.entry_low,0)}–$${fmt(info.entry_high,0)} | 止损: ${((info.stop_loss||0)*100).toFixed(0)}%</span>
    <button class="btn" onclick="openResearch('${info.ticker}')">← 研究详情</button>
  `;
}

function renderPriceChart(bars){
  const container=$('#price-chart');
  container.innerHTML='';
  if(!bars||!bars.length){container.innerHTML='<p style="padding:40px;color:var(--text2)">无K线数据</p>';return;}
  if(priceChart)priceChart.remove();
  priceChart=LightweightCharts.createChart(container,{
    autoSize:true,
    layout:{background:{color:'#161b22'},textColor:'#8b949e'},
    grid:{vertLines:{color:'#21262d'},horzLines:{color:'#21262d'}},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
    timeScale:{borderColor:'#30363d'},rightPriceScale:{borderColor:'#30363d'},
  });
  const cs=priceChart.addCandlestickSeries({
    upColor:'#3fb950',downColor:'#f85149',borderUpColor:'#3fb950',borderDownColor:'#f85149',
    wickUpColor:'#3fb950',wickDownColor:'#f85149',
  });
  cs.setData(bars.map(b=>({time:b.date,open:b.open,high:b.high,low:b.low,close:b.close})));
  const vs=priceChart.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'vol'});
  priceChart.priceScale('vol').applyOptions({scaleMargins:{top:0.8,bottom:0}});
  vs.setData(bars.map(b=>({time:b.date,value:b.volume,color:b.close>=b.open?'rgba(63,185,80,0.3)':'rgba(248,81,73,0.3)'})));
  if(bars.length>=20){const s=priceChart.addLineSeries({color:'#58a6ff',lineWidth:1,title:'SMA20'});s.setData(calcSMA(bars,20));}
  if(bars.length>=50){const s=priceChart.addLineSeries({color:'#d29922',lineWidth:1,title:'SMA50'});s.setData(calcSMA(bars,50));}
  priceChart.timeScale().fitContent();
}

function calcSMA(bars,p){
  const r=[];
  for(let i=p-1;i<bars.length;i++){let s=0;for(let j=i-p+1;j<=i;j++)s+=bars[j].close;r.push({time:bars[i].date,value:s/p});}
  return r;
}

function renderSignalChart(signals){
  const container=$('#signal-chart');
  container.innerHTML='';
  if(!signals||!signals.length){container.innerHTML='<p style="padding:40px;color:var(--text2)">无信号数据</p>';return;}
  if(signalChart)signalChart.remove();
  signalChart=LightweightCharts.createChart(container,{
    autoSize:true,
    layout:{background:{color:'#161b22'},textColor:'#8b949e'},
    grid:{vertLines:{color:'#21262d'},horzLines:{color:'#21262d'}},
    timeScale:{borderColor:'#30363d'},rightPriceScale:{borderColor:'#30363d'},
  });
  const sorted=[...signals].sort((a,b)=>a.date.localeCompare(b.date));
  const ls=signalChart.addLineSeries({color:'#58a6ff',lineWidth:2,title:'Score'});
  ls.setData(sorted.map(s=>({time:s.date,value:s.total_score||0})));
  const b75=signalChart.addLineSeries({color:'rgba(63,185,80,0.4)',lineWidth:1,lineStyle:2});
  b75.setData(sorted.map(s=>({time:s.date,value:75})));
  const s25=signalChart.addLineSeries({color:'rgba(248,81,73,0.4)',lineWidth:1,lineStyle:2});
  s25.setData(sorted.map(s=>({time:s.date,value:25})));
  signalChart.timeScale().fitContent();
}

function renderIndicators(bars){
  const panel=$('#indicators-panel');
  if(!bars||bars.length<5){panel.innerHTML='';return;}
  const closes=bars.map(b=>b.close);
  const latest=closes[closes.length-1];
  const sma20=closes.length>=20?avg(closes.slice(-20)):null;
  const sma50=closes.length>=50?avg(closes.slice(-50)):null;
  const sma200=closes.length>=200?avg(closes.slice(-200)):null;
  const rsi=calcRSI(closes,14);
  const vols=bars.map(b=>b.volume);
  const avgVol=avg(vols.slice(-20));
  const volRatio=avgVol>0?vols[vols.length-1]/avgVol:null;
  const macd=calcMACD(closes);
  const boll=calcBollinger(closes,20);
  const items=[
    {label:'价格',val:'$'+fmt(latest)},
    {label:'SMA20',val:sma20?'$'+fmt(sma20):'—',cls:latest>sma20?'color:var(--green)':'color:var(--red)'},
    {label:'SMA50',val:sma50?'$'+fmt(sma50):'—',cls:latest>(sma50||0)?'color:var(--green)':'color:var(--red)'},
    {label:'SMA200',val:sma200?'$'+fmt(sma200):'—',cls:sma200?latest>sma200?'color:var(--green)':'color:var(--red)':''},
    {label:'RSI(14)',val:rsi!=null?fmt(rsi,0):'—',cls:rsi>70?'color:var(--red)':rsi<30?'color:var(--green)':''},
    {label:'MACD',val:macd?fmt(macd.histogram,2):'—',cls:macd?macd.histogram>0?'color:var(--green)':'color:var(--red)':''},
    {label:'布林带',val:boll?'$'+fmt(boll.lower,0)+' - $'+fmt(boll.upper,0):'—'},
    {label:'量比',val:volRatio?fmt(volRatio,1)+'x':'—',cls:volRatio>2?'color:var(--yellow)':''},
    {label:'成交量',val:fmtK(vols[vols.length-1])},
  ];
  panel.innerHTML=items.map(i=>`<div class="ind-item"><div class="ind-label">${i.label}</div><div class="ind-val" style="${i.cls||''}">${i.val}</div></div>`).join('');
}
function avg(a){return a.reduce((s,v)=>s+v,0)/a.length;}
function calcRSI(c,p){if(c.length<p+1)return null;let g=0,l=0;for(let i=c.length-p;i<c.length;i++){const d=c[i]-c[i-1];if(d>0)g+=d;else l-=d;}if(l===0)return 100;return 100-100/(1+g/p/(l/p));}
function calcEMA(data,period){if(data.length<period)return null;const k=2/(period+1);let ema=avg(data.slice(0,period));for(let i=period;i<data.length;i++)ema=data[i]*k+ema*(1-k);return ema;}
function calcMACD(closes){if(closes.length<26)return null;const ema12=calcEMA(closes,12),ema26=calcEMA(closes,26);if(ema12==null||ema26==null)return null;const macdLine=ema12-ema26;const macdArr=[];let e12=avg(closes.slice(0,12)),e26=avg(closes.slice(0,26));const k12=2/13,k26=2/27;for(let i=0;i<closes.length;i++){if(i>=12)e12=closes[i]*k12+e12*(1-k12);if(i>=26){e26=closes[i]*k26+e26*(1-k26);macdArr.push(e12-e26);}}if(macdArr.length<9)return{macd:macdLine,signal:macdLine,histogram:0};let sig=avg(macdArr.slice(0,9));const ks=2/10;for(let i=9;i<macdArr.length;i++)sig=macdArr[i]*ks+sig*(1-ks);return{macd:macdArr[macdArr.length-1],signal:sig,histogram:macdArr[macdArr.length-1]-sig};}
function calcBollinger(closes,p){if(closes.length<p)return null;const slice=closes.slice(-p);const m=avg(slice);const variance=slice.reduce((s,v)=>s+(v-m)*(v-m),0)/p;const sd=Math.sqrt(variance);return{middle:m,upper:m+2*sd,lower:m-2*sd};}

function renderFilings(filings){
  const p=$('#filings-panel');
  if(!p)return;
  if(!filings||!filings.length){p.innerHTML='';return;}
  const rows=filings.map(f=>`<tr>
    <td>${f.filing_date||f.date||'—'}</td>
    <td>${f.form_type||f.type||'—'}</td>
    <td>${f.description||f.title||'—'}</td>
    <td>${f.score!=null?f.score:'—'}</td>
  </tr>`).join('');
  p.innerHTML=`<h3 style="font-size:15px;margin-bottom:8px">SEC Filing事件</h3>
    <table class="data-table full-width"><thead><tr><th>日期</th><th>类型</th><th>描述</th><th>影响分</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function renderSupplyChainPanel(supply){
  const p=$('#supply-panel');
  if(!p)return;
  if(!supply||!supply.length){p.innerHTML='';return;}
  const rows=supply.map(s=>`<tr>
    <td>${s.mention_type||s.keyword||'—'}</td>
    <td>${s.mention_count||s.count||'—'}</td>
    <td style="font-size:12px">${s.context||s.snippet||'—'}</td>
  </tr>`).join('');
  p.innerHTML=`<h3 style="font-size:15px;margin-bottom:8px">10-K供应链扫描</h3>
    <table class="data-table full-width"><thead><tr><th>关键词</th><th>次数</th><th>上下文</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function renderTradeAdvice(info,sig,val,bars){
  const panel=$('#trade-advice');
  const s=sig||{};
  const price=val?val.price:(bars&&bars.length?bars[bars.length-1].close:null);
  const inZone=price&&info.entry_low&&info.entry_high&&price>=info.entry_low&&price<=info.entry_high;
  const belowZone=price&&info.entry_low&&price<info.entry_low;
  const aboveZone=price&&info.entry_high&&price>info.entry_high;

  let advice='';
  if(s.signal==='STRONG_BUY'||s.signal==='BUY'){
    if(belowZone) advice=`<span style="color:var(--green)">价格$${fmt(price)} < 入场区间$${fmt(info.entry_low,0)}，低于预期，技术面看多 → 考虑建仓</span>`;
    else if(inZone) advice=`<span style="color:var(--green)">价格在入场区间内，技术面看多 → 建议分批建仓(30%/35%/35%)</span>`;
    else advice=`<span style="color:var(--yellow)">技术面看多但价格高于入场区间 → 等回调到$${fmt(info.entry_high,0)}以下</span>`;
  } else if(s.signal==='SELL'){
    advice=`<span style="color:var(--red)">技术面看空(score=${s.total_score}) → 回避，不建议入场</span>`;
  } else {
    advice=`<span style="color:var(--text2)">技术面中性(score=${s.total_score||'—'}) → 持有观望，等待更好入场点</span>`;
  }

  const stopPrice=price&&info.stop_loss?price*(1+info.stop_loss):null;

  panel.innerHTML=`<h3>交易建议</h3>
    <p>${advice}</p>
    <p style="margin-top:8px;font-size:12px;color:var(--text2)">入场区间: $${fmt(info.entry_low,0)} – $${fmt(info.entry_high,0)} | 目标金额: $${fmtK(info.target_usd)} | 止损: ${((info.stop_loss||0)*100).toFixed(0)}% ${stopPrice?'($'+fmt(stopPrice,0)+')':''}</p>
  `;
}

// ---- Supply Chain Visual Map ----
const SM_NODES = [
  { id:'dc', x:50, y:50, icon:'🏗️', label:'AI数据中心', desc:'GPU + 光互联 + 电力 + 冷却', type:'center' },
  // GPU cluster — top area, aligned to grid rows
  { id:'gpu', x:50, y:18, icon:'🔲', label:'GPU计算集群', desc:'AI训练/推理', type:'group', parent:'dc', color:'#58a6ff' },
  { id:'hbm',    x:20, y:6,  icon:'🧊', label:'HBM内存', tickers:['MU','HYNIX'], parent:'gpu' },
  { id:'cowos',  x:38, y:6,  icon:'🔬', label:'先进封装', desc:'CoWoS', parent:'gpu' },
  { id:'serdes', x:62, y:6,  icon:'⚡', label:'SerDes', tickers:['CRDO'], parent:'gpu' },
  { id:'power',  x:80, y:6,  icon:'🔌', label:'功率模块', tickers:['VICR'], parent:'gpu' },
  { id:'inspect',x:28, y:32, icon:'🔍', label:'封装检测', tickers:['CAMT'], parent:'cowos' },
  { id:'mask',   x:46, y:32, icon:'🎭', label:'光掩模', tickers:['PLAB'], parent:'cowos' },
  { id:'pkgip',  x:64, y:32, icon:'📐', label:'封装IP', tickers:['ADEA'], parent:'gpu' },
  // Optical — left column
  { id:'optical', x:16, y:50, icon:'💡', label:'光互联网络', desc:'机架/集群互联', type:'group', parent:'dc', color:'#3fb950' },
  { id:'xcvr',    x:10, y:36, icon:'📡', label:'光模块800G', tickers:['COHR'], parent:'optical' },
  { id:'laser',   x:10, y:62, icon:'🔴', label:'EML激光器', tickers:['LITE'], parent:'optical' },
  { id:'inp',     x:10, y:76, icon:'💎', label:'InP衬底', tickers:['AXTI'], parent:'optical' },
  // Nuclear — right column
  { id:'nuclear', x:84, y:50, icon:'☢️', label:'电力(核能)', desc:'24/7供电', type:'group', parent:'dc', color:'#d29922' },
  { id:'smr',     x:90, y:36, icon:'⚛️', label:'SMR', tickers:['SMR'], parent:'nuclear' },
  { id:'fuel',    x:90, y:62, icon:'🟡', label:'核燃料', tickers:['LEU'], parent:'nuclear' },
  { id:'nksvc',   x:84, y:76, icon:'🚛', label:'核服务', tickers:['NNE'], parent:'nuclear' },
  { id:'grid',    x:90, y:82, icon:'🔧', label:'电网接入', tickers:['WLDN'], parent:'nuclear' },
  // Materials — bottom area
  { id:'materials', x:50, y:80, icon:'🧪', label:'基础材料', desc:'半导体上游', type:'group', parent:'dc', color:'#f85149' },
  { id:'silicon', x:38, y:90, icon:'🪨', label:'硅金属', tickers:['GSM'], parent:'materials' },
  { id:'mosfet',  x:62, y:90, icon:'🔋', label:'MOSFET', tickers:['MX'], parent:'materials' },
];

let supplyMapData = null;

async function loadSupplyMap(){
  if(!dashData) dashData = await api('/api/dashboard');
  supplyMapData = {};
  (dashData.watchlist||[]).forEach(w=>{
    supplyMapData[w.ticker] = {
      price: w.valuation?.price,
      verdict: w.thesis?.verdict || 'HOLD',
      name: w.name,
    };
  });
  renderSupplyMapVisual();
}

function renderSupplyMapVisual(){
  const container = $('#supplymap-root');
  const W = 1000, H = 900;
  const nodeMap = {};
  SM_NODES.forEach(n=> nodeMap[n.id]=n);

  let svgLines = '';
  SM_NODES.forEach(n=>{
    if(!n.parent) return;
    const p = nodeMap[n.parent];
    if(!p) return;
    const x1=p.x*W/100, y1=p.y*H/100, x2=n.x*W/100, y2=n.y*H/100;
    const isMain = n.type==='group';
    const cls = isMain ? 'sm-line-main' : 'sm-line-sub';
    const mx = (x1+x2)/2, my = (y1+y2)/2;
    const cpx1 = x1, cpy1 = my, cpx2 = x2, cpy2 = my;
    if(Math.abs(x1-x2) < 30) {
      svgLines += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="${cls}"/>`;
      if(isMain) svgLines += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="sm-line-glow"/>`;
    } else {
      svgLines += `<path d="M${x1},${y1} C${cpx1},${cpy1} ${cpx2},${cpy2} ${x2},${y2}" class="${cls}"/>`;
      if(isMain) svgLines += `<path d="M${x1},${y1} C${cpx1},${cpy1} ${cpx2},${cpy2} ${x2},${y2}" class="sm-line-glow"/>`;
    }
    if(isMain){
      svgLines += `<circle cx="${mx}" cy="${my}" r="3" fill="${n.color||'#58a6ff'}" class="sm-pulse-dot"/>`;
    }
  });

  let svg = `<svg class="sm-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    <defs>
      <pattern id="sm-grid" width="40" height="40" patternUnits="userSpaceOnUse">
        <path d="M 40 0 L 0 0 0 40" fill="none" class="sm-grid-line"/>
      </pattern>
    </defs>
    <rect width="100%" height="100%" fill="url(#sm-grid)" opacity="0.3"/>
    ${svgLines}
  </svg>`;

  let cards = '';
  SM_NODES.forEach(n=>{
    const left = n.x + '%';
    const top = n.y + '%';
    let cls = 'sm-card';
    if(n.type==='center') cls += ' sm-center';
    if(n.type==='group') cls += ' sm-group';
    let style = `left:${left};top:${top};`;
    if(n.color && n.type==='group') style += `border-color:${n.color};`;

    let tickersHtml = '';
    if(n.tickers){
      tickersHtml = '<div class="sm-card-tickers">' + n.tickers.map(t=>{
        const d = supplyMapData[t] || {};
        const v = d.verdict || 'HOLD';
        const p = d.price ? `$${fmt(d.price)}` : '';
        return `<span class="sm-tbadge" data-ticker="${t}"><span class="sm-dot v-${v}"></span>${t}${p?` <span class="sm-tprice">${p}</span>`:''}</span>`;
      }).join('') + '</div>';
    }

    cards += `<div class="${cls}" style="${style}" data-id="${n.id}">
      <span class="sm-card-icon">${n.icon}</span>
      <div class="sm-card-label">${n.label}</div>
      ${n.desc?`<div class="sm-card-desc">${n.desc}</div>`:''}
      ${tickersHtml}
    </div>`;
  });

  container.innerHTML = svg + cards;
  container.classList.add('sm-canvas');

  container.querySelectorAll('.sm-tbadge').forEach(badge=>{
    badge.addEventListener('click', e=>{
      e.stopPropagation();
      openResearch(badge.dataset.ticker);
    });
  });
}

// ---- Demand ----
async function loadDemand(){
  const data=await api('/api/demand');
  renderDemandChart(data);
  renderDemandTable(data);
}

function renderDemandChart(signals){
  const container=$('#demand-chart');
  if(!signals||!signals.length){container.innerHTML='<p style="padding:40px;color:var(--text2)">无需求数据</p>';return;}

  const byQ={};
  signals.forEach(s=>{
    if(!byQ[s.quarter])byQ[s.quarter]={};
    byQ[s.quarter][s.source]=s;
  });
  const quarters=Object.keys(byQ).sort();
  const sources=['MSFT','GOOG','META','AMZN'];
  const colors={'MSFT':'#58a6ff','GOOG':'#3fb950','META':'#d29922','AMZN':'#f85149'};

  let html='<h4>季度CapEx($B)</h4><div style="display:flex;gap:4px;margin-bottom:8px">'+sources.map(s=>`<span style="font-size:11px;color:${colors[s]}">${s}</span>`).join(' | ')+'</div>';
  html+='<div class="bar-chart">';
  quarters.forEach(q=>{
    sources.forEach(src=>{
      const d=byQ[q]?.[src];
      const v=d?d.capex:0;
      const h=v*10;
      html+=`<div class="bar-group"><div class="bar-val">${v?v.toFixed(0):''}</div><div class="bar" style="height:${h}px;background:${colors[src]}"></div><div class="bar-label">${q===quarters[0]?src:''}</div></div>`;
    });
    html+=`<div class="bar-group" style="width:20px"><div class="bar-label" style="font-size:9px">${q.replace('CY','')}</div></div>`;
  });
  html+='</div>';
  container.innerHTML=html;
}

function renderDemandTable(signals){
  const tbody=$('#demand-table tbody');
  if(!signals||!signals.length){tbody.innerHTML='<tr><td colspan="5" style="color:var(--text2)">无数据</td></tr>';return;}
  tbody.innerHTML=signals.map(s=>`<tr>
    <td><b>${s.source}</b></td><td>${s.quarter}</td>
    <td>$${s.capex?.toFixed(1)||'—'}B</td>
    <td style="color:${s.capex_yoy>30?'var(--green)':'var(--text)'}">${s.capex_yoy?'+'+s.capex_yoy+'%':'—'}</td>
    <td style="font-size:12px">${s.ai_capex_guidance||''}</td>
  </tr>`).join('');
}

// ---- Watchlist ----
async function loadWatchlist(){
  const data=await api('/api/dashboard');
  const wl=data.watchlist;
  const tbody=$('#wl-table tbody');
  tbody.innerHTML=wl.map(w=>{
    const val=w.valuation||{};
    const thesis=w.thesis||{};
    const fromHigh=val.pct_from_high!=null?fmt(val.pct_from_high,0)+'%':'—';
    const cls=val.pct_from_high<-30?'color:var(--green)':val.pct_from_high>-10?'color:var(--red)':'';
    return `<tr>
      <td><b><a href="#" onclick="event.preventDefault();openResearch('${w.ticker}')">${w.ticker}</a></b></td>
      <td>${w.name||''}</td><td>${w.layer||''}</td>
      <td>${w.category||'observe'}</td>
      <td><span class="signal-badge verdict-${thesis.verdict||'HOLD'}">${thesis.verdict||'—'}</span></td>
      <td>${val.pe_ttm?fmt(val.pe_ttm,1):'—'}</td>
      <td style="${cls}">${fromHigh}</td>
      <td>$${fmt(w.entry_low,0)} – $${fmt(w.entry_high,0)}</td>
      <td><button class="btn" onclick="openResearch('${w.ticker}')">研究</button>
          <button class="btn" onclick="openTrading('${w.ticker}')">交易</button></td>
    </tr>`;
  }).join('');
  loadSettings();
  loadPipeline();
}

['fundamentals','trader','research','valuation','insider','filing'].forEach(mod=>{
  const btn=$(`#wl-collect-${mod}`);
  if(btn) btn.addEventListener('click',async()=>{
    toast(`正在采集 ${mod}...`);
    const r=await api(`/api/collect/${mod}`,{method:'POST'});
    toast(r.ok?`${mod} 采集完成`:`${mod} 采集失败`,r.ok?'success':'error');
  });
});

$('#wl-collect-all').addEventListener('click',async()=>{
  const mods=['fundamentals','trader','valuation','insider','filing'];
  toast('一键采集开始...');
  for(const mod of mods){
    toast(`正在采集 ${mod}...`);
    try{await api(`/api/collect/${mod}`,{method:'POST'});}catch(e){}
  }
  toast('全部采集完成');
});

$('#wl-add-btn').addEventListener('click',()=>{
  const form=$('#wl-form');
  form.classList.remove('hidden');
  form.innerHTML=`
    <div><label>Ticker</label><input type="text" id="wf-ticker"></div>
    <div><label>名称</label><input type="text" id="wf-name"></div>
    <div><label>层级</label><input type="text" id="wf-layer"></div>
    <div><label>分类</label><select id="wf-category"><option value="core">核心</option><option value="observe" selected>观察</option><option value="downgrade">降级</option></select></div>
    <div><label>入场低</label><input type="number" id="wf-elow"></div>
    <div><label>入场高</label><input type="number" id="wf-ehigh"></div>
    <div><label>目标($)</label><input type="number" id="wf-target" value="0"></div>
    <div><label>止损</label><input type="number" id="wf-sl" step="0.01" value="-0.15"></div>
    <div class="form-actions"><button class="btn btn-primary" onclick="saveNewTicker()">保存</button><button class="btn" onclick="document.getElementById('wl-form').classList.add('hidden')">取消</button></div>
  `;
});

window.saveNewTicker=async function(){
  const item={
    ticker:$('#wf-ticker').value.trim().toUpperCase(),
    name:$('#wf-name').value.trim(),layer:$('#wf-layer').value.trim(),
    category:$('#wf-category').value,
    entry_low:parseFloat($('#wf-elow').value)||null,
    entry_high:parseFloat($('#wf-ehigh').value)||null,
    target_usd:parseFloat($('#wf-target').value)||0,
    stop_loss:parseFloat($('#wf-sl').value)||-0.15,
  };
  if(!item.ticker){toast('Ticker不能为空','error');return;}
  await api('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item})});
  toast(`${item.ticker} 已保存`);
  $('#wl-form').classList.add('hidden');
  loadWatchlist();
};

window.openResearch=openResearch;

// ---- Settings ----
async function loadSettings(){
  const s=await api('/api/settings');
  const form=$('#settings-form');
  form.innerHTML=`
    <div class="sf-group"><label>LLM API Key</label><input type="password" id="sf-apikey" value="${s.llm_api_key||''}" placeholder="sk-..."></div>
    <div class="sf-group"><label>API URL</label><input type="text" id="sf-apiurl" value="${s.llm_api_url||'https://api.anthropic.com/v1'}" placeholder="https://api.anthropic.com/v1"></div>
    <div class="sf-group"><label>Model</label><input type="text" id="sf-model" value="${s.llm_model||'claude-sonnet-4-20250514'}" placeholder="claude-sonnet-4-20250514"></div>
    <div class="sf-group"><label>钉钉 Webhook</label><input type="text" id="sf-dingtalk-webhook" value="${s.dingtalk_webhook||''}" placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."></div>
    <div class="sf-group"><label>钉钉 Secret</label><input type="password" id="sf-dingtalk-secret" value="${s.dingtalk_secret||''}" placeholder="SEC..."></div>
    <div class="sf-group"><label>SEC Email (User-Agent)</label><input type="text" id="sf-sec-email" value="${s.sec_email||''}" placeholder="name email@example.com"></div>
    <div class="sf-group"><label>自动更新</label><select id="sf-auto-update"><option value="0" ${s.auto_update_enabled!=='1'?'selected':''}>关闭</option><option value="1" ${s.auto_update_enabled==='1'?'selected':''}>开启</option></select></div>
    <div class="sf-group"><label>更新间隔(小时)</label><input type="number" id="sf-update-interval" value="${s.update_interval_hours||'6'}" min="1" max="24"></div>
    <div class="form-actions"><button class="btn btn-primary" onclick="saveSettings()">保存设置</button></div>
  `;
}

window.saveSettings=async function(){
  const data={
    llm_api_key:$('#sf-apikey').value.trim(),
    llm_api_url:$('#sf-apiurl').value.trim(),
    llm_model:$('#sf-model').value.trim(),
    dingtalk_webhook:$('#sf-dingtalk-webhook').value.trim(),
    dingtalk_secret:$('#sf-dingtalk-secret').value.trim(),
    sec_email:$('#sf-sec-email').value.trim(),
    auto_update_enabled:$('#sf-auto-update').value,
    update_interval_hours:$('#sf-update-interval').value,
  };
  await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  toast('设置已保存');
};

async function loadPipeline(){
  try{
    const s=await api('/api/pipeline/status');
    const el=$('#pipeline-panel');
    if(!el)return;
    const last=s.last_run;
    let lastHtml='<span style="color:var(--text2)">从未运行</span>';
    if(last){
      const stages=last.stages||{};
      const dots=Object.entries(stages).map(([k,v])=>{
        const color=v.ok?'var(--green)':'var(--red)';
        return `<span style="color:${color};font-weight:600" title="${k}: ${v.time||0}s">${k} ${v.ok?'✓':'✗'}</span>`;
      }).join(' | ');
      lastHtml=`<span style="font-size:12px">${last.started_at} — ${last.status} — ${dots}</span>`;
    }
    el.innerHTML=`
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px">
        <span style="font-size:12px;color:var(--text2)">自动更新: <b style="color:${s.auto_update_enabled?'var(--green)':'var(--text2)}'}">${s.auto_update_enabled?'开启':'关闭'}</b> (每${s.update_interval_hours}h)</span>
        <button class="btn btn-primary" onclick="runPipeline()">立即运行 Pipeline</button>
      </div>
      <div style="font-size:12px;color:var(--text2)">上次运行: ${lastHtml}</div>
    `;
  }catch(e){}
}
window.runPipeline=async function(){
  toast('Pipeline 已启动...');
  await api('/api/pipeline/run',{method:'POST'});
  setTimeout(loadPipeline,5000);
};

loadDashboard();
})();
