/* Generic controls for the schema provided by the selected Boss. */
window.AnalysisConfigForm = {
  create(container) {
    const drafts = new Map();
    let schema = [], identity = '', roster = [];
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
    function setSchema(next, key, fightRoster = []) {
      if (identity) drafts.set(identity, collect());
      identity = key; schema = next || []; roster = fightRoster || [];
      const saved = drafts.get(identity) || {};
      container.innerHTML = schema.map(field => {
        const value = saved[field.key] ?? field.default ?? (field.type === 'boolean' ? false : '');
        const label = esc(field.label || field.key);
        const help = field.description ? `<small class="muted">${esc(field.description)}</small>` : '';
        let control;
        if (field.type === 'boolean') {
          control = `<label><input data-config-input type="checkbox" ${value ? 'checked' : ''}> ${label}</label>${help}`;
        } else if (field.type === 'interruptGroups') {
          for (const group of field.groups || []) {
            if (!group.migrateFrom) continue;
            if (!value[group.key]?.length) value[group.key] = group.migrateFrom.flatMap(key => value[key] || []);
            group.migrateFrom.forEach(key => {value[key] = [];});
          }
          const groups = field.groups || [];
          const names = roster.map(player => String(player.name || ''));
          const choices = roster.map(player => {
            const name = String(player.name || '');
            return {value: names.filter(item => item === name).length > 1 ? String(player.id) : name, label: name};
          }).filter(player => player.value);
          const playerOptions = choices.map(player => `<option value="${esc(player.value)}">${esc(player.label)}</option>`).join('');
          const configured = groups.filter(group => !group.hidden && (value[group.key] || []).length).length;
          control = `<details class="config-assignments" ${configured ? 'open' : ''}><summary><strong>${label}</strong> <small class="muted" data-group-count>已填 ${configured}/${groups.filter(group => !group.hidden).length} 组</small></summary>${help}<div class="config-group-list">`
            + groups.map((group, index) => {
              const previous = field.copyPrevious && index && !group.hidden ? groups[index - 1] : null;
              return `<div class="config-group-row" ${group.hidden ? 'hidden' : ''}><label class="stack">${esc(group.label)}<input data-group="${esc(group.key)}" value="${esc((value[group.key] || []).join(' '))}" placeholder="${esc(group.placeholder || field.placeholder || '输入玩家名，以空格分隔')}"></label><div class="config-group-actions">${choices.length ? `<select data-roster-choice aria-label="为${esc(group.label)}选择玩家"><option value="">从本场阵容选择玩家</option>${playerOptions}</select><button type="button" data-add-player>加入</button>` : ''}${previous ? `<button type="button" data-copy-group="${esc(previous.key)}">沿用上一轮</button>` : ''}</div></div>`;
            }).join('') + '</div></details>';
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
      container.querySelectorAll('.config-assignments').forEach(details => {
        const count = details.querySelector('[data-group-count]');
        const update = () => {
          const rows = [...details.querySelectorAll('.config-group-row:not([hidden]) input[data-group]')];
          count.textContent = `已填 ${rows.filter(input => list(input.value).length).length}/${rows.length} 组`;
        };
        details.addEventListener('input', update);
        details.addEventListener('change', update);
        details.addEventListener('click', event => {
          const button = event.target.closest('button[data-add-player],button[data-copy-group]');
          if (!button) return;
          const input = button.closest('.config-group-row').querySelector('input[data-group]');
          if (button.hasAttribute('data-copy-group')) {
            const previous = [...details.querySelectorAll('input[data-group]')].find(node => node.dataset.group === button.dataset.copyGroup);
            input.value = previous?.value || '';
          } else {
            const picker = button.closest('.config-group-row').querySelector('[data-roster-choice]');
            if (!picker.value) return;
            input.value = [...list(input.value), picker.value].join(' ');
            picker.value = '';
          }
          input.dispatchEvent(new Event('change', {bubbles:true}));
          update();
        });
      });
      visibility();
    }
    return {setSchema, collect, validate:() => [...container.querySelectorAll('input,select,textarea')].every(node => node.closest('[hidden]') || node.reportValidity())};
  }
};
