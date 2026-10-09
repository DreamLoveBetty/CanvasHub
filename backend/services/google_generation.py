"""Google generation/edit worker lifecycles and existing GPT fallback.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _record_native_response(task_id, response_meta, merge_params, record_event):
    """Keep request/actual dimensions in the existing task, without regenerating."""
    if not response_meta.get('request_endpoint'):
        return
    try:
        merge_params(task_id, dict(response_meta))
        warning = response_meta.get('output_size_warning')
        record_event(
            task_id, 'google_output_size_mismatch' if warning else 'google_native_response',
            warning or 'Google 原生图片响应已接收', stage='saving',
            severity='warning' if warning else 'info', payload=dict(response_meta),
        )
    except Exception as exc:
        # Observability must not discard a paid image or prevent its delivery.
        print(f'⚠️ Google 响应元数据记录失败（原图已保存）：{exc}')


def process_task(
    task_id,
    prompt,
    params,
    *,
    DEFAULT_GOOGLE_IMAGE_MODEL,
    Path,
    _coerce_google_max_tokens,
    _coerce_google_output_controls,
    _effective_image_ratio,
    _finalize_generation_task,
    _is_generic_19_fidelity_prompt,
    _map_quality_to_gpt_resolution,
    _merge_task_params,
    _record_generation_event,
    _result_image_filenames,
    _should_fallback_to_gpt,
    _start_generation_audit,
    _translate_generation_failure,
    daily_output_dir,
    generate_image,
    generate_image_gpt_pool,
    os,
    save_image,
    save_thumbnail,
    send_status_notification,
    send_telegram,
    send_telegram_result,
    time,
    update_task_fields,
    update_task_status,
    write_obsidian_prompt_sidecar,
    google_pool_generate=None,
):
    """后台线程：处理任务（skill 调用支持 GPT 托底）"""
    def progress_cb(stage=None, progress_text=None, heartbeat=False, **extra):
        payload = {}
        if stage is not None:
            payload['stage'] = stage
        if progress_text is not None:
            payload['progress_text'] = progress_text
        if heartbeat:
            payload['heartbeat_at'] = int(time.time())
        payload.update({k: v for k, v in extra.items() if v is not None})
        if payload:
            update_task_fields(task_id, **payload)

    run_id = ''
    task_kind = 'google-gen'
    task_provider = 'google_pool' if (params or {}).get('google_provider_route') == 'google_pool' else 'google'
    task_route = 'google_pool_gen' if task_provider == 'google_pool' else 'google_gen'
    try:
        params = dict(params or {})
        params['ratio'] = _effective_image_ratio(prompt, params.get('ratio'), '1:1')
        if _is_generic_19_fidelity_prompt(prompt):
            _merge_task_params(task_id, {
                'ratio': params['ratio'],
                'prompt_fidelity_locked': True,
                'source_ratio_locked': True,
            })
        print(f"🎨 开始处理任务：{task_id}")

        model = params.get('model', DEFAULT_GOOGLE_IMAGE_MODEL)
        task_kind = 'gpt' if 'gpt' in str(model).lower() else 'google-gen'
        if task_provider == 'google_pool' and task_kind == 'gpt':
            raise ValueError('Google OAuth 线路不能调用 GPT 模型')
        task_provider = 'chatgpt_pool' if task_kind == 'gpt' else task_provider
        task_route = 'gpt_pool' if task_kind == 'gpt' else task_route
        run_id = _start_generation_audit(
            task_id,
            task_kind,
            prompt,
            params,
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )

        send_status_notification(task_id, '已提交图片生成任务，请等待...', '✅')
        update_task_status(task_id, 'preparing', '正在准备生成...', stage='preparing')
        update_task_status(task_id, 'processing', '生成中...', stage='queued')

        aspect_ratio = params.get('ratio', '1:1')
        quality = params.get('quality', 'hd')
        max_tokens = _coerce_google_max_tokens(params.get('max_tokens'))
        temperature = params.get('temperature')
        style = params.get('style', 'raw')
        caller = str(params.get('caller', 'webapp')).lower()
        archive_enabled, telegram_enabled = _coerce_google_output_controls(params)
        params['archive_enabled'] = archive_enabled
        params['telegram_enabled'] = telegram_enabled
        _merge_task_params(task_id, {
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
        })

        # 拼接风格提示词
        final_prompt = prompt
        if style == 'king_hu':
            final_prompt += ", Cinematic Wuxia Aesthetic (King Hu Style), Moon-white & Pale Cyan palette, high-class grey tones. Tyndall morning light piercing through heavy mist, golden backlight halo. Ancient temple gate, mossy stone steps, bamboo forest. Cold porcelain glass skin, jet black ink-like hair with wet dew texture. Ink wash painting negative space, film grain, wide shot, 1970s martial arts masterpiece."
        elif style == 'shadow':
            final_prompt += ", Shadow-play Aesthetic (Ying Style), Teal and Ink scheme, low saturation, high contrast between deep blacks and wet highlights. Cold-toned porcelain skin, high slanted Duo-ma bun, ebony hairpin. Rembrandt lighting, cold side light & golden rim light. Minimalist Zen space, giant translucent rice paper screens, wet ink brushstrokes, rainy atmosphere. Cinnabar dot, Song-style layered silk gauze texture."
        elif style == 'dunhuang':
            final_prompt += ", Dunhuang Mural (Rock Color Aesthetic), Opulent Gold & Lapis Lazuli palette, high contrast warm shadows. Radiant Tang-style porcelain skin, double-loop Wang-xian bun, gold filigree hairpins. Rock color texture, weathered mural surface. Divine god rays in cavern, amber candlelight. Ancient grotto atmosphere, flying ribbons, golden clover huadian, epic religious solemnity."
        elif style == 'candlelight':
            final_prompt += ", Cinematic candlelight portrait: Sony A7R IV with 50mm f/1.2 lens, multiple white candles as natural light source, dramatic chiaroscuro lighting with strong side light contouring, deep layered shadows. Ultra-realistic digital art, photorealistic with Unreal Engine 5 CG cinematic rendering. Extremely detailed skin texture with visible pores, subtle sheen of sweat/oil on skin surface, realistic subsurface scattering (SSS) translucency. 8K ultra-high resolution, ray-traced lighting quality, hyper-detailed micro textures including knitted fabric fibers, velvet plush texture, light scattering on different materials. Classical, mysterious, elegant atmosphere with suppressed luxury, warm brown candlelight interwoven with deep purple and ash grey shadows."
        elif style == 'real':
            final_prompt += ", photorealistic, 8k, highly detailed, sharp focus, cinematic lighting, photography, masterpiece"
        elif style == '3d_info':
            final_prompt += ", 3D infographic poster, C4D claymorphism style, vertical layout, centered composition, matte plastic and soft clay texture, soft diffuse lighting, no harsh highlights, 3D infographic aesthetic, pop art influence, soft glowing 3d icons, similar to Behance 3D illustrations and Apple skeuomorphic icons"
        elif style == 'sketchnote':
            final_prompt = f"请根据以下输入内容，生成一张手绘涂鸦风格的读书笔记信息图，并严格遵循以下风格：1. 整体风格与媒介：采用充满活力的手绘涂鸦笔记 (Sketchnote) 风格，专业知识笔记的学霸风格，不要太卡通。黑色使用深棕、橙黄或海军蓝，轻微水彩进行填色，并搭配柔和的黑色或深棕色细线等勾勒轮廓。竖版 (3:4) 构图。2. 配色方案（关键）：整张图都应该是彩色的，采用明亮、清新、和谐的色彩组合（海军蓝#1E3A8A、浅蓝#60A5FA、金色#F59E0B、奶油色背景#FEFCE8）。背景应有淡淡纸张纹理的米色，或者直接留白，但画面主体必须是五彩斑斓的。颜色填充应模仿彩铅或水彩的质感，带有自然的笔触感，而不是均匀的数字平涂。3. 线条特征：所有轮廓线都必须是不完美、略带抖动的手绘线条，给人一种柔软、亲切的感觉。4. 字体风格：所有文字都必须是彩色的手写体，绝对不要使用任何电脑字体。标题和关键词使用加粗的、或带有简单边框的手写艺术字来突出。正文和注释使用清晰、自然的个人笔记手写体。5. 插图与图标：所有图形元素必须是充满色彩的、简单的涂鸦/简笔画（colorful doodle/stick figure）风格。使用手绘的彩色箭头、框线、项目符号和分割线来组织信息。6. 内容处理：信息精炼，通过关键词加粗、手绘框等方式突出重点。如有故事人物，用此风格的可爱彩色涂鸦形象替代。话语与输入内容保持一致。7. 绘制使用中文绘制成为完整的信息卡输出，尽可能使用 PINCH 的展示方式，将所有内容排版在一页，需要清晰可读，所有中文必须孤立文字图层处理，输出高分辨率 4k。输入内容：{prompt}"
            aspect_ratio = "3:4"

        print(f"📡 调用 API...")
        print(f"   - caller: {caller}")
        print(f"   - ratio: {aspect_ratio}")
        print(f"   - quality: {quality}")
        print(f"   - model: {model}")
        print(f"   - max_tokens: {max_tokens}")
        if temperature is not None:
            print(f"   - temperature: {temperature}")
        print(f"   - style: {style}")

        if 'gpt' in str(model).lower():
            update_task_status(task_id, 'processing', '正在调用 GPT 生成...', stage='calling_gpt')
            send_status_notification(task_id, '生成中... 正在调用 GPT...', '🤖')

            gpt_resolution = params.get('resolution') or _map_quality_to_gpt_resolution(quality)
            _record_generation_event(task_id, 'provider_call_started', '开始调用 GPT 账号池生成图片', stage='calling_gpt', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool'})
            result = generate_image_gpt_pool(
                prompt,
                aspect_ratio,
                gpt_resolution,
                quality,
                image_count=1,
                prompt_mode='smart',
            )
            if not result.get('success'):
                raise RuntimeError(result.get('error', 'GPT 生成失败'))

            telegram_success = False
            if telegram_enabled:
                update_task_status(task_id, 'processing', '正在发送到 Telegram...', stage='sending_telegram')
                send_status_notification(task_id, '生成中... 正在发送图片...', '📤')
                _record_generation_event(task_id, 'telegram_send_started', '开始发送图片到 Telegram', stage='sending_telegram')
                telegram_success = send_telegram_result(
                    result['image_path'],
                    prompt,
                    aspect_ratio,
                    gpt_resolution,
                    image_paths=result.get('image_paths'),
                )
            else:
                update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
                _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

            result_files = _result_image_filenames(result)
            image_count = len(result_files) or len(result.get('image_paths') or [result.get('image_path')])
            filename = result_files[0] if result_files else os.path.basename(result['image_path'])
            if telegram_success:
                ok_text = f'GPT 图片生成成功（共 {image_count} 张）' if image_count > 1 else 'GPT 图片生成成功'
                _finalize_generation_task(
                    task_id,
                    'succeeded',
                    run_id=run_id,
                    provider='chatgpt_pool',
                    route='gpt_pool',
                    task_type=task_kind,
                    result_file=filename,
                    stage='done',
                    progress_text=ok_text,
                    result_files=result_files,
                    image_count=image_count,
                )
                _record_generation_event(task_id, 'run_succeeded', ok_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool', 'image_count': image_count})
                send_status_notification(task_id, '✅ GPT 图片生成成功！', '🎉')
            else:
                progress_text = 'GPT 图片已生成，已按节点开关跳过 Telegram' if not telegram_enabled else 'GPT 图片已生成，但 Telegram 发送失败'
                _finalize_generation_task(
                    task_id,
                    'succeeded_no_telegram',
                    run_id=run_id,
                    provider='chatgpt_pool',
                    route='gpt_pool',
                    task_type=task_kind,
                    result_file=filename,
                    stage='done',
                    progress_text=progress_text,
                    result_files=result_files,
                    image_count=image_count,
                )
                _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool', 'image_count': image_count, 'telegram_enabled': telegram_enabled})
            return

        update_task_status(task_id, 'processing', '正在调用 AI 模型...', stage='calling_api')
        send_status_notification(task_id, '生成中... 正在调用 AI 模型...', '🤖')
        _record_generation_event(task_id, 'provider_call_started', '开始调用 Google 图像生成', stage='calling_api', payload={'provider': task_provider, 'route': task_route})

        image_data = None
        response_meta = {}
        primary_error = None
        try:
            selected_generate = google_pool_generate if task_provider == "google_pool" else generate_image
            if not selected_generate: raise RuntimeError("Google OAuth账号池适配器未装配")
            image_data, response_meta = selected_generate(
                final_prompt,
                aspect_ratio,
                quality,
                model,
                max_tokens=max_tokens,
                temperature=temperature,
                progress_cb=progress_cb,
                **({"task_id": task_id} if task_provider == "google_pool" else {}),
            )
        except Exception as e:
            primary_error = str(e)
            print(f"⚠️ 主路由失败：{primary_error}")

            if _should_fallback_to_gpt(params, primary_error):
                update_task_status(task_id, 'fallback_running', '主路由失败，切换 GPT 托底...', stage='fallback_running')
                send_status_notification(task_id, '主路由失败，切换 GPT 托底中...', '🛟')
                _record_generation_event(task_id, 'fallback_started', 'Google 主路由失败，切换 GPT 托底', stage='fallback_running', severity='warning', payload={'primary_error': primary_error})

                gpt_resolution = params.get('fallback_resolution') or _map_quality_to_gpt_resolution(quality)
                fallback_result = generate_image_gpt_pool(
                    prompt,
                    aspect_ratio,
                    gpt_resolution,
                    quality,
                    image_count=1,
                    prompt_mode='smart',
                )
                if not fallback_result.get('success'):
                    fallback_error = fallback_result.get('error', 'unknown')
                    raise RuntimeError(
                        f"主路由失败：{primary_error} | GPT 托底失败：{fallback_error}"
                    )

                telegram_success = False
                if telegram_enabled:
                    update_task_status(task_id, 'processing', '托底成功，正在发送到 Telegram...', stage='sending_telegram')
                    send_status_notification(task_id, '托底成功，正在发送图片...', '📤')
                    _record_generation_event(task_id, 'telegram_send_started', '托底成功后开始发送到 Telegram', stage='sending_telegram')
                    telegram_success = send_telegram_result(
                        fallback_result['image_path'],
                        prompt,
                        aspect_ratio,
                        gpt_resolution,
                        image_paths=fallback_result.get('image_paths'),
                    )
                else:
                    update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
                    _record_generation_event(task_id, 'telegram_send_skipped', '托底成功后按节点开关跳过 Telegram', stage='saving')

                result_files = _result_image_filenames(fallback_result)
                image_count = len(result_files) or len(fallback_result.get('image_paths') or [fallback_result.get('image_path')])
                filename = result_files[0] if result_files else os.path.basename(fallback_result['image_path'])
                if telegram_success or not telegram_enabled:
                    ok_text = f'托底生成成功（共 {image_count} 张）' if image_count > 1 else '托底生成成功'
                    progress_text = ok_text if telegram_enabled else '托底生成成功，已按节点开关跳过 Telegram'
                    _finalize_generation_task(
                        task_id,
                        'succeeded' if telegram_enabled else 'succeeded_no_telegram',
                        run_id=run_id,
                        provider='chatgpt_pool',
                        route='gpt_pool_fallback',
                        task_type=task_kind,
                        result_file=filename,
                        stage='done',
                        progress_text=progress_text,
                        result_files=result_files,
                        image_count=image_count,
                        extra={'fallback_source': 'chatgpt_pool', 'primary_error': primary_error},
                    )
                    _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool_fallback', 'fallback_source': 'chatgpt_pool', 'image_count': image_count})
                    send_status_notification(task_id, '✅ 托底生成成功！', '🎉')
                    print(f"✅ 托底成功：{task_id} -> {filename}")
                else:
                    progress_text = '托底生成成功，但 Telegram 发送失败'
                    _finalize_generation_task(
                        task_id,
                        'succeeded_no_telegram',
                        run_id=run_id,
                        provider='chatgpt_pool',
                        route='gpt_pool_fallback',
                        task_type=task_kind,
                        result_file=filename,
                        stage='done',
                        progress_text=progress_text,
                        result_files=result_files,
                        image_count=image_count,
                        extra={'fallback_source': 'chatgpt_pool', 'primary_error': primary_error},
                    )
                    _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool_fallback', 'fallback_source': 'chatgpt_pool', 'image_count': image_count, 'telegram_enabled': telegram_enabled})
                    print(f"⚠️ 托底成功但 Telegram 发送失败：{task_id}")
                return

            raise

        update_task_status(
            task_id,
            'processing',
            '正在保存图片...',
            stage='saving',
            bytes_received=response_meta.get('bytes_received'),
            first_byte_at=response_meta.get('first_byte_at'),
            ttfb_ms=response_meta.get('ttfb_ms'),
        )
        send_status_notification(task_id, '生成中... 正在保存图片...', '💾')

        from datetime import datetime
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        model_name = str(model).replace("gemini-", "").replace("-image-preview", "").replace("-image", "").replace(".", "")
        filename_base = f"{model_name}_{timestamp}"

        download_dir = daily_output_dir(now)
        download_dir.mkdir(parents=True, exist_ok=True)

        filename_with_ext = f"{filename_base}.png"
        filepath = str(download_dir / filename_with_ext)
        filename = save_image(image_data, filepath)

        txt_path = download_dir / f"{filename_base}.txt"
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(prompt)
        try:
            write_obsidian_prompt_sidecar(Path(filepath), prompt, txt_path=txt_path)
        except Exception as exc:
            print(f"⚠️ 写入 Obsidian 提示词 md 失败: {exc}")
        print(f"💾 已保存图片：{filepath}")
        print(f"💾 已保存提示词：{txt_path}")
        save_thumbnail(filepath, filename)
        _record_native_response(task_id, response_meta, _merge_task_params, _record_generation_event)

        telegram_success = False
        if telegram_enabled:
            update_task_status(task_id, 'processing', '正在发送到 Telegram...', stage='sending_telegram')
            send_status_notification(task_id, '生成中... 正在发送图片...', '📤')
            _record_generation_event(task_id, 'telegram_send_started', '开始发送图片到 Telegram', stage='sending_telegram')
            try:
                print(f"📤 准备发送 Telegram: {filepath}")
                caption = prompt[:500] + "..." if len(prompt) > 500 else prompt
                telegram_success = send_telegram(None, filepath, caption)
                if telegram_success:
                    print(f"✅ Telegram 发送成功")
                else:
                    error_msg = "Telegram 发送失败：send_telegram returned False"
                    print(f"❌ {error_msg}")
                    error_info = _translate_generation_failure(task_id, error_msg, provider='telegram', route='telegram', task_type=task_kind, stage='telegram_failed')
                    _finalize_generation_task(task_id, 'telegram_failed', run_id=run_id, stage='telegram_failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type='TelegramSendFailed', provider=task_provider, route=task_route, task_type=task_kind)
                    try:
                        send_status_notification(task_id, '❌ 发送失败：请检查 bot token/网络/文件路径', '⚠️')
                    except:
                        pass
            except Exception as e:
                error_msg = f"Telegram 发送失败：{str(e)}"
                print(f"❌ {error_msg}")
                error_info = _translate_generation_failure(task_id, error_msg, provider='telegram', route='telegram', task_type=task_kind, stage='telegram_failed', exception_name=type(e).__name__)
                _finalize_generation_task(task_id, 'telegram_failed', run_id=run_id, stage='telegram_failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type=type(e).__name__, provider=task_provider, route=task_route, task_type=task_kind)
                try:
                    send_status_notification(task_id, f'❌ 发送失败：{str(e)[:100]}', '⚠️')
                except:
                    pass
        else:
            update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
            _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

        if telegram_success:
            ok_text = response_meta.get('output_size_warning') or '图片生成成功'
            _finalize_generation_task(task_id, 'succeeded', run_id=run_id, stage='done', progress_text=ok_text, result_file=filename, result_files=[filename], image_count=1, provider=task_provider, route=task_route, task_type=task_kind)
            _record_generation_event(task_id, 'run_succeeded', '图片生成成功', stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': 1})
            send_status_notification(task_id, '✅ 图片生成成功！', '🎉')
            print(f"✅ 任务成功：{task_id}")
        else:
            progress_text = '图片已保存，已按节点开关跳过 Telegram' if not telegram_enabled else '图片已保存，但 Telegram 发送失败'
            if response_meta.get('output_size_warning'):
                progress_text += '；' + response_meta['output_size_warning']
            _finalize_generation_task(
                task_id,
                'succeeded_no_telegram',
                run_id=run_id,
                provider=task_provider,
                route=task_route,
                task_type=task_kind,
                result_file=filename,
                stage='done',
                progress_text=progress_text,
                result_files=[filename],
                image_count=1,
            )
            _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': 1, 'telegram_enabled': telegram_enabled})
            print(f"⚠️ 任务完成但未发送 Telegram: {task_id}")

    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        error_info = _translate_generation_failure(
            task_id,
            error_msg,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            stage='failed',
            exception_name=error_type,
        )

        print(f"")
        print(f"❌ ════════════════════════════════════════")
        print(f"❌  任务失败：{task_id}")
        print(f"❌  错误类型：{error_type}")
        print(f"❌  错误信息：{error_msg}")
        print(f"❌ ════════════════════════════════════════")
        print(f"")

        _finalize_generation_task(task_id, 'failed', run_id=run_id, stage='failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type=error_type, provider=task_provider, route=task_route, task_type=task_kind)
        send_status_notification(task_id, f"❌ 生成失败：{error_info.get('display_error') or error_msg}", '⚠️')


def process_edit_task(
    task_id,
    prompt,
    images,
    params,
    *,
    DEFAULT_GOOGLE_IMAGE_MODEL,
    Path,
    _coerce_google_max_tokens,
    _coerce_google_output_controls,
    _effective_image_ratio,
    _finalize_generation_task,
    _is_generic_19_fidelity_prompt,
    _map_quality_to_gpt_resolution,
    _merge_task_params,
    _record_generation_event,
    _result_image_filenames,
    _should_fallback_to_gpt,
    _start_generation_audit,
    _translate_generation_failure,
    daily_output_dir,
    generate_image_gpt_pool,
    json,
    os,
    save_image,
    save_thumbnail,
    send_status_notification,
    send_telegram,
    send_telegram_result,
    time,
    update_task_fields,
    update_task_status,
    write_obsidian_prompt_sidecar,
    google_pool_edit=None,
):
    """后台线程：处理编辑任务（skill 调用支持 GPT 托底）"""
    run_id = ''
    task_kind = 'google-edit'
    task_provider = 'google_pool' if (params or {}).get('google_provider_route') == 'google_pool' else 'google'
    task_route = 'google_pool_edit' if task_provider == 'google_pool' else 'google_edit'
    try:
        params = dict(params or {})
        params['ratio'] = _effective_image_ratio(prompt, params.get('ratio'), '1:1')
        if _is_generic_19_fidelity_prompt(prompt):
            _merge_task_params(task_id, {
                'ratio': params['ratio'],
                'prompt_fidelity_locked': True,
                'source_ratio_locked': True,
            })
        print(f"✏️ 开始处理编辑任务：{task_id}")
        print(f"📋 完整 params: {json.dumps(params, ensure_ascii=False)}")

        run_id = _start_generation_audit(
            task_id,
            task_kind,
            prompt,
            params,
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )

        # 发送提交通知
        send_status_notification(task_id, '已提交图片编辑任务，请等待...', '✅')

        # 状态 1: 准备中
        update_task_status(task_id, 'preparing', '正在准备编辑...')
        update_task_status(task_id, 'processing', '编辑中...')

        # 调用 API 编辑图片 - 从 params 提取参数
        aspect_ratio = params.get('ratio', '1:1')
        quality = params.get('quality', 'hd')
        model = params.get('model', DEFAULT_GOOGLE_IMAGE_MODEL)
        max_tokens = _coerce_google_max_tokens(params.get('max_tokens'))
        temperature = params.get('temperature')
        feature = params.get('feature', 'edit')
        caller = str(params.get('caller', 'webapp')).lower()
        archive_enabled, telegram_enabled = _coerce_google_output_controls(params)
        params['archive_enabled'] = archive_enabled
        params['telegram_enabled'] = telegram_enabled
        _merge_task_params(task_id, {
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
        })

        # 前端可能传递的是 aspectRatio 而不是 ratio
        if 'aspectRatio' in params:
            aspect_ratio = params.get('aspectRatio', '1:1')

        print(f"📡 调用 API...")
        print(f"   - caller: {caller}")
        print(f"   - aspect_ratio: {aspect_ratio}")
        print(f"   - quality: {quality}")
        print(f"   - model: {model}")
        print(f"   - max_tokens: {max_tokens}")
        if temperature is not None:
            print(f"   - temperature: {temperature}")
        print(f"   - feature: {feature}")
        print(f"   - images: {len(images)} 张")

        # 状态 2: 调用 API
        update_task_status(task_id, 'processing', '正在调用 AI 模型...')
        send_status_notification(task_id, '编辑中... 正在调用 AI 模型...', '🤖')
        _record_generation_event(task_id, 'provider_call_started', '开始调用 Google 图像编辑', stage='calling_api', payload={'provider': task_provider, 'route': task_route})

        # 主路由：编辑接口
        from ..api_client import edit_image

        def progress_cb(stage=None, progress_text=None, heartbeat=False, **extra):
            payload = {}
            if stage is not None:
                payload['stage'] = stage
            if progress_text is not None:
                payload['progress_text'] = progress_text
            if heartbeat:
                payload['heartbeat_at'] = int(time.time())
            payload.update({k: v for k, v in extra.items() if v is not None})
            if payload:
                update_task_fields(task_id, **payload)

        image_data = None
        response_meta = {}
        primary_error = None
        try:
            selected_edit = google_pool_edit if task_provider == "google_pool" else edit_image
            if not selected_edit: raise RuntimeError("Google OAuth账号池适配器未装配")
            image_data, response_meta = selected_edit(
                prompt,
                images,
                aspect_ratio,
                quality,
                model,
                max_tokens=max_tokens,
                temperature=temperature,
                progress_cb=progress_cb,
                **({"task_id": task_id} if task_provider == "google_pool" else {}),
            )
        except Exception as e:
            primary_error = str(e)
            print(f"⚠️ 编辑主路由失败：{primary_error}")

            if _should_fallback_to_gpt(params, primary_error):
                update_task_status(task_id, 'fallback_running', '编辑主路由失败，切换 GPT 托底...')
                send_status_notification(task_id, '编辑主路由失败，切换 GPT 托底中...', '🛟')
                _record_generation_event(task_id, 'fallback_started', 'Google 编辑主路由失败，切换 GPT 托底', stage='fallback_running', severity='warning', payload={'primary_error': primary_error})

                gpt_resolution = params.get('fallback_resolution') or _map_quality_to_gpt_resolution(quality)
                fallback_prompt = (
                    f"请基于用户编辑需求进行生成（原请求为图像编辑，当前走托底生成）：\n{prompt}"
                )
                fallback_result = generate_image_gpt_pool(
                    fallback_prompt,
                    aspect_ratio,
                    gpt_resolution,
                    quality,
                    image_count=1,
                    prompt_mode='smart',
                )
                if not fallback_result.get('success'):
                    fallback_error = fallback_result.get('error', 'unknown')
                    raise RuntimeError(
                        f"编辑主路由失败：{primary_error} | GPT 托底失败：{fallback_error}"
                    )

                telegram_success = False
                if telegram_enabled:
                    update_task_status(task_id, 'processing', '托底成功，正在发送到 Telegram...')
                    send_status_notification(task_id, '托底成功，正在发送图片...', '📤')
                    _record_generation_event(task_id, 'telegram_send_started', '托底编辑成功后开始发送到 Telegram', stage='sending_telegram')
                    telegram_success = send_telegram_result(
                        fallback_result['image_path'],
                        prompt,
                        aspect_ratio,
                        gpt_resolution,
                        image_paths=fallback_result.get('image_paths'),
                    )
                else:
                    update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
                    _record_generation_event(task_id, 'telegram_send_skipped', '托底编辑成功后按节点开关跳过 Telegram', stage='saving')

                result_files = _result_image_filenames(fallback_result)
                image_count = len(result_files) or len(fallback_result.get('image_paths') or [fallback_result.get('image_path')])
                filename = result_files[0] if result_files else os.path.basename(fallback_result['image_path'])
                if telegram_success or not telegram_enabled:
                    ok_text = f'托底编辑成功（共 {image_count} 张）' if image_count > 1 else '托底编辑成功'
                    progress_text = ok_text if telegram_enabled else '托底编辑成功，已按节点开关跳过 Telegram'
                    _finalize_generation_task(
                        task_id,
                        'succeeded' if telegram_enabled else 'succeeded_no_telegram',
                        run_id=run_id,
                        provider='chatgpt_pool',
                        route='gpt_pool_fallback_edit',
                        task_type=task_kind,
                        result_file=filename,
                        stage='done',
                        progress_text=progress_text,
                        result_files=result_files,
                        image_count=image_count,
                        extra={'fallback_source': 'chatgpt_pool', 'primary_error': primary_error},
                    )
                    _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool_fallback_edit', 'image_count': image_count})
                    send_status_notification(task_id, '✅ 托底编辑成功！', '🎉')
                    print(f"✅ 编辑托底成功：{task_id} -> {filename}")
                else:
                    progress_text = '托底编辑成功，但 Telegram 发送失败'
                    _finalize_generation_task(
                        task_id,
                        'succeeded_no_telegram',
                        run_id=run_id,
                        provider='chatgpt_pool',
                        route='gpt_pool_fallback_edit',
                        task_type=task_kind,
                        result_file=filename,
                        stage='done',
                        progress_text=progress_text,
                        result_files=result_files,
                        image_count=image_count,
                        extra={'fallback_source': 'chatgpt_pool', 'primary_error': primary_error},
                    )
                    _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool_fallback_edit', 'image_count': image_count, 'telegram_enabled': telegram_enabled})
                    print(f"⚠️ 编辑托底成功但 Telegram 发送失败：{task_id}")
                return

            raise

        # 状态 3: 保存图片
        update_task_status(
            task_id,
            'processing',
            '正在保存图片...',
            stage='saving',
            bytes_received=response_meta.get('bytes_received'),
            first_byte_at=response_meta.get('first_byte_at'),
            ttfb_ms=response_meta.get('ttfb_ms'),
        )
        send_status_notification(task_id, '编辑中... 正在保存图片...', '💾')

        # 文件命名：生成模型_日期时间
        from datetime import datetime
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        model_name = model.replace("gemini-", "").replace("-image-preview", "").replace("-image", "").replace(".", "")
        filename_base = f"{model_name}_{timestamp}"

        # 确保下载目录存在
        download_dir = daily_output_dir(now)
        download_dir.mkdir(parents=True, exist_ok=True)

        # 保存图片（带扩展名）
        filename_with_ext = f"{filename_base}.png"
        filepath = str(download_dir / filename_with_ext)
        filename = save_image(image_data, filepath)

        # 保存提示词到同名 txt 文件
        txt_path = download_dir / f"{filename_base}.txt"
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(prompt)
        try:
            write_obsidian_prompt_sidecar(Path(filepath), prompt, txt_path=txt_path)
        except Exception as exc:
            print(f"⚠️ 写入 Obsidian 提示词 md 失败: {exc}")
        print(f"💾 已保存图片：{filepath}")
        print(f"💾 已保存提示词：{txt_path}")
        save_thumbnail(filepath, filename)
        _record_native_response(task_id, response_meta, _merge_task_params, _record_generation_event)

        telegram_success = False
        if telegram_enabled:
            # 状态 4: 发送 Telegram
            update_task_status(task_id, 'processing', '正在发送到 Telegram...', stage='sending_telegram')
            send_status_notification(task_id, '编辑中... 正在发送图片...', '📤')
            _record_generation_event(task_id, 'telegram_send_started', '开始发送编辑结果到 Telegram', stage='sending_telegram')
            try:
                print(f"📤 准备发送 Telegram: {filepath}")
                # Telegram caption 限制 1024 字符，为了安全截断到 500
                caption = prompt[:500] + "..." if len(prompt) > 500 else prompt
                telegram_success = send_telegram(None, filepath, caption)
                if telegram_success:
                    print(f"✅ Telegram 发送成功")
                else:
                    error_msg = "Telegram 发送失败：send_telegram returned False"
                    print(f"❌ {error_msg}")
                    error_info = _translate_generation_failure(task_id, error_msg, provider='telegram', route='telegram', task_type=task_kind, stage='telegram_failed')
                    _finalize_generation_task(task_id, 'telegram_failed', run_id=run_id, stage='telegram_failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type='TelegramSendFailed', provider=task_provider, route=task_route, task_type=task_kind)
                    try:
                        send_status_notification(task_id, '❌ 发送失败：请检查 bot token/网络/文件路径', '⚠️')
                    except:
                        pass
            except Exception as e:
                error_msg = f"Telegram 发送失败：{str(e)}"
                print(f"❌ {error_msg}")
                error_info = _translate_generation_failure(task_id, error_msg, provider='telegram', route='telegram', task_type=task_kind, stage='telegram_failed', exception_name=type(e).__name__)
                _finalize_generation_task(task_id, 'telegram_failed', run_id=run_id, stage='telegram_failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type=type(e).__name__, provider=task_provider, route=task_route, task_type=task_kind)
                try:
                    send_status_notification(task_id, f'❌ 发送失败：{str(e)[:100]}', '⚠️')
                except:
                    pass
        else:
            update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
            _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

        # 状态 5: 完成
        if telegram_success:
            ok_text = response_meta.get('output_size_warning') or '图片编辑成功'
            _finalize_generation_task(task_id, 'succeeded', run_id=run_id, stage='done', progress_text=ok_text, result_file=filename, result_files=[filename], image_count=1, provider=task_provider, route=task_route, task_type=task_kind)
            _record_generation_event(task_id, 'run_succeeded', '图片编辑成功', stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': 1})
            send_status_notification(task_id, '✅ 图片编辑成功！', '🎉')
            print(f"✅ 编辑任务成功：{task_id}")
        else:
            progress_text = '图片已保存，已按节点开关跳过 Telegram' if not telegram_enabled else '图片已保存，但 Telegram 发送失败'
            if response_meta.get('output_size_warning'):
                progress_text += '；' + response_meta['output_size_warning']
            _finalize_generation_task(
                task_id,
                'succeeded_no_telegram',
                run_id=run_id,
                provider=task_provider,
                route=task_route,
                task_type=task_kind,
                result_file=filename,
                stage='done',
                progress_text=progress_text,
                result_files=[filename],
                image_count=1,
            )
            _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': 1, 'telegram_enabled': telegram_enabled})
            print(f"⚠️ 任务完成但未发送 Telegram: {task_id}")

    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        error_info = _translate_generation_failure(task_id, error_msg, provider=task_provider, route=task_route, task_type=task_kind, stage='failed', exception_name=error_type)
        print(f"❌ 编辑任务失败：{task_id} - {error_msg}")
        _finalize_generation_task(task_id, 'failed', run_id=run_id, stage='failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type=error_type, provider=task_provider, route=task_route, task_type=task_kind)
        send_status_notification(task_id, f'❌ 编辑失败：{(error_info.get("display_error") or error_msg)[:100]}', '⚠️')


def _is_retryable_generation_error(error_msg):
    """判断是否属于可托底错误（网络/超时/服务暂时不可用）"""
    text = (error_msg or "").lower()

    non_retryable_markers = [
        '内容安全', '安全过滤', '服务端拒绝', 'invalid prompt',
        'invalid api key', 'api key is required', 'missing prompt',
        'http 错误 401', 'http 错误 403', 'unauthorized', 'forbidden',
    ]
    if any(m in text for m in non_retryable_markers):
        return False

    retryable_markers = [
        'timeout', '超时', 'connection', '连接', 'network', '网络',
        'remote end closed', 'connection reset', 'socket',
        'temporarily unavailable', 'service unavailable',
        'http 错误 500', 'http 错误 502', 'http 错误 503', 'http 错误 504',
    ]
    return any(m in text for m in retryable_markers)


def _map_quality_to_gpt_resolution(quality):
    q = (quality or '2k').strip().lower()
    if q in ('hd', '4k'):
        return '4k'
    if q in ('1k', 'low', 'normal'):
        return '1k'
    return '2k'


def _should_fallback_to_gpt(params, primary_error_msg, *, _is_retryable_generation_error):
    """skill 调用时是否触发 GPT 托底"""
    if (params or {}).get('google_provider_route') == 'google_pool':
        return False  # Explicit Google OAuth selection never silently routes to GPT.
    caller = str((params or {}).get('caller', 'webapp')).lower()
    if caller != 'skill':
        return False

    fallback_cfg = (params or {}).get('fallback') if isinstance((params or {}).get('fallback'), dict) else {}
    enabled = fallback_cfg.get('enabled', True)
    target = str(fallback_cfg.get('target', 'gpt')).lower()
    retryable_only = fallback_cfg.get('retryable_only', True)
    force = fallback_cfg.get('force', False)

    if not enabled or target != 'gpt':
        return False

    if force or (not retryable_only):
        return True

    return _is_retryable_generation_error(primary_error_msg)
