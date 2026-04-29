"""Day-1 种子事件库 (anchors)：高频出现专家观点的论坛/采访栏目，agent 可优先挖出席名单."""

DEFAULT_EVENTS = [
    {"name": "中国发展高层论坛", "kind": "forum", "host": "国务院发展研究中心",
     "url": "https://www.cdf-foundation.com/", "description": "中国最具影响力的高层政策对话论坛"},
    {"name": "世界人工智能大会 (WAIC)", "kind": "forum", "host": "上海市人民政府",
     "url": "https://www.worldaic.com.cn/", "description": "中国 AI 产业旗舰大会"},
    {"name": "Stanford HAI", "kind": "paper", "host": "Stanford University",
     "url": "https://hai.stanford.edu/", "description": "斯坦福 Human-Centered AI 研究所，年度 AI Index 报告"},
    {"name": "GTC", "kind": "keynote", "host": "NVIDIA",
     "url": "https://www.nvidia.com/gtc/", "description": "NVIDIA 年度大会，黄仁勋主旨演讲"},
    {"name": "Google I/O", "kind": "keynote", "host": "Google",
     "url": "https://io.google/", "description": "Google 年度开发者大会"},
    {"name": "All-In Podcast", "kind": "podcast", "host": "Chamath/Sacks/Friedberg/Calacanis",
     "url": "https://allin.com/", "description": "硅谷投资人圆桌"},
    {"name": "Stratechery", "kind": "blog", "host": "Ben Thompson",
     "url": "https://stratechery.com/", "description": "科技战略分析"},
    {"name": "a16z Podcast", "kind": "podcast", "host": "Andreessen Horowitz",
     "url": "https://a16z.com/podcasts/", "description": "a16z 合伙人访谈"},
    {"name": "央广财经评论", "kind": "interview", "host": "央广网",
     "url": "https://www.cnr.cn/", "description": "央广财经访谈类节目"},
    {"name": "Lex Fridman Podcast", "kind": "podcast", "host": "Lex Fridman",
     "url": "https://lexfridman.com/podcast/", "description": "AI/科学/思想长访谈"},
]
