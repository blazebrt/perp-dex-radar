/* Read-only paper ledger. Current policy is never substituted for entry-time authority. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.PERFORMANCE = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const esc = x => String(x == null ? 'unknown' : x).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = x => typeof x === 'number' && Number.isFinite(x);
  const rtext = x => num(x) ? x.toFixed(3) + ' R' : 'unavailable';
  const utc = x => Number.isSafeInteger(x) && x > 0 && x < 8640000000000 ? new Date(x * 1000).toISOString().replace('T', ' ').slice(0,19) : 'unknown';
  function model(decision, journal) {
    if (!decision || decision.schema !== 'v8.decision/1' || !Number.isSafeInteger(decision.as_of) ||
        !journal || !Array.isArray(journal.open) || !Array.isArray(journal.closed)) throw Error('Invalid ledger inputs');
    const records = [], ids = new Set();
    for (const state of ['open', 'closed']) for (const tr of journal[state]) {
      if (!tr || typeof tr !== 'object' || Array.isArray(tr)) throw Error('Invalid journal row');
      if (tr.id != null) {
        const id = JSON.stringify(tr.id);
        if (ids.has(id)) throw Error('Duplicate journal identity');
        ids.add(id);
      }
      records.push({id:tr.id, coin:tr.c, strategy:tr.s, side:tr.d === 1 ? 'long' : tr.d === -1 ? 'short' : 'unknown',
        state, entered:tr.t_in, exited:tr.t_out, reportedR:state === 'closed' && num(tr.r) ? tr.r : null,
        execution:(tr.execution || {}).state || 'unknown', entryTier:'unrecorded'});
    }
    records.sort((a,b) => (num(b.exited) ? b.exited : num(b.entered) ? b.entered : 0) -
                         (num(a.exited) ? a.exited : num(a.entered) ? a.entered : 0));
    const tiers = decision.strategy_tiers || {}, expectations = [];
    for (const tier of ['FULL', 'PROBATION']) for (const row of Array.isArray(tiers[tier]) ? tiers[tier] : []) {
      if (!row || typeof row !== 'object') continue;
      const sides = row.sides && typeof row.sides === 'object' ? row.sides : {};
      if (!Object.keys(sides).length) expectations.push({tier, strategy:row.strategy, side:'unspecified', expectation:{}, forward:{}, state:'unavailable'});
      for (const side of Object.keys(sides).sort()) {
        const s = sides[side] || {};
        expectations.push({tier, strategy:row.strategy, side, expectation:s.expectation || {}, forward:s.forward_test || {}, state:s.forward_test_state || 'unavailable'});
      }
    }
    return {asOf:decision.as_of, validUntil:decision.valid_until, records, expectations,
      open:journal.open.length, closed:journal.closed.length};
  }
  async function verify(bytes, ref, path) {
    if (!ref || ref.path !== path || !Number.isSafeInteger(ref.bytes) || ref.bytes !== bytes.byteLength ||
        typeof ref.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(ref.sha256)) throw Error('Missing or inconsistent file binding');
    const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
    const hex = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,'0')).join('');
    if (hex !== ref.sha256) throw Error('Snapshot files changed between requests; reload to obtain one consistent scan');
  }
  async function load(D) {
    const read = async path => {
      const response = await fetch(path, {cache:'no-cache'});
      if (!response.ok) throw Error('Ledger source unavailable');
      return response.arrayBuffer();
    };
    const [decisionBytes, journalBytes, auditResult] = await Promise.all([
      read('data/v8/decision.json'), read('data/quant_journal.json'), D.loadAudit()]);
    if (auditResult.status !== 'OK' || !auditResult.data) throw Error('Audit binding unavailable');
    const audit = auditResult.data, refs = audit.legacy_output_refs;
    if (!Array.isArray(refs)) throw Error('Journal binding unavailable');
    const matches = refs.filter(r => r && r.path === 'data/quant_journal.json');
    if (matches.length !== 1) throw Error('Ambiguous journal binding');
    await Promise.all([verify(decisionBytes, ((audit.manifest || {}).decision || {}).file, 'data/v8/decision.json'),
      verify(journalBytes, matches[0], 'data/quant_journal.json')]);
    const decode = bytes => JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes));
    const decision = decode(decisionBytes), validity = D.authority(decision, Math.floor(Date.now()/1000));
    if (!['AVAILABLE','STALE'].includes(validity.status)) throw Error('Invalid decision snapshot');
    return model(decision, decode(journalBytes));
  }
  function render(data, filter={}, now=Math.floor(Date.now()/1000)) {
    let h = '<p class="note">Snapshot ' + esc(utc(data.asOf)) + (num(data.validUntil) && now > data.validUntil ? ' — stale; historical display only' : '') + '. Paper records, not exchange-account results.</p>';
    h += '<h2>Current authority and registered expectations</h2><p class="note">Current tiers are shown only as current policy. They do not establish a historical trade’s tier or authorization. Archive intervals describe historical research, not a forecast interval for live returns.</p>';
    for (const tier of ['FULL','PROBATION']) {
      const rows = data.expectations.filter(r => r.tier === tier);
      h += '<h3>' + (tier === 'FULL' ? 'Full authority' : 'Probation') + '</h3>';
      if (!rows.length) h += '<p>No side is reported in this tier in this decision. This is not a claim of zero historical trades.</p>';
      for (const row of rows) {
        const e = row.expectation, f = row.forward;
        h += '<section class="tile"><h4>' + esc(row.strategy) + ' · ' + esc(row.side) + '</h4><p>Archive out-of-sample mean: ' + esc(rtext(e.out_of_sample_mean_R)) +
          '; 95% interval: ' + esc(rtext(e.out_of_sample_lower_95)) + ' to ' + esc(rtext(e.out_of_sample_upper_95)) + '.</p><p>Registered forward-test diagnostic: ' +
          esc(Number.isSafeInteger(f.closed) && f.closed >= 0 ? f.closed : 'unknown') + ' closed; mean ' + esc(rtext(f.mean_R)) + '; state ' + esc(row.state) +
          '.</p><p class="note">Experiment ' + esc(f.experiment_id) + '; effective ' + esc(utc(f.effective_from)) + '. The engine’s diagnostic may include unqualified paper outcomes; it is not independently verified live performance.</p></section>';
      }
    }
    const records = data.records.filter(r => (!filter.strategy || r.strategy === filter.strategy) && (!filter.state || r.state === filter.state));
    h += '<h2>Retained paper journal</h2><p>' + data.open + ' open and ' + data.closed + ' closed records retained; showing ' + records.length + '.</p>' +
      '<p class="note">The journal prunes old closed records; this is not a complete lifetime ledger. Entry-time authority tier is unrecorded and is never inferred from current policy. Reported R is the journal value, not a claim of qualified net performance. Missing R remains unavailable; open trades have no realized R here.</p>';
    h += '<div style="overflow:auto"><table><thead><tr><th>ID</th><th>Coin</th><th>Strategy</th><th>Side</th><th>State</th><th>Entry UTC</th><th>Exit UTC</th><th>Reported R</th><th>Execution evidence</th><th>Entry tier</th></tr></thead><tbody>';
    for (const r of records) h += '<tr>' + [r.id,r.coin,r.strategy,r.side,r.state,utc(r.entered),utc(r.exited),rtext(r.reportedR),r.execution,r.entryTier].map(v=>'<td>'+esc(v)+'</td>').join('') + '</tr>';
    return h + '</tbody></table></div>';
  }
  return {model, verify, load, render};
});
