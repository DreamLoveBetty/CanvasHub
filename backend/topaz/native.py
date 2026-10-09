"""Private ABI bridge. Load/call vendor code only inside an isolated worker.

No binary patches, credential access, license-file changes or key serialization.
The pointer passed to iai_proc is the loaded library's own request context.
Library hashes are checked before resolving any private symbol.
"""
import ctypes
import os
from pathlib import Path
import re
import subprocess


def sanitize(message):
    return '\n'.join('[hardware identifier redacted]' if re.search(
        r'machine.?id|hardware.?uuid|\bserial\b', line, re.I) else line
        for line in str(message).splitlines())[:8192]


def run(app, models, source, output, request, report, *, protocol='native'):
    from catalog import check_installation
    reason = check_installation(app)
    if reason:
        raise RuntimeError(reason)
    app = Path(app)
    path = app / 'Frameworks/libimageai.dylib'
    library = ctypes.CDLL(str(path))
    library.iai_init.argtypes = [ctypes.c_char_p]
    library.iai_init.restype = ctypes.c_int
    if protocol not in ('native', 'stack'):
        raise ValueError('未知 Topaz 原生请求协议')
    process = library.iai_stack_proc if protocol == 'stack' else library.iai_proc
    process.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                       ctypes.POINTER(ctypes.c_ubyte)]
    process.restype = ctypes.c_int
    if library.iai_init(os.fsencode(models)) != 0:
        raise RuntimeError('Topaz 原生引擎初始化失败')
    # nm reads symbols, not user files. ASLR relocation is resolved in this child.
    symbols = {}
    for line in subprocess.check_output(['nm', str(path)], text=True, timeout=20).splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] != 'U':
            symbols[parts[2]] = int(parts[0], 16)
    context_symbol = next(name for name in symbols if 'crypto_details' in name and 'AIE_KEY' in name)
    slide = ctypes.cast(library.iai_init, ctypes.c_void_p).value - symbols['_iai_init']
    pointer = ctypes.c_void_p.from_address(slide + symbols[context_symbol]).value
    if not pointer:
        raise RuntimeError('Topaz 原生请求上下文尚未初始化')
    context = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ubyte))
    engine = ctypes.CDLL(str(app / 'Frameworks/libaiengine.dylib'))
    callback_type = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p)
    def on_log(level, message):
        text = sanitize(message.decode('utf-8', 'replace'))
        match = re.search(r'\[PROGRESS\]\s+(\d+)', text)
        if match:
            report(dict(event='progress', percent=max(0, min(100, int(match[1])))))
        else:
            report(dict(event='log', level=level, message=text))
    callback = callback_type(on_log)  # Keep alive until synchronous iai_proc returns.
    setter = getattr(engine, '_Z12aieSetLoggerPFviPKcE')
    setter.argtypes = [callback_type]
    setter.restype = None
    setter(callback)
    try:
        code = process(os.fsencode(source), os.fsencode(output), os.fsencode(request), context)
        if code != 0:
            raise RuntimeError(f'Topaz 原生处理失败（{code}）')
    finally:
        setter(callback_type())
