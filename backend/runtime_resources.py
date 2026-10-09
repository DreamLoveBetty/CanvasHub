"""Explicit cooperative lease for local inference workers; no domain state imports."""
from contextlib import contextmanager
import os


class IdleWorkerCoordinator:
    """Server-owned registry of public unload ports, called under the lease.

    This is explicitly injected into runtimes, not a process-global container.
    The cross-process lease, rather than a domain's private busy flag, proves
    that it is safe to unload a resident model.
    """
    def __init__(self, workers):
        self._workers = dict(workers)

    def release_other(self, owner):
        for name, release in self._workers.items():
            if name != owner:
                release()

    def release_all(self):
        for release in self._workers.values():
            release()


@contextmanager
def local_accelerator(path, cancelled, progress):
    # MLX audio and ReShot are Mac-local. The remote Windows H3 service owns its
    # own GPU scheduler; this lease is not a claim of a global cross-host lock.
    if os.name != 'posix':
        raise RuntimeError('此本地推理环境要求 POSIX 系统')
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        waiting = False
        while not cancelled.is_set():
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not waiting:
                    progress({'stage': '等待本地推理资源', 'message': '等待其他本地音频或视频控制任务释放资源'})
                    waiting = True
                cancelled.wait(.2)
        # Yield the live lease so long-running child processes can inherit its
        # descriptor with ``pass_fds``.  If the supervisor is killed abruptly,
        # the kernel then keeps the accelerator locked until that child exits.
        try: yield handle
        finally: fcntl.flock(handle, fcntl.LOCK_UN)
