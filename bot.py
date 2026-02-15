import asyncio
import logging
import json
import urllib.parse
import os
import requests
import random
from datetime import datetime
from zoneinfo import ZoneInfo # Правильний час
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from staticmap import StaticMap, Line, CircleMarker

# --- НАЛАШТУВАННЯ ---
API_TOKEN = '8342216853:AAF-_LtBQejUR1Wx9FS9mA0dmWPZuiEei58' # <-- Встав новий токен сюди!
ADMIN_IDS = [6889016268, 8489017722]
COURIER_CHAT_ID = -1003843457222
WEB_APP_URL = "https://myshchyshyn9898-bit.github.io/delivery-bot/" 

# Координати Hero Sushi (Zamenhofa)
SUSHI_LAT = 50.0369285
SUSHI_LON = 22.0068997

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Warsaw")
orders_db = []

# --- ГЕНЕРАТОР КАРТИ ---
def generate_route_image(end_lat, end_lon, filename="map_preview.png"):
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{SUSHI_LON},{SUSHI_LAT};{end_lon},{end_lat}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return None
        
        route_data = r.json()
        if not route_data.get('routes'):
            return None
            
        coordinates = route_data['routes'][0]['geometry']['coordinates']
        
        m = StaticMap(600, 300, 10)
        line = Line(coordinates, 'blue', 3)
        m.add_line(line)
        
        marker_sushi = CircleMarker((SUSHI_LON, SUSHI_LAT), 'green', 10)
        m.add_marker(marker_sushi)
        
        marker_client = CircleMarker((end_lon, end_lat), 'red', 10)
        m.add_marker(marker_client)
        
        image = m.render()
        image.save(filename)
        return filename
    except Exception as e:
        print(f"Помилка карти: {e}")
        return None

# --- СТАРТ ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📝 Створити замовлення", web_app=WebAppInfo(url=WEB_APP_URL))],
        [KeyboardButton(text="📊 Зробити звіт")]
    ], resize_keyboard=True)
    await message.answer("👇 Оберіть дію:", reply_markup=kb)

# --- ЗВІТ ---
@dp.message(F.text == "📊 Зробити звіт")
async def manual_report(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("⛔ Тільки адмін.")
        return
    if not orders_db:
        await message.reply("📭 База пуста.")
        return

    stats = {}
    total_cash = 0
    total_terminal = 0 # Лічильник для терміналу

    for o in orders_db:
        name = o['courier']
        if name not in stats: stats[name] = {"cash": 0, "terminal": 0, "online": 0, "total": 0}
        
        stats[name]["total"] += 1
        
        if o['type'] == 'cash':
            stats[name]["cash"] += o['amount']
            total_cash += o['amount']
        elif o['type'] == 'terminal':
            stats[name]["terminal"] += o['amount']
            total_terminal += o['amount']
        else:
            stats[name]["online"] += 1

    time_now = datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%H:%M")
    report = f"📊 **ЗВІТ (на {time_now})**\n➖➖➖➖➖➖➖➖➖➖\n\n"
    
    for name, d in stats.items():
        report += f"👤 **{name}**: {d['total']} зам. | Готівка: {d['cash']:.2f} zł | Терм: {d['terminal']:.2f} zł\n"
        
    report += f"➖➖➖➖➖➖➖➖➖➖\n💰 **КАСА (Готівка на руках):** {total_cash:.2f} zł\n💳 **ТЕРМІНАЛ (Безготівково):** {total_terminal:.2f} zł"
    
    await bot.send_message(COURIER_CHAT_ID, report, parse_mode="Markdown")
    if message.chat.id != COURIER_CHAT_ID:
        await message.answer("✅ Звіт відправлено.")

# --- ОБРОБКА ДАНИХ ---
@dp.message(F.content_type == types.ContentType.WEB_APP_DATA)
async def web_app_data_handler(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        
        address = data['address']
        details = f"Кв/Оф: {data['apt']}, Пов: {data['floor']}"
        phone = data['phone']
        pay_type = data['payType']
        comment = data.get('comment', '')
        
        client_lat = data.get('lat')
        client_lon = data.get('lon')

        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        rand_letter = random.choice(letters)
        rand_num = random.randint(10, 99)
        order_id = f"#{rand_letter}{rand_num}"

        if pay_type == 'cash':
            amount = float(data['sum'])
            money_str = f"💵 **Готівка/Терм:** {amount:.2f} zł"
        else:
            amount = 0
            money_str = f"💳 **Оплата:** ОНЛАЙН (Сплачено)"

        courier_text = (
            f"📦 **НОВЕ ЗАМОВЛЕННЯ {order_id}**\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"**Статус:** 🟢 Активний\n\n"
            f"📍 **Адреса:** {address}\n"
            f"🏢 **Деталі:** {details}\n"
            f"📞 **Тел:** {phone}\n"
            f"{money_str}\n"
            f"➖➖➖➖➖➖➖➖➖➖"
        )
        if comment:
            courier_text += f"\n🗣 **Коментар:** {comment}"

        encoded_addr = urllib.parse.quote(address)
        maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_addr}"

        # --- КНОПКА ДЗВІНКА ---
        phone_clean = phone.strip()
        call_url = f"{WEB_APP_URL}call.html?code={phone_clean}"

        if phone_clean.isdigit() and len(phone_clean) == 8:
            call_button_text = "🚖 Uber Call"
        else:
            call_button_text = "📞 Подзвонити"

        # --- ГЕНЕРАЦІЯ КНОПОК ---
        keyboard_list = [
            [InlineKeyboardButton(text="🗺 Маршрут", url=maps_url)],
            [InlineKeyboardButton(text=call_button_text, url=call_url)]
        ]

        if pay_type == 'cash':
            keyboard_list.append([
                InlineKeyboardButton(text="💵 Готівка", callback_data=f"close_cash_{amount}"),
                InlineKeyboardButton(text="🏧 Tермінал", callback_data=f"close_terminal_{amount}")
            ])
        else:
            keyboard_list.append([
                InlineKeyboardButton(text="✅ Закрити (Онлайн)", callback_data=f"close_online_0")
            ])

        kb_courier = InlineKeyboardMarkup(inline_keyboard=keyboard_list)

        # Відправка
        photo_sent = False
        if client_lat and client_lon:
            map_file = generate_route_image(float(client_lat), float(client_lon))
            if map_file:
                await bot.send_photo(
                    COURIER_CHAT_ID, 
                    photo=FSInputFile(map_file), 
                    caption=courier_text, 
                    reply_markup=kb_courier, 
                    parse_mode="Markdown"
                )
                photo_sent = True
                try: os.remove(map_file)
                except: pass

        if not photo_sent:
            await bot.send_message(COURIER_CHAT_ID, courier_text, reply_markup=kb_courier, parse_mode="Markdown")

        await message.answer(f"✅ Замовлення створено!")
        
    except Exception as e:
        print(f"❌ ПОМИЛКА: {e}")
        await message.answer(f"Помилка: {e}")

# --- Закриття ---
@dp.callback_query(F.data.startswith("close_"))
async def close_order(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        p_type = parts[1] # 'cash', 'terminal' або 'online'
        amount = float(parts[2])
        courier = callback.from_user.first_name

        time_now = datetime.now(ZoneInfo("Europe/Warsaw")).strftime("%H:%M")
        
        # Формуємо статус залежно від типу оплати
        if p_type == 'terminal':
            status_text = f"🔴 Закрито ({time_now}, {courier} - 🏧 )"
        elif p_type == 'cash':
            status_text = f"🔴 Закрито ({time_now}, {courier} - 💵 )"
        else:
            status_text = f"🔴 Закрито ({time_now}, {courier} - ✅ ОНЛАЙН)"

        if callback.message.photo:
            original_text = callback.message.caption
            new_text = original_text.replace("🟢 Активний", status_text)
            await callback.message.edit_caption(caption=new_text, reply_markup=None)
        else:
            original_text = callback.message.text
            new_text = original_text.replace("🟢 Активний", status_text)
            await callback.message.edit_text(new_text, reply_markup=None)

        orders_db.append({"courier": courier, "type": p_type, "amount": amount})
        await callback.answer(f"Прийнято! Тип оплати: {p_type}.")
    except Exception as e:
        print(f"Помилка закриття: {e}")

# --- Обнулення ---
async def daily_reset():
    if orders_db: orders_db.clear()

scheduler.add_job(daily_reset, "cron", hour=0, minute=0)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 Бот готовий! (Карта з лінією + Оновлені кнопки)")
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
