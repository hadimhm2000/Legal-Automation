"""همه‌ی selectorها و متن‌های صفحه‌ها در یک جا (قابل‌تنظیم).

✅ = از ضبط واقعی کارفرما (فایل‌های steps.json / گزارش HTML، آبان ۱۴۰۵)
⏳ = حدس بر پایه‌ی متن دکمه‌ها در ضبط؛ باید بعد از دیدن HTML واقعی تنظیم شود.
selectorهای موقعیتی ضبط‌شده (nth-of-type) عمداً استفاده نشده‌اند چون با کوچک‌ترین تغییر صفحه می‌شکنند؛
به‌جایشان از id یا متن قابل‌مشاهده‌ی دکمه استفاده شده است.
"""

# ── صفحه‌ی اصلی adliran.ir ──
HOME_POPUP_CLOSE = ["بستن"]                                   # ✅ پاپ‌آپ اطلاعیه‌ی ابتدای سایت
CARD_EBLAGH = ["ابلاغ الکترونیک قضایی"]                       # ✅
LINK_EBLAGH_MAIN = ["سامانه ابلاغ الکترونیک قضایی"]           # ✅ فقط سامانه‌ی اصلی (نه پشتیبان)
CARD_RESULTCASE = ["اطلاع‌رسانی پرونده"]                      # ✅
LINK_RESULTCASE = {
    "person": ["اطلاع‌رسانی پرونده برای اشخاص حقیقی"],        # ✅
    "lawyer": ["اطلاع‌رسانی پرونده برای وکلا"],               # ✅
}
CARD_TURN = ["نوبت‌دهی قضایی", "نوبت دهی قضایی"]              # ✅ (متن لینک داخل پاپ‌آپ)

# ── صفحه‌ی ورود iehraz.adliran.ir ──
NATIONAL_CODE = "#personNationalCode"                         # ✅
PASSWORD = "#personUserPassword"                              # ✅
CAPTCHA_INPUT = "#captcha"                                    # ✅ بعد از رمز اشتباه ظاهر می‌شود
CAPTCHA_IMAGE = "img[src*='Captcha' i], img[src*='captcha' i]"  # ⏳ تصویر کپچا (GetCaptchaImage)
OTP = "#otpPassowrd"                                          # ✅ (املای خود سایت)
NEXT_STEP_BTN = ["مرحله بعد"]                                 # ✅
OTP_RESEND = ["ارسال مجدد رمز موقت"]                          # ✅
CHECK_LOGIN_API = "/Login/CheckPersonLogin"                   # ✅ 200=موفق، 409=نادرست
CHECK_OTP_API = "/Login/CheckPersonOtpLogin"                  # ✅ 200=موفق، 409=نادرست
SEND_OTP_API = "/Login/SendOtpPasswordForPerson"              # ✅
EXPIRED_TEXT = ["اعتبار شما منقضی شده است", "خطای امنیتی"]    # ✅ از متن ارسالی کارفرما
EXPIRED_BACK = ["ورود به صفحه اصلی عدل ایران"]                # ✅

# ── ابلاغ (eblagh1.adliran.ir) ──
EBLAGH_HOSTS = ("eblagh1.adliran.ir", "eblagh.adliran.ir")
NEW_NOTICES = ["ابلاغیه‌های جدید"]                            # ✅
NEW_NOTICES_ID = "#NewNotice"                                 # ✅
VIEWED_NOTICES = ["ابلاغیه‌های مشاهده شده"]                   # ✅
VIEW_BTN = ["مشاهده"]                                         # ✅
DETAIL_TAB = "#eblagh-detail-tab"                             # ✅
ATTACH_TAB = "#eblagh-attachment-tab"                         # ✅
PRINT_BTN = ["نسخه چاپی"]                                     # ✅ → تب جدید Report/ENoticePrint.aspx
BACK_BTN = ["بازگشت"]                                         # ✅
SEARCH_NOTICE = ["جستجوی ابلاغیه"]                            # ✅
SEARCH_NOTICE_GO = ["بازیابی ابلاغیه"]                        # ✅
RANGE_FROM = 'input[name="fromDate"]'                         # ✅
RANGE_TO = 'input[name="toDate"]'                             # ✅
RANGE_GO = ["بازیابی اطلاعات"]                                # ✅
ATTACH_BUSY_TEXT = ["در حال استخراج", "هنوز به پایان نرسیده"]  # ✅ متن alert پیوست
# ⏳ کارت هر ابلاغیه در فهرست: نزدیک‌ترین والدِ دکمه‌ی «مشاهده» که شماره‌ی ابلاغیه را دارد
NOTICE_CARD_XPATH = ("xpath=ancestor::*[self::div or self::tr or self::li]"
                     "[string-length(normalize-space(.))>40][1]")

# ── اطلاع‌رسانی پرونده (resultcase.adliran.ir) ──
RC_LIVE = "#liveCase"                                         # ✅ «مختومه نشده»
RC_ARCHIVED = "#archivedCase"                                 # ✅ «مختومه شده»
RC_LIVE_LABEL = ["مختومه نشده"]
RC_ARCHIVED_LABEL = ["مختومه شده"]
RC_CASE_NO = "#txtHstCaseNo"                                  # ✅
RC_SEARCH = ["بازیابی اطلاعات"]                               # ✅
RC_VIEW = ["مشاهده"]                                          # ✅ → تب CaseListWithPasswordByCaseNo
RC_CASE_INFO = '[ng-bind-html="viewModel.caseInfo"]'          # ✅ از HTML ارسالی کارفرما
RC_PRINT = ["نسخه چاپی"]                                      # ✅ → Reports/PrintResultCase
RC_TABS = ["روند کار پرونده", "آخرین موضوعات پرونده"]         # ✅ (از resultCaseTitle در ضبط)
RC_PAGE_SIZE = "select"                                       # ⏳ انتخاب تعداد در صفحه (3..100)

# ── نوبت‌دهی (adliran.ir/Turn) ──
TURN_BY_CASE = ["اخذ نوبت بر اساس شماره پرونده"]              # ✅
TURN_CASE_INPUT = "#txtCaseNo"                                # ✅ (فوکوس‌شده در ضبط)
TURN_MY_CASES = "#btnHstcaseList"                             # ✅ «فهرست پرونده های من»
TURN_MY_CASES_SEARCH = "#txtCaseNoSearch"                     # ✅
TURN_MY_CASES_GO = ["بازیابی پرونده"]                         # ✅
TURN_CHECK = "#btnCheckUnitTurn"                              # ✅ «بررسی اطلاعات پرونده فوق»
TURN_ROLE_PLACEHOLDER = ["انتخاب سمت جهت ملاقات"]             # ✅
TURN_ROLE_WORD = "دادورز"                                     # ✅ همیشه دادورز
TURN_PERSON_PLACEHOLDER = ["هیچ موردی انتخاب نشده"]           # ✅ فهرست دوم (زیر دادورز)
TURN_NEXT = "#btnNextStep"                                    # ✅
TURN_REASON_BTN = "#btnUnitReferalReasonTypeModal"            # ✅ «فهرست علت ها»
TURN_UNDERSTOOD = ["متوجه شدم"]                               # ✅
TURN_CREATE = "#btnCreateUnitTurn"                            # ✅ «ثبت و دریافت نوبت»
TURN_YES = ["بلی", "بله"]                                     # ✅
TURN_CLOSE = ["بستن"]                                         # ✅
TURN_PRINT = "#btnPrintUnitTurn"                              # ✅ → Reports/PrintUnitTurn?No=
TURN_CREATE_API = "/Turn/CMSUnitTurnCreate"                   # ✅ 500 = نوبت انتخابی پر/نامعتبر
EXECUTION_WORDS = ("اجرای احکام", "اجرا احکام", "اجراي احكام", "اجراي احکام", "اجرای احكام")
