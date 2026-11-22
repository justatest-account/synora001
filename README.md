# SYNORA — Where Connections Come Alive

چت بلادرنگ دو زبانه (فارسی/English) با Kivy، رمزنگاری سرتاسری و سرور رله‌ی سبک.

## ساختار
```
server/server.py        سرور رله (websockets + SQLite)
client/main.py          برنامه Kivy (منطق، شبکه، رمزنگاری)
client/synora.kv        رابط کاربری (KV language)
client/widgets.py       آیکون‌ها و ویجت‌های سفارشی
client/textfix.py       شکل‌دهی و ترتیب‌دهی متن فارسی
client/crypto_utils.py  X25519 + HKDF + ChaCha20-Poly1305
client/vault.py         ذخیره‌ی رمزشده‌ی کلید و تاریخچه روی دستگاه
client/net.py           اتصال WebSocket در Thread جدا
tests/                  تست منطق سرور و رمزنگاری
```

## اجرا روی کامپیوتر
```
# ترمینال ۱ (سرور)
cd server && pip install -r requirements.txt && python server.py
# ترمینال ۲ و ۳ (دو کلاینت)
cd client && pip install -r requirements.txt && python main.py
```
فونت Vazirmatn را در `client/fonts/` بگذارید. آدرس پیش‌فرض سرور `ws://127.0.0.1:8765` است
و از فیلد «آدرس سرور» در صفحه‌ی ورود قابل تغییر است.

## استقرار رایگان روی Render (پیشنهادی)
1. کل پوشه‌ی `synora` را در یک ریپوی GitHub بگذارید (ریشه‌ی ریپو همین پوشه باشد).
2. در render.com با GitHub ثبت‌نام کنید → New + → Web Service → ریپو را انتخاب کنید.
3. تنظیمات: Runtime = Python 3، Build Command = `pip install -r server/requirements.txt`،
   Start Command = `python server/server.py`، Instance Type = Free، Health Check Path = `/healthz`.
   (پورت را Render خودش در `PORT` می‌دهد؛ سرور آن را می‌خواند. چیزی را ویرایش نکنید.)
4. آدرس سرویس مثل `https://synora-relay.onrender.com` است. در برنامه بنویسید: `wss://synora-relay.onrender.com`.
5. برای اینکه سرویس نخوابد، یک مانیتور HTTP رایگان (مثلاً UptimeRobot) هر ۵ دقیقه آدرس بالا را صدا بزند.

نکته: دیسک پلن رایگان موقتی است؛ با ری‌استارت یا دیپلوی دوباره، حساب‌ها پاک می‌شوند.
حساب‌های دمو را چند دقیقه قبل از ارائه بسازید.

## ساخت APK
`buildozer android debug` (در WSL2/Linux) با فایل `buildozer.spec` همین پوشه.
