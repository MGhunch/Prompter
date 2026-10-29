/* Prompter — fix.js. FIX IT: the profile, tick it or tweak it, start again.
   Plain scripts sharing one page; index.html loads them in order:
   words, helpers, feed, fix, shape. */
/* ═══════════════════════════════════════════════════════════════
   REVISE — tick-it-or-tweak-it.
   Reuses live profileData / escHtml / threeWordSentence /
   buildPromptMd / downloadPdf / downloadMd. State is namespaced
   (revise*) and the two browser-global footguns are renamed
   (open → openTweak, history → reviseHistory).
   ═══════════════════════════════════════════════════════════════ */
const esc = escHtml;
let reviseActive = null;       // {section,index,highlight,opener,lastReason}
let reviseHistory = [];        // chat turns for /api/revise
let reviseProposal = null;     // pending proposal awaiting Lock
let reviseTweaks = [];         // in-session receipt: {label,why,before,after}
let reviseView = 'profile';    // card face: 'profile' | 'prompt'
let reviseMouseupBound = false;

const PENCIL = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`;
const SVG_DL = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;

const OPENERS = {
  brand:       p => `This is your Brand — the whole voice in a paragraph.\n\nWhat do you want to tweak?`,
  brandHi:     (p,h) => `You've highlighted “${h}” in your Brand.\n\nWhat do you want to tweak?`,
  behaviours:  (p,i) => `This is a Who-we-are pair — “${p.behaviours[i].we}” against “${p.behaviours[i].not}”.\n\nWhat do you want to tweak?`,
  behavioursHi:(p,i,h) => `You've highlighted “${h}”.\n\nWhat do you want to tweak?`,
  examples:    (p,i) => `This is a More / Less example.\n\nWhat do you want to tweak?`,
  examplesHi:  (p,i,h) => `You've highlighted “${h}”.\n\nWhat do you want to tweak?`,
  houseRules:  (p,i) => `This is your “${p.houseRules[i].key}” rule.\n\nWhat do you want to tweak?`,
  houseRulesHi:(p,i,h) => `You've highlighted “${h}” in the “${p.houseRules[i].key}” rule.\n\nWhat do you want to tweak?`,
  descriptors:  (p,i) => `These are your three words — the voice brief that runs through the prompt.\n\nWhat do you want to tweak?`,
  descriptorsHi:(p,i,h) => `You've highlighted “${h}”.\n\nWant a different word?`,
};

/* reveal entry point — builds card + rail, then renders both */
function renderProfileZone(p) {
  reviseActive = null; reviseHistory = []; reviseProposal = null;
  reviseTweaks = []; reviseView = 'profile';
  const mp = document.getElementById('mainPage'); if (mp) mp.classList.add('revealed');

  document.getElementById('profileZone').innerHTML = `
    <div class="stage" id="reviseStage">
      <div class="cardwrap"><div class="profile-zone" id="reviseCard"></div></div>
      <div class="rail" id="rail">
        <div class="rail-head" id="railHead"></div>
        <div class="rail-idle" id="railIdle"></div>
        <div class="rail-chat" id="railChat">
          <div class="dp-head">
            <div class="dp-dot">D</div>
            <div><div class="dp-title">Dot</div><div class="dp-sub" id="dpSub">Tweaking a block</div></div>
            <button class="dp-x" onclick="closePanel()">&times;</button>
          </div>
          <div class="dp-body" id="dpBody"></div>
          <div class="dp-foot">
            <input class="dp-input" id="dpInput" placeholder="Tell Dot what to tweak…" onkeydown="if(event.key==='Enter')sendFeedback()">
            <button class="dp-send" onclick="sendFeedback()">Send</button>
          </div>
        </div>
        <div class="rail-foot" id="railFoot"></div>
      </div>
    </div>`;

  if (!reviseMouseupBound) {
    document.addEventListener('mouseup', onCardMouseup);
    reviseMouseupBound = true;
  }
  reviseRender(); renderHead(); renderRail(); renderFoot();
}

/* ── the artefact (card) — editable ── */
function reviseRender() {
  const p = profileData, bn = p.brandName || 'Brand';
  const titleWord = reviseView === 'prompt' ? 'PROMPT' : 'VOICE';
  let h = `<div class="profile-header">
    <div class="profile-title">YOUR <span>${esc(bn.toUpperCase())}</span> ${titleWord}</div>
    <div class="view-toggle" data-noexport>
      <button class="vt ${reviseView==='profile'?'active':''}" onclick="reviseSetView('profile')">Profile</button>
      <button class="vt ${reviseView==='prompt'?'active':''}" onclick="reviseSetView('prompt')">Prompt</button>
    </div>
  </div>`;

  if (reviseView === 'prompt') {
    h += buildPromptBlocksHtml(p);
    document.getElementById('reviseCard').innerHTML = h;
    bindEditablePencils();
    return;
  }

  h += `<div class="psec editable" data-section="brand" data-index="0">
    <button class="pencil" title="Tweak">${PENCIL}</button>
    <div class="plbl">Brand</div>
    <div class="pbody"><span data-text data-field="brand">${esc(p.brand)}</span>${descLineHtml(p)}</div></div>`;

  h += `<div class="psec"><div class="plbl">Who we are</div><table class="ptable">
    <tr><th>We are</th><th>We're not</th></tr>` +
    p.behaviours.map((b,i)=>`<tr class="editable" data-section="behaviours" data-index="${i}">
      <td data-text data-field="we">${esc(b.we)}</td><td class="less" data-text data-field="not">${esc(b.not)}<button class="pencil" title="Tweak">${PENCIL}</button></td></tr>`).join('') +
    `</table></div>`;

  h += `<div class="psec"><div class="plbl">Examples</div><table class="ptable">
    <tr><th>More this</th><th>Less this</th></tr>` +
    p.examples.map((e,i)=>`<tr class="editable" data-section="examples" data-index="${i}">
      <td data-text data-field="more">${esc(e.more)}</td><td class="less" data-text data-field="less">${esc(e.less)}<button class="pencil" title="Tweak">${PENCIL}</button></td></tr>`).join('') +
    `</table></div>`;

  h += `<div class="psec"><div class="plbl">House Rules</div><div class="rules-list">` +
    p.houseRules.map((r,i)=>`<div class="rule-item editable" data-section="houseRules" data-index="${i}">
      <span class="rule-key" data-text data-field="key">${esc(r.key)}</span><span class="rule-val" data-text data-field="rule">${esc(r.rule)}</span>
      <button class="pencil" title="Tweak">${PENCIL}</button></div>`).join('') +
    `</div></div>`;

  h += `<div class="psec footer-row"><span class="footer-note">Remember, robots are good. But keep a human in the loop.</span></div>`;

  document.getElementById('reviseCard').innerHTML = h;
  bindEditablePencils();
}

function bindEditablePencils() {
  document.querySelectorAll('#reviseCard .editable').forEach(el=>{
    const pen = el.querySelector('.pencil');
    if (!pen) return;
    pen.addEventListener('mousedown', ev=>ev.preventDefault());  // don't let the click collapse the user's highlight
    pen.addEventListener('click', ev=>{
      ev.stopPropagation();
      openTweak(el.dataset.section, +el.dataset.index, highlightWithin(el));
    });
  });
}

/* ── the hero — persistent, stays put while Dot grows ── */
function renderHead() {
  document.getElementById('railHead').innerHTML = `<div class="rl-hero">
      <div class="rl-eyebrow">Quick sensecheck</div>
      <div class="rl-hed">Tick it.<br><span class="rl-tweak">Or tweak it.</span></div>
      <div class="rl-intro">Here's our take on your voice.</div>
    </div>`;
}

/* ── Dot's section, at rest (becomes the chat when live) ── */
function renderRail() {
  let h = `<div class="rl-dot">
      <div class="rl-dot-av">D</div>
      <div class="rl-dot-bubble">See something worth fixing?<br>Just highlight it and let's chat.</div>
    </div>`;

  if (reviseTweaks.length) {
    h += `<div class="tweaks-made" id="tweaksMade">
        <button class="tm-head" onclick="document.getElementById('tweaksMade').classList.toggle('open')">
          <span class="tm-count"><span class="tick">✓</span> ${reviseTweaks.length} tweak${reviseTweaks.length>1?'s':''} made</span>
          <span class="tm-chev">▾</span>
        </button>
        <div class="tm-list">` +
        reviseTweaks.map(t=>`<div class="tw-item"><div class="tw-lbl">${esc(t.label)}</div><div class="tw-why">${esc(t.why)}</div></div>`).join('') +
        `</div></div>`;
  }

  document.getElementById('railIdle').innerHTML = h;
}

/* the exit — persistent footer, survives the chat */
function renderFoot() {
  document.getElementById('railFoot').innerHTML = `<div class="gtg">
      <div class="gtg-hed">Good to go?</div>
      <button class="dl-btn" id="reviseDownload" onclick="reviseDownloadAll()">${SVG_DL} Download</button>
    </div>
    <button class="rail-restart" onclick="startAgain()">Start again</button>`;
}

/* rail download — takes both faces at once (PDF + prompt) */
async function reviseDownloadAll() {
  if (reviseView === 'prompt') reviseSetView('profile'); // export the profile, not the raw prompt
  const btn = document.getElementById('reviseDownload');
  if (btn) btn.disabled = true;
  try { await downloadPdf(); downloadMd(); }
  finally { if (btn) btn.disabled = false; }
}

/* ── word-level diff (LCS) → brand-red on changed tokens ── */
function diffWords(oldS, newS) {
  const tok = s => (s||'').split(/(\s+)/);
  const o = tok(oldS), n = tok(newS);
  const m = o.length, k = n.length;
  const dp = Array.from({length:m+1}, ()=>new Array(k+1).fill(0));
  for (let i=m-1;i>=0;i--) for (let j=k-1;j>=0;j--)
    dp[i][j] = o[i]===n[j] ? dp[i+1][j+1]+1 : Math.max(dp[i+1][j], dp[i][j+1]);
  let i=0, j=0, out='';
  while (j<k) {
    if (i<m && o[i]===n[j]) { out+=esc(n[j]); i++; j++; }
    else if (i<m && dp[i+1][j] >= dp[i][j+1]) { i++; }
    else { out += n[j].trim()==='' ? esc(n[j]) : '<mark class="changed">'+esc(n[j])+'</mark>'; j++; }
  }
  return out;
}

/* ── descriptors — the three words, individually tweakable ── */
function descInner(bn, words) {
  const w = (words||[]).map((x,i)=>`<span class="desc-w" data-text data-di="${i}">${esc(String(x).toLowerCase())}</span>`);
  if (!w.length) return '';
  const list = w.length > 1 ? w.slice(0,-1).join(', ') + ' and ' + w[w.length-1] : w[0];
  return `${esc(bn)} is ${list}.`;
}
function descLineHtml(p) {
  if (!p.descriptors || !p.descriptors.length) return '';
  const bn = p.brandName || 'The brand';
  return ` <span class="desc-line" data-section="descriptors" data-index="0">${descInner(bn, p.descriptors)}</span>`;
}
function descDiff(oldArr, newArr) {
  const bn = (profileData.brandName || 'The brand');
  const parts = (newArr||[]).map((nw,i)=>diffWords(String((oldArr||[])[i]||'').toLowerCase(), String(nw).toLowerCase()));
  if (!parts.length) return '';
  const list = parts.length > 1 ? parts.slice(0,-1).join(', ') + ' and ' + parts[parts.length-1] : parts[0];
  return `${esc(bn)} is ${list}.`;
}
/* prompt-face descriptor rendering — "Think, a, b, c." (no brand-name scaffold) */
function descPromptInner(words) {
  return (words||[]).map((x,i)=>`<span class="desc-w" data-text data-di="${i}">${esc(String(x).toLowerCase())}</span>`).join(', ');
}
function descDiffPrompt(oldArr, newArr) {
  return (newArr||[]).map((nw,i)=>diffWords(String((oldArr||[])[i]||'').toLowerCase(), String(nw).toLowerCase())).join(', ');
}

/* The Prompt face — same editable blocks as the Profile, laid out as a prompt.
   Framing lines are fixed (template, not voice); every voice block is wired to
   the same profileData, so editing either face writes to one place. */
function buildPromptBlocksHtml(p) {
  const bn = p.brandName || 'this brand';
  const P = `<button class="pencil" title="Tweak">${PENCIL}</button>`;
  let h = `<div class="prompt-view">`;
  let intro = `You are crafting communications for <b>${esc(bn)}</b>. Your job is to write in their voice.`;
  if (p.descriptors && p.descriptors.length)
    intro += ` Think, <span class="desc-line" data-section="descriptors" data-index="0">${descPromptInner(p.descriptors)}</span>.`;
  h += `<div class="pv-fixed">${intro}</div><div class="pv-rule">———</div>`;

  h += `<div class="pv-h">## Brand</div>
    <div class="editable pv-blk" data-section="brand" data-index="0">${P}<span data-text data-field="brand">${esc(p.brand)}</span></div>`;

  h += `<div class="pv-h">## Who we are</div>` +
    p.behaviours.map((b,i)=>`<div class="editable pv-blk" data-section="behaviours" data-index="${i}">- <b>Are:</b> <span data-text data-field="we">${esc(b.we)}</span><br>&nbsp;&nbsp;<b>Are not:</b> <span class="less" data-text data-field="not">${esc(b.not)}</span>${P}</div>`).join('');

  h += `<div class="pv-h">## Write more like this</div>` +
    p.examples.map((e,i)=>`<div class="editable pv-blk" data-section="examples" data-index="${i}">- ✓ <span data-text data-field="more">${esc(e.more)}</span><br>&nbsp;&nbsp;✗ <span class="less" data-text data-field="less">${esc(e.less)}</span>${P}</div>`).join('');

  h += `<div class="pv-h">## House rules</div>` +
    p.houseRules.map((r,i)=>`<div class="rule-item editable pv-blk" data-section="houseRules" data-index="${i}">- <b><span data-text data-field="key">${esc(r.key)}</span>:</b> <span data-text data-field="rule">${esc(r.rule)}</span>${P}</div>`).join('');

  h += `<div class="pv-rule">———</div><div class="pv-fixed">Now write like this. Every time. No exceptions.</div></div>`;
  return h;
}

/* ── highlighter ── */
function highlightWithin(el) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return '';
  const txt = sel.toString().trim();
  if (!txt) return '';
  const anc = sel.getRangeAt(0).commonAncestorContainer;
  const node = anc.nodeType === 3 ? anc.parentElement : anc;
  if (node && node.closest && node.closest('.desc-line')) return '';  // descriptors route themselves
  return el.contains(node) ? txt : '';
}
function onCardMouseup() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return;
  const txt = sel.toString().trim();
  if (!txt) return;
  const anc = sel.getRangeAt(0).commonAncestorContainer;
  const node = anc.nodeType === 3 ? anc.parentElement : anc;
  const desc = node && node.closest ? node.closest('#reviseCard .desc-line') : null;
  if (desc) {
    if (reviseActive && reviseActive.section==='descriptors' && reviseActive.highlight===txt) return;
    openTweak('descriptors', 0, txt);
    return;
  }
  const el = node && node.closest ? node.closest('#reviseCard .editable') : null;
  if (!el) return;
  if (reviseActive && reviseActive.section===el.dataset.section && reviseActive.index===+el.dataset.index && reviseActive.highlight===txt) return;
  openTweak(el.dataset.section, +el.dataset.index, txt);
}
function litHighlight(section, index, hl) {
  if (!hl) return;
  const el = blockEl(section,index);
  if (!el) return;
  for (const node of el.querySelectorAll('[data-text]')) {
    const t = node.textContent;
    const i = t.indexOf(hl);
    if (i >= 0) { node.innerHTML = esc(t.slice(0,i))+'<mark class="hl">'+esc(hl)+'</mark>'+esc(t.slice(i+hl.length)); break; }
  }
}

function blockValue(section,index) { return section==='brand' ? profileData.brand : section==='descriptors' ? profileData.descriptors : profileData[section][index]; }
function blockEl(section,index) { return document.querySelector(`#reviseCard [data-section="${section}"][data-index="${index}"]`); }

function openTweak(section, index, highlight) {
  if (reviseActive) { const prev = reviseActive; reviseActive = null; restoreBlock(prev.section, prev.index); }
  clearActive();
  reviseActive = { section, index, highlight: highlight||'', lastReason:'' };
  reviseHistory = []; reviseProposal = null;
  const el = blockEl(section,index);
  if (el) el.classList.add('active');
  if (highlight) litHighlight(section, index, highlight);

  let opener;
  const hk = section+'Hi';
  if (highlight && OPENERS[hk]) opener = section==='brand' ? OPENERS.brandHi(profileData,highlight) : OPENERS[hk](profileData,index,highlight);
  else opener = section==='brand' ? OPENERS.brand(profileData) : OPENERS[section](profileData,index);
  reviseActive.opener = opener;

  document.getElementById('dpSub').textContent = subLabel(section,index);
  document.getElementById('dpBody').innerHTML = '';
  addMsg('dot', opener);
  document.getElementById('reviseStage').classList.add('editing');
  setTimeout(()=>document.getElementById('dpInput').focus(), 200);
}
function subLabel(section,index) {
  if (section==='brand') return 'Brand';
  if (section==='behaviours') return 'Who we are · row '+(index+1);
  if (section==='examples') return 'Examples · row '+(index+1);
  if (section==='houseRules') return profileData.houseRules[index].key;
  if (section==='descriptors') return 'The three words';
  return section;
}
function clearActive() {
  document.querySelectorAll('#reviseCard .editable.active, #reviseCard .editable.preview, #reviseCard .desc-line.active, #reviseCard .desc-line.preview').forEach(e=>e.classList.remove('active','preview'));
}
function closePanel() {
  document.getElementById('reviseStage').classList.remove('editing');
  reviseActive = null; reviseProposal = null; reviseHistory = [];
  reviseRender(); renderRail();
}

/* ── chat ── */
function addMsg(who, text, opts={}) {
  const body = document.getElementById('dpBody');
  const d = document.createElement('div');
  d.className = 'msg '+who+(opts.pb?' pb':'');
  d.textContent = text;
  body.appendChild(d); body.scrollTop = body.scrollHeight;
}
function addProposal(section, index, prop) {
  const body = document.getElementById('dpBody');
  const cur = blockValue(section, index);
  let inner = '';
  if (section==='brand') inner = `<span class="pf">${diffWords(cur, typeof prop==='string'?prop:(prop.brand||''))}</span>`;
  else if (section==='behaviours') inner = `<span class="pf"><span class="lbl">We are</span> ${diffWords(cur.we, prop.we||'')}</span><span class="pf"><span class="lbl">We're not</span> ${diffWords(cur.not, prop.not||'')}</span>`;
  else if (section==='examples') inner = `<span class="pf"><span class="lbl">More</span> ${diffWords(cur.more, prop.more||'')}</span><span class="pf"><span class="lbl">Less</span> ${diffWords(cur.less, prop.less||'')}</span>`;
  else if (section==='houseRules') inner = `<span class="pf"><b>${diffWords(cur.key, prop.key||cur.key)}</b></span><span class="pf">${diffWords(cur.rule, prop.rule||'')}</span>`;
  else if (section==='descriptors') inner = `<span class="pf">${descDiff(cur, prop)}</span>`;
  const card = document.createElement('div'); card.className='proposal';
  card.innerHTML = `<div class="pl">Proposed</div>${inner}`;
  body.appendChild(card);
  const row = document.createElement('div'); row.className='lock-row';
  const b = document.createElement('button'); b.className='lock-btn'; b.textContent='✓ Lock this?'; b.onclick=reviseCommit;
  row.appendChild(b); body.appendChild(row); body.scrollTop = body.scrollHeight;
}
function thinking(on) {
  const body = document.getElementById('dpBody');
  let t = document.getElementById('thinkingDots');
  if (on) { if (t) return; t=document.createElement('div'); t.id='thinkingDots'; t.className='thinking';
    t.innerHTML='<span></span><span></span><span></span>'; body.appendChild(t); body.scrollTop=body.scrollHeight; }
  else if (t) { t.remove(); }
}
async function sendFeedback() {
  const inp = document.getElementById('dpInput');
  const text = inp.value.trim();
  if (!text || !reviseActive) return;
  inp.value=''; addMsg('me', text);
  reviseHistory.push({role:'user', content:text});
  thinking(true);
  try {
    const res = await fetch('/api/revise', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        profile: profileData,
        target:{section:reviseActive.section, index:reviseActive.index},
        blockValue: blockValue(reviseActive.section, reviseActive.index),
        highlight: reviseActive.highlight || null,
        opener: reviseActive.opener, history: reviseHistory
      })
    });
    const data = await res.json();
    thinking(false);
    if (!data.success) { addMsg('dot', limitLine(data) || "Something's up. Please let us know."); return; }
    reviseHistory.push({role:'assistant', content:data.message});
    if (data.proposal) {
      reviseProposal = data.proposal; reviseActive.lastReason = data.message || '';
      if (data.message) addMsg('dot', data.message);
      addProposal(reviseActive.section, reviseActive.index, data.proposal);
      preview(reviseActive.section, reviseActive.index, data.proposal);
    } else { reviseProposal=null; restoreBlock(reviseActive.section, reviseActive.index); addMsg('dot', data.message, {pb:data.pushback}); }
  } catch (err) { thinking(false); addMsg('dot', "Can't find the robot. Please try again."); }
}

/* ── preview on the card (DOM only) ── */
function setField(el, field, html) { const n = el.querySelector(`[data-field="${field}"]`); if (n) n.innerHTML = html; }
function preview(section, index, prop) {
  const el = blockEl(section,index); if (!el) return;
  el.classList.remove('active'); el.classList.add('preview');
  const cur = blockValue(section,index);
  if (section==='brand') setField(el,'brand', diffWords(cur, typeof prop==='string'?prop:(prop.brand||'')));
  else if (section==='behaviours') { setField(el,'we', diffWords(cur.we, prop.we||'')); setField(el,'not', diffWords(cur.not, prop.not||'')); keepPencil(el,'not'); }
  else if (section==='examples') { setField(el,'more', diffWords(cur.more, prop.more||'')); setField(el,'less', diffWords(cur.less, prop.less||'')); keepPencil(el,'less'); }
  else if (section==='houseRules') { setField(el,'key', diffWords(cur.key, prop.key||cur.key)); setField(el,'rule', diffWords(cur.rule, prop.rule||'')); }
  else if (section==='descriptors') { el.innerHTML = reviseView==='prompt' ? descDiffPrompt(cur, prop) : descDiff(cur, prop); }
}
function keepPencil(el, field) {
  const node = el.querySelector(`[data-field="${field}"]`);
  if (node && !node.querySelector('.pencil')) {
    const b = document.createElement('button'); b.className='pencil'; b.title='Tweak'; b.innerHTML=PENCIL;
    b.addEventListener('click', ev=>{ ev.stopPropagation(); openTweak(el.dataset.section,+el.dataset.index,''); });
    node.appendChild(b);
  }
}
function restoreBlock(section,index) {
  const el = blockEl(section,index); if (!el) return;
  el.classList.remove('preview'); el.classList.add('active');
  const cur = blockValue(section,index);
  if (section==='brand') setField(el,'brand', esc(cur));
  else if (section==='behaviours') { setField(el,'we',esc(cur.we)); setField(el,'not',esc(cur.not)); keepPencil(el,'not'); }
  else if (section==='examples') { setField(el,'more',esc(cur.more)); setField(el,'less',esc(cur.less)); keepPencil(el,'less'); }
  else if (section==='houseRules') { setField(el,'key',esc(cur.key)); setField(el,'rule',esc(cur.rule)); }
  else if (section==='descriptors') { el.innerHTML = reviseView==='prompt' ? descPromptInner(cur) : descInner(profileData.brandName||'The brand', cur); }
  if (reviseActive && reviseActive.highlight) litHighlight(section,index,reviseActive.highlight);
}

/* ── commit: Lock writes to truth + logs the tweak ── */
function reviseCommit() {
  if (!reviseActive || !reviseProposal) return;
  const {section,index} = reviseActive;
  const before = JSON.parse(JSON.stringify(blockValue(section,index)));
  if (section==='brand') profileData.brand = typeof reviseProposal==='string' ? reviseProposal : (reviseProposal.brand||profileData.brand);
  else if (section==='descriptors') profileData.descriptors = Array.isArray(reviseProposal) ? reviseProposal : profileData.descriptors;
  else profileData[section][index] = reviseProposal;

  reviseTweaks.push({
    label: subLabel(section,index),
    why: reviseActive.lastReason || 'Tweaked.',
    before, after: JSON.parse(JSON.stringify(reviseProposal))
  });

  reviseProposal = null;
  addMsg('dot', "Locked in. Profile and prompt both updated.");
  reviseRender(); toast('Locked in');
  setTimeout(closePanel, 650);
}

function reviseSetView(v) {
  if (reviseView===v) return;
  reviseView=v; reviseActive=null;
  const st = document.getElementById('reviseStage'); if (st) st.classList.remove('editing');
  reviseRender();
}
function toast(msg) { const t=document.getElementById('toast'); if (!t) return; t.textContent=msg; t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),1700); }

function startAgain() {
  uploadedFiles = []; profileData = null; consultHistory = [];
  notesCounter = 0; dotReady = false;
  confirmChecks = []; confirmResults = []; currentCheck = 0;
  senseCheckPrefetch = null;
  reviseActive = null; reviseProposal = null; reviseHistory = []; reviseTweaks = []; reviseView = 'profile';
  document.getElementById('mainPage').classList.remove('revealed');
  document.getElementById('fileList').innerHTML = '';
  document.getElementById('responseArea').innerHTML = '';
  document.getElementById('profileZone').style.display = 'none';
  document.getElementById('profileZone').innerHTML = '';
  document.getElementById('inputZone').style.display = 'flex';
  document.getElementById('consultZone').style.display = 'none';
  document.getElementById('goWrap').style.display = 'none';
  document.getElementById('hero').style.display = 'flex';
  document.getElementById('dotOpening').style.display = 'flex';
  document.getElementById('goBtn').disabled = true;
  document.getElementById('goBtn').classList.remove('ready');
  document.getElementById('dotMsgText').style.display = 'none';
  document.getElementById('dotThinking').style.display = 'flex';
  document.getElementById('sensecheckScreen').classList.remove('active');
  document.getElementById('thinkingScreen').classList.remove('active');
  document.getElementById('mainPage').style.display = 'flex';
  document.getElementById('pageFooter').style.display = 'block';
  resetHistoryUI();
  showError('');
  document.getElementById('feedRoom').style.display = 'flex';
  document.getElementById('mainPage').classList.add('feed');
  houseRules = []; rulesLooked = false; renderRules();
  frSay(''); document.getElementById('dumpText').value = '';
  updateBounceCount(); renderFileList();
  frOpen(1);
}

