(function (global) {
  'use strict';

  const RENDERERS = {
    wipe: 'generic-wipe',
    avoidable: 'generic-avoidable',
    interrupts: 'generic-interrupts',
    dispels: 'generic-dispels',
    mistakes: 'mistake-tracker',
    verdict: 'mistake-verdict',
    replay: 'field-audit',
  };

  function hasRows(value) {
    if (Array.isArray(value)) return value.length > 0;
    if (value && typeof value === 'object') return Object.values(value).some(hasRows);
    return value !== null && value !== undefined && value !== false;
  }

  function capability(enabled, renderer) {
    return { enabled: Boolean(enabled), renderer };
  }

  function hasFieldAudit(data) {
    return (data.page1_wipeAnalysis || []).some(
      fight => Boolean(fight?.crownOfTheCosmos?.fieldAudit),
    );
  }

  function resolveAnalysisCapabilities(payload) {
    const meta = payload?.meta || {};
    const data = payload?.data || {};
    const features = meta.features || {};
    const hasMistakes = hasRows(data.page3_courtBoard)
      || hasRows(data.page4_finalVerdict)
      || features.finalVerdict === true;
    const hasAvoidable = hasRows(data.page2_avoidableBoard)
      || hasRows(data.page2_glaiveBoard);
    const dispelAnalysis = data.page3_dispelAnalysis;
    const hasDispels = features.dispels === true
      || Boolean(
        dispelAnalysis
        && dispelAnalysis.enabled !== false
        && hasRows(dispelAnalysis.fights || dispelAnalysis.summary),
      );
    const hasInterrupts = Object.prototype.hasOwnProperty.call(features, 'interrupts')
      ? features.interrupts !== false
      : meta.bossKey === 'midnight_falls'
        || hasRows(data.page3_interruptAnalysis)
        || hasRows(data.page2_interruptBoard);

    const resolved = {
      wipe: capability(Object.prototype.hasOwnProperty.call(data, 'page1_wipeAnalysis'), RENDERERS.wipe),
      avoidable: capability(hasAvoidable || hasMistakes, hasMistakes ? RENDERERS.mistakes : RENDERERS.avoidable),
      interrupts: capability(hasInterrupts, RENDERERS.interrupts),
      dispels: capability(hasDispels, RENDERERS.dispels),
      mistakes: capability(hasMistakes, RENDERERS.mistakes),
      verdict: capability(
        hasMistakes && (
          Object.prototype.hasOwnProperty.call(data, 'page4_finalVerdict')
          || features.finalVerdict === true
        ),
        RENDERERS.verdict,
      ),
      replay: capability(hasFieldAudit(data), RENDERERS.replay),
    };

    Object.entries(meta.capabilities || {}).forEach(([key, value]) => {
      if (typeof value === 'boolean') {
        resolved[key] = capability(value, RENDERERS[key] || key);
        return;
      }
      if (value && typeof value === 'object') {
        resolved[key] = {
          ...(resolved[key] || capability(false, RENDERERS[key] || key)),
          ...value,
          enabled: Boolean(value.enabled),
        };
      }
    });
    return resolved;
  }

  function resolveMistakeTracker(payload, capabilities) {
    const meta = payload?.meta || {};
    const courtConfig = meta.courtConfig || {};
    const explicit = meta.mistakeTracker || {};
    return {
      schemaVersion: 1,
      enabled: Boolean(capabilities?.mistakes?.enabled),
      pointsPerUnit: Number(courtConfig.verdictPointsPerCount ?? 10),
      roleMultipliers: {
        tank: Number(courtConfig.verdictTankMultiplier ?? 1),
      },
      definitions: [],
      ...explicit,
    };
  }

  global.AnalysisCapabilities = {
    resolve: resolveAnalysisCapabilities,
    resolveMistakeTracker,
  };
})(window);
