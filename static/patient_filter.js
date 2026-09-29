// 患者を選ぶ<select data-patient-select>の上に、名前・カナ・カルテNoで絞り込む検索欄を追加する。
// 入力すると候補が下にリスト表示され、クリックするとそのまま選択できる（selectを開かなくて済む）。
// select自体は隠さずそのまま残すので、必須項目としてのフォーム送信チェックはそのまま働く。
document.querySelectorAll('select[data-patient-select]').forEach(function (select) {
  var all = Array.from(select.options).map(function (o) {
    return { value: o.value, text: o.text, selected: o.selected, dataset: Object.assign({}, o.dataset) };
  });

  var wrap = document.createElement('div');
  wrap.className = 'patient-combo';
  select.parentNode.insertBefore(wrap, select);

  var input = document.createElement('input');
  input.type = 'text';
  input.className = 'patient-combo-input';
  input.placeholder = '名前・カナ・カルテNoで検索';
  input.autocomplete = 'off';
  wrap.appendChild(input);

  var list = document.createElement('div');
  list.className = 'patient-combo-list';
  list.hidden = true;
  wrap.appendChild(list);

  wrap.appendChild(select);

  function renderSelect(q) {
    var current = select.value;
    var shown = all.filter(function (o) { return !q || o.text.toLowerCase().indexOf(q) !== -1 || o.value === current; }).slice(0, 100);
    select.innerHTML = '';
    shown.forEach(function (o) {
      var opt = new Option(o.text, o.value, false, o.value === current);
      Object.keys(o.dataset).forEach(function (k) { opt.dataset[k] = o.dataset[k]; });
      select.add(opt);
    });
  }

  function closeSuggestions() { list.hidden = true; list.innerHTML = ''; }

  function renderSuggestions(q) {
    if (!q) { closeSuggestions(); return; }
    var shown = all.filter(function (o) { return o.value && o.text.toLowerCase().indexOf(q) !== -1; }).slice(0, 20);
    list.innerHTML = '';
    if (!shown.length) { closeSuggestions(); return; }
    shown.forEach(function (o) {
      var item = document.createElement('div');
      item.className = 'patient-combo-item';
      item.textContent = o.text;
      item.addEventListener('mousedown', function (e) {
        e.preventDefault();
        renderSelect('');
        select.value = o.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        input.value = '';
        closeSuggestions();
      });
      list.appendChild(item);
    });
    list.hidden = false;
  }

  input.addEventListener('input', function () {
    var q = input.value.trim().toLowerCase();
    renderSelect(q);
    renderSuggestions(q);
  });
  input.addEventListener('blur', function () { setTimeout(closeSuggestions, 150); });
  select.addEventListener('change', function () { input.value = ''; closeSuggestions(); });

  renderSelect('');
  if (!select.value) select.selectedIndex = 0;
});
