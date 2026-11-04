"""Каталог тем и источников.

Каждая тема: название, эмодзи, цвет, ключевые слова и собственные RSS-ленты.

Ключевые слова — это начала слов (стемы), регистр не важен:
    "нейросет" найдёт «нейросеть», «нейросети», «нейросетевой».
Слово с «$» на конце ищется целиком: "intel$" не совпадёт с «intelligence».
acronyms — короткие аббревиатуры, ищутся целиком и С учётом регистра ("ИИ", "AI").

Ленты:
    mode="bound"    — всё из ленты относится к теме (+ к другим темам по ключевым словам);
    mode="fallback" — тема определяется по ключевым словам, а если ни одна не подошла —
                      новость попадает в эту тему (удобно для DTF и похожих сайтов);
GENERAL_FEEDS — общие ленты: новости раскладываются по темам только по ключевым словам.

Чтобы добавить источник, достаточно дописать строку в нужный список.
Если лента перестала отвечать, она просто пропускается (статус виден внизу страницы).
"""

def feed(name: str, url: str, mode: str = "bound", weight: float = 0.0) -> dict:
    return {"name": name, "url": url, "mode": mode, "weight": weight}


TOPICS: dict[str, dict] = {
    # ------------------------------------------------------------ базовые темы
    "ai": {
        "name": "ИИ",
        "emoji": "🤖",
        "color": "#0EA5E9",
        "default": True,
        "description": "Нейросети, LLM, релизы моделей",
        "keywords": [
            "нейросет", "нейронн", "искусственн интеллект", "искусственного интеллекта",
            "машинн обучен", "машинного обучения", "языков модел", "chatgpt", "openai",
            "anthropic", "claude$", "gemini", "deepseek", "qwen", "llama", "mistral",
            "midjourney", "stable diffusion", "гигачат", "gigachat", "yandexgpt", "алиса ai",
            "machine learning", "deep learning", "neural", "language model", "чат-бот",
            "chatbot", "генеративн", "hugging face", "copilot", "агентн", "ии-агент",
            "ии-модел", "ии-ассистент", "ai-агент",
        ],
        "acronyms": ["ИИ", "AI", "LLM", "LLMs", "GPT", "AGI", "ML", "RAG", "GPT-5", "GPT-4o"],
        "feeds": [
            feed("Хабр · ИИ", "https://habr.com/ru/rss/hubs/artificial_intelligence/articles/?fl=ru"),
            feed("Хабр · ML", "https://habr.com/ru/rss/hubs/machine_learning/articles/?fl=ru"),
            feed("The Verge · AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
            feed("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
        ],
    },
    "games": {
        "name": "Игры",
        "emoji": "🎮",
        "color": "#8B5CF6",
        "default": True,
        "description": "Релизы, анонсы, индустрия",
        "keywords": [
            "игр", "игров", "геймер", "геймпле", "геймдев", "видеоигр", "steam$", "valve",
            "nintendo", "playstation", "xbox", "ps5", "ps6", "switch 2", "трейлер игры",
            "dlc$", "ремастер", "ремейк", "remake", "early access", "ранний доступ", "киберспорт",
            "esports", "unreal engine", "game", "gaming", "gamer", "epic games", "gta",
            "the witcher", "ведьмак", "cyberpunk", "киберпанк", "bethesda", "ubisoft", "blizzard",
        ],
        "acronyms": ["RPG", "MMO", "MMORPG", "FPS", "AAA", "PS5", "PS6"],
        "feeds": [
            feed("StopGame", "https://rss.stopgame.ru/rss_news.xml"),
            feed("DTF", "https://dtf.ru/rss/all", mode="fallback"),
            feed("PlayGround", "https://www.playground.ru/rss/news.xml"),
            feed("Игромания", "https://www.igromania.ru/rss/news.xml"),
            feed("3DNews · Игры", "https://3dnews.ru/games/rss/"),
            feed("Rock Paper Shotgun", "https://www.rockpapershotgun.com/feed"),
            feed("PC Gamer", "https://www.pcgamer.com/rss/"),
        ],
    },
    "hardware": {
        "name": "Железо",
        "emoji": "🖥️",
        "color": "#F97316",
        "default": True,
        "description": "Процессоры, видеокарты, ПК",
        "keywords": [
            "процессор", "видеокарт", "видеоускорител", "материнск плат", "материнской плат",
            "оперативн памят", "твердотельн", "накопител", "чипсет", "полупроводник", "техпроцесс",
            "микросхем", "nvidia", "geforce", "rtx", "radeon", "ryzen", "threadripper", "epyc",
            "intel$", "intel core", "core ultra", "xeon", "amd$", "tsmc", "qualcomm", "snapdragon",
            "ddr5", "ddr6", "gddr", "hbm", "nvme", "ssd$", "pcie", "монитор",
            "cpu$", "gpu$", "gpus$", "chip$", "chips$", "semiconductor", "motherboard",
            "graphics card", "processor", "оверклок", "разгон", "сборк пк", "игровой пк",
            "ноутбук", "apple m4", "apple m5", "байкал", "эльбрус",
        ],
        "acronyms": ["CPU", "GPU", "SSD", "AMD", "RTX", "ПК", "ЦП", "DDR5", "TSMC"],
        "feeds": [
            feed("3DNews · Железо", "https://3dnews.ru/hardware-news/rss/"),
            feed("Хабр · Железо", "https://habr.com/ru/rss/hubs/hardware/articles/?fl=ru"),
            feed("Overclockers", "https://overclockers.ru/rss/all.rss"),
            feed("Tom's Hardware", "https://www.tomshardware.com/feeds/all"),
            feed("VideoCardz", "https://videocardz.com/feed"),
        ],
    },
    # ------------------------------------------------------- популярные темы (+)
    "space": {
        "name": "Космос",
        "emoji": "🚀",
        "color": "#6366F1",
        "description": "Запуски, телескопы, планеты",
        "keywords": [
            "космос", "космическ", "ракет", "spacex", "starship", "falcon", "роскосмос", "nasa",
            "мкс$", "орбит", "спутник", "телескоп", "james webb", "уэбб", "марс", "луна$", "луну$",
            "лунн", "астроном", "галактик", "экзопланет", "астероид", "комет", "blue origin",
        ],
        "acronyms": ["NASA", "МКС", "ESA"],
        "feeds": [
            feed("Хабр · Космонавтика", "https://habr.com/ru/rss/hubs/space/articles/?fl=ru"),
            feed("Хабр · Астрономия", "https://habr.com/ru/rss/hubs/astronomy/articles/?fl=ru"),
        ],
    },
    "science": {
        "name": "Наука",
        "emoji": "🔬",
        "color": "#14B8A6",
        "description": "Открытия и исследования",
        "keywords": [
            "учёные", "ученые", "исследовател", "физик", "биолог", "генетик", "квантов",
            "эксперимент", "nature$", "science$", "медицин", "мозг", "эволюци", "палеонтолог",
        ],
        "acronyms": ["ДНК", "РНК"],
        "feeds": [
            feed("N + 1", "https://nplus1.ru/rss"),
            feed("Naked Science", "https://naked-science.ru/feed"),
        ],
    },
    "movies": {
        "name": "Кино и сериалы",
        "emoji": "🎬",
        "color": "#EC4899",
        "description": "Премьеры, трейлеры, стриминг",
        "keywords": [
            "фильм", "сериал", "кино", "трейлер фильм", "трейлер сериал", "режиссёр", "режиссер", "актёр",
            "актер", "актрис", "netflix", "hbo", "кинопоиск", "marvel", "дисней", "disney",
            "оскар", "кассов", "сезон сериала", "экранизаци", "мультфильм", "аниме",
        ],
        "acronyms": [],
        "feeds": [
            feed("Канобу", "https://kanobu.ru/rss/"),
        ],
    },
    "gadgets": {
        "name": "Смартфоны и гаджеты",
        "emoji": "📱",
        "color": "#22C55E",
        "description": "Телефоны, носимая электроника",
        "keywords": [
            "смартфон", "iphone", "android", "galaxy", "xiaomi", "redmi", "pixel", "oneplus",
            "huawei", "honor", "планшет", "ipad", "умные часы", "смарт-часы", "apple watch",
            "наушник", "airpods", "гаджет", "ios$", "ios 2", "складн",
        ],
        "acronyms": [],
        "feeds": [
            feed("4PDA", "https://4pda.to/feed/"),
        ],
    },
    "dev": {
        "name": "Программирование",
        "emoji": "💻",
        "color": "#3B82F6",
        "description": "Языки, фреймворки, open source",
        "keywords": [
            "программист", "python", "javascript", "typescript",
            "rust$", "golang", "kotlin", "java$", "c++", "linux", "github", "open source",
            "опенсорс", "фреймворк", "компилятор", "api$", "devops", "kubernetes",
        ],
        "acronyms": ["IDE", "SQL"],
        "feeds": [
            feed("Хабр · Разработка", "https://habr.com/ru/rss/flows/develop/articles/?fl=ru"),
        ],
    },
    "security": {
        "name": "Кибербезопасность",
        "emoji": "🛡️",
        "color": "#EF4444",
        "description": "Уязвимости, утечки, взломы",
        "keywords": [
            "уязвимост", "хакер", "взлом", "утечк", "кибератак", "вымогател", "ransomware",
            "малвар", "вредонос", "фишинг", "эксплойт", "exploit", "zero-day", "ботнет",
            "кибербезопасност", "информационн безопасност", "vulnerability", "breach",
        ],
        "acronyms": ["CVE", "DDoS", "ИБ"],
        "feeds": [
            feed("Хабр · ИБ", "https://habr.com/ru/rss/hubs/infosecurity/articles/?fl=ru"),
            feed("SecurityLab", "https://www.securitylab.ru/rss/allnews/"),
        ],
    },
    "crypto": {
        "name": "Криптовалюты",
        "emoji": "🪙",
        "color": "#EAB308",
        "description": "Биткоин, блокчейн, рынок",
        "keywords": [
            "биткоин", "bitcoin", "криптовалют", "крипторын", "криптобирж", "ethereum", "эфириум", "блокчейн",
            "blockchain", "стейблкоин", "майнинг", "binance", "solana", "toncoin",
        ],
        "acronyms": ["BTC", "ETH", "TON", "NFT"],
        "feeds": [
            feed("ForkLog", "https://forklog.com/feed"),
        ],
    },
    "auto": {
        "name": "Авто и электрокары",
        "emoji": "🚗",
        "color": "#0891B2",
        "description": "Электромобили, автопилоты",
        "keywords": [
            "электромобил", "электрокар", "автомобил", "автопилот", "беспилотн", "tesla",
            "byd$", "zeekr", "lixiang", "аккумулятор", "зарядн станци", "робомобил", "робакси",
        ],
        "acronyms": ["EV"],
        "feeds": [],
    },
}

GENERAL_FEEDS = [
    feed("3DNews", "https://3dnews.ru/news/rss/", mode="classify"),
    feed("iXBT", "https://www.ixbt.com/export/news.rss", mode="classify"),
    feed("Хабр · Новости", "https://habr.com/ru/rss/news/?fl=ru", mode="classify"),
    feed("Хабр · Лучшее за сутки", "https://habr.com/ru/rss/articles/top/daily/?fl=ru", mode="classify", weight=1.5),
    feed("CNews", "https://www.cnews.ru/inc/rss/news.xml", mode="classify"),
    feed("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", mode="classify"),
    feed("The Verge", "https://www.theverge.com/rss/index.xml", mode="classify"),
]

DEFAULT_TOPICS = [k for k, t in TOPICS.items() if t.get("default")]


def all_feeds() -> list[dict]:
    """Все ленты с привязкой к теме (topic=None для общих)."""
    out = []
    for key, topic in TOPICS.items():
        for f in topic["feeds"]:
            out.append({**f, "topic": key})
    for f in GENERAL_FEEDS:
        out.append({**f, "topic": None})
    return out


def catalog() -> list[dict]:
    return [
        {"id": k, "name": t["name"], "emoji": t["emoji"], "color": t["color"],
         "default": bool(t.get("default")), "description": t.get("description", "")}
        for k, t in TOPICS.items()
    ]
