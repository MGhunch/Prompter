/* Prompter — words.js. The new interface lines, bracketed until Michael writes them.
   Plain scripts sharing one page; index.html loads them in order:
   words, helpers, feed, fix, shape. */
/* ---------- WELCOME + FEED IT (Oct 2026) ----------
   New interface words live here, in brackets until Michael writes them. */
const WORDS = {
  dumpSum:      (n, st, sh) => `[${n} in: ${st} stated, ${sh} shown]`,
  sorting:      '[SORTING…]',
  bounceCount:  n => `[${n} OF 3]`,
  rulesReading: '[Reading your stuff for rules…]',
  ruleFound:    '[FOUND]',
  rulesSum:     n => `[${n} rule${n === 1 ? '' : 's'} set]`,
};
