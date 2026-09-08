/* Generic controls for the schema provided by the selected Boss. */
window.AnalysisConfigForm = {
  create(container) {
    const drafts = new Map();
    let schema = [], identity = '';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const list = value => String(value || '').split(/[\s,，、;；]+/).filter(Boolean);
    const sections = () => [...container.querySelectorAll('[data-config-key]')];
    function read(section) {
      const input = section.querySelector('[data-config-input]');
      switch (section.dataset.configType) {
        case 'boolean': return input.checked;
        case 'number': return input.value === '' ? null : Number(input.value);
        case 'playerList': case 'textList': return list(input.value);
        case 'interruptGroups': return Object.fromEntries([...section.querySelectorAll('[data-group]')].map(node => [node.dataset.group, list(node.value)]));
        default: return input.value;
      }
    }
    function collect() { return Object.fromEntries(sections().map(section => [section.dataset.configKey, read(section)])); }
    function visibility() {
      const values = collect();
      const byKey = Object.fromEntries(sections().map(section => [section.dataset.configKey, section]));
      schema.forEach(field => {
        const condition = field.visibleWhen;
        if (!condition) return;
        const actual = values[condition.field];
        byKey[field.key].hidden = byKey[condition.field]?.hidden || ('equals' in condition ? actual !== condition.equals : actual === condition.notEquals);
      });
    }
    function setSchema(next, key) {
      if (identity) drafts.set(identity, collect());
      identity = key; schema = next || [];
      const saved = drafts.get(identity) || {};
      container.innerHTML = schema.map(field => {
        const value = saved[field.key] ?? field.default ?? (field.type === 'boolean' ? false : '');
        const label = esc(field.label || field.key);
        const help = field.description ? `<small class="muted">${esc(field.description)}</small>` : '';
        let control;
        if (field.type === 'boolean') {
          control = `<label><input data-config-input type="checkbox" ${value ? 'checked' : ''}> ${label}</label>${help}`;
        } else if (field.type === 'interruptGroups') {
          control = `<strong>${label}</strong>${help}` + (field.groups || []).map(group => `<label class="stack">${esc(group.label)}<input data-group="${esc(group.key)}" value="${esc((value[group.key] || []).join(' '))}" placeholder="玩家名，以空格分隔"></label>`).join('');
        } else {
          let input;
          if (field.type === 'select') {
            input = `<select data-config-input>${field.options.map(option => {const v = typeof option === 'object' ? option.value : option;return `<option value="${esc(v)}" ${String(value) === String(v) ? 'selected' : ''}>${esc(typeof option === 'object' ? option.label : option)}</option>`;}).join('')}</select>`;
          } else if (['playerList','textList'].includes(field.type)) {
            input = `<textarea data-config-input rows="2">${esc(Array.isArray(value) ? value.join(' ') : value)}</textarea>`;
          } else {
            input = `<input data-config-input type="${field.type === 'number' ? 'number' : 'text'}" value="${esc(value)}" ${['min','max','step'].filter(k => field[k] != null).map(k => `${k}="${esc(field[k])}"`).join(' ')}>`;
          }
          control = `<label class="stack">${label}${help}${input}</label>`;
        }
        return `<div class="config-field stack" data-config-key="${esc(field.key)}" data-config-type="${esc(field.type)}">${control}</div>`;
      }).join('');
      container.querySelectorAll('input,select,textarea').forEach(node => node.addEventListener('change', visibility));
      visibility();
    }
    return {setSchema, collect, validate:() => [...container.querySelectorAll('input,select,textarea')].every(node => node.closest('[hidden]') || node.reportValidity())};
  }
};
