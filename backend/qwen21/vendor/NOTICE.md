# MFLUX Qwen reference source attribution

Original upstream: https://github.com/mflux-community/mflux
Revision: adcbe85975760d545ca142069713781929898be0
License: MIT; full text in MFLUX-LICENSE.

The two `.original` source snapshots are unmodified, deterministic patch inputs:
- src/mflux/models/qwen21/variants/edit/qwen_image_21_edit.py
- src/mflux/models/qwen21/reference/model/qwen_image21_text_encoder/text_encoder.py

CanvasHub changes are kept in `source_adapter.py`: explicit scheduler selection,
independent reference-resolution/noise control and compatibility with the pinned
Heretic text config's `rope_parameters`. Only the independently downloaded Qwen
checkout receives these changes. The Krea checkout and installed dependencies are
not patched. Runtime copies keep upstream licenses and source headers.

Viggle schedule provenance:
- https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo
- Optional eight-step profile: https://github.com/vanch007/mflux/blob/3d494b7866a221213a3eedb5ae6b995556564960/src/mflux/models/qwen21/model/qwen21_scheduler.py
