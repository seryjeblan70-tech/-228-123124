import asyncio
import uvicorn
import logging
import os
import hashlib
import hmac
import urllib.parse
import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, JSON, BigInteger, select, desc
from sqlalchemy.sql import func

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# -------------------- Настройка логирования --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- Конфигурация --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./game.db")
MINI_APP_URL = "https://seryjeblan70-tech.github.io/my-pets-bot-app123123/"

# -------------------- База данных --------------------
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

# -------------------- Модель данных --------------------
class UserGameData(Base):
    __tablename__ = "user_game_data"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)

    food = Column(Integer, default=50)
    gems = Column(Float, default=100.0)
    total_clicks = Column(Integer, default=0)
    stamina = Column(Integer, default=100)
    max_stamina = Column(Integer, default=100)
    stamina_regen_rate = Column(Float, default=1.0)
    click_power = Column(Float, default=1.0)

    click_upgrade_level = Column(Integer, default=0)
    regen_upgrade_level = Column(Integer, default=0)
    max_stamina_upgrade_level = Column(Integer, default=0)

    selected_pet_id = Column(String, default="dog")
    pet_levels = Column(JSON, default={"dog": 1, "cat": 1, "rabbit": 1})

    inventory = Column(JSON, default=[])

    quests = Column(JSON, default=[])

    last_daily_claim = Column(DateTime, nullable=True)
    daily_streak = Column(Integer, default=0)

    combo = Column(Integer, default=0)
    last_click_time = Column(DateTime, nullable=True)

    total_stamina_restored = Column(Integer, default=0)
    boosters_used = Column(Integer, default=0)
    food_eaten = Column(Integer, default=0)
    max_combo = Column(Integer, default=0)

    invited_by = Column(BigInteger, nullable=True)
    friends_count = Column(Integer, default=0)

    first_login = Column(DateTime(timezone=True), server_default=func.now())

# -------------------- Аутентификация Telegram --------------------
def validate_init_data(init_data: str) -> bool:
    try:
        data_dict = {}
        for item in init_data.split('&'):
            if not item:
                continue
            if '=' not in item:
                logger.warning(f"Skipping malformed item in init_data: {item}")
                continue
            key, value = item.split('=', 1)
            data_dict[key] = urllib.parse.unquote(value)

        received_hash = data_dict.pop('hash', None)
        if not received_hash:
            logger.warning("No hash in init_data")
            return False

        # Сортируем ключи и формируем строку проверки
        data_check_string = '\n'.join(
            f"{k}={v}" for k, v in sorted(data_dict.items())
        )

        secret_key = hmac.new(
            key=b"WebAppData",
            msg=BOT_TOKEN.encode(),
            digestmod=hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode(),
            digestmod=hashlib.sha256
        ).hexdigest()

        return calculated_hash == received_hash
    except Exception as e:
        logger.error(f"Exception in validate_init_data: {e}")
        return False

def extract_user_id(init_data: str) -> int:
    data_dict = {}
    for item in init_data.split('&'):
        key, value = item.split('=', 1)
        data_dict[key] = urllib.parse.unquote(value)
    user_json = data_dict.get('user', '{}')
    user = json.loads(user_json)
    return user.get('id')

# -------------------- Эндпоинты FastAPI --------------------
router = APIRouter(prefix="/api", tags=["game"])

async def get_user(init_data: str = Header(..., alias="X-Telegram-Init-Data"), db: AsyncSession = Depends(get_db)):
    logger.info("get_user called")
    if not validate_init_data(init_data):
        logger.warning("Validation failed")
        raise HTTPException(status_code=401, detail="Invalid init data")
    user_id = extract_user_id(init_data)
    if not user_id:
        raise HTTPException(status_code=400, detail="User not found")
    result = await db.execute(select(UserGameData).where(UserGameData.telegram_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        user = UserGameData(telegram_id=user_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user

@router.post("/init")
async def init(user: UserGameData = Depends(get_user)):
    days_in_game = (datetime.utcnow() - user.first_login).days + 1
    return {
        "food": user.food,
        "gems": user.gems,
        "total_clicks": user.total_clicks,
        "stamina": user.stamina,
        "max_stamina": user.max_stamina,
        "stamina_regen_rate": user.stamina_regen_rate,
        "click_power": user.click_power,
        "click_upgrade_level": user.click_upgrade_level,
        "regen_upgrade_level": user.regen_upgrade_level,
        "max_stamina_upgrade_level": user.max_stamina_upgrade_level,
        "selected_pet_id": user.selected_pet_id,
        "pet_levels": user.pet_levels,
        "inventory": user.inventory,
        "quests": user.quests,
        "daily_streak": user.daily_streak,
        "combo": user.combo,
        "friends_count": user.friends_count,
        "days_in_game": days_in_game,
    }

@router.post("/click")
async def click(user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    if user.stamina < 1:
        raise HTTPException(status_code=400, detail="Not enough stamina")
    now = datetime.utcnow()
    if user.last_click_time and (now - user.last_click_time).total_seconds() < 2:
        user.combo += 1
    else:
        user.combo = 1
    user.last_click_time = now
    if user.combo > user.max_combo:
        user.max_combo = user.combo
    gain = user.click_power
    user.gems += gain
    user.stamina -= 1
    user.total_clicks += 1
    await db.commit()
    return {
        "gems": user.gems,
        "stamina": user.stamina,
        "combo": user.combo,
        "total_clicks": user.total_clicks,
    }

@router.post("/feed")
async def feed(user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    if user.food <= 0:
        raise HTTPException(status_code=400, detail="No food")
    user.food -= 1
    restore = min(10, user.max_stamina - user.stamina)
    user.stamina += restore
    user.total_stamina_restored += restore
    user.food_eaten += 1
    await db.commit()
    return {"food": user.food, "stamina": user.stamina}

@router.post("/play")
async def play(user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    if user.stamina < 20:
        raise HTTPException(status_code=400, detail="Not enough stamina")
    user.stamina -= 20
    reward = 30
    user.gems += reward
    await db.commit()
    return {"stamina": user.stamina, "gems": user.gems}

@router.post("/buy_click_upgrade")
async def buy_click_upgrade(user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    cost = 10 + user.click_upgrade_level * 5
    if user.gems < cost:
        raise HTTPException(status_code=400, detail="Not enough gems")
    user.gems -= cost
    user.click_upgrade_level += 1
    user.click_power += 0.2
    await db.commit()
    return {"gems": user.gems, "click_upgrade_level": user.click_upgrade_level, "click_power": user.click_power}

@router.post("/buy_regen_upgrade")
async def buy_regen_upgrade(user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    cost = 15 + user.regen_upgrade_level * 8
    if user.gems < cost:
        raise HTTPException(status_code=400, detail="Not enough gems")
    user.gems -= cost
    user.regen_upgrade_level += 1
    user.stamina_regen_rate += 0.5
    await db.commit()
    return {"gems": user.gems, "regen_upgrade_level": user.regen_upgrade_level, "stamina_regen_rate": user.stamina_regen_rate}

@router.post("/buy_max_stamina_upgrade")
async def buy_max_stamina_upgrade(user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    cost = 30 + user.max_stamina_upgrade_level * 10
    if user.gems < cost:
        raise HTTPException(status_code=400, detail="Not enough gems")
    user.gems -= cost
    user.max_stamina_upgrade_level += 1
    user.max_stamina += 20
    user.stamina += 20
    await db.commit()
    return {"gems": user.gems, "max_stamina_upgrade_level": user.max_stamina_upgrade_level, "max_stamina": user.max_stamina, "stamina": user.stamina}

@router.post("/buy_item")
async def buy_item(payload: dict, user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    item_id = payload.get("itemId")
    price = payload.get("price")
    if not item_id or not price:
        raise HTTPException(status_code=400, detail="Invalid item data")
    if user.gems < price:
        raise HTTPException(status_code=400, detail="Not enough gems")
    inv = user.inventory or []
    found = False
    for it in inv:
        if it["id"] == item_id:
            it["quantity"] = it.get("quantity", 0) + 1
            found = True
            break
    if not found:
        inv.append({"id": item_id, "quantity": 1})
    user.inventory = inv
    user.gems -= price
    await db.commit()
    return {"gems": user.gems, "inventory": user.inventory}

@router.post("/use_item")
async def use_item(payload: dict, user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    item_id = payload.get("itemId")
    inv = user.inventory or []
    found_item = None
    for it in inv:
        if it["id"] == item_id and it.get("quantity", 0) > 0:
            found_item = it
            break
    if not found_item:
        raise HTTPException(status_code=400, detail="Item not available")
    if item_id == "food_bag":
        user.food = min(user.food + 30, 100)
        user.food_eaten += 1
    found_item["quantity"] -= 1
    if found_item["quantity"] <= 0:
        inv = [i for i in inv if i["id"] != item_id]
    user.inventory = inv
    await db.commit()
    return {"inventory": user.inventory, "food": user.food}

@router.post("/claim_daily")
async def claim_daily(user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow().date()
    last = user.last_daily_claim.date() if user.last_daily_claim else None
    if last == now:
        raise HTTPException(status_code=400, detail="Already claimed today")
    if last and (now - last).days == 1:
        user.daily_streak += 1
    else:
        user.daily_streak = 1
    reward = 50 + user.daily_streak * 10
    user.gems += reward
    user.last_daily_claim = datetime.utcnow()
    await db.commit()
    return {"gems": user.gems, "streak": user.daily_streak}

@router.post("/claim_quest")
async def claim_quest(payload: dict, user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    quest_id = payload.get("id")
    quests = user.quests or []
    found = None
    for q in quests:
        if q["id"] == quest_id:
            found = q
            break
    if not found or found.get("completed") or found.get("progress", 0) < found.get("target", 0):
        raise HTTPException(status_code=400, detail="Quest not available")
    reward = found.get("reward", 0)
    user.gems += reward
    found["completed"] = True
    user.quests = quests
    await db.commit()
    return {"gems": user.gems, "quests": user.quests}

@router.post("/upgrade_pet")
async def upgrade_pet(payload: dict, user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    pet_id = payload.get("petId")
    # Заглушка
    raise HTTPException(status_code=501, detail="Not implemented")

@router.post("/select_pet")
async def select_pet(payload: dict, user: UserGameData = Depends(get_user), db: AsyncSession = Depends(get_db)):
    pet_id = payload.get("petId")
    user.selected_pet_id = pet_id
    await db.commit()
    return {"selectedPetId": user.selected_pet_id}

@router.get("/leaders")
async def get_leaders(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserGameData)
        .order_by(desc(UserGameData.gems))
        .limit(50)
    )
    leaders = result.scalars().all()
    return [
        {
            "name": user.first_name or f"User{user.telegram_id}",
            "score": user.gems,
        }
        for user in leaders
    ]

@router.post("/register_referral")
async def register_referral(data: dict, db: AsyncSession = Depends(get_db)):
    invited_by = data.get("invited_by")
    new_user_id = data.get("new_user_id")
    if not invited_by or not new_user_id:
        raise HTTPException(status_code=400, detail="Missing ids")
    result = await db.execute(select(UserGameData).where(UserGameData.telegram_id == invited_by))
    inviter = result.scalar_one_or_none()
    if inviter:
        inviter.friends_count += 1
        inviter.gems += 1000
        await db.commit()
    return {"ok": True}

# -------------------- Бот (aiogram) --------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('ref_'):
        try:
            invited_by = int(args[1][4:])
            # Здесь можно вызвать эндпоинт или прямо обновить БД
        except:
            pass
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Играть", web_app=WebAppInfo(url=MINI_APP_URL))
        ]]
    )
    await message.answer("Привет! Нажми кнопку, чтобы начать игру.", reply_markup=keyboard)

# -------------------- Создание FastAPI приложения --------------------
fastapi_app = FastAPI(title="My Pet Game API")

# CORS
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://seryjeblan70-tech.github.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware для логирования запросов (опционально)
@fastapi_app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response

# Подключаем роутер
fastapi_app.include_router(router)

# Тестовый эндпоинт
@fastapi_app.get("/ping")
async def ping():
    return {"ping": "pong"}

@fastapi_app.get("/docs")
async def custom_docs():
    return {"message": "docs are at /docs"}

# -------------------- Запуск --------------------
port = int(os.getenv("PORT", 8000))
config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=port, log_level="info")
server = uvicorn.Server(config)

async def main():
    await init_db()
    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

if __name__ == "__main__":

    asyncio.run(main())
