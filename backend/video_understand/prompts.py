"""Prompt templates for the video understanding presets."""
from __future__ import annotations

from typing import Iterable, Optional, Tuple


def format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS.d matching WeMM storyboard timecodes."""
    sec = max(0.0, float(seconds))
    minutes = int(sec // 60)
    rem = sec - minutes * 60
    return f"{minutes:02d}:{rem:04.1f}"


def format_h3_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS.mmm matching MiniMax H3 cut timecodes."""
    total_ms = max(0, int(round(float(seconds) * 1000)))
    minutes, rem_ms = divmod(total_ms, 60_000)
    return f"{minutes:02d}:{rem_ms / 1000:06.3f}"


def _extra_section(custom_prompt: str) -> str:
    extra = str(custom_prompt or "").strip()
    if not extra:
        return ""
    return f"\n\n【补充分析要求】\n{extra}"


def _audio_hint(use_audio: bool, *, with_audio: str, without_audio: str) -> str:
    return with_audio if use_audio else without_audio


def build_prompt(
    mode: str,
    *,
    duration: float = 0.0,
    shots: Optional[Iterable[Tuple[float, float]]] = None,
    custom_prompt: str = "",
    use_audio: bool = True,
) -> str:
    """Build the user prompt passed to WeMM-Video for the selected preset mode."""
    dur = max(0.0, float(duration or 0.0))
    dur_str = format_timestamp(dur)
    shot_list = [(float(s), float(e)) for s, e in (shots or ())]
    extra = _extra_section(custom_prompt)

    if mode == "storyboard":
        if shot_list:
            lines = [
                f"- Shot {idx + 1:02d}: {format_timestamp(s)} - {format_timestamp(e)} ({max(0.0, e - s):.1f}s)"
                for idx, (s, e) in enumerate(shot_list)
            ]
            anchor_block = (
                f"\n【精确时间轴锚点（由视频帧切镜检测自动提取，总时长 {dur_str}，共 {len(shot_list)} 个真实镜头）】\n"
                + "\n".join(lines)
                + "\n请严格沿用以上每一个镜头的编号与精确起止时间填写分镜表，禁止自行均分或压缩时间轴，确保最后一镜精确对齐片尾 "
                + dur_str
                + "。\n"
            )
        else:
            anchor_block = (
                f"\n本视频总时长精确为 {dur_str}（{dur:.1f} 秒）。请严格对齐视频中给出的时间标记，禁止均分或压缩时间轴。\n"
                if dur > 0
                else "\n请按时间顺序逐段对齐视频中的真实时间标记。\n"
            )
        audio_col = _audio_hint(
            use_audio,
            with_audio="原始台词（含说话人）与声音设计",
            without_audio="画面叙事与节奏留白（当前未启用音轨）",
        )
        audio_intro = _audio_hint(
            use_audio,
            with_audio="结合完整画面与原始对白/音效，",
            without_audio="基于完整连续画面（未启用音轨），",
        )
        return (
            f"你是一位资深的电影导演兼剪辑师。请对这段总时长 {dur_str} 的视频片段进行专业级“电影拉片解读”，"
            f"{audio_intro}按时间顺序覆盖从 00:00.0 到片尾全部内容，语言精炼专业，不要中途省略。"
            + anchor_block
            + "\n请严格按以下三个部分完整输出：\n\n"
            "## 一、全片剧情与戏剧结构概览\n"
            "概括本场戏的场景氛围、核心人物关系、戏剧冲突升级节点（起、承、转、合，标明真实时间段）以及视听语言特点。\n\n"
            "## 二、逐镜头拉片与 Storyboard（分镜反推表）\n"
            "严格对应每个镜头，使用 Markdown 表格输出完整 Storyboard，包含以下列（每格表述精准凝练）：\n"
            f"| 镜号 | 起止时间 | 景别与机位视角 | 运镜方式 | 画面构图与光影调度 | 人物动作与微表情 | {audio_col} | 导演意图/戏剧功能 |\n\n"
            "## 三、剪辑节奏与视听技法复盘\n"
            "总结本场戏在轴线调度、节奏停顿、景别切换情绪张力以及整体视听设计上的亮点（完整收尾）。"
            + extra
        )

    if mode == "prompt_reverse":
        sound_rule = _audio_hint(
            use_audio,
            with_audio="同时结合原始语音、环境音与配乐情绪提取声画氛围关键词。",
            without_audio="当前仅分析视觉画面，请勿臆测音轨对白。",
        )
        duration_hint = f"（视频总时长 {dur_str}）" if dur > 0 else ""
        return (
            f"你是一位精通 AI 视频生成与摄影导演的提示词工程专家。请仔细观看这段视频{duration_hint}，"
            f"{sound_rule}按时间顺序反推出可直接用于下游视频/图像生成模型的高质量提示词。\n\n"
            "请按以下结构清晰输出（避免空洞套话，全部写可执行的视觉与动态描述）：\n"
            "1. **核心画面与主体设定**：人物外貌、服装材质、道具细节、环境空间与时代/风格基调。\n"
            "2. **构图、光影与色彩美学**：景别变化、主光源方向与色温、反差质感、色调配色与胶片/数字质感。\n"
            "3. **运镜调度与时间段动作指令**：按时间顺序写清镜头运动轨迹（推拉摇移跟升/手持/固定）及主体连贯动作。\n"
            "4. **可直接复用的完整生成提示词（中/英双版）**：各整理一段连贯完整、可直接复制粘贴给生成模型的正向提示词。"
            + extra
        )

    if mode == "h3_prompt":
        dur_h3 = format_h3_timestamp(dur)
        dur_two_dec = f"{dur:.2f}"
        if len(shot_list) == 1:
            h3_anchor_block = (
                f"\n[Detected Timeline Anchors]\n"
                f"Single continuous shot detected (00:00.000 to {dur_h3}, {dur_two_dec}s). "
                "Write ONLY [Shot 1] (NO timestamp prefix on [Shot 1]) describing the continuous visual and audio progression, "
                "and do NOT invent artificial cuts unless an unmistakable hard edit is visibly present.\n"
            )
        elif len(shot_list) >= 2:
            anchor_lines = [
                f"- [Shot 1] (00:00.000 - {format_h3_timestamp(shot_list[0][1])}, "
                f"{max(0.0, shot_list[0][1] - shot_list[0][0]):.2f}s — NO timestamp prefix on [Shot 1])"
            ]
            for idx, (s, e) in enumerate(shot_list[1:], start=2):
                anchor_lines.append(
                    f"- [Shot {idx}] At {format_h3_timestamp(s)}, ... "
                    f"(to {format_h3_timestamp(e)}, {max(0.0, e - s):.2f}s)"
                )
            h3_anchor_block = (
                f"\n[Detected Shot-Cut Anchors — Total Duration {dur_h3} ({dur_two_dec}s), {len(shot_list)} shots]\n"
                + "\n".join(anchor_lines)
                + f"\nFollow these sequential shot indices and MM:SS.mmm cut timestamps through {dur_h3}. "
                "Ignore only obvious false-positive flash or strobe frames if the underlying camera take is continuous.\n"
            )
        elif dur > 0:
            h3_anchor_block = (
                f"\n[Timeline Reference]\n"
                f"Total duration is {dur_h3} ({dur_two_dec}s). Begin with [Shot 1] (NO timestamp prefix). "
                f"Insert [Shot N] At MM:SS.mmm, the camera cuts to ... with strictly increasing timestamps inside 00:00.000-{dur_h3} "
                "only at true visual cuts; if the video is uncut, keep a single [Shot 1].\n"
            )
        else:
            h3_anchor_block = (
                "\n[Timeline Reference]\n"
                "Begin with [Shot 1] (NO timestamp prefix). Insert [Shot N] At MM:SS.mmm, the camera cuts to ... "
                "only at true visual cuts.\n"
            )

        if use_audio:
            speaker_and_audio_rules = (
                "7. **Speakers, Dialogue, Singing, Voiceover & Diegetic Sound**:\n"
                "   - Assign stable global IDs `(S1)`, `(S2)` in order of first vocal appearance (`(S1,S2)` only when already-numbered speakers speak/sing together in unison). "
                "Characters who never vocalize receive NO speaker ID.\n"
                "   - On a speaker's first vocal appearance, establish identity and vocal traits outside `<d>` (speaker type, age/gender, on-screen vs off-screen, pitch, timbre, speaking pace, delivery).\n"
                "   - Put spoken dialogue or lyrics strictly inside `<d>[Language] verbatim text.</d>` in their original language (e.g. `<d>[English] ...</d>`, `<d>[Chinese] ...</d>`, `<d>[Japanese] ...</d>`); use standard punctuation (`,`, `.`, `?`, `!`) and `[unclear]` for unintelligible words—never guess, translate, or paraphrase.\n"
                "   - For off-screen voiceover when an on-screen subject is silent, write `says in an off-screen voiceover: <d>[Language] ...</d> while his/her/their lips remain completely closed.`\n"
                "   - When dialogue or lyrics cross a cut, place `<scenetrans>` at both sides of the cut with explicit continuity phrasing (`continues seamlessly across the cut` or `carries over from the previous shot`). Use `<cutoff>` if speech or singing is truncated by the end of the clip.\n"
                "   - Keep in-scene music (singing, instruments, radio/TV/phone audio) and shot-synced sound effects inside the corresponding shot.\n\n"
                "**overall_soundscape** (1-4 English sentences in one continuous paragraph):\n"
                "- Summarize ambient environment sound, physical/Foley action sounds (footsteps, cloth rustle, handling, impacts, engines, wind, rain), and non-verbal human sounds (breathing, laughter, panting) across the full clip.\n"
                "- Do NOT repeat dialogue, singing, or diegetic music here. Output `N/A` if the clip has no ambient/Foley sound.\n\n"
                "**non_diegetic_music** (1-3 English sentences):\n"
                "- Describe background score audible only to the audience by instrumentation, tempo, rhythm, layering, and volume/dynamic changes.\n"
                "- Forbid abstract emotion words or commentary explaining why the score fits. Keep diegetic music in `integrated_multimodal_description`. Output `N/A` if there is no non-diegetic music."
            )
        else:
            speaker_and_audio_rules = (
                "7. **Audio Track Disabled Mode (`use_audio=False`)**:\n"
                "   - You do NOT have audio access. Do NOT invent dialogue, lyrics, voiceover, speaker IDs `(S1)`, `<d>` tags, or background music.\n"
                "   - Describe only visibly observable events (if someone visibly moves their lips or plays an instrument, describe only the visual motion without fabricating words or sound).\n\n"
                "**overall_soundscape**:\n"
                "- Output `N/A` (audio analysis disabled for this run).\n\n"
                "**non_diegetic_music**:\n"
                "- Output `N/A`"
            )

        extra_req = str(custom_prompt or "").strip()
        extra_block = (
            f"\n\n[Additional User Requirements]\n{extra_req}\n"
            "Apply these requirements while preserving valid MiniMax H3 formatting."
            if extra_req
            else ""
        )

        last_shot_label = f"[Shot {len(shot_list)}]" if shot_list else "[Shot N]"
        return (
            "You are an expert MiniMax H3 video generation prompt engineer. Watch the entire video carefully and reverse-engineer it "
            "into a production-ready MiniMax H3 generation prompt strictly grounded in what is actually visible"
            + (" and audible" if use_audio else " in the video frames")
            + ". Generalize cleanly to whatever genre the video is (live-action narrative, dance/MV, commercial/product, 2D/3D animation, "
            "stop-motion, documentary, sports/action, vlog, tutorial, or motion graphics)."
            + h3_anchor_block
            + "\n[Strict Output Structure]\n"
            "1. Output ONLY the raw MiniMax H3 prompt in English (preserving original language ONLY verbatim inside `<d>[Language] ...</d>` and `\"...\"` visible text). "
            "Do NOT include markdown code fences, headings, bullet lists, explanations, or commentary.\n"
            "2. Default to H3 Base (T2VA) format with these three exact fields in order, separated by blank lines:\n"
            "integrated_multimodal_description: [Shot 1] ...\n\n"
            "overall_soundscape: ...\n\n"
            "non_diegetic_music: ...\n"
            "3. Only if `[Additional User Requirements]` explicitly asks for I2VA / FL2VA / L2VA, prepend the exact H3 alignment instruction line "
            "(for I2VA: `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`; "
            f"for FL2VA: `How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot {len(shot_list) or 'N'}) aligns with the {dur_two_dec}-second mark of the target video.`; "
            f"for L2VA: `How the reference pictures align with the target video — <Picture 1> (from {last_shot_label}) aligns with the {dur_two_dec}-second mark of the target video.`), "
            "followed by one blank line before the three fields. Only if explicitly asked for `Ref2VA`, use the six-section structure "
            "(`subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `overall_soundscape`, `non_diegetic_music`) with consistent `<Subject N>`, `<Picture N>`, `<Video N>`, `<Audio N>` labels.\n\n"
            "[Field Rules — `integrated_multimodal_description`]\n"
            "1. **Medium, Style & Opening Anchors**: Begin `[Shot 1]` directly with the observed visual medium/style (e.g., `Live-action, cinematic`, `Handheld documentary`, `2D-animated`, `3D CG`, `Stop-motion claymation`, `Watercolor animation`, `Vintage film`, `Motion graphics`, `Photorealistic commercial`) and initial shot size. Establish concrete details: subjects (appearance, age/type, outfit materials and colors, screen positions), environment layout, key props, lighting direction/color temperature/contrast, and visual texture. Avoid vague praise words (`beautiful`, `stunning`, `masterpiece`).\n"
            "2. **Concrete Motion & Physics**: Describe continuous physical motion and observable state changes in playback order—body mechanics, posture/weight shifts, choreography, hand-object interactions, facial expressions/gaze, fluid/cloth/hair physics, lighting shifts, or UI/graphic animations. Maintain strict identity, wardrobe, prop, and spatial continuity across shots.\n"
            "3. **Shots & Cuts**: NEVER put a timestamp on `[Shot 1]`. Begin every subsequent shot inline as `[Shot N] At MM:SS.mmm, the camera cuts to ...` (or `the shot cuts to`, `transitions to`, `switches to`, `cross-dissolves to`, `fades to` when matching the actual edit) with strictly increasing timestamps.\n"
            "4. **H3 Camera Grammar**: Weave camera movement into natural English prose inside each shot using H3 canonical terms (`Static Shot`, `Push In`, `Pull Out`, `Zoom In`, `Zoom Out`, `Pan Left`, `Pan Right`, `Truck Left`, `Truck Right`, `Tilt Up`, `Tilt Down`, `Pedestal Up`, `Pedestal Down`, `Arc Shot`, `Tracking Shot`, `POV`, `Shake Slightly`, `Shake Strongly`, `Roll Clockwise`, `Roll Counterclockwise`) with amplitude (`with small amplitude` / `with large amplitude`) and speed (`at slow speed` / `at fast speed`) when meaningful, naming what the camera follows, frames, or reveals. Never tack on standalone camera keyword lists.\n"
            "5. **Visible On-Screen Text**: Quote any visibly readable sign, label, subtitle, banner, UI label, or title card verbatim inside English double quotes `\"...\"` in its original language without translating.\n"
            "6. **Factuality**: Describe only what actually occurs; do not invent unseen details or wrap up with meta plot summaries.\n"
            + speaker_and_audio_rules
            + extra_block
        )

    if mode == "summary":
        duration_hint = f"（总时长 {dur_str}）" if dur > 0 else ""
        audio_part = _audio_hint(
            use_audio,
            with_audio="\n## 三、原始对白与声音氛围\n按时间顺序尽量忠实记录主要对白/旁白（区分说话人）及关键音效/配乐变化。",
            without_audio="\n## 三、视觉节奏与信息要点\n归纳画面叙事逻辑与可提取的关键信息点（当前未启用音轨）。",
        )
        return (
            f"请对这段视频{duration_hint}进行结构化音画理解与内容摘要，严格基于实际观察到的内容输出，不要虚构未出现的细节：\n\n"
            "## 一、全片内容摘要\n"
            "用简洁准确的语言概括视频主题、人物/主体、场景背景与核心事件脉络。\n\n"
            "## 二、关键时间节点事件\n"
            "按真实时间段列出重要画面转换与核心动作节点。"
            + audio_part
            + extra
        )

    if mode == "custom":
        prompt = str(custom_prompt or "").strip()
        if not prompt:
            raise ValueError("自定义分析模式需要填写提问")
        if dur > 0:
            return f"（视频总时长 {dur_str}）\n{prompt}"
        return prompt

    raise ValueError(f"不支持的分析模式: {mode}")
