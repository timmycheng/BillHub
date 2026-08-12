/* BillHub 前端交互：合同列表选中高亮 + 切换合同时重置审批表预览区 */
document.addEventListener('click', function (e) {
  var item = e.target.closest('.contract-item');
  if (!item) return;
  document.querySelectorAll('.contract-item.selected').forEach(function (el) {
    el.classList.remove('selected');
  });
  item.classList.add('selected');
  // 右栏预览区回退到占位（避免显示上一个合同的审批表）
  var pv = document.getElementById('approval-preview');
  if (pv) {
    pv.innerHTML = '<div class="placeholder"><h3>🖨 审批表预览</h3>' +
      '<p class="hint">填表后点「预览本次」，或生成报销单后自动显示</p></div>';
  }
});
