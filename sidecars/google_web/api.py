"""Protected Web routes; independent of OAuth generation and all GPT routes."""
import asyncio
import json
import logging
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from ..google_pool.api import read_body
from .errors import WebError

logger = logging.getLogger(__name__)


def create_router(runtime, require_auth):
    router = APIRouter()

    @router.get('/api/google-web/status')
    def status(authorization: str | None = Header(default=None)):
        require_auth(authorization)
        return runtime.status()

    @router.post('/api/google-web/{action}')
    async def control(action: str, request: Request, authorization: str | None = Header(default=None)):
        require_auth(authorization)
        try:
            body = await read_body(request, 2 * 1024 * 1024)
            return await runtime.action(action, body)
        except WebError as error:
            return JSONResponse(error.public(), status_code=error.status)
        except Exception as error:
            if action in ('browser-profiles', 'browser-import'):
                logger.warning('Web browser action failed: action=%s error_type=%s errno=%s',
                               action, type(error).__name__, error.errno if isinstance(error, OSError) else None)
            return JSONResponse({'error': 'Web 账号操作失败，请检查请求格式或服务状态', 'error_code': 'web_control_error'}, status_code=400)

    @router.post('/api/google-web/models/{operation}')
    async def generate(operation: str, request: Request, authorization: str | None = Header(default=None)):
        require_auth(authorization)
        try:
            model, _, method = operation.rpartition(':')
            if method not in ('generateContent', 'streamGenerateContent'):
                raise WebError('不支持此图片方法', 400, 'invalid_method')
            body = await read_body(request)
            if method == 'generateContent':
                return await runtime.pool.generate(model, body)
            async def events():
                cancelled = asyncio.Event()
                task = asyncio.create_task(runtime.pool.generate(model, body, cancelled))
                try:
                    while not task.done():
                        if await request.is_disconnected():
                            return
                        done, _ = await asyncio.wait({task}, timeout=5)
                        if not done:
                            yield ': google-web heartbeat\n\n'
                    try:
                        result = task.result()
                    except WebError as error:
                        result = error.public()
                    except Exception:
                        result = {'error': 'Web 生图失败，未重新提交', 'error_code': 'web_error'}
                    yield 'data: ' + json.dumps(result, ensure_ascii=False) + '\n\n'
                finally:
                    cancelled.set()
                    if not task.done():
                        task.add_done_callback(lambda future: None if future.cancelled() else future.exception())
            return StreamingResponse(events(), media_type='text/event-stream',
                                     headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        except WebError as error:
            return JSONResponse(error.public(), status_code=error.status)
        except Exception:
            return JSONResponse({'error': 'Web 图片请求无效', 'error_code': 'invalid_request'}, status_code=400)

    return router
