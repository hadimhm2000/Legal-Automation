# فاز ۰ — یافته‌ها از ضبط‌های کارفرما و آنچه باید روی سایت واقعی آزموده شود

منابع: سه فایل zip ضبط (`login_bot.py` + `steps.json` + گزارش HTML) برای «ابلاغ»، «اطلاع‌رسانی پرونده» و
«نوبت‌دهی»؛ متن دستورالعمل کارفرما؛ PDFهای نمونه‌ی 3333 و 2323؛ HTML ارسالی کارفرما (پاپ‌آپ‌ها و caseInfo).

## ✅ تأییدشده از ضبط‌ها

| مورد | یافته |
|---|---|
| ورود | `#personNationalCode` ← `#personUserPassword` ← Enter یا «مرحله بعد» ← `#otpPassowrd` ← Enter |
| نتیجه‌ی ورود | `POST /Login/CheckPersonLogin` و `/Login/CheckPersonOtpLogin`: **200 = موفق، 409 = نادرست** (تشخیص از روی پاسخ شبکه، نه حدس از متن صفحه) |
| کپچا | بعد از رمز اشتباه، `#captcha` ظاهر می‌شود (`/Login/GetCaptchaImage`). ربات فقط تصویر کپچا را برای خود کاربر می‌فرستد تا خودش حل کند (دور زدن نیست). |
| ارسال مجدد رمز موقت | متن «ارسال مجدد رمز موقت» ← `POST /Login/SendOtpPasswordForPerson` |
| سامانه‌ی اصلی ابلاغ | `http://eblagh1.adliran.ir` ← ورود ← `eblagh1.adliran.ir/ENotice/Index`. سامانه‌ی پشتیبان (`eblagh.adliran.ir`) در ضبط خطای 401/500 و محافظ ضدربات TSPD داشت؛ ربات از آن استفاده نمی‌کند. |
| ابلاغیه | «ابلاغیه‌های جدید» (`#NewNotice`) ← «مشاهده» ← `#eblagh-detail-tab` ← «نسخه چاپی» (تب جدید `Report/ENoticePrint.aspx`) ← `#eblagh-attachment-tab` ← «مشاهده» (`Report/HstDocumentPrint.aspx` = PDF) ← «بازگشت» ← «ابلاغیه‌های مشاهده شده» |
| پیوست | alert «سیستم در حال استخراج اطلاعات پیوست… دو دقیقه» ← ربات ۲ دقیقه صبر و دوباره تلاش می‌کند (حداکثر ۳ بار) |
| «چاپ گروهی» | به برنامه‌ی محلی سمپ‌یار (`localhost:8010/JSSService`) نیاز دارد ← **استفاده نمی‌شود**؛ هر ابلاغیه جدا چاپ می‌شود |
| بازه‌ی زمانی | `input[name=fromDate]` / `input[name=toDate]` شمسی `1399/09/09` ← «بازیابی اطلاعات» (دکمه‌ی «یک ماه قبل» هم هست) |
| جستجو با پرونده | «جستجوی ابلاغیه» ← فیلد ← «بازیابی ابلاغیه» |
| اطلاع‌رسانی پرونده | `resultcase.adliran.ir/ResultCase/CaseListForPerson` (یا `ForLawyer`)؛ `#liveCase` «مختومه نشده»، `#archivedCase` «مختومه شده»، `#txtHstCaseNo`، «بازیابی اطلاعات»، «مشاهده» ← تب `CaseListWithPasswordByCaseNo` ← متن `[ng-bind-html="viewModel.caseInfo"]` ← «نسخه چاپی» (`Reports/PrintResultCase`، دو عنوان «روند کار پرونده» و «آخرین موضوعات پرونده») |
| نوبت‌دهی | `adliran.ir/Turn/Index#/Main` ← «اخذ نوبت بر اساس شماره پرونده» ← `#btnHstcaseList` ← `#txtCaseNoSearch` ← «بازیابی پرونده» ← `#btnCheckUnitTurn` ← «انتخاب سمت جهت ملاقات» = «دادورز اجراي احكام» ← «هیچ موردی انتخاب نشده» = فهرست دادورزها ← `#btnNextStep` ← `#btnUnitReferalReasonTypeModal` ← «متوجه شدم» ← روز ← ساعت ← `#btnCreateUnitTurn` ← «بلی» (`/Turn/CMSUnitTurnCreate`: 500 = نوبت پذیرفته نشد ← «بستن» و ساعت بعد) ← `#/Detail` ← `#btnPrintUnitTurn` (`Reports/PrintUnitTurn?No=`) |
| متن ابلاغیه | از متن صفحه‌ی چاپ (نه OCR): شماره ابلاغیه/پرونده/بایگانی، شعبه، تاریخ و ساعت حضور (جدول یا متن)، «مهلت حضور : ۱۰روز»، تاریخ ارسال به سامانه |

## ⏳ باید روی سایت واقعی (از سرور داخل ایران) آزموده شود

1. **ورود headless از IP سرور**: آیا محافظ ضدربات (TSPD/F5) یا کپچای همیشگی دارد؟ (ضبط‌ها با پنجره‌ی نمایان روی ویندوز بود.)
2. **کارت‌های فهرست ابلاغیه**: شماره‌ی ابلاغیه از متن کارت خوانده می‌شود (`CARDS_JS` در `eblagh.py`). اگر کارت شماره ندارد، باید از پاسخ JSON `GetNewENoticeWithoutNoticeText` خوانده شود.
3. **صفحه‌بندی** فهرست‌ها (ابلاغیه و پرونده): selector عمومی `.pagination` حدسی است.
4. **فیلدهای تاریخ** ممکن است datepicker فقط‌خواندنی باشند؛ کد در این حالت مقدار را با JS می‌گذارد و رویداد input/change می‌فرستد.
5. **نوبت‌دهی**: فهرست شعبه‌ها در «فهرست پرونده های من»، منوهای ngMultiSelect، تقویم و ساعت‌ها با JS عمومی خوانده می‌شوند (`turn.py`) — اولین اجرای واقعی را مدیر با `TEST_PRICE_TOMAN` انجام دهد.
6. **چاپ با page.pdf**: نسخه‌ی چاپی ابلاغیه HTML است و با Chromium به PDF تبدیل می‌شود؛ پیوست‌ها خودشان PDF هستند و مستقیم گرفته می‌شوند.
7. **بله**: پشتیبانی `?start=` در لینک `ble.ir/<bot>`، دکمه‌ی url، `deleteMessage`، و یکسان بودن آیدی کاربر در دو ربات.

همه‌ی selectorها در `legal_bot/services/selectors.py` با علامت ✅/⏳ هستند و بدون تغییر منطق قابل‌تنظیم‌اند.
