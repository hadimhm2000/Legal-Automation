# Legal-Automation — ربات «اتوماسیون ویژه خدمات حقوقی» (ربات دوم بله)

ربات بله‌ی مستقل (پایتون، aiogram 3 + Playwright) که با اطلاعاتی که کاربر **همان لحظه و مرحله‌به‌مرحله** می‌دهد
(کدملی ← رمز شخصی ← رمز موقت) وارد سامانه‌های عدل ایران می‌شود. **اطلاعات ورود ذخیره نمی‌شود.**
از ربات اصلی (`online.judicial.services.ble`) فقط با یک دکمه‌ی مخصوص مدیر و لینک امضاشده وارد می‌شویم.

## بخش‌ها

| بخش | کار |
|---|---|
| 📩 ابلاغیه‌ها | بررسی ابلاغیه‌های جدید (۸ و ۱۸ یا دستی) ← نسخه‌ی چاپی PDF + همه‌ی پیوست‌ها؛ جستجو با شماره پرونده؛ جستجو در بازه‌ی زمانی (تکه‌های ۳۰ روزه تا پایان بازه) |
| ⏰ یادآوری | جلسه: ۲ روز و ۱ روز قبل (و صبح همان روز) با شماره پرونده، بایگانی و شعبه؛ مهلت («مهلت حضور ۱۰ روز»): هر ۳ روز و روز قبل؛ مهلت دلخواه کاربر (تاریخ یا تعداد روز)؛ دکمه‌ی «✅ مراجعه و انجام شد» |
| 🖨 گزارش | چاپ پرونده‌های جاری / به اتمام رسیده / همه / لیست جلسات آینده (PDF فارسی) |
| 📂 اطلاع‌رسانی پرونده | ۱) همه ۲) جاری ۳) مختومه ۴) جزئیات با شماره پرونده (+ لوایح دارای «220») ۵) ثبت پرونده برای بررسی روزانه ساعت ۸ — هر بار انتخاب «اشخاص حقیقی / وکیل» |
| 🗓 ثبت نوبت قضائی | ۷۰٬۰۰۰ تومان پیش از هر درخواست ← شماره پرونده یا بایگانی ← فقط شعبه‌های «اجرای احکام» ← همیشه «دادورز» ← انتخاب دادورز توسط کاربر ← اولین نوبت خالی ← PDF نوبت |
| 💳 اشتراک | تست ۳ روزه‌ی یک‌باره، ۳ پلن، قفل، فاکتور، کارت‌به‌کارت با رسید و تأیید مدیر، ارتقای نسبی، تمدید |

## راه‌اندازی

```sh
python -m venv .venv && . .venv/bin/activate      # ویندوز: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium            # لینوکس: playwright install-deps chromium
cp env.example .env                    # مقادیر را پر کنید
python bot_main.py
```

در ربات اصلی (`online.judicial.services.ble`) در `.env`: `LEGAL_BOT_USERNAME` و همان `HANDOFF_SECRET`.

## تست

```sh
python -m pytest            # ۴۰ تست؛ شامل ورود کامل و روند ابلاغیه روی سایت ساختگی (بدون اینترنت)
```

## ساختار

```
bot_main.py                     # تک‌پروسه: ربات + scheduler + مرورگر
legal_bot/config.py · db.py · texts.py · keyboards.py · handoff.py · utils.py
legal_bot/handlers/             # start, plans, payment, notices, cases, turn, admin, job_input
legal_bot/services/session.py   # Job: پرسش از کاربر وسط کار مرورگر + SecretVault (فقط RAM)
legal_bot/services/sana_login.py  # تنها جایی که اطلاعات ورود در فرم نوشته می‌شود
legal_bot/services/eblagh.py · notice_parser.py · reminders.py · reports.py
legal_bot/services/resultcase.py · case_parser.py · turn.py · selectors.py · scheduler.py
docs/phase0.md                  # چه چیزی از ضبط‌ها تأیید شده و چه چیزی باید روی سایت واقعی آزموده شود
docs/open-questions.md
```

## دستورات مدیر

`/legal_help` · `/legal_runs` · `/legal_errors` · `/legal_user <id>` · `/legal_allow <id>` · `/legal_deny <id>` · `/legal_guide` · `/legal_tick`

هر خطا در هر مرحله (L01…L12) فوراً با زنجیره‌ی ✅/❌ مراحل به مدیر گزارش می‌شود (بدون هیچ مقدار ورودی کاربر).
