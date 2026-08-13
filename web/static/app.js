/* BillHub 前端：弹窗（报销/预览）+ 合同行展开 */
function openModal(id) {
  var m = document.getElementById(id);
  if (m) { m.removeAttribute('hidden'); document.body.classList.add('modal-open'); }
}
function closeModal(id) {
  var m = document.getElementById(id);
  if (m) m.setAttribute('hidden', '');
  if (!document.querySelector('.modal:not([hidden])')) {
    document.body.classList.remove('modal-open');
  }
}
// ESC 关闭最上层弹窗，其次关闭下拉菜单
document.addEventListener('keydown', function (e) {
  if (e.key !== 'Escape') return;
  var mods = document.querySelectorAll('.modal:not([hidden])');
  if (mods.length) { closeModal(mods[mods.length - 1].id); return; }
  document.querySelectorAll('.dropdown.open').forEach(function (d) { d.classList.remove('open'); });
});

// 打开报销弹窗（HTMX 加载表单）
function openReimburse(cid) {
  htmx.ajax('GET', '/payments/form/' + cid,
    { target: '#modal-reimburse-content', swap: 'innerHTML' });
  openModal('modal-reimburse');
}
// 打开审批表预览弹窗
function openPreview(pid) {
  htmx.ajax('GET', '/preview/' + pid,
    { target: '#modal-preview-content', swap: 'innerHTML' });
  openModal('modal-preview');
}
// 合同行展开/收起
function toggleExpand(cid) {
  var row = document.getElementById('expand-row-' + cid);
  if (row) row.classList.toggle('open');
}

// 顶栏下拉菜单（管理 / 用户）
function toggleDropdown(id) {
  var dd = document.getElementById(id);
  if (!dd) return;
  var willOpen = !dd.classList.contains('open');
  document.querySelectorAll('.dropdown.open').forEach(function (d) { d.classList.remove('open'); });
  if (willOpen) dd.classList.add('open');
}
// 点击别处关闭下拉
document.addEventListener('click', function (e) {
  if (!e.target.closest('.dropdown')) {
    document.querySelectorAll('.dropdown.open').forEach(function (d) { d.classList.remove('open'); });
  }
});
