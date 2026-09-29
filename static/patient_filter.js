document.querySelectorAll('select[data-patient-select]').forEach(function (select) {
  var all = Array.from(select.options).map(function (o) {
    return { value: o.value, text: o.text, selected: o.selected, dataset: Object.assign({}, o.dataset) };
  });
  var input = document.createElement('input');
  input.type = 'text';
  input.placeholder = '名前・カナ・カルテNoで絞り込み';
  input.style.marginBottom = '6px';
  select.parentNode.insertBefore(input, select);
  function render() {
    var q = input.value.trim().toLowerCase();
    var current = select.value;
    var shown = all.filter(function (o) { return !q || o.text.toLowerCase().indexOf(q) !== -1 || o.value === current; }).slice(0, 100);
    select.innerHTML = '';
    shown.forEach(function (o) {
      var opt = new Option(o.text, o.value, false, o.value === current);
      Object.keys(o.dataset).forEach(function (k) { opt.dataset[k] = o.dataset[k]; });
      select.add(opt);
    });
    if (!q && !select.value) select.selectedIndex = 0;
  }
  input.addEventListener('input', render);
  render();
});
