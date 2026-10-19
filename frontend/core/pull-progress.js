/* WCL fightPercentage is encounter-wide remaining progress, including phases. */
((global) => {
  function phaseCode(pull) {
    const code = String(pull.phaseCode || pull.wipePhase || pull.fightPhase || '').match(/\bP\d+(?:\.\d+)?\b/i);
    return code ? code[0].toUpperCase() : '';
  }
  function completion(pull) {
    if (pull.isKill) return 100;
    const multiPhase = new Set((pull.phaseTimeline || []).filter(p => !['wipe','kill'].includes(p.key)).map(p => p.key)).size > 1
      || /P(?:[2-9]|1\.)/i.test(phaseCode(pull));
    const remaining = pull.fightPercentage ?? (multiPhase ? null : pull.bossPercentage);
    if (remaining == null || remaining === '') return null;
    const value = Number(remaining);
    return Number.isFinite(value) ? Math.max(0, Math.min(100, 100-value)) : null;
  }
  function color(pull) {
    const progress = completion(pull);
    return progress>=99?'#e268a8':progress>=95?'#ff8000':progress>=75?'#a335ee':progress>=50?'#0070ff':progress>=25?'#1eff00':'#999999';
  }
  global.MythicPullProgress = {phaseCode, completion, color};
})(window);
