/* Prompter — shape.js. SHAPE IT: the sliders, the feeling, and building the profile.
   Plain scripts sharing one page; index.html loads them in order:
   words, helpers, feed, fix, shape. */
let confirmChecks = [];
let confirmResults = [];
let currentCheck = 0;
let checkMoved = false;
let senseCheckPrefetch = null;  // Promise resolving to checks[], warmed when Dot signals ready

// Single source for the confirm request — used by both the prefetch and the live fallback.
async function requestSenseChecks() {
  const res = await fetch('/api/confirm', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      files: materialPayload(),
      history: consultHistory
    })
  });
  const data = await res.json();
  if (!data.success || !data.checks || !data.checks.length) {
    const err = new Error('No checks');
    err.line = limitLine(data);
    throw err;
  }
  return data.checks;
}

// Fire the confirm call in the background while the user reads Dot's last line.
// Errors resolve to null so a failed prefetch quietly falls back to a live fetch.
function prefetchSenseChecks() {
  senseCheckPrefetch = requestSenseChecks().catch(() => null);
}

// Any change to the material or the conversation makes a warmed prefetch stale.
function invalidateSenseCheckPrefetch() {
  senseCheckPrefetch = null;
}

function goButtonPressed() {
  document.getElementById('goBtn').disabled = true;
  showError('');
  // Show sense check screen in loading state
  document.getElementById('sensecheckScreen').classList.add('active');
  document.getElementById('scLoading').style.display = 'flex';
  startScLoadingLines();
  fetchSenseChecks();
}

// Mostly genuine progress, with the odd gag for contrast. The joke only
// lands next to a straight line. Dots bounce on the final line.
const SC_LOADING_LINES = ['Reading your inputs…', 'Finding my glasses…', 'Checking the detail…', 'Sorting my thoughts…', 'Almost there…'];
let scLineTimer = null;
function setScDotsBounce(on) {
  const d = document.getElementById('scDots');
  if (d) d.classList.toggle('bounce', on);
}
function startScLoadingLines() {
  const el = document.getElementById('scLoadingLine');
  if (!el) return;
  const last = SC_LOADING_LINES.length - 1;
  let i = 0;
  el.textContent = SC_LOADING_LINES[0];
  el.style.opacity = '1';
  setScDotsBounce(false);
  clearInterval(scLineTimer);
  scLineTimer = setInterval(() => {
    i = (i + 1) % SC_LOADING_LINES.length;
    el.style.opacity = '0';
    setTimeout(() => {
      el.textContent = SC_LOADING_LINES[i];
      el.style.opacity = '1';
      setScDotsBounce(i === last);
    }, 200);
  }, 1100);
}
function stopScLoadingLines() {
  clearInterval(scLineTimer); scLineTimer = null;
  setScDotsBounce(false);
}

async function fetchSenseChecks() {
  try {
    // Use the warmed prefetch if we have one: it resolves to the checks, to
    // null if the prefetch failed, or is simply awaited if still in flight.
    // Fall back to a live request when there's nothing warmed.
    let checks = senseCheckPrefetch ? await senseCheckPrefetch : null;
    if (!checks) checks = await requestSenseChecks();
    confirmChecks = checks;
    confirmResults = [];
    currentCheck = 0;
    renderSenseCheck(0);
  } catch (e) {
    // The sliders are the heart of it -- never skip them. Say so, and let
    // them press Let's go again.
    hideSenseCheckScreen();
    showError((e && e.line) || "Something's glitchy, please try again.");
    document.getElementById('goBtn').disabled = false;
  } finally {
    senseCheckPrefetch = null;  // consumed — re-warmed on the next ready
  }
}

const SC_RETRY_LABEL = "Neither's quite me — let me try again";

function renderSenseCheck(idx) {
  stopScLoadingLines();
  const inner = document.getElementById('scInner');
  const check = confirmChecks[idx];
  checkMoved = false;

  const isLast = idx === confirmChecks.length - 1;
  const nextLabel = isLast ? 'Build my profile' : 'Next';
  const pips = confirmChecks.map((_,i) => `<div class="sc-pip${i===idx?' on':''}"></div>`).join('');

  const eyebrow = `
    <div class="sc-eyebrow">
      <div class="sc-label">Quick sense check</div>
      <div class="sc-progress">${pips}</div>
    </div>`;

  let cardBody = '';

  if (check.type === 'boundary') {
    cardBody = `
      <div class="sc-boundary">
        <div class="sc-boundary-stem">We're <strong>${escHtml(check.trait)}</strong>, but not...</div>
        <div class="sc-options">
          ${check.options.map((opt, i) => `
            <div class="sc-option" id="scOpt${i}" onclick="selectBoundary(${i})">${escHtml(opt)}</div>
          `).join('')}
        </div>
      </div>`;

  } else if (check.type === 'sentence') {
    cardBody = `
      <div class="sc-question" id="scQuestion">Which sounds more like you?</div>
      <div class="sc-pair">
        <div class="sc-sent" id="scSentA">
          <div class="sc-sent-lbl">A</div>
          <p>${escHtml(check.sentenceA)}</p>
        </div>
        <div class="sc-sent" id="scSentB">
          <div class="sc-sent-lbl">B</div>
          <p>${escHtml(check.sentenceB)}</p>
        </div>
      </div>
      <div class="sc-slider-wrap">
        <div class="sc-track"><div class="sc-fill" id="scFill"></div></div>
        <input class="sc-range" type="range" min="0" max="100" value="50" step="1"
          id="scSlider" oninput="updateSenseCheck(this.value)"/>
      </div>
      <div class="sc-retry-wrap">
        <span class="sc-retry" id="scRetry" onclick="regenerateSentence()">${SC_RETRY_LABEL}</span>
      </div>`;

  } else if (check.type === 'feeling') {
    cardBody = `
      <div class="sc-feeling">
        <div class="sc-feeling-stem">When people read our stuff they should feel... <em>pick one</em></div>
        <div class="sc-options">
          ${check.options.map((opt, i) => `
            <div class="sc-option" id="scOpt${i}" onclick="selectFeeling(${i})">${escHtml(opt)}</div>
          `).join('')}
        </div>
      </div>`;
  }

  inner.innerHTML = `
    ${eyebrow}
    <div class="sc-card">
      ${cardBody}
      <div class="sc-actions">
        <button class="btn-ghost" onclick="skipSenseCheck()" style="color:var(--white-mid);">Skip</button>
        <button class="btn-primary" id="scNextBtn" onclick="nextSenseCheck()" ${check.type !== 'sentence' ? 'disabled' : ''}>${nextLabel}</button>
      </div>
    </div>`;
}

let selectedBoundary = null;
let selectedFeeling = null;

function selectBoundary(idx) {
  selectedBoundary = idx;
  document.querySelectorAll('.sc-option').forEach((el, i) => {
    el.classList.toggle('selected', i === idx);
  });
  document.getElementById('scNextBtn').disabled = false;
}

function selectFeeling(idx) {
  selectedFeeling = idx;
  document.querySelectorAll('.sc-option').forEach((el, i) => {
    el.classList.toggle('selected', i === idx);
  });
  document.getElementById('scNextBtn').disabled = false;
}

function updateSenseCheck(v) {
  v = parseInt(v);
  const a = document.getElementById('scSentA');
  const b = document.getElementById('scSentB');
  const q = document.getElementById('scQuestion');
  const fill = document.getElementById('scFill');
  const check = confirmChecks[currentCheck];

  fill.style.width = v + '%';
  a.classList.remove('leaning-a', 'dim');
  b.classList.remove('leaning-b', 'dim');

  if (!checkMoved) {
    checkMoved = true;
    q.classList.add('fade');
    setTimeout(() => {
      q.classList.remove('fade');
      updateSenseCheckQuestion(v, check);
    }, 180);
    return;
  }
  updateSenseCheckQuestion(v, check);
  if (v < 38) { a.classList.add('leaning-a'); b.classList.add('dim'); }
  else if (v > 62) { b.classList.add('leaning-b'); a.classList.add('dim'); }
}

function updateSenseCheckQuestion(v, check) {
  const q = document.getElementById('scQuestion');
  if (!q) return;
  if (v < 38) q.innerHTML = `<strong>${escHtml(check.noteA)}</strong>`;
  else if (v > 62) q.innerHTML = `<strong>${escHtml(check.noteB)}</strong>`;
  else q.innerHTML = 'Which sounds more like you?';
}

function nextSenseCheck() {
  const check = confirmChecks[currentCheck];
  let result = { type: check.type, dimension: check.dimension };

  if (check.type === 'boundary') {
    result.trait = check.trait;
    result.options = check.options;
    result.selected = selectedBoundary;
    selectedBoundary = null;
  } else if (check.type === 'sentence') {
    const v = parseInt(document.getElementById('scSlider').value);
    result.sentenceA = check.sentenceA;
    result.sentenceB = check.sentenceB;
    result.value = v;
  } else if (check.type === 'feeling') {
    result.options = check.options;
    result.selected = selectedFeeling;
    selectedFeeling = null;
  }

  confirmResults.push(result);

  if (currentCheck < confirmChecks.length - 1) {
    currentCheck++;
    checkMoved = false;
    renderSenseCheck(currentCheck);
  } else {
    hideSenseCheckScreen();
    runExtractWithCalibration();
  }
}

function skipSenseCheck() {
  const check = confirmChecks[currentCheck];
  let result = { type: check.type, dimension: check.dimension, skipped: true };

  if (check.type === 'boundary') {
    result.trait = check.trait; result.options = check.options; result.selected = null;
    selectedBoundary = null;
  } else if (check.type === 'sentence') {
    result.sentenceA = check.sentenceA; result.sentenceB = check.sentenceB; result.value = 50;
  } else if (check.type === 'feeling') {
    result.options = check.options; result.selected = null;
    selectedFeeling = null;
  }

  confirmResults.push(result);
  currentCheck < confirmChecks.length - 1
    ? (currentCheck++, checkMoved = false, renderSenseCheck(currentCheck))
    : (hideSenseCheckScreen(), runExtractWithCalibration());
}

async function regenerateSentence() {
  const link = document.getElementById('scRetry');
  if (!link || link.classList.contains('busy')) return;
  const rejected = confirmChecks[currentCheck];
  link.classList.add('busy');
  link.innerHTML = 'Having another think<span class="inline-dots"><span></span><span></span><span></span></span>';
  const nextBtn = document.getElementById('scNextBtn');
  if (nextBtn) nextBtn.disabled = true;
  try {
    const res = await fetch('/api/confirm/regenerate', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        files: materialPayload(),
        history: consultHistory,
        reject: {
          dimension: rejected.dimension,
          sentenceA: rejected.sentenceA,
          sentenceB: rejected.sentenceB,
          noteA: rejected.noteA,
          noteB: rejected.noteB
        }
      })
    });
    const data = await res.json();
    if (!data.success || !data.check || data.check.type !== 'sentence') throw new Error('bad regen');
    confirmChecks[currentCheck] = data.check;
    checkMoved = false;
    renderSenseCheck(currentCheck);
  } catch (e) {
    link.classList.remove('busy');
    link.textContent = SC_RETRY_LABEL;
    if (nextBtn) nextBtn.disabled = false;
  }
}

function hideSenseCheckScreen() {
  stopScLoadingLines();
  document.getElementById('sensecheckScreen').classList.remove('active');
}

async function runExtractWithCalibration() {
  document.getElementById('mainPage').style.display = 'none';
  document.getElementById('pageFooter').style.display = 'none';
  document.getElementById('thinkingScreen').classList.add('active');
  const stepsDone = animateSteps();
  let line = null;

  try {
    const res = await fetch('/api/extract', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        files: materialPayload(),
        history: consultHistory,
        calibration: confirmResults,
        rules: houseRules.map(r => r.text)
      })
    });
    const data = await res.json();
    if (!data.success) { line = limitLine(data); throw new Error(data.error); }
    profileData = data.profile;
    renderProfileZone(profileData);

    await stepsDone;  // let all five beats land before revealing — whichever finishes last wins
    document.getElementById('thinkingScreen').classList.remove('active');
    document.getElementById('mainPage').style.display = 'flex';
    document.getElementById('pageFooter').style.display = 'block';
    document.getElementById('hero').style.display = 'none';
    document.getElementById('dotOpening').style.display = 'none';
    document.getElementById('inputZone').style.display = 'none';
    document.getElementById('consultZone').style.display = 'none';
    document.getElementById('goWrap').style.display = 'none';
    document.getElementById('feedRoom').style.display = 'none';
    document.getElementById('mainPage').classList.remove('feed');
    document.getElementById('profileZone').style.display = 'block';
  } catch {
    if (stepTimer) { clearInterval(stepTimer); stepTimer = null; }
    document.getElementById('thinkingScreen').classList.remove('active');
    document.getElementById('mainPage').style.display = 'flex';
    document.getElementById('pageFooter').style.display = 'block';
    showError(line || 'Something went wrong. Please try again.');
    document.getElementById('goBtn').disabled = false;
  }
}
