// History deletion and mutation helpers
  function deleteHistoryEntry(item) {
    if (!item) return Promise.resolve();
    const q = new URLSearchParams();
    if (item.task_id) q.set('task_id', item.task_id);
    if (item.timestamp) q.set('timestamp', item.timestamp);
    return api.request('/api/history/delete?' + q.toString(), { method: 'DELETE' })
      .then(() => loadHistory());
  }

  function deleteHistoryItem() {
    if (!currentModalItem) return;
    if (!confirm('确定删除这条记录吗？')) return;
    deleteHistoryEntry(currentModalItem).then(() => {
      closeModal();
    });
  }

  function deleteFailedHistory() {
    if (!confirm('确定一键删除所有失败记录吗？')) return;

    api.json('/api/history/delete_failed', { method: 'DELETE' })
      .then(data => {
        const n = (data && typeof data.deleted === 'number') ? data.deleted : 0;
        alert(`已删除失败记录 ${n} 条`);
        loadHistory();
      })
      .catch(e => {
        alert('删除失败记录失败: ' + e);
      });
  }

  function deleteHistoryItemByIdentity(taskId, timestamp) {
    const target = (historyRecords || []).find(item => item.task_id === taskId && item.timestamp === timestamp);
    if (!target) {
      showStatusMessage('这条记录刚刚刷新了，请稍后重试。', 'info');
      return;
    }
    if (!confirm('确定删除这条记录吗？')) return;
    deleteHistoryEntry(target).then(() => {
      showStatusMessage('记录已删除。', 'success');
    });
  }
