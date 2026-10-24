import os

SRC = r"C:\Users\armen\.zcode\tmp\paste-attachments\2026-10-24\pasted-text-20261024-184431-3ed3878a.txt"
OUT = r"C:\Users\armen\.zcode\workspace\default\matham_bot"

with open(SRC, "r", encoding="utf-8") as fh:
    LINES = fh.read().splitlines()

EOF = len(LINES)


def seg(a, b):
    """1-based inclusive slice."""
    return "\n".join(LINES[a - 1:b])


def drop(lines_text, ranges):
    """Remove 1-based inclusive line ranges from a text block re-read as lines."""
    keep = []
    for i, line in enumerate(lines_text.splitlines(), start=1):
        if any(lo <= i <= hi for lo, hi in ranges):
            continue
        keep.append(line)
    return "\n".join(keep)


os.makedirs(os.path.join(OUT, "handlers"), exist_ok=True)

AIOM_HANDLER = '''import asyncio
import copy
import csv
import html
import io
import json
import logging
import os
import random
import re
import uuid

from aiogram import F, types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
    InlineQuery, InlineQueryResultArticle, InlineQueryResultCachedDocument,
    InputTextMessageContent,
)

from .. import core
from ..config import *
from ..utils import *
from ..texts import *
from ..core import *
from ..db import *
from ..states import *
from ..keyboards import *
from ..views import *
from ..ziputil import *
from ..broadcast import *
from ..translate import *

'''

CONFIG_H = '''import logging
import os
from datetime import timedelta, timezone

'''

TEXTS_H = ""
STATE_H = ""
DB_H = '''import copy
import uuid
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorClient

from .config import *
from .state import *
from .utils import *

'''

TRANSLATE_H = '''import re

import aiohttp

from .config import *
from .core import get_user_lang

'''

CORE_H = '''import copy
import html
import re

from aiogram import Bot, Dispatcher, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from .config import *
from .utils import *
from .texts import *
from .db import *

'''

MIDDLEWARE_H = '''from datetime import datetime, timedelta, timezone

from aiogram import types, BaseMiddleware

from .config import *
from .core import *

'''

STATES_H = '''from aiogram.fsm.state import State, StatesGroup

'''

KEYBOARDS_H = '''from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import *
from .utils import *
from .texts import *
from .core import *
from .translate import *

'''

ZIPUTIL_H = '''import io
import os
import shutil
import tempfile
import zipfile

from aiogram import types
from aiogram.enums import ParseMode

from .config import *
from .utils import *
from .texts import *
from .core import *
from .translate import *

'''

VIEWS_H = '''import html

from aiogram import types
from aiogram.enums import ParseMode

from .config import *
from .utils import *
from .texts import *
from .core import *
from .keyboards import *
from .translate import *

'''

BROADCAST_H = '''import asyncio
import html

from aiogram import types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import core
from .config import *
from .texts import *
from .core import *
from .translate import *

'''

MAIN_H = '''import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot
from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from . import core
from . import handlers  # noqa: F401  -- importing registers all handlers
from .config import *
from .core import bot, dp, DATABASE, BOT_USERNAME
from .db import load_db
from .middlewares import SimpleRateLimitMiddleware, UserActivityMiddleware

'''

INIT_HANDLERS = '''"""Importing this package registers every handler on the dispatcher.

Order matters: the catch-all fallback must be registered last.
"""

from . import (
    commands,
    catalog,
    search,
    tags,
    favorites,
    tasks,
    links,
    submissions,
    admin,
    admin_tasks,
    inline,
    fallback,
)
'''

# ---------------- config.py ----------------
write = lambda rel, text: open(os.path.join(OUT, rel), "w", encoding="utf-8", newline="\n").write(text)

config_body = seg(33, 57)
write("config.py", CONFIG_H + config_body + "\n")

# ---------------- texts.py (TEXTS dict only) ----------------
write("texts.py", seg(71, 551) + "\n")

# ---------------- utils.py ----------------
utils_body = "\n\n".join([seg(832, 833), seg(904, 916), seg(1590, 1593)])
write("utils.py", 'import re\n\nfrom .config import YEREVAN_TZ\n\n\n' + utils_body + "\n")

# ---------------- state.py ----------------
write("state.py", seg(742, 784) + "\n")

# ---------------- db.py ----------------
db_body = seg(1166, 1268)
write("db.py", DB_H + seg(58, 62) + "\n\n\n" + db_body + "\n")

# ---------------- translate.py ----------------
write("translate.py", TRANSLATE_H + seg(569, 741) + "\n")

# ---------------- core.py ----------------
helpers = drop(seg(828, 1165), [(832 - 828 + 1, 833 - 828 + 1), (904 - 828 + 1, 916 - 828 + 1)])
core_body = seg(64, 69) + "\n\n\n" + seg(552, 566) + "\n\n\n" + helpers
write("core.py", CORE_H + core_body + "\n")

# ---------------- middlewares.py ----------------
write("middlewares.py", MIDDLEWARE_H + seg(785, 827) + "\n")

# ---------------- states.py ----------------
write("states.py", STATES_H + seg(1269, 1366) + "\n")

# ---------------- keyboards.py ----------------
write("keyboards.py", KEYBOARDS_H + seg(1367, 1589) + "\n")

# ---------------- ziputil.py ----------------
write("ziputil.py", ZIPUTIL_H + seg(1594, 1735) + "\n")

# ---------------- views.py ----------------
write("views.py", VIEWS_H + seg(1736, 1868) + "\n")

# ---------------- broadcast.py (channel announce removed) ----------------
broadcast_body = seg(1869, 1972).replace("BOT_USERNAME", "core.BOT_USERNAME")
write("broadcast.py", BROADCAST_H + broadcast_body + "\n")

# ---------------- handlers ----------------
hwrite = lambda name, text: write("handlers/" + name, text)

hwrite("search.py", AIOM_HANDLER + seg(2007, 2033) + "\n\n\n" + seg(2661, 2866) + "\n")
hwrite("commands.py", AIOM_HANDLER + seg(2034, 2250) + "\n")

catalog_body = seg(2251, 2660).replace("BOT_USERNAME", "core.BOT_USERNAME")
hwrite("catalog.py", AIOM_HANDLER + catalog_body + "\n")

hwrite("tags.py", AIOM_HANDLER + seg(2867, 3015) + "\n")

fav_body = seg(3016, 3145).replace("BOT_USERNAME", "core.BOT_USERNAME")
hwrite("favorites.py", AIOM_HANDLER + fav_body + "\n")

hwrite("tasks.py", AIOM_HANDLER + seg(3146, 3931) + "\n")
hwrite("links.py", AIOM_HANDLER + seg(3932, 4021) + "\n")
hwrite("submissions.py", AIOM_HANDLER + seg(4022, 4156) + "\n")

admin_body = (seg(4157, 4322) + "\n\n\n" + seg(4583, 5049))
admin_body = "\n".join(
    l for l in admin_body.splitlines() if "await announce_file_to_channel" not in l
)
hwrite("admin.py", AIOM_HANDLER + admin_body + "\n")

hwrite("admin_tasks.py", AIOM_HANDLER + seg(4323, 4582) + "\n")
hwrite("inline.py", AIOM_HANDLER + seg(5050, 5091) + "\n")
hwrite("fallback.py", AIOM_HANDLER + seg(5092, 5111) + "\n")

write(os.path.join("handlers", "__init__.py"), INIT_HANDLERS)

# ---------------- main.py ----------------
main_body = seg(5112, EOF)
main_body = main_body.replace(
    "    global DATABASE, BOT_USERNAME", "    global BOT_USERNAME"
).replace(
    "    DATABASE = await load_db()",
    "    DATABASE.clear()\n    DATABASE.update(await load_db())",
).replace(
    '    BOT_USERNAME = me.username or ""',
    '    core.BOT_USERNAME = me.username or ""\n    BOT_USERNAME = core.BOT_USERNAME',
)
write("main.py", MAIN_H + main_body + "\n")

print("done")
