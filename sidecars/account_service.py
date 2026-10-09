"""Composition root for independent GPT and Google pools on one HTTP listener.

The legacy GPT app, its lifespan and existing routes stay unchanged. Google has a
separate store/router/runtime and depends only on the injected host auth function.
"""

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from sidecars.chatgpt_pool.app import (
    app as gpt_app,
    require_auth,
    settings as host_settings,
)
from sidecars.google_pool.api import GoogleRuntime, create_router
from sidecars.google_pool.config import load_settings


def compose(gpt_app, require_auth, google):
    @asynccontextmanager
    async def lifespan(app):
        async with gpt_app.router.lifespan_context(gpt_app):
            google.start()
            try:
                yield
            finally:
                google.close()

    host = FastAPI(title='CanvasHub account services', lifespan=lifespan)
    host.include_router(create_router(google, require_auth))
    host.mount('/', gpt_app)
    return host


class OAuthCallbackLogFilter(logging.Filter):
    def filter(self, record):
        # Authorization codes/state belong to the callback exchange, not access logs.
        return '/oauth-callback' not in record.getMessage()


logging.getLogger('uvicorn.access').addFilter(OAuthCallbackLogFilter())
app = compose(
    gpt_app,
    require_auth,
    GoogleRuntime(settings=load_settings(callback_port=host_settings.port)),
)
