/* BillHub 前端交互：合同列表选中高亮（HTMX 加载后委托） */
document.addEventListener('click', function (e) {
  var item = e.target.closest('.contract-item');
  if (!item) return;
  document.querySelectorAll('.contract-item.selected').forEach(function (el) {
    el.classList.remove('selected');
  });
  item.classList.add('selected');
});
