/* Prompter — feed.js. FEED IT: the welcome, the three stops, files, labels, Dot's chat, the rules.
   Plain scripts sharing one page; index.html loads them in order:
   words, helpers, feed, fix, shape. */
let uploadedFiles = [];
let profileData = null;
let consultHistory = [];
let notesCounter = 0;
let dotReady = false;
let exchangeCount = 0;
let historyOpen = false;

/* ---------- WELCOME + FEED IT (Oct 2026) ---------- */

// The four kinds of material, under the two piles.
const PILE = { GUIDELINES: 'STATED', DIRECTION: 'STATED', EXAMPLES: 'SHOWN', WEBSITE: 'SHOWN' };

// What the robot gets: each item's name, text and type.
function materialPayload() {
  return uploadedFiles.map(f => ({ filename: f.filename, text: f.text, label: f.label || '' }));
}

// The OPEN sign swings when the welcome draws, and again when touched.
function signSwing() {
  const el = document.querySelector('#welcomeSign .open-sign');
  if (!el) return;
  el.classList.remove('swing'); void el.getBoundingClientRect(); el.classList.add('swing');
}
window.addEventListener('DOMContentLoaded', () => {
  const el = document.querySelector('#welcomeSign .open-sign');
  if (el) { el.addEventListener('mouseenter', signSwing); el.addEventListener('click', signSwing); }
});

function welcomeShow(on) {
  document.getElementById('welcome').classList.toggle('on', on);
  if (on) signSwing();
  document.getElementById('mainPage').style.display = on ? 'none' : 'flex';
  document.getElementById('pageFooter').style.display = on ? 'none' : 'block';
}
function welcomeStart() { welcomeShow(false); window.scrollTo(0, 0); }
function openHiw() { document.getElementById('hiwModal').classList.add('active'); }
function closeHiw() { document.getElementById('hiwModal').classList.remove('active'); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeHiw(); });

// One stop open at a time.
function frOpen(n) {
  [1, 2, 3].forEach(i => {
    const stop = document.getElementById('stop' + i);
    stop.classList.toggle('open', i === n);
    stop.querySelector('.fr-card-top').setAttribute('aria-expanded', i === n ? 'true' : 'false');
  });
  if (n === 3) rulesFirstLook();
}

function frSay(msg) { document.getElementById('dumpNote').textContent = msg || ''; }

// DUMP IT: one box. A lone web address is fetched; anything else is notes.
function looksLikeLink(t) {
  return !/\s/.test(t) && /^(https?:\/\/)?[\w-]+(\.[\w-]+)+(\/\S*)?$/i.test(t);
}
async function addFromBox() {
  const box = document.getElementById('dumpText');
  const text = box.value.trim();
  if (!text) return;
  frSay('');
  const btn = document.getElementById('dumpAdd');
  btn.disabled = true;
  if (looksLikeLink(text)) {
    document.getElementById('weblinkInput').value = text;
    await fetchWeblink();
    if (!document.getElementById('weblinkInput').value) box.value = '';
  } else {
    document.getElementById('notesInput').value = text;
    box.value = '';
    await addNotes();
  }
  btn.disabled = false;
}

// Ask the light robot what type an item is. Unsure means EXAMPLES.
async function labelItem(item) {
  try {
    const res = await fetch('/api/summarise', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ text: item.text.slice(0, 500) })
    });
    const data = await res.json();
    item.label = (data.success && PILE[data.label]) ? data.label : 'EXAMPLES';
  } catch { item.label = 'EXAMPLES'; }
}

function chatReplies() {
  return consultHistory.filter(h => h.role === 'user'
    && !String(h.content).startsWith('More material just landed')).length;
}
function updateBounceCount() {
  const n = chatReplies();
  document.getElementById('bounceCount').textContent = consultHistory.length ? WORDS.bounceCount(n) : '';
}

// SET THE RULES: the robot suggests, the person keeps, drops or adds.
let houseRules = [];        // [{text, found}]
let rulesLooked = false;
async function rulesFirstLook() {
  if (rulesLooked || !uploadedFiles.length) { renderRules(); return; }
  rulesLooked = true;
  document.getElementById('rulesList').innerHTML = `<div class="fr-small">${escHtml(WORDS.rulesReading)}</div>`;
  try {
    const res = await fetch('/api/rules', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ files: materialPayload() })
    });
    const data = await res.json();
    if (data.success) {
      (data.rules || []).forEach(t => {
        if (!houseRules.find(r => r.text.toLowerCase() === t.toLowerCase())) houseRules.push({ text: t, found: true });
      });
    }
  } catch { /* no suggestions is fine: they can still add their own */ }
  renderRules();
}
function renderRules() {
  document.getElementById('rulesList').innerHTML = houseRules.map((r, i) =>
    `<div class="fr-rule"><span>${escHtml(r.text)}${r.found ? `<small>${escHtml(WORDS.ruleFound)}</small>` : ''}</span>` +
    `<button class="b-quiet x" type="button" aria-label="Remove rule" onclick="removeRule(${i})">&times;</button></div>`).join('');
  const sum = document.getElementById('stop3Sum');
  if (!sum.dataset.empty) sum.dataset.empty = sum.textContent;
  sum.textContent = houseRules.length ? WORDS.rulesSum(houseRules.length) : sum.dataset.empty;
}
function addRule() {
  const input = document.getElementById('ruleInput');
  const text = input.value.trim();
  if (!text) return;
  if (!houseRules.find(r => r.text.toLowerCase() === text.toLowerCase())) houseRules.push({ text, found: false });
  input.value = '';
  renderRules();
}
function removeRule(i) { houseRules.splice(i, 1); renderRules(); }

window.addEventListener('DOMContentLoaded', () => welcomeShow(true));

// Load opening message on page load
window.addEventListener('load', async () => {
  try {
    const res = await fetch('/api/opening');
    const data = await res.json();
    if (data.success) {
      document.getElementById('dotOpenText').textContent = data.message;
    }
  } catch {
    document.getElementById('dotOpenText').textContent = "How you talk is who you are. Let's craft a prompt so you sound like you.";
  }
});

// SUITE TEASER MODALS (Slicer / Wrangler — not yet built)
const SUITE_TEASERS = {
  slicer: {
    hed: 'SLICER',
    body: "Slicer is an app that takes a block of copy and recrafts it for different channels. Email, socials, even text. It's not fully built yet. Yell if you want it now.",
    cta: 'BUILD SLICER FASTER'
  },
  wrangler: {
    hed: 'WRANGLE',
    body: "Wrangler is an app that wrangles feedback. See what we did with the name? It's designed to solve the conflicting feedback puzzle. But it isn't ready yet.",
    cta: 'BUILD WRANGLE FASTER'
  }
};

function openSuiteModal(key) {
  const t = SUITE_TEASERS[key];
  if (!t) return;
  document.getElementById('suiteModalHed').textContent = t.hed;
  document.getElementById('suiteModalBody').textContent = t.body;
  const cta = document.getElementById('suiteModalCta');
  cta.textContent = t.cta;
  cta.classList.remove('sent');
  cta.disabled = false;
  document.getElementById('suiteModal').classList.add('active');
}

function closeSuiteModal() {
  document.getElementById('suiteModal').classList.remove('active');
}

function suiteModalAction() {
  // Cosmetic for now — registers the "yell" in-UI but doesn't send anywhere yet.
  const cta = document.getElementById('suiteModalCta');
  cta.textContent = 'YELL HEARD.';
  cta.classList.add('sent');
  cta.disabled = true;
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSuiteModal(); });

// TABS — gone with the one box (Oct 2026). Kept as a no-op for old callers.
function switchTab() {}

// FILE HANDLING
function handleDragOver(e) { e.preventDefault(); document.getElementById('dropZone').classList.add('drag-over'); }
function handleDragLeave() { document.getElementById('dropZone').classList.remove('drag-over'); }
function handleDrop(e) { e.preventDefault(); document.getElementById('dropZone').classList.remove('drag-over'); uploadFiles(Array.from(e.dataTransfer.files)); }
function handleFileSelect(e) { uploadFiles(Array.from(e.target.files)); e.target.value = ''; }

// The server's guard (guard.py) sends a code with its own words for the
// hourly cap, the daily close and too-much-material. Show those as sent.
function limitLine(data) {
  return (data && data.code && data.error) ? data.error : null;
}

async function uploadFiles(files) {
  const allowed = files.filter(f => /\.(pdf|docx?)$/i.test(f.name));
  if (allowed.length < files.length) frSay("I can't read that one. Try a PDF or Word doc.");
  if (!allowed.length) return;
  for (const file of allowed) {
    if (uploadedFiles.find(f => f.filename === file.name)) continue;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/upload', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.success) {
        const item = { filename: data.filename, text: data.text, size: file.size };
        uploadedFiles.push(item);
        renderFileList();
        await labelItem(item);
      }
      else frSay(data.error || 'Something went wrong.');
    } catch { frSay('Doh, I dropped that on the way. Try again.'); }
  }
  afterFilesChanged();
}

async function fetchWeblink() {
  const input = document.getElementById('weblinkInput');
  const btn = document.getElementById('weblinkBtn');
  const url = input.value.trim();
  if (!url) return;
  btn.disabled = true; btn.textContent = '...';
  try {
    const res = await fetch('/api/fetch', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({url}) });
    const data = await res.json();
    if (data.success) {
      if (!uploadedFiles.find(f => f.filename === data.filename)) uploadedFiles.push({ filename: data.filename, text: data.text, size: data.text.length, kind: 'web', label: 'WEBSITE' });
      input.value = '';
      afterFilesChanged();
    } else frSay(limitLine(data) || "Can't find any words in that file.");
  } catch { frSay("Couldn't read that page. Can you paste it instead?"); }
  btn.disabled = false; btn.textContent = 'Fetch';
}

async function addNotes() {
  const textarea = document.getElementById('notesInput');
  const text = textarea.value.trim();
  if (!text) return;
  notesCounter++;
  const btn = document.querySelector('.notes-add-btn');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }

  // Get a two-word label from Claude
  let label = 'EXAMPLES';
  try {
    const res = await fetch('/api/summarise', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ text })
    });
    const data = await res.json();
    if (data.success && PILE[data.label]) label = data.label;
  } catch { /* fallback label is fine */ }

  uploadedFiles.push({ filename: `Notes ${notesCounter}`, text, size: text.length, label });
  textarea.value = '';
  if (btn) { btn.disabled = false; btn.textContent = 'Add these notes'; }
  afterFilesChanged();
}

function removeFile(filename) {
  uploadedFiles = uploadedFiles.filter(f => f.filename !== filename);
  renderFileList();
  if (!uploadedFiles.length) {
    document.getElementById('consultZone').style.display = 'none';
    document.getElementById('goWrap').style.display = 'none';
    document.getElementById('goBtn').disabled = true;
    consultHistory = []; dotReady = false; exchangeCount = 0;
    invalidateSenseCheckPrefetch();
    resetHistoryUI();
    document.getElementById('dotOpening').style.display = 'flex';
    updateBounceCount();
    frOpen(1);
  }
}

function afterFilesChanged() {
  invalidateSenseCheckPrefetch();  // material changed — warmed checks no longer match
  rulesLooked = false;             // new material may hold new rules
  renderFileList();
  if (uploadedFiles.length > 0 && consultHistory.length === 0) {
    startConsultation();
  } else if (uploadedFiles.length > 0) {
    updateGoBtn();
    showSoaking();
    // Inject a nudge so Dot knows new material arrived
    consultHistory.push({
      role: 'user',
      content: 'More material just landed. Give whatever is new a soft, brief nod by name -- not a full recap -- and carry on.'
    });
    setTimeout(async () => {
      document.getElementById('responseArea').innerHTML = '';
      await runConsult();
    }, 1200);
  }
}

function showSoaking() {
  document.getElementById('consultZone').style.display = 'flex';
  document.getElementById('dotOpening').style.display = 'none';
  document.getElementById('responseArea').innerHTML = '';
  // Show soaking bubble
  document.getElementById('dotThinking').style.display = 'none';
  const el = document.getElementById('dotMsgText');
  el.style.display = 'block';
  el.innerHTML = 'Soaking up your stuff <span class="inline-dots"><span></span><span></span><span></span></span>';
  // Re-trigger animation
  const bubble = document.getElementById('dotBubble');
  bubble.style.animation = 'none';
  bubble.offsetHeight;
  bubble.style.animation = 'fadeUp 0.3s ease';
}

const FR_ICON = {
  pdf: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/><path d="M10 14h5M10 17h5"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/><path d="M10 12h6M10 15h6M10 18h4"/></svg>',
  web: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>',
  note: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 5h14M5 10h14M5 15h9"/></svg>',
};

function renderFileList() {
  const list = document.getElementById('fileList');
  const n = uploadedFiles.length;
  const stated = uploadedFiles.filter(f => PILE[f.label] === 'STATED').length;
  const shown = uploadedFiles.filter(f => PILE[f.label] === 'SHOWN').length;
  const sum = document.getElementById('stop1Sum');
  if (!sum.dataset.empty) sum.dataset.empty = sum.textContent;
  sum.textContent = n ? WORDS.dumpSum(n, stated, shown) : sum.dataset.empty;
  document.getElementById('stop1').classList.toggle('done', n > 0);
  if (!n) { list.innerHTML = ''; return; }
  list.innerHTML = uploadedFiles.map((f, i) => {
    const icon = f.kind === 'web' ? FR_ICON.web
      : /\.pdf$/i.test(f.filename) ? FR_ICON.pdf
      : /\.docx?$/i.test(f.filename) ? FR_ICON.doc : FR_ICON.note;
    const type = PILE[f.label] ? f.label : '';
    const pile = type ? PILE[type] : '';
    const tag = type
      ? `<span class="fr-pile">${pile}</span><span class="fr-type ${pile === 'SHOWN' ? 'shown' : ''}">${type}</span>`
      : `<span class="fr-type wait">${escHtml(WORDS.sorting)}</span>`;
    return `<div class="fr-file"><span class="fr-file-n">${icon}<span>${escHtml(f.filename)}</span></span>` +
      `<span class="fr-file-r">${tag}<button class="b-quiet x" type="button" aria-label="Remove ${escHtml(f.filename)}" onclick="removeFileAt(${i})">&times;</button></span></div>`;
  }).join('');
}
function removeFileAt(i) { const f = uploadedFiles[i]; if (f) removeFile(f.filename); }

function updateGoBtn() {
  document.getElementById('goBtn').disabled = false;
  document.getElementById('goWrap').style.display = 'flex';
}

// CONSULTATION
async function startConsultation() {
  frOpen(2);
  // Hide the opening bubble — Dot is now in the consult zone
  document.getElementById('dotOpening').style.display = 'none';
  document.getElementById('consultZone').style.display = 'flex';
  document.getElementById('goWrap').style.display = 'flex';
  updateGoBtn();
  showDotThinking();
  await runConsult();
}

async function runConsult() {
  showDotThinking();
  try {
    const res = await fetch('/api/consult', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        files: materialPayload(),
        history: consultHistory
      })
    });
    const data = await res.json();
    if (!data.success) {
      showDotMessage(limitLine(data) || "Hmm, that one didn't come through. Give it another go?");
      renderResponseArea();
      return;
    }

    consultHistory.push({ role: 'assistant', content: data.message });
    showDotMessage(data.message);
    updateBounceCount();
    dotReady = data.ready;
    invalidateSenseCheckPrefetch();  // conversation just changed — any warmed checks are stale

    if (dotReady) {
      document.getElementById('goBtn').classList.add('ready');
      document.getElementById('responseArea').innerHTML = '';
      prefetchSenseChecks();  // warm the confirm call now, so it's ready by the time they hit Let's Go
    } else {
      document.getElementById('goBtn').classList.remove('ready');
      renderResponseArea();
    }
  } catch {
    showDotMessage("Hmm, that one didn't come through. Give it another go?");
    renderResponseArea();
  }
}

function showDotThinking() {
  document.getElementById('dotThinking').style.display = 'flex';
  document.getElementById('dotMsgText').style.display = 'none';
}

function showDotMessage(text) {
  document.getElementById('dotThinking').style.display = 'none';
  const el = document.getElementById('dotMsgText');
  el.style.display = 'block';
  el.textContent = text;
  // Re-trigger animation
  const bubble = document.getElementById('dotBubble');
  bubble.style.animation = 'none';
  bubble.offsetHeight;
  bubble.style.animation = 'fadeUp 0.3s ease';
}

function renderResponseArea() {
  const area = document.getElementById('responseArea');
  area.innerHTML = `<div class="reply-row">
    <input class="reply-input" type="text" id="replyInput" placeholder="Type your reply..." />
    <button class="reply-send" id="replySend">Send</button>
  </div>`;
  const input = document.getElementById('replyInput');
  const send = document.getElementById('replySend');
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) submitResponse(); });
  send.addEventListener('click', submitResponse);
  setTimeout(() => input.focus(), 100);
}

async function submitResponse() {
  const input = document.getElementById('replyInput');
  const userReply = input ? input.value.trim() : '';
  if (!userReply) return;

  const dotMsg = document.getElementById('dotMsgText').textContent;
  consultHistory.push({ role: 'user', content: userReply });
  exchangeCount++;
  archiveExchange(dotMsg, userReply);
  document.getElementById('responseArea').innerHTML = '';
  await runConsult();
}

function archiveExchange(dotMsg, userMsg) {
  const hist = document.getElementById('historyFull');
  const dDiv = document.createElement('div');
  dDiv.className = 'history-dot-msg';
  dDiv.textContent = dotMsg;
  const uDiv = document.createElement('div');
  uDiv.className = 'history-user-msg';
  uDiv.textContent = userMsg;
  hist.appendChild(dDiv);
  hist.appendChild(uDiv);

  // Show/update the toggle
  const toggle = document.getElementById('historyToggle');
  toggle.style.display = 'flex';
  document.getElementById('historyLabel').textContent = `Stuff we've covered (${exchangeCount})`;
}

function toggleHistory() {
  historyOpen = !historyOpen;
  document.getElementById('historyFull').classList.toggle('open', historyOpen);
  document.getElementById('historyToggle').classList.toggle('open', historyOpen);
}

function resetHistoryUI() {
  document.getElementById('historyFull').innerHTML = '';
  document.getElementById('historyToggle').style.display = 'none';
  document.getElementById('historyToggle').classList.remove('open');
  document.getElementById('historyFull').classList.remove('open');
  exchangeCount = 0; historyOpen = false;
}

