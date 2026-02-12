import asyncio
import logging
import json
import urllib.parse
import os
import requests
import random 
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from staticmap import StaticMap, Line, CircleMarker

# --- НАЛАШТУВАННЯ ---
API_TOKEN = '8342216853:AAF-_LtBQejUR1Wx9FS9mA0dmWPZuiEei58'
ADMIN_IDS = [6889016268, 8489017722]
COURIER_CHAT_ID = -1003843457222
WEB_APP_URL = "https://myshchyshyn9898-bit.github.io/delivery-bot/" 

# Координати Hero Sushi (Zamenhofa)
SUSHI_LAT = 50.0415
SUSHI_LON = 22.0140

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
        if r.status_code != 200: return None
        
        route_data = r.json()
        if not route_data.get('routes'): return None
            
        coordinates = route_data['routes'][0]['geometry']['coordinates']
        
        m = StaticMap(600, 300, 10) 
        line = Line(coordinates, 'blue', 3)
        m.add_line(line)
        m.add_marker(CircleMarker((SUSHI_LON, SUSHI_LAT), 'green', 10))
        m.add_marker(CircleMarker((end_lon, end_lat), 'red', 10))
        
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
    for o in orders_db:
        name = o['courier']
        if name not in stats: stats[name] = {"cash": 0, "online": 0, "total": 0}
        stats[name]["total"] += 1
        if o['type'] == 'cash':
            stats[name]["cash"] += o['amount']
            total_cash += o['amount']
        else:
            stats[name]["online"] += 1

    time_now = datetime.now().strftime("%H:%M")
    # Тут використовуємо <b> замість ** бо parse_mode буде HTML
    report = f"📊 <b>ЗВІТ (на {time_now})</b>\n➖➖➖➖➖➖➖➖➖➖\n\n"
    for name, d in stats.items():
        report += f"👤 <b>{name}</b>: {d['total']} зам. | {d['cash']:.2f} zł\n"
    report += f"➖➖➖➖➖➖➖➖➖➖\n💰 <b>ВСЯ КАСА:</b> {total_cash:.2f} zł"
    
    await bot.send_message(COURIER_CHAT_ID, report, parse_mode="HTML")
    if message.chat.id != COURIER_CHAT_ID:
        await message.answer("✅ Звіт відправлено.")

# --- ОБРОБКА ДАНИХ (ТУТ ЗМІНИ) ---
@dp.message(F.content_type == types.ContentType.WEB_APP_DATA)
async def web_app_data_handler(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        
        # 1. Генерація ID
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        rand_letter = random.choice(letters)
        rand_num = random.randint(10, 99)
        order_id = f"#{rand_letter}{rand_num}"

        # 2. Отримуємо дані
        address = data.get('address', 'Не вказано')
        details = f"Кв/Оф: {data.get('apt', '-')}, Пов: {data.get('floor', '-')}"
        pay_type = data.get('payType', 'cash')
        comment = data.get('comment', '')
        
        # --- ЛОГІКА UBER (З ОДНОЮ КОМОЮ) ---
        raw_phone = str(data.get('phone', '')).replace(' ', '').replace('-', '').replace('+', '')
        
        if len(raw_phone) == 8 and raw_phone.isdigit():
            # Одна кома = коротка пауза
            phone_display = f'🚕 <a href="tel:+48223076593,{raw_phone}#"><b>Uber Call (Натисни)</b></a>'
        else:
            phone_display = f"📞 <b>Тел:</b> <code>{data.get('phone')}</code>"
        # -----------------------------------

        # 3. Оплата
        if pay_type == 'cash':
            amount = float(data.get('sum', 0))
            money_str = f"💵 <b>Готівка:</b> {amount:.2f} zł"
        else:
            amount = 0
            money_str = f"💳 <b>Оплата:</b> ОНЛАЙН (Сплачено)"

        # 4. Текст повідомлення (Замінив ** на <b> для сумісності)
        courier_text = (
            f"📦 <b>НОВЕ ЗАМОВЛЕННЯ {order_id}</b>\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"<b>Статус:</b> 🟢 Активний\n\n"
            f"📍 <b>Адреса:</b> {address}\n"
            f"🏢 <b>Деталі:</b> {details}\n"
            f"{phone_display}\n" 
            f"{money_str}\n"
            f"➖➖➖➖➖➖➖➖➖➖"
        )
        if comment:
            courier_text += f"\n🗣 <b>Коментар:</b> {comment}"

        # 5. Кнопки
        encoded_addr = urllib.parse.quote(address)
        maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded_addr}"
        callback_data = f"close_{pay_type}_{amount}"

        kb_courier = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗺 Маршрут", url=maps_url)],
            [InlineKeyboardButton(text="✅ Закрити замовлення", callback_data=callback_data)]
        ])

        # 6. Відправка (parse_mode="HTML" щоб працювало посилання)
        client_lat = data.get('lat')
        client_lon = data.get('lon')
        photo_sent = False

        if client_lat and client_lon:
            map_file = generate_route_image(float(client_lat), float(client_lon), order_id)
            if map_file:
                await bot.send_photo(
                    COURIER_CHAT_ID, 
                    photo=FSInputFile(map_file), 
                    caption=courier_text, 
                    reply_markup=kb_courier, 
                    parse_mode="HTML"  # <--- ТУТ ВАЖЛИВО
                )
                photo_sent = True
                try: os.remove(map_file)
                except: pass

        if not photo_sent:
            await bot.send_message(COURIER_CHAT_ID, courier_text, reply_markup=kb_courier, parse_mode="HTML") # <--- ТУТ ВАЖЛИВО

        await message.answer(f"✅ Замовлення {order_id} створено!")
        
    except Exception as e:
        print(f"❌ ПОМИЛКА: {e}")
        await message.answer(f"Помилка: {e}")

# --- Закриття ---
@dp.callback_query(F.data.startswith("close_"))
async def close_order(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        p_type = parts[1]
        amount = float(parts[2])
        courier = callback.from_user.first_name

        time_now = datetime.now().strftime("%H:%M")
        status_line = f"🔴 Закрито ({time_now}, {courier})"
        
        # Тут також треба HTML, бо повідомлення було відправлене як HTML
        if callback.message.photo:
            original_text = callback.message.caption
            new_text = original_text.replace("🟢 Активний", status_line)
            await callback.message.edit_caption(caption=new_text, reply_markup=None, parse_mode="HTML")
        else:
            original_text = callback.message.text
            new_text = original_text.replace("🟢 Активний", status_line)
            await callback.message.edit_text(new_text, reply_markup=None, parse_mode="HTML")

        orders_db.append({"courier": courier, "type": p_type, "amount": amount})
        await callback.answer(f"Прийнято! {amount} zł.")
    except Exception as e:
        print(f"Помилка закриття: {e}")

# --- Обнулення ---
async def daily_reset():
    if orders_db: orders_db.clear()

scheduler.add_job(daily_reset, "cron", hour=0, minute=0)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("🤖 Бот готовий!")
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
