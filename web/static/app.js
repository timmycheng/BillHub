/* BillHub 2.0 前端：弹窗 / 下拉菜单 / Flash 自动消失 / 日期 */
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
// 点击遮罩（弹窗根节点自身）关闭
document.addEventListener('click', function (e) {
  if (e.target.classList && e.target.classList.contains('modal')) {
    closeModal(e.target.id);
  }
  // 点击别处关闭下拉
  if (!e.target.closest('.dropdown')) {
    document.querySelectorAll('.dropdown.open').forEach(function (d) { d.classList.remove('open'); });
  }
});
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

// 顶栏下拉菜单
function toggleDropdown(id) {
  var dd = document.getElementById(id);
  if (!dd) return;
  var willOpen = !dd.classList.contains('open');
  document.querySelectorAll('.dropdown.open').forEach(function (d) { d.classList.remove('open'); });
  if (willOpen) dd.classList.add('open');
}

// 报销记录行点击展开/收起时间轴（点击链接/按钮等不触发）
document.addEventListener('click', function (e) {
  if (e.target.closest('a, button, input, select, textarea, label')) return;
  var row = e.target.closest('tr');
  if (!row || row.classList.contains('tl-row')) return;
  var tl = row.nextElementSibling;
  if (!tl || !tl.classList.contains('tl-row')) return;
  tl.hidden = !tl.hidden;
});

document.addEventListener('DOMContentLoaded', function () {
  // 顶栏日期
  document.querySelectorAll('.date-chip').forEach(function (el) {
    var d = new Date();
    el.textContent = d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  });
  // Flash 消息 4 秒后自动淡出
  document.querySelectorAll('.flash-container .flash').forEach(function (f) {
    setTimeout(function () {
      f.classList.add('hide');
      setTimeout(function () { f.remove(); }, 350);
    }, 4000);
  });
});
