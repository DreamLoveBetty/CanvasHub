// Direct audio-reference dependency planning. No DOM, provider or duplicate job polling.
// The controller owns submission/polling; this module only orders their execution.
(function () {
  const stopped = () => Object.assign(new Error('已停止执行链'), { name: 'AbortError' });
  function wait(promise, signal) {
    if (!signal) return promise;
    return new Promise((resolve, reject) => {
      const abort = () => reject(stopped());
      if (signal.aborted) abort();
      else signal.addEventListener('abort', abort, { once: true });
      Promise.resolve(promise).then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
    });
  }
  function create({ getCanvas, getNodeState, runTranscription }) {
    const incoming = id => (getCanvas().edges || []).filter(edge => edge.to === id);
    function reference(node) {
      const refs = incoming(node.id).map(edge => getNodeState(edge.from)).filter(n => n?.type === 'music_transcribe');
      if (refs.length > 1) throw new Error('音乐生成仅接受一个转谱参考');
      return refs[0] || null;
    }
    function isChained(node) {
      return node.type === 'music_transcribe' && (getCanvas().edges || []).some(edge => edge.from === node.id && getNodeState(edge.to)?.type === 'music_generate');
    }
    function transcriptionKey(node) {
      const sources = incoming(node.id).map(edge => getNodeState(edge.from)).filter(n => n?.type === 'audio');
      const source = sources[0];
      if (sources.length !== 1 || !source || !(source.audioAssetId || source.mediaUrl)) return '';
      return JSON.stringify([1, source.id, source.audioAssetId || '', source.mediaUrl || '', source.sourceTaskId || '',
        node.transcribeTask, node.preset, node.maxSeconds]);
    }
    function cached(node, key) {
      return Boolean(key && node.status === 'succeeded' && node.jobId && node.resultJobId === node.jobId
        && node.transcriptionResultKey === key && node.resultAbc?.trim());
    }
    function hasAncestor(id, target, seen = new Set()) {
      if (id === target) return true;
      if (seen.has(id)) return false;
      seen.add(id);
      return incoming(id).some(edge => hasAncestor(edge.from, target, seen));
    }
    async function prepare(node, { signal, valid, stage }) {
      const ref = reference(node);
      if (!ref) return null;
      if (node.cot === 'off') throw new Error('音频转谱参考需要 full 或 melody 模式');
      if (hasAncestor(ref.id, node.id)) throw new Error('音频参考存在循环连线，请使用独立参考音频');
      const key = transcriptionKey(ref);
      if (!key) throw new Error('请给上游转谱节点接入有效音频素材');
      const check = () => {
        if (signal.aborted) throw stopped();
        if (!valid() || getNodeState(ref.id) !== ref || reference(node) !== ref || transcriptionKey(ref) !== key) {
          throw new Error('执行期间输入或连线已变化，请重新开始生成');
        }
      };
      check();
      if (!cached(ref, key)) {
        stage('等待上游转谱');
        await wait(runTranscription(ref, key, signal), signal);
      }
      check();
      if (!cached(ref, key)) throw new Error('上游转谱未完成或没有有效 ABC，未提交音乐生成');
      return ref.resultAbc;
    }
    return Object.freeze({ reference, isChained, transcriptionKey, cached, prepare });
  }
  window.DesktopMusicWorkflow = Object.freeze({ create, wait });
})();
