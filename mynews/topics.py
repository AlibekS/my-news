"""Каталог тем и источников.

Темы
----
Каждая тема: название, эмодзи, цвет, ключевые слова и собственные RSS-ленты.
Ключевые слова — начала слов (стемы), регистр не важен: "нейросет" найдёт
«нейросеть», «нейросетевой». Слово с «$» на конце ищется целиком: "intel$" не
совпадёт с «intelligence». acronyms — аббревиатуры, ищутся целиком и С учётом
регистра ("ИИ", "AI").

Ленты
-----
feed(название, адрес или список адресов, mode=..., region=...)

  region: "ru" — русскоязычные СМИ, "en" — англоязычные, "kz" — СМИ Казахстана.
          На сайте это кнопки RU / EN / KZ.
  mode:   "bound"    — всё из ленты относится к теме (+ к другим по ключевым словам);
          "fallback" — тема по ключевым словам, а если ни одна не подошла — эта тема;
          "classify" — только по ключевым словам (для общих лент, GENERAL_FEEDS).

Можно указать несколько адресов — используется первый, который ответил. Можно дать
просто адрес главной страницы сайта: RSS-лента найдётся автоматически
(по тегу <link rel="alternate" type="application/rss+xml">).
"""


def feed(name: str, urls, mode: str = "bound", region: str = "ru", weight: float = 0.0) -> dict:
    return {"name": name, "urls": [urls] if isinstance(urls, str) else list(urls),
            "mode": mode, "region": region, "weight": weight}


REGIONS = {"ru": "RU", "en": "EN", "kz": "KZ"}

TOPICS: dict[str, dict] = {
    # ---------------------------------------------------------- темы на главной
    "ai": {
        "name": "ИИ", "emoji": "🤖", "color": "#0EA5E9", "default": True,
        "description": "Нейросети, LLM, релизы моделей",
        "keywords": [
            "нейросет", "нейронн", "искусственн интеллект", "искусственного интеллекта",
            "машинн обучен", "машинного обучения", "языков модел", "chatgpt", "openai",
            "anthropic", "claude$", "gemini", "deepseek", "qwen", "llama", "mistral",
            "midjourney", "stable diffusion", "гигачат", "gigachat", "yandexgpt", "алиса ai",
            "machine learning", "deep learning", "neural", "language model", "чат-бот",
            "chatbot", "генеративн", "hugging face", "copilot", "агентн", "ии-агент",
            "ии-модел", "ии-ассистент", "ai-агент", "artificial intelligence",
        ],
        "acronyms": ["ИИ", "AI", "LLM", "LLMs", "GPT", "AGI", "ML", "RAG", "GPT-5", "GPT-4o"],
        "feeds": [
            feed("Хабр · ИИ", "https://habr.com/ru/rss/hubs/artificial_intelligence/articles/?fl=ru"),
            feed("Хабр · ML", "https://habr.com/ru/rss/hubs/machine_learning/articles/?fl=ru"),
            feed("The Verge · AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", region="en"),
            feed("MIT Tech Review · AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed", region="en"),
            feed("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", region="en"),
        ],
    },
    "games": {
        "name": "Игры", "emoji": "🎮", "color": "#8B5CF6", "default": True,
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
            feed("Игромания", ["https://www.igromania.ru/rss/news.xml", "https://www.igromania.ru/"]),
            feed("3DNews · Игры", "https://3dnews.ru/games/rss/"),
            feed("Rock Paper Shotgun", "https://www.rockpapershotgun.com/feed", region="en"),
            feed("PC Gamer", "https://www.pcgamer.com/rss/", region="en"),
            feed("Eurogamer", "https://www.eurogamer.net/feed", region="en"),
        ],
    },
    "hardware": {
        "name": "Железо", "emoji": "🖥️", "color": "#F97316", "default": True,
        "description": "Процессоры, видеокарты, ПК",
        "keywords": [
            "процессор", "видеокарт", "видеоускорител", "материнск плат", "материнской плат",
            "оперативн памят", "твердотельн", "накопител", "чипсет", "полупроводник", "техпроцесс",
            "микросхем", "nvidia", "geforce", "rtx", "radeon", "ryzen", "threadripper", "epyc",
            "intel$", "intel core", "core ultra", "xeon", "amd$", "tsmc", "qualcomm", "snapdragon",
            "ddr5", "ddr6", "gddr", "hbm", "nvme", "ssd$", "pcie", "монитор",
            "cpu$", "gpu$", "gpus$", "chip$", "chips$", "semiconductor", "motherboard",
            "graphics card", "processor", "оверклок", "разгон", "сборк пк", "игровой пк",
            "ноутбук", "apple m4", "apple m5", "байкал", "эльбрус", "дата-центр", "суперкомпьютер",
        ],
        "acronyms": ["CPU", "GPU", "SSD", "AMD", "RTX", "ПК", "ЦП", "DDR5", "TSMC"],
        "feeds": [
            feed("3DNews · Железо", "https://3dnews.ru/hardware-news/rss/"),
            feed("Хабр · Железо", "https://habr.com/ru/rss/hubs/hardware/articles/?fl=ru"),
            feed("Overclockers", ["https://overclockers.ru/rss/all.rss", "https://overclockers.ru/"]),
            feed("Tom's Hardware", "https://www.tomshardware.com/feeds/all", region="en"),
            feed("VideoCardz", "https://videocardz.com/feed", region="en"),
        ],
    },
    "economy": {
        "name": "Экономика", "emoji": "📈", "color": "#10B981", "default": True,
        "description": "Рынки, курсы, бизнес",
        "keywords": [
            "экономик", "экономическ", "инфляц", "тенге", "курс доллар", "курс рубл", "курс валют",
            "нацбанк", "национальный банк", "центробанк", "ключев ставк", "базов ставк",
            "бюджет", "налог", "инвестиц", "инвестор", "бирж", "фондов рынок", "ipo$", "нефт",
            "brent", "опек", "рынок труда", "зарплат", "ипотек", "кредит", "банков", "импорт",
            "экспорт", "пошлин", "тариф", "выручк", "прибыл", "капитализац", "дефолт", "рецесси",
            "госдолг", "стартап", "economy", "economic", "inflation",
            "interest rate", "stock market", "stocks", "earnings", "recession", "tariff", "gdp",
            "federal reserve", "wall street", "oil price",
        ],
        "acronyms": ["ВВП", "ФРС", "ЦБ", "НБК", "ОПЕК", "IPO", "GDP", "ЕАЭС", "S&P", "KASE"],
        "feeds": [
            feed("Коммерсантъ · Экономика", "https://www.kommersant.ru/RSS/section-economics.xml"),
            feed("BBC · Business", "https://feeds.bbci.co.uk/news/business/rss.xml", region="en"),
            feed("The Guardian · Business", "https://www.theguardian.com/business/rss", region="en"),
        ],
    },
    "politics": {
        "name": "Политика", "emoji": "🏛️", "color": "#64748B", "default": True,
        "description": "Власть, выборы, мир",
        "keywords": [
            "президент", "правительств", "парламент", "мажилис", "сенат", "госдум", "выборы$",
            "выборов$", "выборах$", "предвыборн",
            "министр", "депутат", "законопроект", "санкци", "переговор", "дипломат", "посол",
            "кремл", "белый дом", "токаев", "путин", "трамп", "зеленск", "евросоюз", "премьер-министр",
            "аким", "референдум", "оппозици", "протест", "войн", "перемири", "саммит", "генсек",
            "president", "government", "election", "parliament", "senate", "congress", "minister",
            "sanctions", "white house", "kremlin", "trump", "ceasefire", "summit", "diplomat",
        ],
        "acronyms": ["НАТО", "ООН", "ЕС", "ОДКБ", "ШОС", "СНГ", "NATO", "UN", "EU", "МИД"],
        "feeds": [
            feed("Коммерсантъ · Политика", "https://www.kommersant.ru/RSS/section-politics.xml"),
            feed("BBC · World", "https://feeds.bbci.co.uk/news/world/rss.xml", mode="fallback", region="en"),
            feed("The Guardian · Politics", "https://www.theguardian.com/politics/rss", region="en"),
        ],
    },
    "space": {
        "name": "Космос", "emoji": "🚀", "color": "#6366F1", "default": True,
        "description": "Запуски, Байконур, телескопы",
        "keywords": [
            "космос", "космическ", "космонавт", "астронавт", "ракет", "spacex", "starship", "falcon",
            "роскосмос", "байконур", "nasa", "мкс$", "орбит", "спутник", "телескоп", "james webb",
            "уэбб", "марс", "луна$", "луну$", "лунн", "астроном", "галактик", "экзопланет",
            "астероид", "комет", "blue origin", "rocket", "spacecraft", "satellite", "telescope",
        ],
        "acronyms": ["NASA", "МКС", "ESA", "ISS"],
        "feeds": [
            feed("Хабр · Космонавтика", "https://habr.com/ru/rss/hubs/space/articles/?fl=ru"),
            feed("Хабр · Астрономия", "https://habr.com/ru/rss/hubs/astronomy/articles/?fl=ru"),
            feed("Space.com", "https://www.space.com/feeds/all", region="en"),
        ],
    },
    "movies": {
        "name": "Кино и сериалы", "emoji": "🎬", "color": "#EC4899", "default": True,
        "description": "Премьеры, трейлеры, стриминг",
        "keywords": [
            "фильм", "сериал", "кино", "трейлер фильм", "трейлер сериал", "режиссёр", "режиссер",
            "актёр", "актер", "актрис", "netflix", "hbo", "кинопоиск", "marvel", "дисней", "disney",
            "оскар", "кассов", "прокат", "кинопрокат", "сборы фильм", "экранизаци", "мультфильм", "аниме", "movie", "film", "box office",
            "streaming", "season finale",
        ],
        "acronyms": [],
        "feeds": [
            feed("Канобу", ["https://kanobu.ru/rss/", "https://kanobu.ru/"]),
            feed("Film.ru", ["https://www.film.ru/rss.xml", "https://www.film.ru/"]),
            feed("Variety", "https://variety.com/feed/", region="en"),
        ],
    },
    # ------------------------------------------------- дополнительные темы (+)
    "science": {
        "name": "Наука", "emoji": "🔬", "color": "#14B8A6",
        "description": "Открытия и исследования",
        "keywords": [
            "учёные", "ученые", "исследовател", "физик", "биолог", "генетик", "квантов",
            "эксперимент", "nature$", "science$", "медицин", "мозг", "эволюци", "палеонтолог",
            "scientists", "researchers", "study finds",
        ],
        "acronyms": ["ДНК", "РНК", "DNA"],
        "feeds": [
            feed("N + 1", "https://nplus1.ru/rss"),
            feed("Naked Science", "https://naked-science.ru/feed"),
            feed("ScienceDaily", "https://www.sciencedaily.com/rss/all.xml", region="en"),
        ],
    },
    "gadgets": {
        "name": "Смартфоны и гаджеты", "emoji": "📱", "color": "#22C55E",
        "description": "Телефоны, носимая электроника",
        "keywords": [
            "смартфон", "iphone", "android", "galaxy", "xiaomi", "redmi", "pixel", "oneplus",
            "huawei", "honor", "планшет", "ipad", "умные часы", "смарт-часы", "apple watch",
            "наушник", "airpods", "гаджет", "ios$", "складн", "smartphone",
        ],
        "acronyms": [],
        "feeds": [
            feed("4PDA", "https://4pda.to/feed/"),
            feed("GSMArena", "https://www.gsmarena.com/rss-news-reviews.php3", region="en"),
        ],
    },
    "dev": {
        "name": "Программирование", "emoji": "💻", "color": "#3B82F6",
        "description": "Языки, фреймворки, open source",
        "keywords": [
            "программист", "python", "javascript", "typescript", "rust$", "golang", "kotlin",
            "java$", "c++", "linux", "github", "open source", "опенсорс", "фреймворк",
            "компилятор", "api$", "devops", "kubernetes", "programming", "developer",
        ],
        "acronyms": ["IDE", "SQL"],
        "feeds": [
            feed("Хабр · Разработка", "https://habr.com/ru/rss/flows/develop/articles/?fl=ru"),
        ],
    },
    "security": {
        "name": "Кибербезопасность", "emoji": "🛡️", "color": "#EF4444",
        "description": "Уязвимости, утечки, взломы",
        "keywords": [
            "уязвимост", "хакер", "взлом", "утечк", "кибератак", "вымогател", "ransomware",
            "малвар", "вредонос", "фишинг", "эксплойт", "exploit", "zero-day", "ботнет",
            "кибербезопасност", "информационн безопасност", "vulnerability", "breach", "hackers",
        ],
        "acronyms": ["CVE", "DDoS", "ИБ"],
        "feeds": [
            feed("Хабр · ИБ", "https://habr.com/ru/rss/hubs/infosecurity/articles/?fl=ru"),
            feed("SecurityLab", ["https://www.securitylab.ru/rss/allnews/", "https://www.securitylab.ru/"]),
            feed("BleepingComputer", "https://www.bleepingcomputer.com/feed/", region="en"),
        ],
    },
    "crypto": {
        "name": "Криптовалюты", "emoji": "🪙", "color": "#EAB308",
        "description": "Биткоин, блокчейн, рынок",
        "keywords": [
            "биткоин", "bitcoin", "криптовалют", "крипторын", "криптобирж", "ethereum", "эфириум",
            "блокчейн", "blockchain", "стейблкоин", "майнинг", "binance", "solana", "toncoin", "crypto",
        ],
        "acronyms": ["BTC", "ETH", "TON", "NFT"],
        "feeds": [
            feed("ForkLog", "https://forklog.com/feed"),
            feed("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", region="en"),
        ],
    },
    "auto": {
        "name": "Авто и электрокары", "emoji": "🚗", "color": "#0891B2",
        "description": "Электромобили, автопилоты",
        "keywords": [
            "электромобил", "электрокар", "автомобил", "автопилот", "беспилотн", "tesla",
            "byd$", "zeekr", "lixiang", "зарядн станци", "робомобил", "роботакси",
            "electric vehicle", "robotaxi",
        ],
        "acronyms": ["EV", "EVs"],
        "feeds": [
            feed("Electrek", "https://electrek.co/feed/", region="en"),
        ],
    },
}

GENERAL_FEEDS = [
    # Русскоязычные СМИ
    feed("3DNews", "https://3dnews.ru/news/rss/", mode="classify"),
    feed("iXBT", "https://www.ixbt.com/export/news.rss", mode="classify"),
    feed("Хабр · Новости", "https://habr.com/ru/rss/news/?fl=ru", mode="classify"),
    feed("Хабр · Лучшее за сутки", "https://habr.com/ru/rss/articles/top/daily/?fl=ru", mode="classify", weight=1.5),
    feed("CNews", "https://www.cnews.ru/inc/rss/news.xml", mode="classify"),
    feed("РБК", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", mode="classify"),
    feed("Интерфакс", "https://www.interfax.ru/rss.asp", mode="classify"),
    feed("Коммерсантъ", "https://www.kommersant.ru/RSS/news.xml", mode="classify"),
    feed("Ведомости", ["https://www.vedomosti.ru/rss/news", "https://www.vedomosti.ru/"], mode="classify"),
    feed("BBC News Русская служба", "https://feeds.bbci.co.uk/russian/rss.xml", mode="classify"),
    feed("Медуза", "https://meduza.io/rss/all", mode="classify"),
    # Англоязычные
    feed("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", mode="classify", region="en"),
    feed("The Verge", "https://www.theverge.com/rss/index.xml", mode="classify", region="en"),
    # Казахстан (на русском)
    feed("Tengrinews", ["https://tengrinews.kz/news.rss", "https://tengrinews.kz/"], mode="classify", region="kz"),
    feed("Kapital.kz", ["https://kapital.kz/rss", "https://kapital.kz/feed", "https://kapital.kz/"],
         mode="fallback", region="kz"),
    feed("Курсив", ["https://kz.kursiv.media/feed/", "https://kursiv.kz/feed/", "https://kz.kursiv.media/"],
         mode="fallback", region="kz"),
    feed("ZTB.kz", ["https://ztb.kz/rss", "https://ztb.kz/feed/", "https://ztb.kz/"], mode="classify", region="kz"),
    feed("Zakon.kz", ["https://www.zakon.kz/rss/", "https://www.zakon.kz/"], mode="classify", region="kz"),
    feed("Казинформ", ["https://www.inform.kz/ru/rss", "https://www.inform.kz/rss/ru.xml", "https://www.inform.kz/"],
         mode="classify", region="kz"),
    feed("Forbes Kazakhstan", ["https://forbes.kz/rss", "https://forbes.kz/feed/", "https://forbes.kz/"],
         mode="fallback", region="kz"),
    feed("Vlast.kz", ["https://vlast.kz/rss", "https://vlast.kz/feed", "https://vlast.kz/"],
         mode="fallback", region="kz"),
    feed("Orda.kz", ["https://orda.kz/feed/", "https://orda.kz/"], mode="classify", region="kz"),
    feed("Informburo", ["https://informburo.kz/rss", "https://informburo.kz/"], mode="classify", region="kz"),
    feed("Nur.kz", ["https://www.nur.kz/rss/all.rss", "https://www.nur.kz/"], mode="classify", region="kz"),
    feed("Profit.kz", ["https://profit.kz/rss/", "https://profit.kz/"], mode="classify", region="kz"),
    feed("Digital Business", ["https://digitalbusiness.kz/feed/", "https://digitalbusiness.kz/"],
         mode="classify", region="kz"),
]

# Тема по умолчанию для общих лент в режиме fallback.
FALLBACK_TOPIC = {"Kapital.kz": "economy", "Курсив": "economy", "Forbes Kazakhstan": "economy",
                  "Vlast.kz": "politics"}

DEFAULT_TOPICS = [k for k, t in TOPICS.items() if t.get("default")]
MAX_TOPICS = 7


def all_feeds() -> list[dict]:
    """Все ленты с привязкой к теме (topic=None для общих)."""
    out = []
    for key, topic in TOPICS.items():
        for f in topic["feeds"]:
            out.append({**f, "topic": key})
    for f in GENERAL_FEEDS:
        out.append({**f, "topic": FALLBACK_TOPIC.get(f["name"])})
    return out


def catalog() -> list[dict]:
    return [
        {"id": k, "name": t["name"], "emoji": t["emoji"], "color": t["color"],
         "default": bool(t.get("default")), "description": t.get("description", "")}
        for k, t in TOPICS.items()
    ]
