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

# ── UI جدید سامانه‌ی ابلاغ (HTMLهای ارسالی کارفرما — آبان ۱۴۰۵) ──
# کارت شمارنده‌ی «ابلاغیه بازنشده» روی صفحه‌ی اصلی؛ عدد داخل span کنار <strong> است.
NEW_BADGE_CARD = ["ابلاغیه بازنشده"]                          # ✅ متن کارت (strong)
BADGE_CARD_SEL = '[data-lb-badge="new"]'                      # برچسبی که BADGE_JS روی کارت می‌گذارد
# کارت «ابلاغیه‌های مشاهده شده» صفحه‌ی اصلی (ورود به بخش جستجو — دستور کارفرما)
VIEWED_CARD_SEL = '[data-lb-viewed="1"]'                      # برچسبی که VIEWED_CARD_JS می‌گذارد
# دکمه‌ی «مشاهده» هر ردیف جدول ابلاغیه‌ها → مودال #modalXXL باز می‌شود
OPEN_NOTICE_BTN = 'button[ng-click="actions.openNotice(item,false)"]'   # ✅
# مودال جزئیات ابلاغیه (وقتی باز است کلاس show می‌گیرد)
MODAL_OPEN = ".modal.show"                                    # ✅ #modalXXL
MODAL_CLOSE = ".modal.show .btn-close"                        # ✅ دکمه‌ی × (ng-click="actions.clearMessage()")
# دکمه‌ی «نسخه چاپی» داخل مودال → تب جدید ENoticePrint.aspx
PRINT_BTN_NG = 'button[ng-click="actions.getENoticeDocumentPrint()"]'   # ✅
# دکمه‌ی «۳ ماه قبل» — بازیابی جدول وقتی بعد از بستن مودال خالی ماند
MONTHS3_BTN = 'button[ng-click="actions.changeDateWithMonth(-3,1)"]'    # ✅
MONTHS3_BACK = ["3 ماه قبل", "۳ ماه قبل"]                      # ✅ متن دکمه

# ── فرم «جستجوی ابلاغیه» داخل بخش «ابلاغیه‌های مشاهده شده» (HTML ارسالی کارفرما) ──
# دکمه‌ی باز کردن فرم جستجو (collapse #SeenEblaghSearchBox)
SEARCH_BOX_BTN = 'button[data-bs-toggle="collapse"][href="#SeenEblaghSearchBox"]'   # ✅
SEARCH_BOX_COLLAPSE = "#SeenEblaghSearchBox"                                        # ✅
# فیلد «شماره پرونده» فرم جستجو
SEARCH_CASE_INPUT = 'input[ng-model="ENotifySearchCriteria.NoticedDocCaseNo"]'      # ✅
# فیلد «شماره ابلاغیه» فرم جستجو
SEARCH_NO_INPUT = 'input[ng-model="ENotifySearchCriteria.NoticedDocNo"]'            # ✅
# دکمه‌ی «بازیابی ابلاغیه» (فرم جستجو — با «بازیابی اطلاعات» بازه‌ی زمانی فرق دارد)
SEARCH_GO_NG = 'button[ng-click="actions.getAllENotice(viewModel.pageSize, 1)"]'    # ✅
# پیام خطای قرمز جستجو («با شرایط وارد شده ابلاغیه‌ای یافت نشد.»)
SEARCH_ERR_SEL = '.alert-danger[role="alert"]'                                      # ✅

# ── اطلاع‌رسانی پرونده (resultcase.adliran.ir) ──
RC_LIVE = "#liveCase"                                         # ✅ «مختومه نشده»
RC_ARCHIVED = "#archivedCase"                                 # ✅ «مختومه شده»
RC_LIVE_LABEL = ["مختومه نشده"]
RC_ARCHIVED_LABEL = ["مختومه شده"]
RC_CASE_NO = "#txtHstCaseNo"                                  # ✅
RC_SEARCH = ["بازیابی اطلاعات"]                               # ✅ (استعلام)
RC_VIEW = ["مشاهده"]                                          # ✅ → تب CaseListWithPasswordByCaseNo
RC_CASE_INFO = '[ng-bind-html="viewModel.caseInfo"]'          # ✅ از HTML ارسالی کارفرما
RC_PRINT = ["نسخه چاپی"]                                      # ✅ → Reports/PrintResultCase
RC_TAB_FLOW = ["روند کاری پرونده", "روند کار پرونده"]          # ✅ pills-profile-tab (printType=2)
RC_TAB_SUBJECT = ["آخرین موضوعات"]                            # ✅ pills-disabled-tab (printType=4)
# ✅ فیلدهای تاریخ جستجو (از HTML ارسالی کارفرما — persian-datepicker-popup)
RC_DATE_FROM = 'input[name="saveFromDate"]'
RC_DATE_TO = 'input[name="saveToDate"]'
# ✅ پیام‌های سامانه (GGG) — هر سه روی viewModel نمایش داده می‌شوند
RC_MSG_WARNING = '[ng-bind-html="viewModel.warningMessage"]'  # «صف پردازش…»
RC_MSG_INFO = '[ng-bind-html="viewModel.infoMessage"]'        # «پرونده ای یافت نشد»
RC_MSG_ERROR = '[ng-bind-html="viewModel.errorMessage"]'      # «تاخیر در اجرای سرویس…»
RC_QUEUE_TEXTS = ["صف پردازش"]                                # ✅ هر دو متن هشدار GGG
RC_NOT_FOUND_TEXTS = ["پرونده ای یافت نشد", "موردی یافت نشد"]  # ✅ پیام اطلاع GGG
RC_SVC_DELAY_TEXTS = ["تاخیر در اجرای سرویس"]                  # ✅ پیام خطای قرمز
RC_PAGE_SIZE_VALUE = "100"                                    # ✅ همیشه ۱۰۰ (دستور کارفرما)
RC_GET_LIST_API = "GetCaseList"                               # ✅ POST فهرست (409 = صف پردازش)

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
