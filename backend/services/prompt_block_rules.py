"""Reusable prompt-block rules, including the generic 19-module split.

Primary-type inference, block templates and module tables (filled from the prompt
library templates at import), the generic-19 anchor, constraint, body-shape, quality and
merge rules, and the blocks built from an image analysis. Pure functions and constants
only; the model calls and the generic-19 result cache stay in prompt_skill_client.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from ..prompt_library import TYPE_SPECS, built_in_templates
from .prompt_text_rules import _as_dict, _as_list
from .prompt_image_analysis_rules import _clean_string


PROMPT_BLOCK_IMAGE_GENERIC_19_SYSTEM = """你是图像生成提示词素材块的高保真视觉指纹解析器。
你的唯一任务是直接阅读输入图片，先分类，再逐项记录决定复现结果的客观视觉锚点，最后把锚点归入固定高保真模块体系。体系包含 19 个基础模块，以及人物、人像、时尚、角色图片专属的 body_shape（体形身材）扩展模块。不得调用或复述普通“图片分析”功能，不得凭审美习惯美化、年轻化、瘦身、增肌、简化、补全或替换原图事实。

核心标准：不是“描述得长”，而是“重新生成时不容易把关键类别换掉”。人物年龄感、脸部几何、体态、服装剪裁和材质；商品结构和工艺；建筑体量和立面；场景地标；画幅、裁切、透视、光源、色温、文字层级等高显著性事实都必须被锚定。

处理顺序：
1. primary_type 必须从 portrait、landscape、product、food、architecture、interior、character、scene_concept、animal、fashion、storyboard、illustration、poster、social、infographic、three_d、pattern 中选择，并返回 type_confidence=high/medium/low。
2. 先输出 visual_blueprint。visual_blueprint.global_anchor 只用一句话概括媒介、核心主体和整体视觉身份；不写源尺寸、比例、裁切、详细色彩或局部外观。visual_blueprint.anchors 是唯一事实基线，后续模块只引用这些锚点。
3. 每条全局 anchor 必须有唯一 id、module_type、target、attribute、value、relation、importance、confidence、negative_pair。value 和 relation 只写正向可见事实，所有反向混淆项只能写入 negative_pair。module_type 必须属于下方允许的模块；attribute 只能使用 category/count/shape/proportion/position/orientation/crop/material/texture/color/lighting/camera/relation/text/style/quality/constraint/detail。
4. 每个素材块输出 anchor_ids，引用 visual_blueprint.anchors；也可输出 evidence 作为补充事实。evidence 只能补充该模块的新可见事实，不能改写已存在 anchor。后端会按 anchors 和 evidence 确定性生成详细 content，因此不要为了语言流畅牺牲事实。
5. critical 锚点必须写出区分性，而不是“自然、精致、协调”等评价。例如 value 写“象牙白高光缎面，表面平滑无罗纹”，negative_pair 单独写“罗纹针织或哑光棉质”；不要把“避免……”塞回 value，也不要只写“浅色柔软上衣”。
6. 一条 anchor 只记录一个对象的一项原子视觉事实。眉形、眼型、鼻形、唇形必须拆成不同 anchors；服装品类、领口、肩带、剪裁、面料、光泽、边饰也必须拆开。禁止在一个 value 中用分号打包多个器官、组件或属性来凑数量。
7. 对本图适用且被要求输出的模块，最低原子锚点数量为：goal 2、identity 3、appearance 8、body_shape 6、pose 4、expression 4、clothing 7、makeup_hair 6、accessories 3、subject 4、scene 5、composition 5、camera 4、lighting 5、color 4、style 4、material 5、quality 4、constraints 4、custom 2。看不见的条件模块不要虚构，但一旦输出就必须达到该模块的最低数量。
8. 同一事实只允许出现在 visual_blueprint.anchors 一次；blocks 只用 anchor_ids 引用，不要再把同一句事实复制进 evidence 或 content。content 可留空，避免模型文案覆盖结构化事实。

固定模块：
- module_type 只能使用 goal、identity、appearance、body_shape、pose、expression、clothing、makeup_hair、accessories、subject、scene、composition、camera、lighting、color、style、material、quality、constraints、custom，并按此顺序；每种最多一项。body_shape 只用于画面中存在人物且身体相关区域可见的 portrait、fashion、character；其他类型不要输出。
- 所有图片必须有 goal、subject、composition、color、style、constraints。摄影、写实渲染、商品、建筑、室内和 3D 图必须有 camera、lighting；背景有可辨空间时必须有 scene；材质决定视觉身份时必须有 material。
- goal 只用 2-3 个短锚点概括媒介、核心主体和整体视觉身份；不写源尺寸、宽高比、裁切、详细色彩、局部五官、服装或背景事实，也不写反向限制。
- composition 独占画幅比例、主体占比、边缘裁切、留白、版式和视觉动线；原图尺寸和推荐比例只能在这里完整出现。
- constraints 只用 4-6 条最高风险的反向漂移限制，格式为“类别：不要错误结果”。不得写“保持……”，不得复述其他模块已经写出的正向事实、原图尺寸、主体占比或裁切；画幅只允许保留一条简短的“不要改用明显不同宽高比”限制。优先使用 critical anchor 的 negative_pair，不堆“低质量、水印、8K”等通用词。

人物、人像、时尚图：
- identity：人数、宽范围可见年龄段（如约 30-40 岁、约 40-50 岁）及成熟度线索、人物呈现和主次；年龄段是人物复现的强制锚点，即使只能判断宽范围也不能省略；不猜姓名、职业、精确年龄或无法确认的族群。
- appearance：只记录面部与皮肤，按脸部纵横比例与轮廓、额头/颧骨/下颌/下巴、眉形粗细弧度、眼型大小间距与眼睑、鼻梁长度宽度与鼻尖、唇厚嘴宽、肤色底调与皮肤纹理/修饰的顺序记录。禁止把肩宽、胸腰、躯干或整体身材塞进 appearance，也禁止用“椭圆脸、五官自然”代替几何事实。
- body_shape：独立记录原图实际可见的身体结构与体量，至少拆成肩部宽窄与斜度、颈部长度粗细、锁骨显著度、胸廓/胸部体量、躯干宽窄与厚薄、腰线/腰部体量、可见四肢粗细、整体轮廓或头身比例等原子 anchors；只写裁切范围内能确认的部分，不从脸或服装猜测被遮挡身体。不得美化为“苗条匀称”、不得瘦身、丰胸、增肌、弱化骨架，也不得把衣服的蓬松度误判为人体体量。极近面部特写中身体证据不足时可省略 body_shape。
- pose：躯干朝向、肩线倾斜、头部偏转/俯仰、双臂和双手是否可见、重心、裁切与遮挡；近距离构图不等于自拍。只有手机、持机手、明显伸向镜头的前臂或确定的广角手臂透视可见时才能写“自拍”；否则只描述机位与裁切，并明确禁止添加伸长前臂、手掌或手机。
- expression：眼睑张力、视线目标、嘴唇开合与嘴角幅度、面颊参与程度、情绪强度。
- clothing：准确品类、领口/肩带/袖型、剪裁贴合与松量、边饰宽度和覆盖比例、层次；面料类别、织法、光泽和垂坠不得被泛化。
- makeup_hair：发际线、分缝、顶部蓬松度、发丝朝向、马尾/发髻等束发类别、碎发；底妆覆盖、眉眼妆、唇色和后期磨皮程度。
- accessories：逐件记录佩戴位置、数量、耳钉/耳环/耳坠等类别、形状、尺寸、链条粗细、吊坠比例和材质。
- scene：按左上、左中、中央后方、右中、右侧边界逐区清点背景地标；对灯具、门洞、沙发、椅背、窗帘等分别记录类别、颜色、材质、相对人物的位置与遮挡，不得概括成“现代室内背景”。
- color：以中性参照物（白墙、白衣、灰家具）判断白平衡，再记录肤色冷暖；不要因肤色本身偏暖就把整图误判为暖色调。
- 人像/时尚/角色通常至少覆盖 12 个适用模块；只要肩颈、胸部、躯干、腰部或四肢有足够可见区域，就必须输出独立 body_shape；appearance、body_shape、clothing、makeup_hair、composition、camera、lighting、scene、material 必须优先记录区分性锚点。

其它类型的类型化核对：
- product/three_d：主体类别、外轮廓和比例、组件数量/连接/开孔/按钮位置、材料与表面处理、Logo/包装文字、摆放、镜头、反射、高光与投影。
- architecture/interior：体块/房间比例、层数或开间、门窗与立面节奏、家具清单及方位、动线和视轴、墙地顶材质、尺度参照、透视消失方向与光线。
- landscape/scene_concept：地貌几何、地平线高度、前中后景、关键地标及方位、植被密度、水体状态、天气大气、尺度关系和色彩分区。
- food：菜品类别与数量、切法/熟度/汁水、摆盘顺序、器皿形状尺寸、配料和装饰方位、表面质感、蒸汽冷凝、镜头与光泽。
- animal：物种/品种外观、可见年龄阶段、头身和四肢比例、毛羽长度密度与花纹分布、姿势、神态、接触关系和栖息环境。
- illustration/character：轮廓、头身比例、服装/装备结构、线条粗细、平涂/厚涂/水彩/赛璐璐等上色方式、材质笔触、世界观元素和调色。
- poster/social/infographic：画布比例、网格与对齐、标题/副标题/数据文字的准确内容、行数、位置、层级、字体类别、图标节点连线、Logo/安全区；不能只写“现代排版”。
- pattern：纹样单元形状与数量、旋转/镜像/错位重复规则、尺度、密度、间距、边缘接缝、底色与印刷/织物质感。
- storyboard：景别、机位、角色调度、动作瞬间、视线、运镜暗示和前后镜头连续性。
- 非人物类型通常至少覆盖 7-9 个适用模块，以关键实体、几何、空间、表面、光学、光照、色彩、环境、处理和防漂移锚点的覆盖为准，不为凑数虚构。
- 海报、信息图、UI、图案等平面图不虚构摄影机、景深、棚拍灯光和实体材质；camera/lighting 只在原图确有摄影或三维渲染证据时输出。所有类型都先做“实体/组件清单 + 相对位置关系 + 容易误换类别”三遍核对，避免只描述主物体而漏掉决定复现的次级地标。

输出要求：
1. name 使用固定模块的中文名；compact_content 是 10-50 个中文字符的真正精简版；english_content 可省略，优先保证中文 anchors 完整；tags 1-5 个。
2. content 可省略或写为 anchors 的忠实串联，后端会以 anchors 为准重建详细 content。
3. 不写“图片中、画面中出现、看起来、可能、似乎”等分析口吻；置信度不足时降低 confidence，但仍写最窄的可见范围。
4. 可读文字对海报、包装、信息图、UI 和品牌图形是关键事实，放入 custom 并记录文字、行数、位置、对齐和字体类别；普通场景中无关小字可忽略。
5. 输出前核对：主体数量、几何、占比、方位、裁切、材质类别、镜头透视、背景地标、光源方向、冷暖和后期处理是否都存在 critical/major 锚点；任何 critical 锚点缺失都继续补足。
6. 输出严格 JSON，不要 Markdown、解释或代码围栏。

JSON 形状：
{"primary_type":"portrait","type_confidence":"high","visual_blueprint":{"global_anchor":"室内写实摄影中的单名成年女性肖像，视觉身份自然克制","anchors":[{"id":"a1","module_type":"appearance","target":"脸型","attribute":"shape","value":"纵向偏长的窄椭圆轮廓，下颌向尖窄下巴收束","relation":"正脸轻微侧转时仍保持较长中庭","importance":"critical","confidence":"high","negative_pair":"短圆脸、饱满双颊或小圆下巴"}],"spatial_relations":[],"visible_text":[]},"blocks":[{"name":"外貌","module_type":"appearance","anchor_ids":["a1"],"evidence":[],"compact_content":"长窄椭圆脸与成熟克制五官","english_content":"","tags":["长窄脸"]}]}"""

PROMPT_BLOCK_MODULE_ALIASES = {
    "character_identity": "identity", "role": "identity", "人物身份": "identity", "角色身份": "identity", "身份": "identity",
    "looks": "appearance", "visual_traits": "appearance", "外貌": "appearance",
    "body_shape": "body_shape", "body_type": "body_shape", "physique": "body_shape", "figure": "body_shape",
    "体形": "body_shape", "体型": "body_shape", "身材": "body_shape", "体形身材": "body_shape",
    "action": "pose", "动作": "pose", "姿态": "pose", "动作姿态": "pose",
    "facial_expression": "expression", "表情": "expression", "表情视线": "expression",
    "outfit": "clothing", "costume": "clothing", "服装": "clothing", "服装造型": "clothing",
    "hair": "makeup_hair", "makeup": "makeup_hair", "妆发": "makeup_hair",
    "target": "goal", "生成目标": "goal", "props": "accessories", "配饰": "accessories", "主体": "subject", "场景": "scene",
    "layout": "composition", "构图": "composition", "镜头": "camera", "光线": "lighting",
    "palette": "color", "色彩": "color", "风格": "style", "视觉风格": "style",
    "texture": "material", "材质": "material", "质量": "quality", "负面": "constraints",
    "negative": "constraints", "negative_prompt": "constraints", "约束": "constraints",
}

PROMPT_BLOCK_GENERIC_MODULE_LABELS = {
    "goal": "生成目标", "identity": "身份", "appearance": "外貌", "body_shape": "体形身材", "pose": "动作姿态", "expression": "表情视线",
    "clothing": "服装造型", "makeup_hair": "妆发", "accessories": "配饰", "subject": "主体",
    "scene": "场景环境", "composition": "构图", "camera": "视角与镜头", "lighting": "光线",
    "color": "色彩", "style": "视觉风格", "material": "材质细节", "quality": "质量要求",
    "constraints": "负面约束", "custom": "自定义素材",
}

PROMPT_BLOCK_GENERIC_MODULE_DETAIL_HINTS = {
    "goal": "只概括媒介、核心主体和整体视觉身份；不写画幅、裁切、详细色彩或局部外观。",
    "identity": "人数、可确认年龄阶段、人物呈现和主次关系；不猜姓名、职业、精确年龄或无法确认的族群。",
    "appearance": "只记录脸型轮廓、眉眼、鼻唇、肤色与皮肤纹理；不得混入肩宽、胸腰、躯干或整体身材。",
    "body_shape": "独立记录可见肩宽、颈长、锁骨、胸廓/胸部、躯干、腰线、四肢体量、身体轮廓与头身比例；不猜被服装或裁切遮挡的部分。",
    "pose": "身体朝向、肩颈、头部角度、手臂/手势、重心、裁切与遮挡。",
    "expression": "眼睑眼神、视线目标、嘴部状态和情绪强度。",
    "clothing": "服装品类、颜色、领口/肩带/袖型、版型贴合、面料光泽、边饰与层次。",
    "makeup_hair": "发色长度、分缝/束发、发丝状态；底妆、眉眼妆和唇色。",
    "accessories": "佩戴部位、数量、形状、尺寸、颜色、材质和层叠关系。",
    "subject": "核心主体、数量、主次以及与道具或背景的直接关系。",
    "scene": "空间类型、背景物方位、表面材质、远近层次、虚实与遮挡关系。",
    "composition": "独占画幅、景别裁切、主体位置占比、留白、前中后景和视觉动线。",
    "camera": "机位高度、俯仰/侧正角度、距离、透视、焦点与景深；不猜设备或精确焦段。",
    "lighting": "主光来源方向、软硬、补光/环境光、高光、阴影落点和曝光关系。",
    "color": "主辅点缀色、冷暖、白平衡、饱和度、明度和对比关系。",
    "style": "媒介、写实度、成像质感、后期处理和情绪；避免重复色彩与光线。",
    "material": "对象对应的材质、纹理、透明度、粗糙度和反射表现。",
    "quality": "当前画面需要保留的边缘、纹理、肤质、渐变或层次，不写通用 8K 套话。",
    "constraints": "只写 4-6 条最高风险的“类别：不要错误结果”；不复述任何正向事实、尺寸、主体占比或裁切。",
    "custom": "仅容纳无法归入其他模块且复现必需的文字、符号或独特关系。",
}

PROMPT_BLOCK_GENERIC_MIN_DETAIL_CHARS = {
    "goal": 20, "identity": 28, "appearance": 48, "body_shape": 44, "pose": 38, "expression": 30,
    "clothing": 48, "makeup_hair": 38, "accessories": 24, "subject": 36,
    "scene": 48, "composition": 44, "camera": 36, "lighting": 44,
    "color": 36, "style": 34, "material": 34, "quality": 28,
    "constraints": 28, "custom": 22,
}

PROMPT_BLOCK_GENERIC_MIN_DETAIL_CLAUSES = {
    "appearance": 3, "body_shape": 3, "pose": 3, "clothing": 3, "scene": 3, "composition": 3,
    "camera": 3, "lighting": 3, "color": 3, "material": 3,
}

PROMPT_BLOCK_GENERIC_VISUAL_MODULES = {
    "identity", "appearance", "body_shape", "pose", "expression", "clothing", "makeup_hair", "accessories",
    "subject", "scene", "composition", "camera", "lighting", "color", "style", "material",
}

PROMPT_BLOCK_GENERIC_BASE_REQUIRED_MODULES = {
    "goal", "subject", "composition", "color", "style", "constraints",
}

PROMPT_BLOCK_GENERIC_REQUIRED_MODULES_BY_TYPE = {
    "portrait": {
        "identity", "appearance", "pose", "expression", "clothing", "makeup_hair",
        "scene", "camera", "lighting", "material", "quality",
    },
    "fashion": {
        "identity", "appearance", "pose", "expression", "clothing", "makeup_hair",
        "scene", "camera", "lighting", "material", "quality",
    },
    "character": {
        "identity", "appearance", "pose", "expression", "clothing", "makeup_hair",
        "composition", "lighting", "material", "quality",
    },
    "landscape": {"scene", "camera", "lighting", "material", "quality"},
    "scene_concept": {"scene", "camera", "lighting", "material", "quality"},
    "product": {"camera", "lighting", "material", "quality"},
    "food": {"camera", "lighting", "material", "quality"},
    "architecture": {"scene", "camera", "lighting", "material", "quality"},
    "interior": {"scene", "camera", "lighting", "material", "quality"},
    "animal": {"camera", "lighting", "material", "quality"},
    "three_d": {"camera", "lighting", "material", "quality"},
    "storyboard": {"scene", "camera", "lighting", "pose"},
    "illustration": {"quality"},
    "poster": {"custom", "quality"},
    "social": {"custom", "quality"},
    "infographic": {"custom", "quality"},
    "pattern": {"material", "quality"},
}

PROMPT_BLOCK_GENERIC_MIN_MODULES_BY_TYPE = {
    "portrait": 12, "fashion": 12, "character": 12,
    "landscape": 9, "scene_concept": 9, "product": 9, "food": 9,
    "architecture": 9, "interior": 9, "animal": 9, "three_d": 9,
    "storyboard": 8, "illustration": 7, "poster": 7, "social": 7,
    "infographic": 7, "pattern": 7,
}

PROMPT_BLOCK_GENERIC_MIN_ANCHORS = {
    "goal": 2,
    "identity": 3,
    "appearance": 8,
    "body_shape": 6,
    "pose": 4,
    "expression": 4,
    "clothing": 7,
    "makeup_hair": 6,
    "accessories": 3,
    "subject": 4,
    "scene": 5,
    "composition": 5,
    "camera": 4,
    "lighting": 5,
    "color": 4,
    "style": 4,
    "material": 5,
    "quality": 4,
    "constraints": 4,
    "custom": 2,
}

PROMPT_BLOCK_GENERIC_ANCHOR_ATTRIBUTES = {
    "category", "count", "shape", "proportion", "position", "orientation", "crop",
    "material", "texture", "color", "lighting", "camera", "relation", "text", "style",
    "quality", "constraint", "detail",
}

PROMPT_BLOCK_GENERIC_ANCHOR_IMPORTANCE = {"critical", "major", "supporting"}
PROMPT_BLOCK_GENERIC_ANCHOR_CONFIDENCE = {"high", "medium"}

PROMPT_BLOCK_GENERIC_TYPE_FIDELITY_CONTEXT = {
    "portrait": "人物：可见年龄范围与成熟度；脸部纵横比例、颧骨/下颌/下巴；眉眼鼻唇几何；肤色底调、皮肤纹理与磨皮；体形身材独立记录肩宽、颈长、锁骨、胸腰和躯干体量；发型结构；服装剪裁、材质和边饰；配饰类别；姿态裁切；背景地标。",
    "fashion": "时尚：人物稳定外观；体形身材独立记录肩腰比例、躯干与四肢体量；服装品类和廓形；领口肩带袖型；松量与贴合；织法、垂坠、光泽、透明度；缝线蕾丝刺绣等工艺；配饰搭配；展示姿态和镜头。",
    "character": "角色：体形身材独立记录骨架、肩腰、躯干/四肢体量和头身比例；脸部与发型；服装/盔甲层级和材料；装备数量及佩戴位置；姿势、表情、世界观地标、光线和调色。",
    "landscape": "风景：地貌几何、地平线、前中后景、地标方位、植被密度、水体状态、天气大气、尺度参照、光照和色彩分区。",
    "scene_concept": "场景概念：文明与地理结构、关键建筑/设施、遗留物和叙事线索、尺度关系、空间层次、镜头、天气光线和材料。",
    "product": "商品：外轮廓比例、组件数量和连接、开孔按钮位置、材料与表面处理、Logo/包装文字、摆放角度、镜头、反射高光与投影。",
    "food": "食物：菜品类别数量、切法熟度汁水、摆盘次序、器皿尺寸、配料方位、表面质感、蒸汽冷凝、镜头和光泽。",
    "architecture": "建筑：体块比例和层级、层数/开间、门窗幕墙节奏、立面材料、入口与道路景观、尺度参照、透视消失方向和光线。",
    "interior": "室内：功能分区、动线视轴、开间层高、家具清单和坐标、墙地顶材料、软装、镜头透视、窗光和人工光关系。",
    "animal": "动物：物种/品种外观、可见年龄、头身和四肢比例、毛羽长度密度与花纹分布、动作神态、接触关系和栖息环境。",
    "storyboard": "分镜：镜头目的和景别、机位、角色调度、动作瞬间、视线关系、运镜暗示、空间和服装道具连续性。",
    "illustration": "插画：叙事瞬间、主体轮廓和比例、线条粗细节奏、上色方式、笔触/网点/纸张质感、调色、构图和留白。",
    "poster": "海报：画布比例、主视觉、网格与对齐、标题副标题准确文字、行数位置层级、字体类别、Logo 和安全区。",
    "social": "社交图：平台画幅、首屏视觉钩子、标题准确文字、内容层级、品牌色、图形系统、头像按钮和裁切安全区。",
    "infographic": "信息图：数据主题与结论、章节分组、节点连线、标签文字、图标关系、阅读顺序、字号对比和密度。",
    "three_d": "3D：几何体块与圆角比例、组件连接、材质 shader 的粗糙度/金属度/透射、背景地面、灯组、反射与渲染方式。",
    "pattern": "图案：纹样单元形状数量、旋转镜像错位重复、尺度密度间距、边缘接缝、底色和印刷/织物质感。",
}

PROMPT_BLOCK_GENERIC_ANALYSIS_MARKERS = (
    "图片中可见", "图片中有", "画面中出现", "画面中的", "看起来", "似乎",
    "可能是", "可能为", "推测是", "推测为",
)

PROMPT_BLOCK_GENERIC_EMPTY_DETAIL_PHRASES = (
    "高质量", "高清", "超高清", "精致", "细腻", "自然", "真实", "主体突出", "主体清晰",
    "画面和谐", "色彩和谐", "氛围感", "电影感", "高级感", "细节丰富", "专业摄影",
    "最佳质量", "杰作", "8k", "8K",
)

PROMPT_BLOCK_GENERIC_DETAIL_EVIDENCE_PATTERNS = (
    r"\d|单个|两个|两枚|一对|多层|少量|大面积|小面积|占比|比例|尺寸",
    r"黑|白|灰|红|橙|黄|绿|青|蓝|紫|粉|棕|金|银|米色|肤色|冷色|暖色|低饱和|高饱和",
    r"左|右|上|下|前|后|中央|居中|边缘|顶部|底部|侧面|朝向|倾斜|裁切|遮挡|留白|层级|远近",
    r"圆|椭圆|方|矩形|三角|弧形|细长|宽大|窄|厚|薄|轮廓|领口|肩带|袖|边饰|褶皱",
    r"丝|缎|棉|针织|蕾丝|皮革|金属|玻璃|木|石|塑料|陶瓷|绒|纹理|光泽|哑光|透明|反射|粗糙",
    r"特写|近景|中景|全景|半身|全身|平视|俯视|仰视|侧视|透视|焦点|景深|虚化|机位|拍摄距离",
    r"主光|侧光|逆光|顶光|窗光|柔光|硬光|漫射|补光|环境光|高光|阴影|暗部|曝光|明暗",
    r"抬|低|转|倾|伸|弯|握|搭|靠|贴合|垂落|交叠|环绕|连接|接触|位于|靠近|远离|关系",
)
PROMPT_BLOCK_MODULE_LABELS = dict(PROMPT_BLOCK_GENERIC_MODULE_LABELS)

PROMPT_BLOCK_TEMPLATES = {
    str(template["primary_type"]): template
    for template in built_in_templates()
}
PROMPT_BLOCK_PRIMARY_TYPES = set(PROMPT_BLOCK_TEMPLATES)
PROMPT_BLOCK_MODULE_TYPE_OWNERS: dict[str, set[str]] = {}
for _prompt_block_template in PROMPT_BLOCK_TEMPLATES.values():
    for _prompt_block_module in _prompt_block_template.get("modules") or []:
        _module_key = str(_prompt_block_module.get("key") or "").strip()
        _module_label = str(_prompt_block_module.get("label") or "").strip()
        if not _module_key:
            continue
        PROMPT_BLOCK_MODULE_LABELS.setdefault(_module_key, _module_label or _module_key)
        if _module_label:
            _alias_key = _module_label.lower().replace("-", "_").replace(" ", "_")
            PROMPT_BLOCK_MODULE_ALIASES.setdefault(_alias_key, _module_key)
        if str(_prompt_block_module.get("kind") or "") == "specific":
            PROMPT_BLOCK_MODULE_TYPE_OWNERS.setdefault(_module_key, set()).add(str(_prompt_block_template["primary_type"]))


def _split_rule_module_labels(split_rule: dict[str, Any] | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    for module in (split_rule or {}).get("modules") or []:
        if not isinstance(module, dict) or module.get("enabled") is False:
            continue
        key = str(module.get("key") or "").strip()
        if key:
            labels[key] = str(module.get("label") or key).strip() or key
    return labels


def _normalize_prompt_block_type(value: Any, module_labels: dict[str, str] | None = None) -> str:
    raw = str(value or "custom").strip().lower().replace("-", "_").replace(" ", "_")
    labels = {**PROMPT_BLOCK_MODULE_LABELS, **(module_labels or {})}
    if raw in labels:
        return raw
    normalized = PROMPT_BLOCK_MODULE_ALIASES.get(raw, raw)
    if normalized not in labels:
        return "custom"
    return normalized


PROMPT_BLOCK_TYPE_HINTS = (
    ("storyboard", ("分镜", "镜头脚本", "storyboard", "shot list")),
    ("infographic", ("信息图", "数据图表", "流程图", "仪表盘", "infographic", "data visualization", "dashboard")),
    ("pattern", ("无缝图案", "连续纹样", "平铺纹理", "seamless pattern", "repeat pattern")),
    ("three_d", ("3d视觉", "3d 视觉", "三维渲染", "立体渲染", "3d render", "cgi render")),
    ("fashion", ("服装设计", "时装", "穿搭", "秀场", "lookbook", "fashion editorial")),
    ("food", ("美食", "食物摄影", "菜品", "餐饮", "food photography", "dish", "cuisine")),
    ("interior", ("室内设计", "室内空间", "客厅", "卧室", "interior design")),
    ("architecture", ("建筑外观", "建筑设计", "建筑摄影", "architecture", "facade")),
    ("product", ("商品", "产品图", "电商", "包装设计", "product shot", "e-commerce", "packaging")),
    ("animal", ("动物", "宠物", "猫咪", "小狗", "wildlife", "pet portrait")),
    ("landscape", ("风景", "自然景观", "山川", "海岸", "landscape", "scenery")),
    ("character", ("角色设定", "角色设计", "人物设定", "character design", "character sheet")),
    ("scene_concept", ("场景概念", "环境概念", "世界观场景", "concept environment", "environment design")),
    ("social", ("小红书", "社交媒体", "社媒", "公众号首图", "social media", "instagram post")),
    ("poster", ("海报", "主视觉", "kv", "banner", "poster", "key visual", "book cover", "封面")),
    ("portrait", ("人像", "肖像", "人物写真", "portrait", "headshot")),
    ("illustration", ("插画", "漫画", "绘本", "illustration", "comic")),
)


def _infer_prompt_block_primary_type_from_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    for primary_type, markers in PROMPT_BLOCK_TYPE_HINTS:
        if any(marker in normalized for marker in markers):
            return primary_type
    return ""


def _infer_prompt_block_primary_type_from_modules(data: Any) -> str:
    payload = data if isinstance(data, dict) else {}
    raw_blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    scores: dict[str, int] = {}
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        module_type = _normalize_prompt_block_type(item.get("module_type") or item.get("type"))
        for owner in PROMPT_BLOCK_MODULE_TYPE_OWNERS.get(module_type, set()):
            scores[owner] = scores.get(owner, 0) + 1
    if not scores:
        return ""
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return ""
    return ranked[0][0]


def _prompt_block_template_context(primary_type: str, split_rule: dict[str, Any] | None = None) -> str:
    template = split_rule or PROMPT_BLOCK_TEMPLATES.get(str(primary_type or "").strip())
    if not template:
        return "拆分规则：未指定；请根据原文判断 primary_type，并按通用语义拆分。"
    modules = []
    for module in template.get("modules") or []:
        if not isinstance(module, dict) or module.get("enabled") is False:
            continue
        key = str(module.get("key") or "").strip()
        label = str(module.get("label") or "").strip()
        hint = str(module.get("hint") or "").strip()
        if key:
            required = "，重点模块" if module.get("required") else ""
            modules.append(f"- {key}（{label or key}{required}）：{hint}" if hint else f"- {key}（{label or key}{required}）")
    options = template.get("options") if isinstance(template.get("options"), dict) else {}
    granularity = {"compact": "精简", "balanced": "均衡", "detailed": "详细"}.get(str(options.get("granularity") or "balanced"), "均衡")
    max_blocks = max(3, min(30, int(options.get("max_blocks") or 18)))
    return "\n".join([
        f"拆分规则：{template.get('name') or primary_type}（rule_id={template.get('id') or 'system'}，version={template.get('version') or 1}，primary_type={primary_type}）",
        f"拆分粒度：{granularity}；最多输出 {max_blocks} 个素材块。",
        "该类型允许并优先使用以下模块；原文没有对应信息时不要强行生成：",
        *modules,
    ])


def _normalize_extracted_prompt_blocks(
    data: Any,
    primary_type: str = "",
    split_rule: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload = data if isinstance(data, dict) else {}
    raw_blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    applicable_type = str(primary_type or "").strip()
    if applicable_type not in PROMPT_BLOCK_PRIMARY_TYPES:
        applicable_type = ""
    blocks: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    module_labels = _split_rule_module_labels(split_rule)
    allowed_modules = set(module_labels)
    options = (split_rule or {}).get("options") if isinstance((split_rule or {}).get("options"), dict) else {}
    max_blocks = max(3, min(30, int(options.get("max_blocks") or 24)))
    for item in raw_blocks[:30]:
        if not isinstance(item, dict):
            continue
        content = _clean_string(item.get("content") or item.get("text"), 12000)
        if not content:
            continue
        module_type = _normalize_prompt_block_type(item.get("module_type") or item.get("type"), module_labels)
        if allowed_modules and module_type not in allowed_modules:
            continue
        name = _clean_string(item.get("name") or item.get("label"), 120)
        if not name:
            name = module_labels.get(module_type) or PROMPT_BLOCK_MODULE_LABELS.get(module_type, "素材块")
        key = (module_type, re.sub(r"\s+", " ", content).lower())
        if key in seen:
            continue
        seen.add(key)
        tags = []
        for tag in item.get("tags") if isinstance(item.get("tags"), list) else []:
            clean_tag = _clean_string(tag, 32).lstrip("#")
            if clean_tag and clean_tag not in tags:
                tags.append(clean_tag)
        blocks.append({
            "name": name,
            "module_type": module_type,
            "content": content,
            "compact_content": _clean_string(item.get("compact_content") or item.get("compact"), 6000),
            "english_content": _clean_string(item.get("english_content") or item.get("english"), 12000),
            "applicable_types": [applicable_type] if applicable_type else [],
            "tags": tags[:12],
        })
    if not blocks:
        raise ValueError("没有从输入内容中拆出有效素材块")
    return blocks[:max_blocks]


def _split_rule_snapshot(split_rule: dict[str, Any] | None) -> dict[str, Any]:
    if not split_rule:
        return {}
    return {
        "id": str(split_rule.get("id") or ""),
        "name": str(split_rule.get("name") or ""),
        "primary_type": str(split_rule.get("primary_type") or ""),
        "version": int(split_rule.get("version") or 1),
        "system": bool(split_rule.get("system")),
        "base_template_id": str(split_rule.get("base_template_id") or ""),
        "modules": [dict(module) for module in (split_rule.get("modules") or []) if isinstance(module, dict)],
        "options": dict(split_rule.get("options") or {}),
    }


def generic_19_prompt_block_split_rule() -> dict[str, Any]:
    """Return the backward-compatible high-fidelity module scope used by Pinterest splitting."""
    return {
        "id": "generic_19",
        "name": "通用高保真模块",
        "primary_type": "",
        "version": 6,
        "system": True,
        "base_template_id": "",
        "modules": [
            {
                "key": key,
                "label": label,
                "hint": PROMPT_BLOCK_GENERIC_MODULE_DETAIL_HINTS.get(key, "仅在输入中存在明确证据时输出该模块。"),
                "required": key in PROMPT_BLOCK_GENERIC_BASE_REQUIRED_MODULES,
                "kind": "common",
                "enabled": True,
            }
            for key, label in PROMPT_BLOCK_GENERIC_MODULE_LABELS.items()
        ],
        "options": {
            "granularity": "visual_fingerprint",
            "max_blocks": len(PROMPT_BLOCK_GENERIC_MODULE_LABELS),
            "fact_source": "anchors",
        },
    }


def _generic_19_cache_key(
    image_url: str,
    primary_type: str,
    user_direction: str,
    provider_id: str,
    model: str,
    reasoning_effort: str,
    split_rule: dict[str, Any] | None,
) -> str:
    rule_version = int((split_rule or {}).get("version") or 6)
    system_fingerprint = hashlib.sha256(PROMPT_BLOCK_IMAGE_GENERIC_19_SYSTEM.encode("utf-8")).hexdigest()
    digest = hashlib.sha256()
    for value in (
        f"generic_19:v{rule_version}",
        system_fingerprint,
        str(primary_type or ""),
        str(user_direction or ""),
        str(provider_id or ""),
        str(model or ""),
        str(reasoning_effort or ""),
        str(image_url or ""),
    ):
        digest.update(value.encode("utf-8", errors="ignore"))
        digest.update(b"\0")
    return digest.hexdigest()


_GENERIC_19_TYPE_SPEC_INDEX = {
    str(spec.get("id") or "").strip(): spec
    for spec in TYPE_SPECS
    if isinstance(spec, dict) and str(spec.get("id") or "").strip()
}
_GENERIC_19_ANCHOR_MAX_BY_MODULE = {
    "goal": 3,
    "appearance": 16,
    "body_shape": 12,
    "clothing": 14,
    "makeup_hair": 12,
    "scene": 14,
    "composition": 12,
    "camera": 10,
    "lighting": 12,
    "material": 12,
    "constraints": 6,
    "custom": 14,
}
_GENERIC_19_CONSTRAINT_SOURCE_LIMIT = 5
_GENERIC_19_CONSTRAINT_MODULE_PRIORITIES = {
    "identity": 100,
    "appearance": 99,
    "body_shape": 97,
    "clothing": 96,
    "makeup_hair": 94,
    "pose": 92,
    "subject": 90,
    "material": 88,
    "scene": 86,
    "composition": 74,
    "camera": 72,
    "style": 70,
    "color": 68,
    "lighting": 66,
    "custom": 58,
}
_GENERIC_19_ATTRIBUTE_LABELS = {
    "category": "类别",
    "count": "数量",
    "shape": "形状",
    "proportion": "比例",
    "position": "位置",
    "orientation": "朝向",
    "crop": "裁切",
    "material": "材质",
    "texture": "纹理",
    "color": "色彩",
    "lighting": "光线",
    "camera": "镜头",
    "relation": "关系",
    "text": "文字",
    "style": "风格",
    "quality": "细节",
    "constraint": "约束",
    "detail": "细节",
}
_GENERIC_19_CRITICAL_MODULES_BY_TYPE = {
    "portrait": {"identity", "appearance", "body_shape", "clothing", "makeup_hair", "scene", "composition", "camera", "lighting", "material", "constraints"},
    "fashion": {"identity", "appearance", "body_shape", "clothing", "makeup_hair", "composition", "camera", "lighting", "material", "constraints"},
    "character": {"identity", "appearance", "body_shape", "clothing", "makeup_hair", "scene", "composition", "lighting", "material", "constraints"},
    "product": {"subject", "composition", "camera", "lighting", "material", "color", "constraints"},
    "food": {"subject", "composition", "camera", "lighting", "material", "color", "constraints"},
    "architecture": {"subject", "scene", "composition", "camera", "lighting", "material", "constraints"},
    "interior": {"subject", "scene", "composition", "camera", "lighting", "material", "constraints"},
    "landscape": {"subject", "scene", "composition", "camera", "lighting", "color", "constraints"},
    "scene_concept": {"subject", "scene", "composition", "camera", "lighting", "color", "constraints"},
    "animal": {"subject", "scene", "composition", "camera", "lighting", "material", "constraints"},
    "storyboard": {"subject", "scene", "composition", "camera", "pose", "constraints"},
    "illustration": {"subject", "composition", "color", "style", "material", "constraints"},
    "poster": {"subject", "composition", "color", "style", "custom", "constraints"},
    "social": {"subject", "composition", "color", "style", "custom", "constraints"},
    "infographic": {"subject", "composition", "color", "style", "custom", "constraints"},
    "three_d": {"subject", "composition", "camera", "lighting", "material", "color", "constraints"},
    "pattern": {"subject", "composition", "color", "style", "material", "constraints"},
}
_GENERIC_19_BODY_SHAPE_PRIMARY_TYPES = {"portrait", "fashion", "character"}
_GENERIC_19_BODY_SHAPE_ANCHOR_PATTERN = re.compile(
    r"体形|体型|身材|体态(?:轮廓|比例|体量)|"
    r"(?:身体|人体|人物|全身|上身)(?:轮廓|比例|体量|宽窄|厚薄)|"
    r"骨架|骨骼感|肩宽|肩部宽度|肩颈(?:比例|宽窄|体量)?|"
    r"颈长|颈部(?:长度|粗细)|锁骨|胸廓|胸部(?:体量|宽度|轮廓|大小)|"
    r"胸腰|躯干|腰线|腰部(?:体量|宽窄|轮廓)?|腰围|腰臀|臀部(?:体量|宽度)?|"
    r"胯部|骨盆|头身(?:比|比例)|四肢(?:比例|体量|粗细)|"
    r"手臂粗细|腿部粗细|腿长|臂长|上身量感|体脂|肌肉量"
)


def _generic_19_type_context(primary_type: str = "") -> str:
    clean_type = str(primary_type or "").strip()
    if clean_type and clean_type in PROMPT_BLOCK_GENERIC_TYPE_FIDELITY_CONTEXT:
        spec = _GENERIC_19_TYPE_SPEC_INDEX.get(clean_type) or {}
        module_lines = []
        for module in spec.get("modules") or []:
            if not isinstance(module, (list, tuple)) or len(module) < 3:
                continue
            module_lines.append(f"{module[1]}：{module[2]}")
        template_context = "；".join(module_lines[:10])
        return "\n".join(part for part in [
            f"当前类型高保真核对清单：{PROMPT_BLOCK_GENERIC_TYPE_FIDELITY_CONTEXT[clean_type]}",
            f"该类型原有维度参考：{template_context}" if template_context else "",
            "这些类型维度必须映射回允许的高保真模块；只有 portrait、fashion、character 可使用 body_shape，不能创造列表外的 module_type。",
        ] if part)
    catalog = "\n".join(
        f"- {type_id}：{context}"
        for type_id, context in PROMPT_BLOCK_GENERIC_TYPE_FIDELITY_CONTEXT.items()
    )
    return "先自动判断 primary_type，再只应用对应类型的高保真核对清单；未知类型使用主体几何、空间布局、主色与媒介四类通用锚点。\n" + catalog


def _generic_19_visible_char_count(value: Any) -> int:
    return len(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", str(value or "")))


def _generic_19_content_fingerprint(value: Any) -> str:
    return "".join(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", str(value or "").lower()))


def _generic_19_clause_count(value: Any) -> int:
    clauses = re.split(r"[，,；;。.!！?？、：:\n]+", str(value or ""))
    return sum(1 for clause in clauses if _generic_19_visible_char_count(clause) >= 3)


def _generic_19_evidence_count(value: Any) -> int:
    content = str(value or "")
    return sum(1 for pattern in PROMPT_BLOCK_GENERIC_DETAIL_EVIDENCE_PATTERNS if re.search(pattern, content, re.IGNORECASE))


def _generic_19_normalize_module_type(value: Any, fallback: str = "custom") -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = PROMPT_BLOCK_MODULE_ALIASES.get(raw, raw)
    return normalized if normalized in PROMPT_BLOCK_GENERIC_MODULE_LABELS else fallback


def _normalize_generic_19_anchor(
    value: Any,
    default_module_type: str = "",
    fallback_id: str = "",
) -> dict[str, Any] | None:
    if isinstance(value, str):
        text = _clean_string(value, 1200)
        if not text:
            return None
        value = {"value": text, "attribute": "detail"}
    if not isinstance(value, dict):
        return None
    # Once an anchor is being normalized inside one fixed module, that module
    # owns the fact.  Do not let a stray model-authored module_type route an
    # appearance fact into lighting (or vice versa).
    if default_module_type in PROMPT_BLOCK_GENERIC_MODULE_LABELS:
        module_type = default_module_type
    else:
        module_type = _generic_19_normalize_module_type(
            value.get("module_type") or value.get("moduleType"),
            "custom",
        )
    anchor_value = _clean_string(
        value.get("value") or value.get("fact") or value.get("content") or value.get("text"),
        1800,
    )
    if not anchor_value:
        return None
    attribute = str(value.get("attribute") or value.get("dimension") or "detail").strip().lower().replace("-", "_").replace(" ", "_")
    if attribute not in PROMPT_BLOCK_GENERIC_ANCHOR_ATTRIBUTES:
        attribute = "detail"
    importance = str(value.get("importance") or "major").strip().lower()
    if importance not in PROMPT_BLOCK_GENERIC_ANCHOR_IMPORTANCE:
        importance = "major"
    confidence = str(value.get("confidence") or "medium").strip().lower()
    if confidence not in PROMPT_BLOCK_GENERIC_ANCHOR_CONFIDENCE:
        confidence = "medium"
    anchor_id = _clean_string(value.get("id") or value.get("anchor_id") or fallback_id, 80)
    if not anchor_id:
        anchor_id = f"{module_type}_{abs(hash((module_type, attribute, anchor_value))) & 0xffffffff:08x}"
    return {
        "id": anchor_id,
        "module_type": module_type,
        "target": _clean_string(value.get("target") or value.get("object") or "", 260),
        "attribute": attribute,
        "value": anchor_value,
        "relation": _clean_string(value.get("relation") or value.get("spatial_relation") or "", 1000),
        "importance": importance,
        "confidence": confidence,
        "negative_pair": _clean_string(value.get("negative_pair") or value.get("negativePair") or "", 1200),
    }


def _normalize_generic_19_anchors(
    anchors: Any,
    default_module_type: str = "",
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    used_ids: dict[str, int] = {}
    limit = int(max_items or _GENERIC_19_ANCHOR_MAX_BY_MODULE.get(default_module_type) or 10)
    raw_anchors = anchors if isinstance(anchors, list) else ([anchors] if isinstance(anchors, (dict, str)) else [])
    for index, raw_anchor in enumerate(raw_anchors):
        anchor = _normalize_generic_19_anchor(raw_anchor, default_module_type, f"{default_module_type or 'anchor'}_{index + 1}")
        if not anchor:
            continue
        fingerprint = "|".join([
            anchor["module_type"],
            anchor["target"].lower(),
            anchor["attribute"],
            _generic_19_content_fingerprint(anchor["value"]),
            _generic_19_content_fingerprint(anchor["relation"]),
        ])
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        raw_id = str(anchor.get("id") or f"{default_module_type or 'anchor'}_{index + 1}")
        id_count = used_ids.get(raw_id, 0) + 1
        used_ids[raw_id] = id_count
        if id_count > 1:
            anchor["id"] = f"{raw_id}__{id_count}"
        normalized.append(anchor)
        if len(normalized) >= limit:
            break
    return normalized


def _generic_19_anchor_phrase(anchor: dict[str, Any], module_type: str = "") -> str:
    target = _clean_string(anchor.get("target"), 260)
    attribute = str(anchor.get("attribute") or "detail")
    value = _clean_string(anchor.get("value"), 1800)
    relation = _clean_string(anchor.get("relation"), 1000)
    if not value:
        return ""
    if module_type == "constraints" and attribute == "constraint":
        # Constraint values are already rendered as concise negative rules.
        # Do not append their relation or negative_pair a second time.
        return value.strip("，；。 ")
    elif target:
        phrase = f"{target}：{value}"
    else:
        label = _GENERIC_19_ATTRIBUTE_LABELS.get(attribute, "细节")
        phrase = f"{label}：{value}"
    if relation and _generic_19_content_fingerprint(relation) not in _generic_19_content_fingerprint(phrase):
        phrase += f"，{relation}"
    return phrase.strip("，；。 ")


def _generic_19_constraint_label(anchor: dict[str, Any]) -> str:
    label = _clean_string(anchor.get("target"), 80)
    if label:
        return label
    module_type = _generic_19_normalize_module_type(anchor.get("module_type"), "custom")
    return PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(module_type, "视觉类别")


def _generic_19_constraint_negative_pair(anchor: dict[str, Any]) -> str:
    negative_pair = _clean_string(anchor.get("negative_pair"), 220)
    if negative_pair:
        return negative_pair
    value = _clean_string(anchor.get("value"), 600)
    match = re.search(r"(?:不要|避免|不得|禁止|不可|请勿|别)\s*([^；;。\n]+)", value)
    return _clean_string(match.group(1) if match else "", 220)


def _generic_19_negative_constraint_text(value: Any) -> str:
    text = _clean_string(value, 220).strip("，,；;。 ")
    if not text:
        return ""
    english_negative = re.match(r"^(?:do\s+not|don't|avoid|no)\b", text, re.IGNORECASE)
    if english_negative:
        return text
    text = re.sub(r"^(?:不要|避免|不得|禁止|不可|请勿|别)\s*", "", text).strip("，,；;。 ")
    return f"不要{text}" if text else ""


def _generic_19_constraints_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_target = _generic_19_content_fingerprint(left.get("target"))
    right_target = _generic_19_content_fingerprint(right.get("target"))
    if left_target and right_target:
        if left_target == right_target or (
            min(len(left_target), len(right_target)) >= 2
            and (left_target in right_target or right_target in left_target)
        ):
            return True
        if _generic_19_text_similarity(left_target, right_target) >= 0.72:
            return True
    left_negative = _generic_19_content_fingerprint(left.get("negative_pair") or left.get("value"))
    right_negative = _generic_19_content_fingerprint(right.get("negative_pair") or right.get("value"))
    return bool(
        left_negative
        and right_negative
        and _generic_19_text_similarity(left_negative, right_negative) >= 0.72
    )


def _generic_19_select_constraint_anchors(
    source_anchors: list[dict[str, Any]],
    fallback_constraints: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Keep only a compact, distinct set of high-risk anti-drift rules."""
    candidates: list[dict[str, Any]] = []

    def add_candidate(raw_anchor: dict[str, Any], index: int, *, fallback: bool = False) -> None:
        source_module = _generic_19_normalize_module_type(raw_anchor.get("module_type"), "custom")
        if not fallback and source_module in {"goal", "quality", "constraints"}:
            return
        negative_pair = _generic_19_constraint_negative_pair(raw_anchor)
        negative_text = _generic_19_negative_constraint_text(negative_pair)
        if not negative_text:
            return
        label = _generic_19_constraint_label(raw_anchor)
        anchor = _normalize_generic_19_anchor(
            {
                "id": f"constraint_from_{_clean_string(raw_anchor.get('id'), 60) or index}",
                "module_type": "constraints",
                "target": label,
                "attribute": "constraint",
                "value": f"{label}：{negative_text}",
                "importance": "critical" if raw_anchor.get("importance") == "critical" else "major",
                "confidence": raw_anchor.get("confidence") or "medium",
                "negative_pair": negative_pair,
            },
            "constraints",
        )
        if not anchor:
            return
        importance = {"critical": 3, "major": 2, "supporting": 1}.get(str(raw_anchor.get("importance") or ""), 2)
        confidence = 2 if str(raw_anchor.get("confidence") or "").lower() == "high" else 1
        module_priority = _GENERIC_19_CONSTRAINT_MODULE_PRIORITIES.get(source_module, 36 if fallback else 50)
        candidates.append({
            "anchor": anchor,
            "source_module": source_module,
            "index": index,
            "score": importance * 1000 + module_priority * 10 + confidence - (120 if fallback else 0),
        })

    for index, anchor in enumerate(source_anchors):
        if isinstance(anchor, dict):
            add_candidate(anchor, index)
    for index, anchor in enumerate(fallback_constraints or []):
        if isinstance(anchor, dict):
            add_candidate(anchor, len(source_anchors) + index, fallback=True)
    candidates.sort(key=lambda item: (-int(item["score"]), int(item["index"])))

    selected: list[dict[str, Any]] = []
    selected_modules: set[str] = set()
    for require_distinct_module in (True, False):
        for candidate in candidates:
            if len(selected) >= _GENERIC_19_CONSTRAINT_SOURCE_LIMIT:
                break
            if require_distinct_module and candidate["source_module"] in selected_modules:
                continue
            anchor = candidate["anchor"]
            if any(_generic_19_constraints_overlap(anchor, existing) for existing in selected):
                continue
            selected.append(anchor)
            selected_modules.add(candidate["source_module"])
        if len(selected) >= _GENERIC_19_CONSTRAINT_SOURCE_LIMIT:
            break
    return _normalize_generic_19_anchors(selected, "constraints", _GENERIC_19_CONSTRAINT_SOURCE_LIMIT)


def _generic_19_select_goal_anchors(anchors: Any) -> list[dict[str, Any]]:
    """Keep goal as a short global capsule rather than a second full prompt."""
    selected: list[dict[str, Any]] = []
    forbidden_attributes = {
        "shape", "proportion", "position", "orientation", "crop", "material",
        "texture", "color", "lighting", "camera", "text", "quality", "constraint",
    }
    forbidden_detail = re.compile(
        r"画幅|画布|尺寸|宽高|分辨率|裁切|构图|主体占比|留白|边缘|"
        r"主色|辅色|色彩|调色|镜头|机位|布光|光线|材质|纹理|"
        r"脸型|五官|眉|眼|鼻|唇|下巴|体形|体型|身材|肩宽|胸部|躯干|腰部|"
        r"发型|服装|上衣|配饰|背景地标"
    )
    for anchor in _normalize_generic_19_anchors(anchors, "goal", 12):
        if str(anchor.get("attribute") or "") in forbidden_attributes:
            continue
        ownership_text = " ".join([
            _clean_string(anchor.get("target"), 120),
            _clean_string(anchor.get("value"), 500),
            _clean_string(anchor.get("relation"), 300),
        ])
        if forbidden_detail.search(ownership_text):
            continue
        selected.append(anchor)
        if len(selected) >= _GENERIC_19_ANCHOR_MAX_BY_MODULE["goal"]:
            break
    return _normalize_generic_19_anchors(
        selected,
        "goal",
        _GENERIC_19_ANCHOR_MAX_BY_MODULE["goal"],
    )


def _generic_19_is_body_shape_anchor(anchor: dict[str, Any]) -> bool:
    """Identify visible body-proportion facts that do not belong in appearance."""
    attribute = str(anchor.get("attribute") or "detail").strip().lower()
    if attribute in {
        "position", "orientation", "crop", "material", "color", "lighting",
        "camera", "text", "style", "quality", "constraint",
    }:
        return False
    body_text = " ".join([
        _clean_string(anchor.get("target"), 180),
        _clean_string(anchor.get("value"), 900),
        _clean_string(anchor.get("relation"), 500),
    ])
    return bool(_GENERIC_19_BODY_SHAPE_ANCHOR_PATTERN.search(body_text))


def _generic_19_separate_body_shape_block(
    prepared: list[dict[str, Any]],
    first_by_module: dict[str, dict[str, Any]],
    primary_type: str = "",
) -> None:
    """Move body-size/proportion anchors out of appearance into one owned block."""
    clean_type = str(primary_type or "").strip()
    if clean_type and clean_type not in _GENERIC_19_BODY_SHAPE_PRIMARY_TYPES:
        return
    appearance_block = first_by_module.get("appearance")
    if appearance_block is None:
        return
    appearance_anchors = _normalize_generic_19_anchors(
        appearance_block.get("anchors"),
        "appearance",
        _GENERIC_19_ANCHOR_MAX_BY_MODULE.get("appearance"),
    )
    body_anchors = [anchor for anchor in appearance_anchors if _generic_19_is_body_shape_anchor(anchor)]
    if not body_anchors:
        return

    remaining_appearance = [anchor for anchor in appearance_anchors if anchor not in body_anchors]
    if remaining_appearance:
        appearance_block["anchors"] = remaining_appearance
        enriched_appearance = _generic_19_enrich_block_from_anchors(appearance_block)
        appearance_block.clear()
        appearance_block.update(enriched_appearance)
    else:
        prepared[:] = [
            block for block in prepared
            if str(block.get("module_type") or "") != "appearance"
        ]
        first_by_module.pop("appearance", None)

    normalized_body_anchors = [
        normalized
        for anchor in body_anchors
        if (normalized := _normalize_generic_19_anchor(
            {**anchor, "module_type": "body_shape"},
            "body_shape",
            str(anchor.get("id") or "body_shape_anchor"),
        )) is not None
    ]
    body_block = first_by_module.get("body_shape")
    if body_block is None:
        body_block = {"module_type": "body_shape", "anchors": []}
        prepared.append(body_block)
        first_by_module["body_shape"] = body_block
    body_block["anchors"] = _normalize_generic_19_anchors(
        [*(body_block.get("anchors") or []), *normalized_body_anchors],
        "body_shape",
        _GENERIC_19_ANCHOR_MAX_BY_MODULE.get("body_shape"),
    )
    enriched_body = _generic_19_enrich_block_from_anchors(body_block)
    body_block.clear()
    body_block.update(enriched_body)


def _generic_19_compact_from_anchors(anchors: list[dict[str, Any]]) -> str:
    parts = []
    for anchor in anchors:
        value = _clean_string(anchor.get("value"), 180)
        if value and value not in parts:
            parts.append(value)
        if len(parts) >= 2:
            break
    return "；".join(parts)[:300]


def _generic_19_enrich_block_from_anchors(block: dict[str, Any]) -> dict[str, Any]:
    module_type = _generic_19_normalize_module_type(block.get("module_type") or block.get("type"))
    anchors = _normalize_generic_19_anchors(
        block.get("anchors"),
        module_type,
        _GENERIC_19_ANCHOR_MAX_BY_MODULE.get(module_type),
    )
    phrases = [_generic_19_anchor_phrase(anchor, module_type) for anchor in anchors]
    phrases = [phrase for phrase in phrases if phrase]
    original_content = _clean_string(block.get("content") or block.get("text"), 12000)
    # Anchors are the canonical fact source for generic_19. Model-authored content is
    # only a compatibility fallback when no structured facts were returned. Mixing
    # both used to duplicate clauses and could reintroduce unanchored visual guesses.
    if not phrases and original_content:
        for clause in re.split(r"[；;。\n]+", original_content):
            clean_clause = clause.strip(" ，,；;。\n")
            if _generic_19_visible_char_count(clean_clause) < 4:
                continue
            clause_fp = _generic_19_content_fingerprint(clean_clause)
            if any(
                _generic_19_text_similarity(clause_fp, _generic_19_content_fingerprint(existing)) >= 0.92
                for existing in phrases
            ):
                continue
            phrases.append(clean_clause)
            if len(phrases) >= 3:
                break
    content = "；".join(phrases).strip("； ") or original_content
    compact = _clean_string(block.get("compact_content") or block.get("compact"), 2000)
    if not compact or _generic_19_content_fingerprint(compact) == _generic_19_content_fingerprint(content):
        compact = _generic_19_compact_from_anchors(anchors) or content[:300]
    return {
        **block,
        "name": PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(module_type, module_type),
        "module_type": module_type,
        "content": content,
        "compact_content": compact,
        "anchors": anchors,
    }


def _generic_19_prepare_blueprint_blocks(
    parsed: dict[str, Any],
    primary_type_hint: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_items = parsed.get("blocks") if isinstance(parsed.get("blocks"), list) else parsed.get("repair_modules")
    if not isinstance(raw_items, list):
        raw_items = []
    raw_blueprint = parsed.get("visual_blueprint") or parsed.get("visualBlueprint")
    raw_blueprint = raw_blueprint if isinstance(raw_blueprint, dict) else {}
    global_anchor = _clean_string(raw_blueprint.get("global_anchor") or raw_blueprint.get("globalAnchor"), 2400)
    global_anchors = _normalize_generic_19_anchors(raw_blueprint.get("anchors"), "", 180)
    anchors_by_id = {anchor["id"]: anchor for anchor in global_anchors}
    used_anchor_ids: set[str] = set()
    detached_anchors: list[dict[str, Any]] = []
    prepared: list[dict[str, Any]] = []

    for raw_index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            continue
        module_type = _generic_19_normalize_module_type(raw_item.get("module_type") or raw_item.get("type"))
        anchor_ids = [
            _clean_string(anchor_id, 80)
            for anchor_id in (raw_item.get("anchor_ids") or raw_item.get("anchorIds") or [])
            if _clean_string(anchor_id, 80)
        ]
        block_anchors = [
            anchors_by_id[anchor_id]
            for anchor_id in anchor_ids
            if anchor_id in anchors_by_id and anchors_by_id[anchor_id].get("module_type") == module_type
        ]
        used_anchor_ids.update(anchor["id"] for anchor in block_anchors)
        for anchor in _normalize_generic_19_anchors(raw_item.get("anchors"), module_type):
            if anchor.get("module_type") == module_type:
                block_anchors.append(anchor)
            else:
                detached_anchors.append(anchor)
        evidence = raw_item.get("evidence")
        for evidence_index, evidence_item in enumerate(
            evidence if isinstance(evidence, list) else ([evidence] if isinstance(evidence, (dict, str)) else [])
        ):
            anchor = _normalize_generic_19_anchor(
                evidence_item,
                module_type,
                f"{module_type}_e{raw_index + 1}_{evidence_index + 1}",
            )
            if anchor:
                block_anchors.append(anchor)
        prepared.append(_generic_19_enrich_block_from_anchors({**raw_item, "module_type": module_type, "anchors": block_anchors}))

    first_by_module: dict[str, dict[str, Any]] = {}
    for block in prepared:
        first_by_module.setdefault(str(block.get("module_type") or "custom"), block)
    routed_anchors = _normalize_generic_19_anchors([*global_anchors, *detached_anchors], "", 180)
    for anchor in routed_anchors:
        if anchor["id"] in used_anchor_ids:
            continue
        module_type = anchor["module_type"]
        block = first_by_module.get(module_type)
        if block is None:
            block = _generic_19_enrich_block_from_anchors({"module_type": module_type, "anchors": [anchor]})
            prepared.append(block)
            first_by_module[module_type] = block
        else:
            block["anchors"] = _normalize_generic_19_anchors(
                [*(block.get("anchors") or []), anchor],
                module_type,
                _GENERIC_19_ANCHOR_MAX_BY_MODULE.get(module_type),
            )
            enriched = _generic_19_enrich_block_from_anchors(block)
            block.clear()
            block.update(enriched)

    resolved_body_type = (
        str(primary_type_hint or "").strip()
        or str(parsed.get("primary_type") or parsed.get("primaryType") or "").strip()
    )
    _generic_19_separate_body_shape_block(prepared, first_by_module, resolved_body_type)

    goal_block = first_by_module.get("goal")
    if goal_block is not None:
        goal_block["anchors"] = _generic_19_select_goal_anchors(goal_block.get("anchors"))
        if goal_block["anchors"]:
            enriched = _generic_19_enrich_block_from_anchors(goal_block)
            goal_block.clear()
            goal_block.update(enriched)
        else:
            prepared = [
                block for block in prepared
                if str(block.get("module_type") or "") != "goal"
            ]
            first_by_module.pop("goal", None)

    all_anchors = [anchor for block in prepared for anchor in (block.get("anchors") or [])]
    visual_anchors = [
        anchor for anchor in all_anchors
        if str(anchor.get("module_type") or "") != "constraints"
    ]
    model_constraint_anchors = [
        anchor for anchor in all_anchors
        if str(anchor.get("module_type") or "") == "constraints"
    ]
    negative_anchors = _generic_19_select_constraint_anchors(visual_anchors, model_constraint_anchors)
    prepared = [
        block for block in prepared
        if str(block.get("module_type") or "") != "constraints"
    ]
    first_by_module.pop("constraints", None)
    if negative_anchors:
        constraints_block = _generic_19_enrich_block_from_anchors({
            "module_type": "constraints",
            "anchors": negative_anchors,
        })
        prepared.append(constraints_block)
        first_by_module["constraints"] = constraints_block

    blueprint = {
        "global_anchor": global_anchor,
        "type_confidence": str(parsed.get("type_confidence") or parsed.get("typeConfidence") or "medium").strip().lower(),
        "anchor_count": len(visual_anchors) + len(negative_anchors),
    }
    if blueprint["type_confidence"] not in {"high", "medium", "low"}:
        blueprint["type_confidence"] = "medium"
    return prepared, blueprint


def _generic_19_apply_source_geometry(
    blocks: list[dict[str, Any]],
    geometry: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not geometry:
        return blocks
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    recommended_ratio = _clean_string(geometry.get("recommended_ratio"), 32)
    aspect_ratio = geometry.get("aspect_ratio")
    if width <= 0 or height <= 0:
        return blocks
    module_map = {
        str(block.get("module_type") or ""): dict(block)
        for block in blocks
        if isinstance(block, dict)
    }
    orientation = str(geometry.get("orientation") or "").strip().lower()
    if orientation == "square" or abs((width / height) - 1.0) <= 0.03:
        orientation_label = "近似方形画幅"
    elif orientation == "portrait" or height > width:
        orientation_label = "竖幅"
    else:
        orientation_label = "横幅"
    source_description = f"原图 {width}×{height} {orientation_label}，宽高比约 {float(aspect_ratio or width / height):.3f}"
    geometry_anchors = {
        "composition": {
            "id": "source_geometry_composition",
            "target": "画布边界",
            "attribute": "crop",
            "value": source_description,
            "relation": (
                "保持原图主体占比、顶部与两侧留白及边缘裁切位置"
                + (f"，生成参数优先使用 {recommended_ratio}" if recommended_ratio else "")
            ),
            "importance": "critical",
            "confidence": "high",
            "negative_pair": "扩展画布、缩小主体或改变边缘裁切",
        },
        "constraints": {
            "id": "source_geometry_constraint",
            "target": "画幅比例",
            "attribute": "constraint",
            "value": (
                f"画幅比例：不要改用明显不同于 {recommended_ratio} 的宽高比"
                if recommended_ratio else "画幅比例：不要改用明显不同的宽高比"
            ),
            "importance": "critical",
            "confidence": "high",
            "negative_pair": "改用明显不同的宽高比",
        },
    }
    for module_type, raw_anchor in geometry_anchors.items():
        anchor = _normalize_generic_19_anchor(raw_anchor, module_type)
        block = module_map.get(module_type) or {"module_type": module_type, "anchors": []}
        block["anchors"] = _normalize_generic_19_anchors(
            [anchor, *(block.get("anchors") or [])] if anchor else (block.get("anchors") or []),
            module_type,
            _GENERIC_19_ANCHOR_MAX_BY_MODULE.get(module_type),
        )
        module_map[module_type] = _generic_19_enrich_block_from_anchors(block)
    return [
        module_map[module_type]
        for module_type in PROMPT_BLOCK_GENERIC_MODULE_LABELS
        if module_type in module_map
    ]


def _generic_19_block_detail_stats(block: dict[str, Any]) -> dict[str, Any]:
    module_type = str(block.get("module_type") or "custom").strip()
    content = str(block.get("content") or "").strip()
    compact_content = str(block.get("compact_content") or "").strip()
    anchors = _normalize_generic_19_anchors(
        block.get("anchors"),
        module_type,
        _GENERIC_19_ANCHOR_MAX_BY_MODULE.get(module_type),
    )
    visible_chars = _generic_19_visible_char_count(content)
    clause_count = _generic_19_clause_count(content)
    evidence_count = _generic_19_evidence_count(content)
    anchor_count = len(anchors)
    critical_anchor_count = sum(1 for anchor in anchors if anchor.get("importance") == "critical")
    major_anchor_count = sum(1 for anchor in anchors if anchor.get("importance") == "major")
    negative_pair_count = sum(1 for anchor in anchors if anchor.get("negative_pair"))
    distinct_anchor_attributes = sorted({str(anchor.get("attribute") or "") for anchor in anchors if anchor.get("attribute")})
    min_chars = int(PROMPT_BLOCK_GENERIC_MIN_DETAIL_CHARS.get(module_type) or 24)
    min_clauses = int(PROMPT_BLOCK_GENERIC_MIN_DETAIL_CLAUSES.get(module_type) or 2)
    min_anchors = int(PROMPT_BLOCK_GENERIC_MIN_ANCHORS.get(module_type) or 2)
    weak = (
        anchor_count < min_anchors
        or visible_chars < min_chars
        or (clause_count < min_clauses and visible_chars < int(min_chars * 1.5))
    )

    generic_remainder = content
    removed_generic_chars = 0
    for phrase in PROMPT_BLOCK_GENERIC_EMPTY_DETAIL_PHRASES:
        occurrences = generic_remainder.lower().count(phrase.lower())
        if occurrences:
            removed_generic_chars += _generic_19_visible_char_count(phrase) * occurrences
            generic_remainder = re.sub(re.escape(phrase), "", generic_remainder, flags=re.IGNORECASE)
    remainder_chars = _generic_19_visible_char_count(generic_remainder)
    generic_only = (
        removed_generic_chars >= max(6, int(visible_chars * 0.35))
        and remainder_chars < max(12, int(visible_chars * 0.45))
        and evidence_count < 2
        and anchor_count < max(2, min_anchors)
    )
    analysis_tone = [marker for marker in PROMPT_BLOCK_GENERIC_ANALYSIS_MARKERS if marker in content]
    content_fingerprint = _generic_19_content_fingerprint(content)
    compact_same = bool(
        content_fingerprint
        and compact_content
        and content_fingerprint == _generic_19_content_fingerprint(compact_content)
    )
    score = (
        critical_anchor_count * 3.0
        + major_anchor_count * 1.5
        + anchor_count * 0.8
        + len(distinct_anchor_attributes) * 0.6
        + negative_pair_count * 0.5
        + min(1.5, visible_chars / max(1, min_chars))
        - (1.5 if generic_only else 0.0)
        - (0.8 if analysis_tone else 0.0)
        - (0.2 if compact_same else 0.0)
    )
    return {
        "module_type": module_type,
        "visible_chars": visible_chars,
        "clause_count": clause_count,
        "evidence_count": evidence_count,
        "anchor_count": anchor_count,
        "critical_anchor_count": critical_anchor_count,
        "major_anchor_count": major_anchor_count,
        "negative_pair_count": negative_pair_count,
        "distinct_anchor_attributes": distinct_anchor_attributes,
        "weak": weak,
        "generic_only": generic_only,
        "analysis_tone": analysis_tone,
        "compact_same": compact_same,
        "fingerprint": content_fingerprint,
        "score": round(score, 3),
    }


def _generic_19_text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) < 14 or len(right) < 14:
        return 0.0
    left_pairs = {left[index:index + 2] for index in range(len(left) - 1)}
    right_pairs = {right[index:index + 2] for index in range(len(right) - 1)}
    if not left_pairs or not right_pairs:
        return 0.0
    return (2.0 * len(left_pairs & right_pairs)) / (len(left_pairs) + len(right_pairs))


def _generic_19_dedupe_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for block in blocks:
        current_type = str(block.get("module_type") or "")
        fingerprint = _generic_19_content_fingerprint(block.get("content"))
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(kept)
                # goal is the global identity capsule and constraints is the
                # explicit anti-drift capsule. Their intentional overlap with
                # concrete modules must never cause either required block to be
                # discarded.
                if current_type not in {"goal", "constraints"}
                and str(existing.get("module_type") or "") not in {"goal", "constraints"}
                if _generic_19_text_similarity(
                    fingerprint,
                    _generic_19_content_fingerprint(existing.get("content")),
                ) >= 0.985
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(block)
            continue
        existing = kept[duplicate_index]
        if _generic_19_block_quality_rank(block) > _generic_19_block_quality_rank(existing):
            kept[duplicate_index] = block
    order = {module_type: index for index, module_type in enumerate(PROMPT_BLOCK_GENERIC_MODULE_LABELS)}
    return sorted(kept, key=lambda block: order.get(str(block.get("module_type") or "custom"), 999))


def _generic_19_body_shape_expected(blocks: list[dict[str, Any]], primary_type: str) -> bool:
    """Require the portrait extension only when the crop contains body evidence."""
    if str(primary_type or "").strip() not in _GENERIC_19_BODY_SHAPE_PRIMARY_TYPES:
        return False
    module_types = {
        str(block.get("module_type") or "")
        for block in blocks
        if isinstance(block, dict)
    }
    if "body_shape" in module_types:
        return True
    evidence_text = " ".join(
        str(block.get("content") or "")
        for block in blocks
        if isinstance(block, dict)
        and str(block.get("module_type") or "") in {
            "appearance", "pose", "clothing", "subject", "composition", "camera",
        }
    )
    return bool(re.search(
        r"肩颈|肩宽|肩部|锁骨|胸部|胸像|胸廓|上半身|上身|半身|躯干|"
        r"腰部|腰线|腰上|膝上|全身|四肢|手臂|大腿|头身比|"
        r"吊带|上衣|衬衫|外套|连衣裙|礼服|泳装|西装",
        evidence_text,
    ))


def _generic_19_prompt_block_quality(
    blocks: list[dict[str, Any]],
    primary_type: str = "",
    *,
    candidate_blocks: list[dict[str, Any]] | None = None,
    raw_blocks: list[Any] | None = None,
    type_confidence: str = "medium",
) -> dict[str, Any]:
    stats = [_generic_19_block_detail_stats(block) for block in blocks if isinstance(block, dict)]
    stats_by_module = {item["module_type"]: item for item in stats}
    module_order = {module_type: index for index, module_type in enumerate(PROMPT_BLOCK_GENERIC_MODULE_LABELS)}
    issues: list[str] = []
    needs_retry = False
    module_types = {str(block.get("module_type") or "") for block in blocks if isinstance(block, dict)}
    clean_type = str(primary_type or "").strip()
    clean_confidence = str(type_confidence or "medium").strip().lower()
    if clean_confidence not in {"high", "medium", "low"}:
        clean_confidence = "medium"

    raw_items = raw_blocks if isinstance(raw_blocks, list) else []
    empty_module_types: list[str] = []
    invalid_module_types: list[str] = []
    if raw_items:
        for item in raw_items:
            if not isinstance(item, dict):
                empty_module_types.append("invalid_item")
                continue
            raw_type = str(item.get("module_type") or item.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
            normalized_type = PROMPT_BLOCK_MODULE_ALIASES.get(raw_type, raw_type)
            has_anchor_payload = bool(item.get("anchors") or item.get("anchor_ids") or item.get("anchorIds") or item.get("evidence"))
            if not _clean_string(item.get("content") or item.get("text"), 12000) and not has_anchor_payload:
                empty_module_types.append(normalized_type or "missing_type")
            if not raw_type or normalized_type not in PROMPT_BLOCK_GENERIC_MODULE_LABELS:
                invalid_module_types.append(raw_type or "missing_type")
        if len(empty_module_types) >= 2:
            issues.append(f"原始结果含 {len(empty_module_types)} 个空内容且无锚点的模块")
            needs_retry = True
        if invalid_module_types:
            issues.append(f"原始结果含 {len(invalid_module_types)} 个不属于高保真模块体系的类型")
            needs_retry = True

    candidate_items = candidate_blocks if isinstance(candidate_blocks, list) else blocks
    candidate_counts: dict[str, int] = {}
    for block in candidate_items:
        if not isinstance(block, dict):
            continue
        module_type = str(block.get("module_type") or "custom")
        candidate_counts[module_type] = candidate_counts.get(module_type, 0) + 1
    duplicate_modules = [module_type for module_type, count in candidate_counts.items() if count > 1]
    if duplicate_modules:
        labels = [PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(module_type, module_type) for module_type in duplicate_modules]
        issues.append("同一模块重复返回：" + "、".join(labels))
        needs_retry = True

    required_modules = set(PROMPT_BLOCK_GENERIC_BASE_REQUIRED_MODULES)
    if clean_confidence != "low":
        required_modules.update(PROMPT_BLOCK_GENERIC_REQUIRED_MODULES_BY_TYPE.get(clean_type) or set())
        if _generic_19_body_shape_expected(blocks, clean_type):
            required_modules.add("body_shape")
    missing_modules = required_modules - module_types
    if missing_modules:
        labels = [PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(module_type, module_type) for module_type in sorted(missing_modules, key=lambda value: module_order.get(value, 999))]
        issues.append("缺少高保真核心模块：" + "、".join(labels))
        needs_retry = True

    min_modules = int(PROMPT_BLOCK_GENERIC_MIN_MODULES_BY_TYPE.get(clean_type) or 7)
    if clean_confidence == "low":
        min_modules = min(min_modules, 6)
    if len(blocks) < min_modules:
        issues.append(f"有效模块仅 {len(blocks)} 个，低于当前类型至少 {min_modules} 个的覆盖要求")
        needs_retry = True

    weak_stats = [item for item in stats if item["weak"]]
    weak_required_stats = [item for item in weak_stats if item["module_type"] in required_modules]
    if weak_stats:
        weak_labels = [PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(item["module_type"], item["module_type"]) for item in weak_stats]
        issues.append("细节或锚点不足：" + "、".join(weak_labels))
        if weak_required_stats or len(weak_stats) * 100 >= max(1, len(stats)) * 35:
            needs_retry = True

    generic_stats = [item for item in stats if item["generic_only"]]
    if generic_stats:
        issues.append("空泛描述：" + "、".join(PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(item["module_type"], item["module_type"]) for item in generic_stats))
        needs_retry = True
    analysis_stats = [item for item in stats if item["analysis_tone"]]
    if analysis_stats:
        issues.append("含分析口吻：" + "、".join(PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(item["module_type"], item["module_type"]) for item in analysis_stats))
        needs_retry = True
    compact_same_stats = [item for item in stats if item["compact_same"]]
    if compact_same_stats:
        issues.append("详细版与精简版相同：" + "、".join(PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(item["module_type"], item["module_type"]) for item in compact_same_stats))

    duplicate_pairs: list[dict[str, Any]] = []
    duplicate_pair_repair_modules: set[str] = set()
    fingerprints = [(item["module_type"], item["fingerprint"]) for item in stats if item["fingerprint"]]
    for index, (left_type, left_text) in enumerate(fingerprints):
        for right_type, right_text in fingerprints[index + 1:]:
            similarity = _generic_19_text_similarity(left_text, right_text)
            if similarity < 0.92:
                continue
            duplicate_pairs.append({"left": left_type, "right": right_type, "similarity": round(similarity, 3)})
            left_score = float(stats_by_module.get(left_type, {}).get("score") or 0.0)
            right_score = float(stats_by_module.get(right_type, {}).get("score") or 0.0)
            duplicate_pair_repair_modules.add(left_type if left_score < right_score else right_type)
    if duplicate_pairs:
        pair_labels = [
            f"{PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(item['left'], item['left'])}/{PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(item['right'], item['right'])}"
            for item in duplicate_pairs[:4]
        ]
        issues.append("跨模块内容重复：" + "、".join(pair_labels))
        needs_retry = True

    total_anchor_count = sum(int(item["anchor_count"]) for item in stats)
    critical_anchor_count = sum(int(item["critical_anchor_count"]) for item in stats)
    negative_pair_count = sum(int(item["negative_pair_count"]) for item in stats)
    distinct_anchor_attributes = sorted({attribute for item in stats for attribute in item["distinct_anchor_attributes"]})
    expected_anchor_count = sum(
        int(PROMPT_BLOCK_GENERIC_MIN_ANCHORS.get(module_type) or 2)
        for module_type in required_modules
    )
    covered_anchor_count = sum(
        min(
            int(stats_by_module.get(module_type, {}).get("anchor_count") or 0),
            int(PROMPT_BLOCK_GENERIC_MIN_ANCHORS.get(module_type) or 2),
        )
        for module_type in required_modules
    )
    anchor_coverage = round(covered_anchor_count / max(1, expected_anchor_count), 4)
    if total_anchor_count < max(18, min_modules * 2):
        issues.append(f"视觉锚点总数仅 {total_anchor_count} 个，无法稳定复现关键类别")
        needs_retry = True
    if len(distinct_anchor_attributes) < 7:
        issues.append(f"锚点属性只覆盖 {len(distinct_anchor_attributes)} 类，缺少几何、空间、材质或光学区分")
        needs_retry = True
    if negative_pair_count < 3:
        issues.append(f"易混淆类别仅锁定 {negative_pair_count} 项，负面防漂移不足")
        needs_retry = True

    critical_modules = set(PROMPT_BLOCK_GENERIC_BASE_REQUIRED_MODULES)
    critical_modules.update(_GENERIC_19_CRITICAL_MODULES_BY_TYPE.get(clean_type) or set())
    if clean_confidence == "low":
        critical_modules = set(PROMPT_BLOCK_GENERIC_BASE_REQUIRED_MODULES)
    missing_critical_modules = {
        module_type
        for module_type in critical_modules & module_types
        if int(stats_by_module.get(module_type, {}).get("critical_anchor_count") or 0) == 0
        and int(stats_by_module.get(module_type, {}).get("major_anchor_count") or 0) < 2
    }
    if missing_critical_modules:
        labels = [PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(module_type, module_type) for module_type in sorted(missing_critical_modules, key=lambda value: module_order.get(value, 999))]
        issues.append("缺少区分性 critical 锚点：" + "、".join(labels))
        needs_retry = True

    visual_lengths = sorted(item["visible_chars"] for item in stats if item["module_type"] in PROMPT_BLOCK_GENERIC_VISUAL_MODULES)
    visual_median_chars = 0.0
    visual_average_chars = 0.0
    if visual_lengths:
        middle = len(visual_lengths) // 2
        visual_median_chars = float(visual_lengths[middle] if len(visual_lengths) % 2 else (visual_lengths[middle - 1] + visual_lengths[middle]) / 2)
        visual_average_chars = sum(visual_lengths) / len(visual_lengths)

    repair_modules = {
        *(item["module_type"] for item in weak_stats),
        *(item["module_type"] for item in generic_stats),
        *(item["module_type"] for item in analysis_stats),
        *(item["module_type"] for item in compact_same_stats),
        *duplicate_modules,
        *duplicate_pair_repair_modules,
        *missing_modules,
        *missing_critical_modules,
    }
    if needs_retry and not repair_modules:
        # Global failures (for example too few total anchors or too little
        # attribute diversity) still need a concrete repair target. Without
        # this fallback the second pass would be skipped despite needs_retry.
        repair_modules.update(required_modules & module_types)
        if not repair_modules:
            repair_modules.update(required_modules)
    sorted_repair_modules = sorted(repair_modules, key=lambda value: module_order.get(value, 999))
    protected_modules = sorted(module_types - repair_modules, key=lambda value: module_order.get(value, 999))
    quality_score = (
        critical_anchor_count * 3.0
        + total_anchor_count * 0.8
        + len(distinct_anchor_attributes) * 1.5
        + negative_pair_count
        + len(blocks) * 0.5
        - len(duplicate_pairs) * 2.0
        - len(analysis_stats)
    )
    return {
        "quality_version": 2,
        "needs_retry": bool(needs_retry),
        "issues": issues,
        "score": round(quality_score, 3),
        "anchor_coverage": anchor_coverage,
        "anchor_count": total_anchor_count,
        "critical_anchor_count": critical_anchor_count,
        "negative_pair_count": negative_pair_count,
        "distinct_anchor_attributes": distinct_anchor_attributes,
        "module_stats": stats_by_module,
        "weak_modules": [item["module_type"] for item in weak_stats],
        "generic_modules": [item["module_type"] for item in generic_stats],
        "analysis_modules": [item["module_type"] for item in analysis_stats],
        "analysis_tone_modules": [item["module_type"] for item in analysis_stats],
        "compact_same_modules": [item["module_type"] for item in compact_same_stats],
        "duplicate_modules": duplicate_modules,
        "duplicate_pairs": duplicate_pairs,
        "duplicate_pair_modules": sorted(duplicate_pair_repair_modules, key=lambda value: module_order.get(value, 999)),
        "missing_modules": sorted(missing_modules, key=lambda value: module_order.get(value, 999)),
        "missing_critical_modules": sorted(missing_critical_modules, key=lambda value: module_order.get(value, 999)),
        "invalid_module_types": invalid_module_types,
        "empty_module_types": empty_module_types,
        "repair_modules": sorted_repair_modules,
        "protected_modules": protected_modules,
        "visual_median_chars": round(visual_median_chars, 3),
        "visual_average_chars": round(visual_average_chars, 3),
        "module_count": len(blocks),
        "total_visible_chars": sum(item["visible_chars"] for item in stats),
        "type_confidence": clean_confidence,
    }


def _generic_19_quality_rank(report: dict[str, Any]) -> tuple[Any, ...]:
    return (
        0 if report.get("needs_retry") else 1,
        int(report.get("critical_anchor_count") or 0),
        float(report.get("anchor_coverage") or 0.0),
        int(report.get("anchor_count") or 0),
        len(report.get("distinct_anchor_attributes") or []),
        int(report.get("negative_pair_count") or 0),
        float(report.get("score") or 0.0),
        int(report.get("total_visible_chars") or 0),
    )


def _generic_19_block_quality_rank(block: dict[str, Any]) -> tuple[Any, ...]:
    stats = _generic_19_block_detail_stats(block)
    return (
        int(stats.get("critical_anchor_count") or 0),
        int(stats.get("anchor_count") or 0),
        len(stats.get("distinct_anchor_attributes") or []),
        int(stats.get("negative_pair_count") or 0),
        0 if stats.get("generic_only") else 1,
        0 if stats.get("analysis_tone") else 1,
        float(stats.get("score") or 0.0),
        int(stats.get("visible_chars") or 0),
    )


def _generic_19_anchor_targets_overlap(left: Any, right: Any) -> bool:
    left_text = _generic_19_content_fingerprint(left)
    right_text = _generic_19_content_fingerprint(right)
    if not left_text or not right_text:
        return not left_text and not right_text
    if left_text == right_text:
        return True
    if min(len(left_text), len(right_text)) >= 2 and (left_text in right_text or right_text in left_text):
        return True
    left_pairs = {left_text[index:index + 2] for index in range(max(0, len(left_text) - 1))}
    right_pairs = {right_text[index:index + 2] for index in range(max(0, len(right_text) - 1))}
    if not left_pairs or not right_pairs:
        return False
    similarity = (2.0 * len(left_pairs & right_pairs)) / (len(left_pairs) + len(right_pairs))
    return similarity >= 0.72


def _merge_generic_19_anchor_lists(
    initial_anchors: Any,
    repaired_anchors: Any,
    module_type: str,
) -> list[dict[str, Any]]:
    initial = _normalize_generic_19_anchors(initial_anchors, module_type, _GENERIC_19_ANCHOR_MAX_BY_MODULE.get(module_type))
    repaired = _normalize_generic_19_anchors(repaired_anchors, module_type, _GENERIC_19_ANCHOR_MAX_BY_MODULE.get(module_type))
    merged = list(initial)
    initial_ids = {str(anchor.get("id") or "") for anchor in initial if anchor.get("id")}
    for anchor in repaired:
        if str(anchor.get("id") or "") in initial_ids:
            continue
        if any(
            str(existing.get("attribute") or "") == str(anchor.get("attribute") or "")
            and _generic_19_anchor_targets_overlap(existing.get("target"), anchor.get("target"))
            for existing in initial
        ):
            continue
        merged.append(anchor)
    return _normalize_generic_19_anchors(merged, module_type, _GENERIC_19_ANCHOR_MAX_BY_MODULE.get(module_type))


def _merge_generic_19_repaired_blocks(
    initial_blocks: list[dict[str, Any]],
    initial_type: str,
    initial_quality: dict[str, Any],
    repaired_blocks: list[dict[str, Any]],
    repaired_type: str,
) -> tuple[list[dict[str, Any]], str, dict[str, Any], list[str]]:
    """Merge one anchor-level repair pass without replacing stable first-pass facts."""
    initial_by_module = {
        str(block.get("module_type") or ""): block
        for block in initial_blocks
        if isinstance(block, dict) and str(block.get("module_type") or "") in PROMPT_BLOCK_GENERIC_MODULE_LABELS
    }
    repaired_by_module = {
        str(block.get("module_type") or ""): block
        for block in repaired_blocks
        if isinstance(block, dict) and str(block.get("module_type") or "") in PROMPT_BLOCK_GENERIC_MODULE_LABELS
    }
    repair_modules = set(initial_quality.get("repair_modules") or [])
    merged_by_module = dict(initial_by_module)
    applied_modules: list[str] = []

    for module_type in PROMPT_BLOCK_GENERIC_MODULE_LABELS:
        if module_type not in repair_modules:
            continue
        repaired_block = repaired_by_module.get(module_type)
        if repaired_block is None:
            continue
        initial_block = initial_by_module.get(module_type)
        if initial_block is None:
            repaired_stats = _generic_19_block_detail_stats(repaired_block)
            if (
                repaired_stats["anchor_count"] <= 0
                or repaired_stats["weak"]
                or repaired_stats["generic_only"]
                or repaired_stats["analysis_tone"]
            ):
                continue
            merged_by_module[module_type] = repaired_block
            applied_modules.append(module_type)
            continue
        merged_anchors = _merge_generic_19_anchor_lists(
            initial_block.get("anchors"),
            repaired_block.get("anchors"),
            module_type,
        )
        candidate = _generic_19_enrich_block_from_anchors({
            **initial_block,
            "anchors": merged_anchors,
            "english_content": repaired_block.get("english_content") or initial_block.get("english_content") or "",
            "tags": repaired_block.get("tags") or initial_block.get("tags") or [],
        })
        if _generic_19_block_quality_rank(candidate) <= _generic_19_block_quality_rank(initial_block):
            continue
        merged_by_module[module_type] = candidate
        applied_modules.append(module_type)

    resolved_type = str(initial_type or "").strip()
    if resolved_type not in PROMPT_BLOCK_PRIMARY_TYPES:
        candidate_type = str(repaired_type or "").strip()
        resolved_type = candidate_type if candidate_type in PROMPT_BLOCK_PRIMARY_TYPES else ""
    if not applied_modules:
        return initial_blocks, resolved_type, initial_quality, []
    merged_blocks = _generic_19_dedupe_blocks([
        merged_by_module[module_type]
        for module_type in PROMPT_BLOCK_GENERIC_MODULE_LABELS
        if module_type in merged_by_module
    ])
    merged_quality = _generic_19_prompt_block_quality(
        merged_blocks,
        resolved_type,
        type_confidence=str(initial_quality.get("type_confidence") or "medium"),
    )
    if _generic_19_quality_rank(merged_quality) < _generic_19_quality_rank(initial_quality):
        return initial_blocks, resolved_type, initial_quality, []
    return merged_blocks, resolved_type, merged_quality, applied_modules


def _join_prompt_block_parts(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, dict):
            candidates = value.values()
        elif isinstance(value, (list, tuple, set)):
            candidates = value
        else:
            candidates = [value]
        for candidate in candidates:
            text = _clean_string(candidate, 5000)
            if text and text not in parts:
                parts.append(text)
    return "；".join(parts)


def _prompt_block_has_markers(text: str, chinese: tuple[str, ...] = (), english: tuple[str, ...] = ()) -> bool:
    normalized = str(text or "").lower()
    if any(marker in normalized for marker in chinese):
        return True
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(marker.lower())}(?![a-z0-9])", normalized)
        for marker in english
    )


def _prompt_block_has_human_evidence(text: str) -> bool:
    return _prompt_block_has_markers(
        text,
        ("人物", "人像", "肖像", "女性", "男性", "女孩", "男孩", "女士", "男士", "模特", "少女", "少年"),
        ("person", "portrait", "human", "woman", "man", "girl", "boy", "lady", "gentleman", "people", "adult", "child", "teenager", "businesswoman", "businessman"),
    )


def _infer_prompt_block_primary_type(analysis: dict[str, Any], requested: str = "") -> str:
    clean_requested = str(requested or "").strip()
    if clean_requested in PROMPT_BLOCK_PRIMARY_TYPES:
        return clean_requested
    flags = _as_dict(analysis.get("image_type_flags"))
    kind = _clean_string(analysis.get("image_kind"), 120).lower()
    summary = _clean_string(analysis.get("visual_summary"), 600).lower()
    subjects = [item for item in _as_list(analysis.get("subjects")) if isinstance(item, dict)]
    subject_evidence = " ".join(
        _clean_string(subject.get(key), 500).lower()
        for subject in subjects
        for key in ("name", "role", "visual_traits", "outfit", "makeup_hair", "accessories")
        if subject.get(key)
    )
    primary_evidence = f"{kind} {summary}"
    combined = f"{primary_evidence} {subject_evidence}"

    if flags.get("web_design") or _prompt_block_has_markers(combined, ("网页", "网站界面", "应用界面"), ("web design", "landing page", "app interface", "website")):
        return "social"
    if flags.get("cover_template") or _prompt_block_has_markers(combined, ("海报", "封面", "主视觉"), ("poster", "cover", "key visual")):
        return "poster"
    if flags.get("table_card") or _prompt_block_has_markers(combined, ("信息图", "图表", "卡片"), ("infographic", "data chart")):
        return "infographic"
    if _prompt_block_has_markers(combined, ("分镜", "镜头脚本"), ("storyboard", "shot list")):
        return "storyboard"
    if _prompt_block_has_markers(combined, ("无缝图案", "连续纹样", "平铺纹理"), ("seamless pattern", "repeat pattern")):
        return "pattern"
    if _prompt_block_has_markers(combined, ("3d视觉", "3d 视觉", "三维渲染", "立体渲染"), ("3d render", "cgi render")):
        return "three_d"
    if _prompt_block_has_markers(combined, ("服装设计", "时装", "穿搭", "秀场"), ("lookbook", "fashion editorial", "garment design")):
        return "fashion"

    category_markers = (
        ("food", ("美食", "食物", "菜品", "餐饮", "料理", "甜点", "蛋糕"), ("food", "cuisine", "dish", "meal", "dessert", "cake", "cupcake", "hot dog")),
        ("animal", ("动物", "宠物", "猫", "狗", "犬"), ("wildlife", "pet portrait", "dog", "cat", "retriever")),
        ("interior", ("室内", "客厅", "卧室"), ("interior", "living room", "bedroom")),
        ("architecture", ("建筑", "立面", "住宅", "房屋", "大楼"), ("architecture", "facade", "building", "house", "residence")),
        ("product", ("产品", "商品", "包装", "电商", "瓶", "罐", "盒", "杯", "腕表", "手表", "手机", "耳机", "香水"), ("product", "e-commerce", "bottle", "package", "packaging", "cup", "mug", "watch", "phone", "headphone", "headphones", "perfume", "cosmetic", "cosmetics", "device")),
        ("landscape", ("风景", "自然景观", "山川", "海岸"), ("landscape", "scenery")),
        ("character", ("角色设定", "角色设计", "人物设定"), ("character design", "character sheet")),
        ("scene_concept", ("场景概念", "环境概念", "世界观场景"), ("concept environment", "environment design")),
        ("social", ("社交媒体", "社媒", "小红书"), ("social media", "instagram post")),
        ("illustration", ("插画", "漫画", "绘本"), ("illustration", "comic")),
        ("portrait", ("人像", "肖像", "人物写真"), ("portrait", "headshot")),
    )
    for primary_type, chinese, english in category_markers:
        if _prompt_block_has_markers(primary_evidence, chinese, english):
            return primary_type

    for primary_type, chinese, english in category_markers[:4]:
        if _prompt_block_has_markers(subject_evidence, chinese, english):
            return primary_type
    if _prompt_block_has_human_evidence(subject_evidence):
        return "portrait"
    for primary_type, chinese, english in category_markers[4:]:
        if _prompt_block_has_markers(subject_evidence, chinese, english):
            return primary_type
    return "illustration"


def _prompt_blocks_from_image_analysis(
    result: dict[str, Any],
    primary_type: str = "",
    split_rule: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    analysis = _as_dict(result.get("analysis"))
    resolved_type = _infer_prompt_block_primary_type(analysis, primary_type)
    candidates: list[dict[str, Any]] = []

    def add(name: str, module_type: str, content: Any, tags: list[str] | None = None) -> None:
        clean_content = _clean_string(content, 12000)
        if not clean_content:
            return
        candidates.append({
            "name": name,
            "module_type": module_type,
            "content": clean_content,
            "compact_content": clean_content[:240] if len(clean_content) > 240 else clean_content,
            "english_content": "",
            "applicable_types": [resolved_type],
            "tags": ["图片解析", *(tags or [])][:12],
        })

    subjects = [item for item in _as_list(analysis.get("subjects")) if isinstance(item, dict)]
    subject_identity = _join_prompt_block_parts(*[
        _join_prompt_block_parts(subject.get("name"), subject.get("role"), subject.get("relationship"))
        for subject in subjects
    ])
    appearance = _join_prompt_block_parts(*[subject.get("visual_traits") for subject in subjects])
    pose = _join_prompt_block_parts(*[subject.get("pose") for subject in subjects])
    expression = _join_prompt_block_parts(*[
        _join_prompt_block_parts(subject.get("expression"), subject.get("gaze")) for subject in subjects
    ])
    clothing = _join_prompt_block_parts(*[subject.get("outfit") for subject in subjects])
    makeup_hair = _join_prompt_block_parts(*[subject.get("makeup_hair") for subject in subjects])
    accessories = _join_prompt_block_parts(*[subject.get("accessories") for subject in subjects])
    relationship = _join_prompt_block_parts(*[subject.get("relationship") for subject in subjects])
    subject_placement = _join_prompt_block_parts(*[
        _join_prompt_block_parts(subject.get("placement"), subject.get("body_crop")) for subject in subjects
    ])

    visual_summary = _clean_string(analysis.get("visual_summary"), 2000)
    layout = _as_dict(analysis.get("layout"))
    composition = _join_prompt_block_parts(layout, subject_placement)
    hints = _as_dict(analysis.get("generation_hints"))
    camera = _join_prompt_block_parts(hints.get("camera"), hints.get("aspect_ratio"))
    lighting = _join_prompt_block_parts(hints.get("lighting"))
    visual_style = _as_dict(analysis.get("visual_style"))
    color = _join_prompt_block_parts(hints.get("palette"), visual_style.get("palette"))
    prompt_blocks = _as_dict(analysis.get("prompt_blocks"))
    main_prompt = _join_prompt_block_parts(prompt_blocks.get("main_prompt_no_text"))
    style = _join_prompt_block_parts(
        prompt_blocks.get("universal_style_prompt"),
        visual_style.get("medium"), visual_style.get("rendering"), visual_style.get("style_scope"),
    )
    material = _join_prompt_block_parts(
        visual_style.get("texture"), visual_style.get("edge_quality"),
        visual_style.get("resolution_language"), hints.get("rendering"),
    )
    constraints = _join_prompt_block_parts(prompt_blocks.get("negative_prompt"))
    text_regions = [item for item in _as_list(analysis.get("text_regions")) if isinstance(item, dict)]
    text_evidence = _join_prompt_block_parts(*[
        _join_prompt_block_parts(item.get("text"), item.get("role"), item.get("position"), item.get("style"))
        for item in text_regions
    ])
    overlays = [item for item in _as_list(analysis.get("overlays")) if isinstance(item, dict)]
    overlay_evidence = _join_prompt_block_parts(*[
        _join_prompt_block_parts(item.get("type"), item.get("position"), item.get("appearance"), item.get("layering"), item.get("relationship"))
        for item in overlays
    ])

    subject_evidence = _join_prompt_block_parts(subject_identity, appearance)
    has_human_subject = _prompt_block_has_human_evidence(subject_evidence)
    if subjects and (has_human_subject or resolved_type in {"portrait", "character", "fashion"}):
        add("主体身份", "identity", subject_identity)
        add("外貌特征", "appearance", appearance)
        add("动作姿态", "pose", pose)
        add("表情视线", "expression", expression)
        add("服装造型", "clothing", clothing)
        add("妆发细节", "makeup_hair", makeup_hair)
        add("配饰道具", "accessories", accessories)
    elif subjects:
        add("主体特征", "subject", _join_prompt_block_parts(subject_identity, appearance, main_prompt, visual_summary))

    specific_blocks: dict[str, list[tuple[str, str, Any]]] = {
        "portrait": [
            ("人体约束", "anatomy_constraints", constraints),
        ],
        "landscape": [
            ("地貌环境", "landform", visual_summary),
            ("大气效果", "atmosphere", _join_prompt_block_parts(visual_summary, lighting)),
            ("前中后景", "depth", composition),
        ],
        "product": [
            ("商品结构", "product_structure", _join_prompt_block_parts(appearance, main_prompt, visual_summary)),
            ("材质工艺", "craft", material),
            ("核心卖点", "selling_points", visual_summary),
            ("商品摆放", "placement", composition),
            ("商业布光", "commercial_lighting", lighting),
            ("品牌限制", "brand_constraints", _join_prompt_block_parts(text_evidence, color)),
        ],
        "food": [
            ("食材状态", "ingredients", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("摆盘方式", "plating", composition),
            ("食物质感", "food_texture", material),
            ("温度气息", "steam", _join_prompt_block_parts(visual_summary, lighting)),
        ],
        "architecture": [
            ("建筑风格", "architectural_style", style),
            ("建筑体量", "massing", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("立面细节", "facade", _join_prompt_block_parts(appearance, material)),
            ("场地环境", "site", _join_prompt_block_parts(visual_summary, composition)),
        ],
        "interior": [
            ("空间布局", "space_layout", composition),
            ("家具陈设", "furniture", visual_summary),
            ("空间材质", "surface_materials", material),
            ("软装细节", "soft_furnishing", _join_prompt_block_parts(visual_summary, color)),
        ],
        "character": [
            ("角色身份", "character_identity", subject_identity),
            ("世界观", "worldbuilding", _join_prompt_block_parts(visual_summary, style)),
            ("角色轮廓", "silhouette", appearance),
            ("装备道具", "equipment", accessories),
            ("设定视图", "turnaround", composition),
        ],
        "scene_concept": [
            ("世界观", "worldbuilding", _join_prompt_block_parts(visual_summary, style)),
            ("地理环境", "geography", visual_summary),
            ("文明痕迹", "civilization", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("环境叙事", "environment_story", overlay_evidence),
            ("尺度关系", "scale", composition),
        ],
        "animal": [
            ("物种品种", "species", _join_prompt_block_parts(subject_identity, visual_summary)),
            ("毛发羽毛", "fur", _join_prompt_block_parts(appearance, material)),
            ("动作神态", "animal_action", _join_prompt_block_parts(pose, expression)),
            ("栖息环境", "habitat", visual_summary),
        ],
        "fashion": [
            ("服装版型", "garment_shape", clothing),
            ("面料质感", "fabric", _join_prompt_block_parts(clothing, material)),
            ("服装工艺", "craft", material),
            ("整体搭配", "styling", _join_prompt_block_parts(clothing, accessories, color)),
            ("展示姿态", "lookbook_pose", _join_prompt_block_parts(pose, composition)),
        ],
        "storyboard": [
            ("景别", "shot_size", composition),
            ("机位", "camera_position", camera),
            ("人物调度", "blocking", _join_prompt_block_parts(subject_placement, relationship)),
            ("镜头动作", "action", pose),
            ("运镜", "camera_motion", camera),
            ("连续性", "continuity", constraints),
        ],
        "illustration": [
            ("叙事瞬间", "story_moment", visual_summary),
            ("角色关系", "character_relation", _join_prompt_block_parts(subject_identity, relationship)),
            ("线条表现", "linework", style),
            ("上色方式", "rendering", _join_prompt_block_parts(style, material)),
            ("对白区域", "speech_area", _join_prompt_block_parts(text_evidence, composition)),
        ],
        "poster": [
            ("核心视觉", "key_visual", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("文案", "copy", text_evidence),
            ("信息层级", "information_hierarchy", _join_prompt_block_parts(layout, text_evidence)),
            ("版式", "layout", composition),
            ("文字区域", "text_region", text_evidence),
            ("品牌色", "brand_color", color),
            ("Logo 区域", "logo_region", overlay_evidence),
        ],
        "social": [
            ("视觉钩子", "visual_hook", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("标题区域", "headline", text_evidence),
            ("品牌系统", "brand_system", _join_prompt_block_parts(style, color)),
            ("平台安全区", "safe_area", composition),
        ],
        "infographic": [
            ("信息范围", "data_scope", _join_prompt_block_parts(visual_summary, text_evidence)),
            ("信息结构", "information_structure", composition),
            ("图形关系", "diagram", _join_prompt_block_parts(overlay_evidence, layout)),
            ("标注文字", "annotation", text_evidence),
            ("可读性", "readability", _join_prompt_block_parts(layout, constraints)),
        ],
        "three_d": [
            ("建模形态", "model_shape", _join_prompt_block_parts(appearance, main_prompt, visual_summary)),
            ("材质着色", "shader", material),
            ("渲染表现", "render_engine", style),
            ("摄影棚", "studio", _join_prompt_block_parts(visual_summary, lighting)),
        ],
        "pattern": [
            ("图案元素", "motif", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("重复规则", "repeat", _join_prompt_block_parts(layout, composition)),
            ("元素密度", "density", composition),
            ("接缝要求", "seam", constraints),
        ],
    }
    for name, module_type, content in specific_blocks.get(resolved_type, []):
        add(name, module_type, content, ["拆分规则"])

    add("场景主题", "scene", visual_summary)
    add("构图布局", "composition", composition)
    add("镜头视角", "camera", camera)
    add("光线氛围", "lighting", lighting)
    add("色彩方案", "color", color)
    add("视觉风格", "style", style)
    add("材质渲染", "material", material)
    add("负面约束", "constraints", constraints)
    if overlays:
        add("叠加元素", "custom", overlay_evidence)
    if not candidates:
        raise ValueError("图片分析完成，但没有得到可保存的素材块")
    return _normalize_extracted_prompt_blocks({"blocks": candidates}, resolved_type, split_rule), resolved_type
