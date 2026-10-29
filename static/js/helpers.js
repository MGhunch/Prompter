/* Prompter — helpers.js. Shared bits: errors, the thinking beats, escaping, the prompt, the PDF.
   Plain scripts sharing one page; index.html loads them in order:
   words, helpers, feed, fix, shape. */
// HELPERS
let stepTimer = null;
function animateSteps() {
  const steps = ['step1','step2','step3','step4','step5'];
  const labels = ['READING','LISTENING','WRITING','EXAMPLES','LOCKING'];
  const STEP_MS = 1500;  // pace of each beat — tweak here
  let i = 0;
  clearInterval(stepTimer);
  // Resolves once the final beat is lit. The last step stays active (pulsing)
  // until the reveal, so a slow API reads as "still working", not frozen.
  return new Promise(resolve => {
    stepTimer = setInterval(() => {
      if (i > 0) {
        document.getElementById(steps[i-1]).classList.remove('active');
        document.getElementById(steps[i-1]).classList.add('done');
      }
      document.getElementById(steps[i]).classList.add('active');
      document.getElementById('thinkingLabel').textContent = labels[i];
      if (i === steps.length - 1) { clearInterval(stepTimer); stepTimer = null; resolve(); return; }
      i++;
    }, STEP_MS);
  });
}

function showError(msg) { document.getElementById('errorMsg').textContent = msg; }

function escHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function copyProfile() {
  if (!profileData) return;
  const p = profileData; const bn = p.brandName || 'Brand';
  let text = `${bn.toUpperCase()} — BRAND PROFILE\n\nBRAND\n${p.brand}${threeWordSentence(p)}\n\n`;
  text += `WHO WE ARE\n${p.behaviours.map(b=>`We are: ${b.we} / We are not: ${b.not}`).join('\n')}\n\n`;
  text += `EXAMPLES\n${p.examples.map(e=>`More: ${e.more} / Less: ${e.less}`).join('\n')}\n\n`;
  text += `HOUSE RULES\n${p.houseRules.map(r=>`${r.key}: ${r.rule}`).join('\n')}`;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('copyBtn'); btn.textContent = 'Copied ✓'; btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy profile'; btn.classList.remove('copied'); }, 2000);
  });
}

function threeWordSentence(p) {
  if (!p || !p.descriptors || !p.descriptors.length) return '';
  const bn = p.brandName || 'The brand';
  const ws = p.descriptors.map(w => String(w).toLowerCase());
  const list = ws.length > 1 ? ws.slice(0, -1).join(', ') + ' and ' + ws[ws.length - 1] : ws[0];
  return ` ${bn} is ${list}.`;
}

function buildPromptMd() {
  if (!profileData) return '';
  const p = profileData; const bn = p.brandName || 'this brand';
  let md = `You are crafting communications for **${bn}**. Your job is to write in their voice.`;
  if (p.descriptors && p.descriptors.length) md += ` Think, ${p.descriptors.join(', ')}.`;
  md += `\n\n---\n\n`;
  md += `## Brand\n\n${p.brand}\n\n`;
  md += `## Who we are\n\n${p.behaviours.map(b=>`- **Are:** ${b.we}  \n  **Are not:** ${b.not}`).join('\n')}\n\n`;
  md += `## Write more like this\n\n${p.examples.map(e=>`- ✓ ${e.more}  \n  ✗ ${e.less}`).join('\n')}\n\n`;
  md += `## House rules\n\n${p.houseRules.map(r=>`- **${r.key}:** ${r.rule}`).join('\n')}\n\n---\n\nNow write like this. Every time. No exceptions.`;
  return md;
}

function downloadMd() {
  const md = buildPromptMd(); if (!md) return;
  const bn = (profileData && profileData.brandName) || 'brand';
  const blob = new Blob([md], {type:'text/markdown'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url;
  a.download = bn.toLowerCase().replace(/\s+/g,'-') + '-voice-prompt.md';
  a.click(); URL.revokeObjectURL(url);
}

async function downloadPdf() {
  if (!profileData || typeof html2pdf === 'undefined') return;
  const src = document.querySelector('.profile-zone');
  if (!src) return;
  const btn = document.getElementById('pdfBtn');

  // Clone the profile and strip the interactive controls from the capture
  const clone = src.cloneNode(true);
  clone.querySelectorAll('.profile-actions, .start-again, [data-noexport]').forEach(el => el.remove());
  // Render on white with breathing room so it reads as a document, not a screenshot
  const wrap = document.createElement('div');
  wrap.style.cssText = 'background:#fff;padding:28px 32px;width:760px;';
  wrap.appendChild(clone);
  // Hunch AI2 logo at the foot of the PDF
  const pdfLogo = document.createElement('div');
  pdfLogo.style.cssText = 'text-align:center;margin-top:26px;padding-top:18px;border-top:0.5px solid #E8E5E0;';
  pdfLogo.innerHTML = '<img src="images/ai2-logo.png" style="height:32px;opacity:0.9;" />';
  wrap.appendChild(pdfLogo);

  const bn = (profileData.brandName || 'brand').toLowerCase().replace(/\s+/g,'-');
  if (btn) { btn.disabled = true; }
  try {
    await html2pdf().set({
      margin: [8, 8, 8, 8],
      filename: bn + '-voice-profile.pdf',
      image: { type: 'jpeg', quality: 0.98 },
      html2canvas: { scale: 2, backgroundColor: '#ffffff', useCORS: true },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
      pagebreak: { mode: ['css', 'legacy'], avoid: '.psec' }
    }).from(wrap).save();
  } catch (e) {
    console.error('[Prompter] PDF error:', e);
    showError('Could not build the PDF. Try again.');
  } finally {
    if (btn) { btn.disabled = false; }
  }
}

function copyPrompt() {
  const md = buildPromptMd(); if (!md) return;
  navigator.clipboard.writeText(md).then(() => {
    const btn = document.getElementById('copyPromptBtn'); btn.textContent = 'Copied ✓'; btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy prompt'; btn.classList.remove('copied'); }, 2000);
  });
}


// ── SENSE CHECK SCREEN ───────────────────────────────────

