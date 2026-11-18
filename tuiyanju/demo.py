"""Built-in Offline Demo Mode for zero-API-key end-to-end multi-agent deduction."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from fastapi import Request

from .models import (
    AnalyzeRequest,
    build_fallback_casting,
    normalize_casting,
    normalize_depth_key,
    should_include_roundtable,
)


def _chunk_text(text: str, chunk_size: int = 36) -> list[str]:
    clean = str(text or "")
    if not clean:
        return []
    return [clean[idx : idx + chunk_size] for idx in range(0, len(clean), chunk_size)]


def _curated_casting_if_matched(req: AnalyzeRequest) -> dict[str, Any] | None:
    topic = req.topic.strip()
    lower = topic.lower()
    if any(k in lower for k in ("ai", "白领", "大模型", "替代")):
        raw = {
            "issue_type": req.issue_type if req.issue_type != "自动判断" else "科技冲击型",
            "topic_deconstruction": {
                "surface_conflict": f"围绕「{topic}」，舆论表面在争 AI 究竟是生产力福音还是抢饭碗机器",
                "real_dispute": "实际在争岗位标准化红利归谁拿走、初级岗位断层谁来兜底，以及剩下的白领如何重定议价权",
                "key_variables": [
                    "岗位工作流可拆解与可验证程度",
                    "企业真实降本压力与容错责任归属",
                    "组织重构速度与从业者跨界迁移能力",
                ],
                "loud_but_minor": "社交媒体上“三天学会提示词年薪翻倍”或“所有白领立刻失业”的极端叙事",
                "silent_but_powerful": "企业财务预算审批表、合规追责边界以及默默冻招的HC名额",
            },
            "conflict_axes": [
                "效率红利捕获者 vs 议价权受损执行层",
                "工具提效逻辑 vs 事故背锅责任制",
                "短期编制缩减 vs 长期人才梯队断代",
                "高声量技术焦虑 vs 沉默的组织惯性",
            ],
            "agents": [
                {
                    "id": "agent_1",
                    "display_name": "许知夏",
                    "alias": "承压一线白领",
                    "age": "28岁",
                    "identity": "一线城市互联网内容与项目运营",
                    "core_interest": "保住稳定现金流，别沦为只干杂活的工具核对员",
                    "main_fear": "工作量因AI翻倍，岗位单价和不可替代性却一起往下掉",
                    "info_type": "日常高频使用AI工具的真实返工率与团队排期变化",
                    "dimensions": ["直接承受后果", "职业迁移压力"],
                    "blind_spot": "容易把局部裁员和冻招全部归因于AI技术本身",
                    "why_selected": "身处最先被标准化改写的白领工种前线",
                },
                {
                    "id": "agent_2",
                    "display_name": "周明远",
                    "alias": "算账型业务负责人",
                    "age": "40岁",
                    "identity": "中型企业业务线副总裁，背负利润与人效指标",
                    "core_interest": "用同样甚至更少的人力编制把交付速度和毛利率拉起来",
                    "main_fear": "盲目裁掉熟手导致交付翻车，或者不推进AI被董事会质疑保守",
                    "info_type": "部门人力成本账本、客户交付投诉率与采购ROI",
                    "dimensions": ["结果影响力", "成本收益核算"],
                    "blind_spot": "习惯低估隐性沟通协调与新人培养断层的长期代价",
                    "why_selected": "手里握着编制审批和工具采购的真实按钮",
                },
                {
                    "id": "agent_3",
                    "display_name": "梁哲",
                    "alias": "AI落地架构师",
                    "age": "33岁",
                    "identity": "专门帮企业部署Agent工作流的技术交付负责人",
                    "core_interest": "打通高重复场景闭环，拿到可续费的企业级订单",
                    "main_fear": "客户管理层预期过高，把脏数据和烂流程的锅甩给模型",
                    "info_type": "几十家企业POC测试的真实准确率与卡点清单",
                    "dimensions": ["技术边界体感", "内部生态位"],
                    "blind_spot": "习惯从流程可自动化角度看人，轻视组织政治阻力",
                    "why_selected": "最清楚AI在真实企业环境里哪里真能顶人、哪里纯属演示",
                },
                {
                    "id": "agent_4",
                    "display_name": "沈清和",
                    "alias": "劳动合规与制度观察者",
                    "age": "46岁",
                    "identity": "长期处理企业用工调整与责任认定的劳动法务顾问",
                    "core_interest": "权责链条清晰可追责，避免用工调整演变成系统性纠纷",
                    "main_fear": "算法出错没人签字担责，以及初级岗位萎缩带来青年就业摩擦",
                    "info_type": "企业优化补偿案例、合规审查标准与监管风向",
                    "dimensions": ["制度端约束", "责任归属"],
                    "blind_spot": "对市场端灰犀牛式的冻招替代缺乏事前干预抓手",
                    "why_selected": "揭示决定“能不能完全替代人”的终极门槛是签字担责",
                },
                {
                    "id": "agent_5",
                    "display_name": "陈小满",
                    "alias": "应届求职入局者",
                    "age": "22岁",
                    "identity": "即将毕业、正在海投初级白领岗位的本科应届生",
                    "core_interest": "先拿到一张能进场攒经验的入场券",
                    "main_fear": "以前留给新人练手的初级活全归了AI，连上桌学徒的机会都没了",
                    "info_type": "春招秋招岗位缩水体感与同届同学求职去向",
                    "dimensions": ["代际入口冲击", "高脆弱度"],
                    "blind_spot": "还没进过真实职场，容易把宏观周期收缩与技术替代混在一起",
                    "why_selected": "AI最先砍掉的往往不是老员工，而是不招新人的入口岗位",
                },
                {
                    "id": "agent_6",
                    "display_name": "顾清河",
                    "alias": "超级个体操盘手",
                    "age": "35岁",
                    "identity": "离开大厂后带着两名助手加一套AI工具接单的独立顾问",
                    "core_interest": "用极小团队撬动过去十人团队才能接的商业交付",
                    "main_fear": "同质化供给泛滥把客单价卷穿，只剩获客端能赚钱",
                    "info_type": "一人公司交付效率、客户压价幅度与渠道成本",
                    "dimensions": ["顺势套利", "新组织形态"],
                    "blind_spot": "幸存者偏差明显，默认人人都有成熟的客户资源和兜底能力",
                    "why_selected": "代表在白领岗位分化中最先吃到杠杆红利的一批人",
                },
            ],
        }
        return normalize_casting(raw, req)
    return None


def _build_monologue_for_agent(topic: str, agent: dict[str, Any], index: int, depth_key: str) -> str:
    name = agent["display_name"]
    identity = agent["identity"]
    interest = agent["core_interest"]
    fear = agent["main_fear"]
    info = agent["info_type"]

    templates = [
        (
            f"外界聊「{topic}」总爱拿宏大趋势吓唬人，但在我每天干活的工位上，账根本不是这么算的。"
            f"我是做{identity}的，每天睁眼先看手头那堆排期。我现在最大的感受不是突然没活干了，"
            f"而是上面默认你有了新工具、新渠道，一个人就得干以前两个人的活，出活速度还得快一倍。\n\n"
            f"我最在乎的其实就一条：{interest}。可现实最磨人的地方在于，{info}告诉我，"
            f"真正难啃的烂摊子、跨部门扯皮和客户临时变卦一点没少，容易出彩的基础活反倒不值钱了。"
            f"我最怕的是{fear}。接下来我不会傻等着看风向，我会先把手里最依赖“出面协调和拍板兜底”的那部分环节攥紧，"
            f"同时给自己留好随时能迁移的副线技能。"
        ),
        (
            f"如果只看网上吵架，好像谁做决定谁就是坏人；可坐到我这个位置上，每笔支出都是硬邦邦的数字。"
            f"面对「{topic}」，我从来不看口号，我只看两本账：一本是投入多久能回本，另一本是出了岔子谁来扛责。"
            f"我现在掌握的{info}非常明确——任何变化在PPT里都很美，一进真实业务流就会撞上数据脏、标准乱、协同慢。\n\n"
            f"我的核心目标很清楚：{interest}。我也实话实说，我最忌惮的就是{fear}。"
            f"所以我接下来的动作不会是一刀切掀桌子，而是先拿最标准化、试错成本最低的边缘环节开刀：跑通一处，冻结一处新增预算，"
            f"把省出来的筹码押在真正能抗风险的核心骨干身上。"
        ),
        (
            f"大家都在讨论场面上的输赢，很少有人低头看一眼像我这样的普通日子怎么过。"
            f"站在{identity}的处境里，「{topic}」落到家里就是每个月固定的开销、时间怎么分、万一踩空了有没有退路。"
            f"我平时能接触到的就是{info}，看着身边人一会儿一个说法，心里不可能不打鼓。\n\n"
            f"我最看重的就是{interest}，最担心的也是{fear}。"
            f"别人容错率高，试错了拍拍土就能换条赛道；我们这种拖家带口或者刚攒点家底的人，折腾不起。"
            f"所以我接下来的选择一定偏稳：不抢第一波风口，也不信包治百病的焦虑贩卖，先把现金流和确定性守住，看清楚规则真落地了再动。"
        ),
        (
            f"把「{topic}」放回制度与执行链条里看，很多情绪化的争论其实抓错了重点。"
            f"在{identity}的日常工作里，我们每天打交道的是{info}。你会发现一件事能不能推开，"
            f"往往不取决于技术或想法有多激进，而取决于出了责任事故之后，最后那张签字单上写谁的名字。\n\n"
            f"我最核心的考量是{interest}，最警惕的风险是{fear}。"
            f"只要权责边界、合规底线和缓冲机制还没对齐，任何激进推进都会在执行端撞上软抵抗或者回摆。"
            f"接下来大概率的走向，一定是先在局部试点划出红线清单，用准入标准和责任追索把失控风险关进笼子里。"
        ),
        (
            f"别人看「{topic}」看到的是防守，我看到的是一次难得的缝隙重排。"
            f"干{identity}这几年，我靠的就是盯紧{info}里的细微松动：每当旧办法嫌麻烦、大机构转身慢的时候，"
            f"先跑通最小闭环的人就能吃下第一口溢价。\n\n"
            f"我的诉求特别直接：{interest}。当然我也没那么天真，我每天都在提防{fear}。"
            f"窗口期从来不会一直敞着，所以我现在的打法就是快进快出——不求大而全，专挑大团队看不上、个人又搞不定的夹层需求下手，"
            f"赶在门槛被抹平之前把口碑和长期客户锁死。"
        ),
        (
            f"如果我们把时间轴拉长到三五年再回头看，「{topic}」今天吵得最凶的部分，大概率只是过渡期的噪音。"
            f"从我持续跟踪的{info}来看，真正改写结局的从来不是某一次突发热点，而是供需结构、人口与成本曲线在底下慢慢合拢。\n\n"
            f"我真正在意的是{interest}，也一直担心{fear}。"
            f"短期的阵痛确实真实，不该拿长远趋势去轻飘飘地抹平当事人的难处；但反过来，如果只盯着眼前三个月的得失，"
            f"就会漏掉底下正在成型的结构断层。接下来最值得做的，是把观察指标钉在真实的资金流向和入口变化上，而不是跟着热搜摇摆。"
        ),
    ]

    body = templates[(index - 1) % len(templates)]
    if depth_key == "quick":
        first_para = body.split("\n\n")[0]
        return f"{first_para} 对我（{name}）来说，眼下最关键的就是守住「{interest}」，避开「{fear}」。"
    if depth_key in {"pro", "ultra"}:
        extra = (
            "\n\n再补一句只有我们身在局里的人才懂的实情：外人以为我们在争态度，"
            "其实我们在争缓冲期。只要缓冲期够长、规则别朝令夕改，大多数人都能自己找着出路；"
            "怕就怕上面只看报表数字，把原本需要两年消化的账硬压在一个季度里结清。"
        )
        return body + extra
    return body


def _build_demo_roundtable(topic: str, agents: list[dict[str, Any]], depth_key: str) -> str:
    participants = agents if depth_key == "ultra" else agents[: min(4, len(agents))]
    a1 = participants[0]
    a2 = participants[1]
    a3 = participants[2]
    a4 = participants[3] if len(participants) > 3 else participants[0]

    blocks = [
        "# 圆桌激辩",
        f"## {a1['display_name']}\n"
        f"先把窗户纸捅破吧：在「{topic}」这件事上，最让人憋屈的不是变化本身，而是收益和代价根本不对称。"
        f"好听的效率词都在汇报材料里，真落到一线，全是加量不加价的摩擦和随时被替代的不安全感。",
        "[CLASH]",
        f"## {a2['display_name']}\n"
        f"我直接反驳 {a1['display_name']} 一点：你以为做决策的人喜欢折腾团队吗？不是我们想压人，"
        f"是外部账本根本不给人喘气空间。如果我不先把低效环节改掉，半年后整个盘子缩水，到时候连现在这口锅都端不住。"
        f"但你忽略了一件事——真正稀缺的从来不是埋头苦干，而是敢替结果兜底。",
        f"## {a3['display_name']}\n"
        f"顺着 {a2['display_name']} 的话我追问一句：既然你们都承认核心是“谁替结果兜底”，"
        f"那为什么在实际推进里，大家嘴上喊着升级，动作上却总是先把新人的入口和试错缓冲砍掉？"
        f"不同意把所有锅都甩给外部环境，默认规则怎么设，决定了普通人是能顺着台阶往上走，还是直接滑下去。",
        f"## {a4['display_name']}\n"
        f"听下来我反倒发现一个意外共识：不管是 {a1['display_name']} 担心的一线承压，还是 {a2['display_name']} 算的经营死账，"
        f"其实你们都承认「只喊口号或一刀切」一定翻车。真正卡脖子的不是要不要变，而是责任签字权、过渡期成本分摊这两件事没人挑明。"
        f"谁先把权责边界立住，谁才算摸到了真开关。",
    ]

    if depth_key == "ultra" and len(participants) > 4:
        for extra_agent in participants[4:]:
            blocks.append(
                f"## {extra_agent['display_name']}\n"
                f"我再补一块你们刚才没算进去的现实：除了台面上的存量博弈，场外已经有人绕开旧流程在吃增量了。"
                f"等 {a2['display_name']} 和 {a4['display_name']} 把内部流程磨平，外面的客单价和分配格局早就换了一轮。"
            )
    return "\n\n".join(blocks)


def _build_demo_enhancements(topic: str, casting: dict[str, Any], active_modules: list[str]) -> str:
    if not active_modules:
        return ""
    agents = casting["agents"]
    a1 = agents[0]["display_name"]
    a2 = agents[1]["display_name"]
    a4 = agents[3]["display_name"]
    chunks = ["## 增强模块"]

    if "winners" in active_modules:
        chunks.append(
            "### 模块 A：赢家 / 输家地图\n"
            f"- **短期获益者**：手握分发/采购开关与现成客户渠道的决策方（如 {a2} 一侧），能最快把成本压下来。\n"
            f"- **短期受损者**：工作高度标准化、缺乏签字权与议价筹码的一线执行岗及刚入局新人（如 {a1} 一侧）。\n"
            "- **长期可能翻盘者**：掌握跨界协同、复杂现场排雷与责任兜底能力的复合型操盘者。\n"
            "- **长期可能被透支者**：只靠短期压榨存量缓冲、却砍掉人才梯队和信任资产的短视组织。"
        )
    if "timeline" in active_modules:
        chunks.append(
            "### 模块 B：时间切片推演\n"
            f"- **接下来 1 个月**：围绕「{topic}」的情绪争论继续升温，观望者多、试水者小步灰测。\n"
            "- **接下来 6 个月**：第一批算清成本账的机构完成局部替换或规则收口，分化从口水战变成真实收入与岗位结构差距。\n"
            f"- **接下来 2 年**：新默认规则定型，制度与责任边界（{a4} 所指出的签字担责机制）成为新的行业分水岭。"
        )
    if "signal" in active_modules:
        chunks.append(
            "### 模块 C：舆论 vs 真实变量\n"
            f"- **网上最响的点**：围绕「{topic}」的极端个案、道德指责与贩卖焦虑的速成神话。\n"
            "- **真正决定结果的点**：预算审批流向、事故追责机制、默认产品/制度设置，以及场外轻资产套利者的渗透速度。"
        )
    if "action" in active_modules:
        chunks.append(
            "### 模块 D：谁会先行动\n"
            f"最先出手的不会是吵得最凶的围观者，而是两类人：一类是背着硬指标的预算控制者（{a2}），先从冻结边缘增量开始；"
            "另一类是没有历史包袱的场外套利者，直接用新工具+小团队切走高毛利细分单。"
        )
    if "monitor" in active_modules:
        chunks.append(
            "### 模块 E：观察指标\n"
            "1. **初级/入口容量信号**：看真实招聘、准入门槛或新增预算是在放开还是静默收缩。\n"
            "2. **责任认定信号**：看关键节点出事后，行业合同与监管口径把板子打在谁身上。\n"
            "3. **价格与留存信号**：看第一批吃螃蟹者的真实复购率/留存率，而非宣传稿里的渗透率。"
        )
    if "appendix" in active_modules:
        axes_str = "、".join(casting["conflict_axes"])
        chunks.append(
            "### 模块 F：结构化附录\n"
            f"- **议题类型**：{casting['issue_type']}\n"
            f"- **核心冲突轴**：{axes_str}\n"
            f"- **高利害角色**：{a1}、{agents[2]['display_name']}\n"
            f"- **高影响角色**：{a2}、{a4}\n"
            "- **隐藏变量**：签字担责机制、隐性冻招/预算收缩、过渡期摩擦成本\n"
            "- **未来触发器**：标杆性责任事故、头部平台/机构改写默认规则、宏观现金流拐点"
        )

    return "\n\n".join(chunks)


def _build_demo_director_markdown(
    req: AnalyzeRequest,
    casting: dict[str, Any],
    roundtable_markdown: str,
) -> str:
    topic = req.topic.strip()
    decon = casting["topic_deconstruction"]
    agents = casting["agents"]
    a1, a2, a3, a4 = agents[0], agents[1], agents[2], agents[3]

    enhancements_md = _build_demo_enhancements(topic, casting, req.active_modules)
    roundtable_ref = (
        f"尤其在圆桌交锋里，{a1['display_name']} 与 {a2['display_name']} 的正面碰撞直接把“态度之争”剥开了——"
        if roundtable_markdown
        else "把暗房里几份互不通气的独白放在一起对照，立刻就能看清——"
    )

    sections = [
        "# 话题解构\n"
        f"- **表面上在吵什么**：{decon['surface_conflict']}。\n"
        f"- **实际上在争什么**：{decon['real_dispute']}。\n"
        f"- **真正决定走向的变量**：{'；'.join(decon['key_variables'])}。\n"
        f"- **哪些声音很响但未必关键**：{decon['loud_but_minor']}。\n"
        f"- **哪些力量不吭声但最能改结果**：{decon['silent_but_powerful']}。",
        "# 局长整合报告\n\n"
        "### A. 表层冲突\n"
        f"围绕「{topic}」，舆论场上最热闹的是非黑即白的站队：支持者大谈效率跃迁与时代红利，担忧者痛陈冲击与失控。"
        "但如果只停留在这一层，除了制造焦虑和口水仗，解释不了任何现实动作。\n\n"
        "### B. 深层动力\n"
        f"{roundtable_ref}{a1['display_name']} 守的是个人现金流与职业尊严，{a2['display_name']} 算的是组织存活率与投入产出比，"
        f"{a3['display_name']} 看的是家庭与日常秩序的容错底线，而 {a4['display_name']} 盯的是出了事谁签字担责。"
        "每个人都在自己的约束条件里做局部最优解，合在一起却构成了全局紧绷。\n\n"
        "### C. 共识地带\n"
        f"最反直觉的共识在于：表面对立最凶的 {a1['display_name']} 和 {a2['display_name']}，私底下其实都不相信“靠喊口号或一刀切”能解决问题。"
        "双方在行动上都在悄悄做同一件事——砍掉高水分的中间动作，把筹码往“可验证结果”和“真实兜底能力”上集中。\n\n"
        "### D. 断层与错位\n"
        "最大的错位不是认知高低，而是时间尺度与风险敞口严重不对称：手握预算开关的人按季度看报表，试错了可以及时止损；"
        "而直接承接变化的一线个体与家庭按三五年规划生活，一次踩空就要自己吞下全部沉没成本。\n\n"
        "### E. 嗓门与筹码\n"
        "声音最大的是网上的极端个案与情绪化批判，但真正手里握牌、能改写默认规则的是预算审批方、平台机制设计者与制度合规端；"
        "而人数最多、长期扛下结果的普通当事人往往最晚拿到确定性信息。\n\n"
        "### F. 隐藏变量\n"
        f"最大的误区不是低估了「{topic}」的热度，而是把一场由“成本账本 + 签字担责边界 + 默认规则”共同决定的结构重排，误当成了单纯的个人努力或观念问题。\n\n"
        "### G. 未来触发器\n"
        "一旦出现两类信号，局势会迅速加速甚至反转：一是头部机构跑通低风险标准范式并公开压低成本线；"
        "二是发生标志性的越界或质量责任事故，倒逼监管与制度端瞬间收紧准入红线。\n\n"
        "### H. 立体真相\n"
        f"把所有暗房碎片拼回一起，「{topic}」真正的影响当然深远，但它改写现实的方式不是一夜之间掀翻所有人，而是静悄悄地重划议价权分水岭。"
        "它不是一道“支持还是反对”的选择题，而是一道“谁拥有缓冲期、谁能替复杂结果兜底”的生存结构题。",
        "# 行动建议\n\n"
        f"建议一：面向直接承压的一线个体（如 {a1['display_name']}）——最该读这份报告并立刻行动的，是正在一线承受挤压的执行者、手握资源配置的管理者与普通家庭决策者。"
        "本周就盘点手头工作流，主动把耗时但低价值的标准化环节交给工具提效，把省下的精力集中到跨方对齐、复杂判断与结果验收上；"
        "这不需要额外花钱或辞职折腾，在现有岗位上就能立刻启动且失败风险极低。\n\n"
        f"建议二：面向手握预算与团队的决策者（如 {a2['display_name']}）——不要搞运动式一刀切，先挑 1 个边界清晰、容错可控的子场景做 30 天小闭环试点，"
        "同时明确人工复核与签字责任人；这样既能拿到真实ROI数据向上交账，又不会把核心骨干逼走导致交付崩盘。\n\n"
        f"建议三：面向需要做中长期规划的家庭与新入局者（如 {a3['display_name']}）——停止为二手焦虑付费，在做大额投入或路径切换前，"
        "先看目标领域的真实入口岗位数量与近半年现金流质量，留足 6 到 12 个月安全垫再下注。",
        "# 事实 / 推断 / 情绪分层\n\n"
        f"- **事实层**：围绕「{topic}」的工具/规则变化已经进入真实业务与生活场景，各方所处的成本约束、信息渠道与试错缓冲存在显著差异。\n"
        "- **推断层**：未来半年到两年内，纯标准化、无人兜底的中间环节议价权大概率持续走弱，而握有资源开关与合规签字权的节点话语权将进一步集中。\n"
        "- **情绪层**：“一夜彻底归零”或“躺赢暴富”均属传播端放大的焦虑与狂热偏差，不能直接当作个人决策依据。",
    ]

    if enhancements_md:
        sections.append(enhancements_md)

    return "\n\n".join(sections)


def build_demo_bundle(req: AnalyzeRequest) -> dict[str, Any]:
    """Construct a complete, deterministic, topic-aware demo bundle + schema-valid payload."""
    depth_key = normalize_depth_key(req.depth)
    casting = _curated_casting_if_matched(req) or build_fallback_casting(req)
    agent_outputs: list[dict[str, Any]] = []
    for idx, agent in enumerate(casting["agents"], start=1):
        monologue = _build_monologue_for_agent(req.topic.strip(), agent, idx, depth_key)
        agent_outputs.append({**agent, "monologue": monologue})

    roundtable_md = (
        _build_demo_roundtable(req.topic.strip(), casting["agents"], depth_key)
        if should_include_roundtable(req)
        else ""
    )
    director_md = _build_demo_director_markdown(req, casting, roundtable_md)

    # Also build structured JSON conforming to schemas/analysis.json (agents 3..8)
    schema_agents = [
        {
            "id": item["id"],
            "display_name": item["display_name"],
            "alias": item["alias"],
            "identity": item["identity"],
            "core_interest": item["core_interest"],
            "main_fear": item["main_fear"],
            "info_type": item["info_type"],
            "dimensions": item["dimensions"],
            "blind_spot": item["blind_spot"],
            "voice_profile": item["voice_profile"],
            "monologue": item["monologue"],
        }
        for item in agent_outputs[:8]
    ]
    a1 = agent_outputs[0]["display_name"]
    a2 = agent_outputs[1]["display_name"]
    a3 = agent_outputs[2]["display_name"]

    structured = {
        "topic_deconstruction": casting["topic_deconstruction"],
        "agents": schema_agents,
        "director_summary": {
            "surface_conflict": casting["topic_deconstruction"]["surface_conflict"],
            "deep_drivers": "各方在现金流安全、组织ROI、家庭容错底线与责任签字边界上的局部最优彼此拉扯。",
            "common_ground": f"表面对立的 {a1} 与 {a2} 都不相信光喊口号有效，且都在把筹码押向可验证结果与兜底能力。",
            "misalignment": "按季度看报表的资源掌握者与按三五年押注生活的承受者之间存在严重的时间与风险错位。",
            "voice_vs_power": "极端个案声量最大，但预算审批方、默认规则设计者与制度合规端才握有真开关。",
            "hidden_variables": "责任签字机制、隐性预算收缩与迁移缓冲期长度。",
            "future_triggers": "低风险标杆范式跑通压低成本线，或重大责任事故触发强监管收口。",
            "stereo_truth": f"「{req.topic.strip()}」不是简单的利弊站队题，而是议价权与风险缓冲期的重新分配。",
        },
        "action_suggestions": [
            {
                "target": f"直接承压的一线个体（如 {a1}）",
                "suggestion": "主动剥离低价值标准化动作，把时间集中到跨方对齐、复杂判断与结果验收上。",
                "reason": "无需额外资金成本，在现有岗位上即可立刻建立不可替代缓冲垫。",
            },
            {
                "target": f"手握预算与团队的决策者（如 {a2}）",
                "suggestion": "先选 1 个容错可控的子场景做 30 天闭环试点，并明确人工复核签字责任人。",
                "reason": "既能验证真实ROI，又能避免一刀切引发交付事故和骨干流失。",
            },
            {
                "target": f"家庭与路径规划者（如 {a3}）",
                "suggestion": "拒绝为情绪焦虑付费，盯住真实入口岗位与现金流质量，预留 6-12 个月安全垫。",
                "reason": "在高不确定周期里守住容错底线，才能等到规则明朗后的确定性机会。",
            },
        ],
        "layering": {
            "facts": "技术与规则变化已进入真实场景，不同群体掌握的资源开关与试错成本差异客观存在。",
            "inferences": "缺乏责任兜底的纯标准化环节议价权将持续走弱，握有规则与预算开关的一方话语权更集中。",
            "emotions_biases": "“一夜归零”与“躺赢神话”均属传播端放大的情绪极化，不应直接作为决策依据。",
        },
    }

    return {
        "casting": casting,
        "agent_outputs": agent_outputs,
        "roundtable_markdown": roundtable_md,
        "director_markdown": director_md,
        "structured_analysis": structured,
    }


def _sse(event_type: str, **payload: Any) -> str:
    import json

    return f"data: {json.dumps({'type': event_type, **payload}, ensure_ascii=False)}\n\n"


async def stream_demo_multi_agent(
    req: AnalyzeRequest,
    request: Request | None = None,
    *,
    auto_fallback: bool = False,
    chunk_delay: float = 0.02,
) -> AsyncIterator[str]:
    """Stream a realistic multi-agent deduction offline with concurrent darkroom chunks."""
    bundle = build_demo_bundle(req)
    casting = bundle["casting"]
    agent_outputs = bundle["agent_outputs"]
    roundtable_md = bundle["roundtable_markdown"]
    director_md = bundle["director_markdown"]

    yield _sse("mode_resolved", mode="demo", auto_fallback=auto_fallback)
    if auto_fallback:
        yield _sse(
            "status",
            label="未检测到有效 API Key，已自动切换至内置离线演示模式（零配置完整推演）",
        )
    else:
        yield _sse("status", label="已启动内置离线演示模式 · 正在拆解话题与核心冲突轴")

    if chunk_delay > 0:
        await asyncio.sleep(chunk_delay)
    if request is not None and await request.is_disconnected():
        return

    yield _sse(
        "casting",
        issue_type=casting["issue_type"],
        topic_deconstruction=casting["topic_deconstruction"],
        conflict_axes=casting["conflict_axes"],
        agents=casting["agents"],
    )
    yield _sse(
        "status",
        label=f"已完成选角，{len(agent_outputs)} 位 Agent 正并发进入独立暗房（物理隔离演示）",
    )

    # Start all agents concurrently so UI shows parallel darkroom cards updating live
    per_agent_chunks: list[tuple[dict[str, Any], list[str]]] = []
    for item in agent_outputs:
        agent_meta = {k: v for k, v in item.items() if k != "monologue"}
        yield _sse("agent_start", agent=agent_meta)
        per_agent_chunks.append((item, _chunk_text(item["monologue"], 34)))

    max_steps = max((len(chunks) for _, chunks in per_agent_chunks), default=0)
    finished_ids: set[str] = set()
    for step_idx in range(max_steps):
        if request is not None and await request.is_disconnected():
            return
        for item, chunks in per_agent_chunks:
            aid = item["id"]
            if step_idx < len(chunks):
                yield _sse("agent_chunk", agent_id=aid, content=chunks[step_idx])
            elif aid not in finished_ids:
                finished_ids.add(aid)
                yield _sse("agent_done", agent_id=aid)
        if chunk_delay > 0:
            await asyncio.sleep(chunk_delay)

    for item, _ in per_agent_chunks:
        aid = item["id"]
        if aid not in finished_ids:
            finished_ids.add(aid)
            yield _sse("agent_done", agent_id=aid)

    if roundtable_md:
        if request is not None and await request.is_disconnected():
            return
        yield _sse("roundtable_start", label="暗房门打开，圆桌激辩正式开始")
        for piece in _chunk_text(roundtable_md, 48):
            if request is not None and await request.is_disconnected():
                return
            yield _sse("roundtable_chunk", content=piece)
            if chunk_delay > 0:
                await asyncio.sleep(chunk_delay)
        yield _sse("roundtable_done")

    if request is not None and await request.is_disconnected():
        return
    yield _sse("director_start", label="局长正在整合所有暗房与交锋材料")
    for piece in _chunk_text(director_md, 56):
        if request is not None and await request.is_disconnected():
            return
        yield _sse("director_chunk", content=piece)
        if chunk_delay > 0:
            await asyncio.sleep(chunk_delay)

    yield _sse("director_done")
    yield _sse("status", label="离线演示推演完成，可体验 30 秒摘要与 Full / Share 导出")
    yield _sse("done")


async def stream_demo_single_stream(
    req: AnalyzeRequest,
    request: Request | None = None,
    *,
    auto_fallback: bool = False,
    chunk_delay: float = 0.015,
) -> AsyncIterator[str]:
    """Stream a single-pass Markdown demo when single_stream runs without API credentials."""
    bundle = build_demo_bundle(req)
    casting = bundle["casting"]
    agent_outputs = bundle["agent_outputs"]
    roundtable_md = bundle["roundtable_markdown"]
    director_md = bundle["director_markdown"]

    roster_lines = [
        "# 动态选角",
        f"- **议题类型**：{casting['issue_type']}",
        f"- **核心冲突轴**：{'；'.join(casting['conflict_axes'])}",
        "",
    ]
    for agent in casting["agents"]:
        roster_lines.append(
            f"- **{agent['display_name']}**（{agent['age']} · {agent['alias']}）：{agent['identity']}｜核心利益：{agent['core_interest']}"
        )

    monologue_lines = ["# 独立思考暗房"]
    for item in agent_outputs:
        monologue_lines.append(f"## {item['display_name']}（{item['alias']}）\n\n{item['monologue']}")

    parts = [
        "\n".join(roster_lines),
        "\n\n".join(monologue_lines),
    ]
    if roundtable_md:
        parts.append(roundtable_md)
    parts.append(director_md)
    full_markdown = "\n\n---\n\n".join(parts)

    yield _sse("mode_resolved", mode="single_stream", auto_fallback=auto_fallback, demo=True)
    yield _sse(
        "status",
        label="未检测到有效 API Key，已使用内置离线引擎演示极速单流推演",
    )
    for piece in _chunk_text(full_markdown, 64):
        if request is not None and await request.is_disconnected():
            return
        yield _sse("chunk", content=piece)
        if chunk_delay > 0:
            await asyncio.sleep(chunk_delay)
    yield _sse("status", label="单流推演已完成")
    yield _sse("done")
