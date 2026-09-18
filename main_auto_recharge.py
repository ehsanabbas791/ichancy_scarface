from telegram import BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
#from Database_updated1 import (
#    get_user, update_balance, create_recharge, create_withdraw,
#    update_ichancy_account, update_user_agreed, get_user_balance, get_user_recharges, get_user_withdraws,
#    update_recharge_status, update_withdraw_status,
#    get_last_spin_date, update_last_spin_date,
#    get_all_users,
#    get_usdt_rate, set_usdt_rate, approve_verified_recharge
#)
from databasse import (
    get_user, update_balance, create_recharge, create_withdraw,
    update_ichancy_account, update_user_agreed, get_user_balance,
    get_user_recharges, get_user_withdraws,
    update_recharge_status, update_withdraw_status,
    get_last_spin_date, update_last_spin_date,
    get_last_spin_at, update_last_spin_at,
    get_spin_cooldown_hours, set_spin_cooldown_hours,
    get_active_spin_prizes, get_all_spin_prizes,
    add_spin_prize, set_spin_prize_active, delete_spin_prize,
    update_spin_prize_weight,
    get_spin_prize, pick_random_spin_prize,
    get_all_users,
    get_usdt_rate, set_usdt_rate, approve_verified_recharge,set_referrer,
    get_referral_info,
    get_referrer,get_referral_users,
    activate_referral_after_recharge,
    get_referral_users,
    create_gift_code,
    redeem_gift_code,
    get_all_referrals,
    get_referral_commission_percent, set_referral_commission_percent,
    get_referral_period_days, set_referral_period_days,
    log_referral_commission, get_pending_commission_total,
    mark_referral_commissions_paid, init_referral_cycle_if_missing,
    get_referral_cycle_start, reset_referral_cycle,
    get_all_referrer_ids, get_recent_referral_payouts,
    get_bonus_percent, set_bonus_percent, get_all_bonus_percents,
    log_ichancy_transaction, get_ichancy_movement_since,
    get_cashback_snapshot, init_cashback_snapshot_if_missing, update_cashback_snapshot,
    record_cashback_payout, get_cashback_percent, set_cashback_percent,
    get_users_with_ichancy, get_recent_cashback_payouts
)
import os
import secrets
import string
import json
import asyncio
import math
import urllib.parse
from datetime import datetime, timedelta
from ichancy_api2 import (
    init_api, register_player, get_player_by_username,
    deposit_to_player, withdraw_from_player, get_all_players,get_player_balance
)
from payment_api import verify_payment

# ============================
# الإعدادات الأساسية
# ============================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8681125871:AAEmqFKLJq8ZPuT_2HnXfsDWUBBKXDxmcRQ")
ADMIN_IDS = [6756808076]  # ← حط IDs الأدمنية هون
#
# دالة مساعدة لإرسال رسالة لجميع الأدمنية
async def notify_admins(bot, text, reply_markup=None):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception:
            pass

WITHDRAW_FEE_PERCENT   = 0.10   # حسم السحب = 10%

# ============================
# نسب بونص الشحن (قابلة للتعديل من لوحة الأدمن)
# ============================
# مفاتيح طرق الشحن كما تُخزَّن في قاعدة البيانات (settings)
BONUS_METHOD_LABELS = {
    "syriatel": "🟢 Syriatel Cash",
    "shamcash": "⚡ Sham Cash",
    "usdt": "💰 USDT",
}


def _bonus_key_for_method(method):
    """
    تحويل اسم طريقة الشحن (كما يُخزَّن في recharge_requests) إلى مفتاح
    موحّد يُستخدم لجلب/تعديل نسبة البونص من الإعدادات.
    """
    method = (method or "").strip()

    if method.startswith("Sham Cash"):
        return "shamcash"
    if method.startswith("USDT"):
        return "usdt"
    if method.startswith("Syriatel Cash"):
        return "syriatel"

    return None


# ============================
# الاسترداد الأسبوعي (Cashback)
# ============================
CASHBACK_INTERVAL_SECONDS = 7 * 24 * 60 * 60   # أسبوع
CASHBACK_INITIAL_DELAY_SECONDS = 60            # مهلة بسيطة بعد إقلاع البوت قبل أول فحص

# ============================
# عمولة الإحالة المستمرة (Referral Commission)
# ============================
REFERRAL_CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # فحص كل 6 ساعات لمن استحق التوزيع
REFERRAL_CHECK_INITIAL_DELAY_SECONDS = 90

# ============================
# عجلة الحظ (Spin Wheel)
# ============================
SPIN_WEBAPP_BASE_URL = "https://ehsanabbas791.github.io/ichancu-spin/spin.html"


def _build_spin_webapp_url(labels, eligible, land_index=None, remaining_text="", prize_type=None):
    """
    يبني رابط الـ WebApp للعجلة. النتيجة (land_index) والنوع (prize_type)
    تُحدَّد من السيرفر مسبقاً — الواجهة (spin.html) تعرضها فقط، ولا تقرر
    أي جائزة بنفسها. prize_type يُستخدم فقط لعرض رسالة دقيقة بعد اللف
    (كل نوع جائزة له رسالة مختلفة صحيحة).
    """
    payload = {
        "labels": labels,
        "eligible": bool(eligible),
        "land": land_index,
        "remaining": remaining_text,
        "prize_type": prize_type,
    }
    encoded = urllib.parse.quote(json.dumps(payload, ensure_ascii=False))
    return f"{SPIN_WEBAPP_BASE_URL}?data={encoded}"

# ============================
# إعدادات العملة
# ============================
CURRENCY_LABEL   = "ل.س"       # عملة البوت: ليرة سورية
ICHANCY_CURRENCY = "NSP"       # عملة الإيشانسي
LSP_PER_NSP      = 1           # 1 NSP = 1 ل.س (مبلغ البوت = مبلغ iChancy مباشرة)

def ls_to_nsp(amount_ls: float) -> float:
    """تحويل ليرة سورية → NSP (1:1)"""
    return float(amount_ls)

def nsp_to_ls(amount_nsp: float) -> float:
    """تحويل NSP → ليرة سورية (1:1)"""
    return float(amount_nsp)

CHANNEL_USERNAME = "@ichancy_scarface"
CHANNEL_LINK = "https://t.me/ichancy_scarface"

# القنوات المطلوب الاشتراك بها لاستخدام البوت (قناة البوت فقط حالياً)
REQUIRED_CHANNELS = [
    {"username": CHANNEL_USERNAME, "link": CHANNEL_LINK, "label": "قناة البوت"},
]

TEXT = """عند الضغط على زر موافقة فأنت توافق على الشروط القائمة ضمن البوت ويحق لك الإعتراض في حال مواجهة أي مشكلة خارجة عن شروط وقوانين البوت

يرجى قراءة هذه الشّروط قبل استخدام البوت لضمان تجربة آمنة وسلسة:

البوت مخصّص لإنشاء الحسابات، والسّحب، والتعبئة الفورية لحسابات موقع Ichancy.

1_منع الحسابات المتعدّدة:
إنشاء أكثر من حساب للشّخص الواحد مخالف للقوانين، وقد يؤدّي إلى حظر الحسابات المرتبطة وتجميد أرصدتها، وذلك بناءاً على سياسة اللّعب النظيف.

2_تبديل طرق الدفع غير مسموح:
لا يُسمح بشحن رصيد وسحبه بغرض التبديل بين وسائل الدفع المختلفة. في حال اكتشاف عملية كهذه، يتم سحب الرّصيد والتّحفظ عليه دون إشعار مسبق.

3_شروط أرباح الإحالات:
تُحتسب أرباح الإحالة فقط بعد تسجيل 3 إحالات نشطة أو أكثر (أي قاموا بالتعبئة الفعلية).

⛔️تنبيه:
أي محاولة للتّحايل أو مخالفة الشروط ستؤدي إلى إيقاف الحساب وتجميد الأرصدة.
"""

# ============================
# وظائف مساعدة
# ============================
def generate_password(length=10):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

def generate_gift_code(length=10):
    chars = string.ascii_uppercase + string.digits

    while True:
        code = "GIFT-" + "".join(
            secrets.choice(chars)
            for _ in range(length)
        )

        return code
    
async def is_subscribed_to_channel(bot, channel_username, user_id):
    try:
        member = await asyncio.wait_for(
            bot.get_chat_member(channel_username, user_id),
            timeout=5.0
        )
        return member.status in ["member", "administrator", "creator"]
    except asyncio.TimeoutError:
        return True   # في حال تأخر الاتصال نعامله كمشترك لتجنب التعليق
    except Exception:
        return False


async def get_unsubscribed_channels(bot, user_id):
    """
    ترجع قائمة بالقنوات (من REQUIRED_CHANNELS) التي لم يشترك بها
    المستخدم بعد.
    """
    missing = []
    for channel in REQUIRED_CHANNELS:
        subscribed = await is_subscribed_to_channel(bot, channel["username"], user_id)
        if not subscribed:
            missing.append(channel)
    return missing


async def is_user_subscribed(bot, user_id):
    """
    التحقق من اشتراك المستخدم بكل القنوات المطلوبة (قناة البوت + القناة الشخصية).
    """
    missing = await get_unsubscribed_channels(bot, user_id)
    return len(missing) == 0

# ============================
# لوحات المفاتيح
# ============================
def join_channel_keyboard(missing_channels=None):
    channels = missing_channels if missing_channels else REQUIRED_CHANNELS
    keyboard = [
        [InlineKeyboardButton(f"🔔 الانضمام إلى {ch['label']}", url=ch["link"])]
        for ch in channels
    ]
    keyboard.append([InlineKeyboardButton("✅ تحقّق من الاشتراك", callback_data="check_join")])
    return InlineKeyboardMarkup(keyboard)

def main_menu(user_id=None):
    buttons = [
        ["🧾  حساب Ichancy", "💰 اعرف رصيدي"],
        ["📥 شحن رصيد", "📤 سحب رصيد"],
        ["شحن حسابي ichancy من رصيد البوت", "سحب من حسابي ichancy لرصيد البوت"],
        ["🎁 إهداء رصيد","🤝نظام الإحالات"],
        ["💎كود هدية"],
        ["🎰 اللفة المجانية"],
        ["✉️ رسالة للإدمن", "📞 تواصل معنا"],
        ["📜 السجل", "☁️ الشروحات"],
        ["📱 ichancy apk"],
        ["📌 الشروط والأحكام"],
    ]
    if user_id in ADMIN_IDS:
        buttons.append(["🛠️ لوحة تحكم الأدمن"])

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup(
        [["❌ تراجع عن العملية"]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# ======================================================
# ✅ التعديل: أضفنا زر "تعديل المبلغ" لرسالة الأدمن
# ======================================================
def admin_recharge_keyboard(user_id, amount):
    keyboard = [
        [
            InlineKeyboardButton("✅ تأكيد الشحن", callback_data=f"approve_{user_id}_{amount}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"reject_{user_id}_{amount}")
        ],
        [
            InlineKeyboardButton("✏️ تعديل المبلغ", callback_data=f"edit_amount_{user_id}_{amount}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_withdraw_keyboard(user_id, amount, account):
    keyboard = [
        [
            InlineKeyboardButton("✅ تأكيد السحب", callback_data=f"wdapprove_{user_id}_{amount}_{account}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"wdreject_{user_id}_{amount}_{account}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def faq_menu():
    keyboard = [
        [InlineKeyboardButton("❓ ما هو Ichancy؟", callback_data="faq_what")],
        [InlineKeyboardButton("📥 كيف أشحن رصيد؟", callback_data="faq_recharge")],
        [InlineKeyboardButton("📤 كيف أسحب رصيد؟", callback_data="faq_withdraw")],
        [InlineKeyboardButton("🎰 اللفة المجانية", callback_data="faq_spin")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="faq_back")]
    ]
    return InlineKeyboardMarkup(keyboard)

def history_menu():
    keyboard = [
        [
            InlineKeyboardButton("📥 سجل الشحن", callback_data="history_recharge"),
            InlineKeyboardButton("📤 سجل السحب", callback_data="history_withdraw")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ============================
# معالجات الأوامر الأساسية
# ============================
async def start(update, context):

    user_id = update.effective_user.id

    # =====================================================
    # Referral System
    # =====================================================

    referral_args = context.args

    if referral_args:

        referral_code = referral_args[0]

        if referral_code.startswith("ref_"):

            try:
                referrer_id = int(
                    referral_code.replace("ref_", "")
                )

                # منع إحالة المستخدم لنفسه
                if referrer_id != user_id:

                    # تسجيل الإحالة
                    set_referrer(
                        referred_user_id=user_id,
                        referrer_id=referrer_id
                    )

            except (ValueError, TypeError):
                pass

    # =====================================================
    # باقي كود start الحالي
    # =====================================================

    missing_channels = await get_unsubscribed_channels(context.bot, user_id)

    if missing_channels:

        await update.message.reply_text(
            "يجب الاشتراك بكل القنوات التالية أولاً لاستخدام البوت 🔔",
            reply_markup=join_channel_keyboard(missing_channels)
        )
        return

    user = get_user(user_id)

    if user.get("agreed") == 1:

        context.user_data["agreed"] = True

        await update.message.reply_text(
            "👋 أهلاً بك من جديد!",
            reply_markup=main_menu(user_id)
        )

        return

    keyboard = [[
        InlineKeyboardButton(
            "✅ موافق",
            callback_data="agree"
        ),
        InlineKeyboardButton(
            "❌ غير موافق",
            callback_data="disagree"
        )
    ]]

    await update.message.reply_text(
        TEXT,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_balance(update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    balance_ls = user['balance']
    balance_nsp = ls_to_nsp(balance_ls)
    await update.message.reply_text(
        f"💰 رصيدك داخل البوت: {balance_ls:,} {CURRENCY_LABEL}\n"
        #f"🎮 ما يعادله بالإيشانسي: {balance_nsp:.2f} {ICHANCY_CURRENCY}"
    )

async def admin_command(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ ليس لديك صلاحية الوصول لهذه الأوامر")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 قائمة المستخدمين", callback_data="admin_users_1")]
    ])
    await update.message.reply_text("🛠️ لوحة تحكم الأدمن", reply_markup=keyboard)

# ============================
# Callback Queries
# ============================
async def terms_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "agree":
        context.user_data["agreed"] = True
        update_user_agreed(user_id, True)
        await query.edit_message_text("✅ تمّت الموافقة على الشروط.")
        await query.message.reply_text("👋 أهلاً بك في Ichancy ⚡\nاختر من القائمة:", reply_markup=main_menu(user_id))

    elif query.data == "disagree":
        await query.edit_message_text("❌ لا يمكنك استخدام البوت بدون الموافقة على الشروط.")

async def check_join_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    try:
        missing_channels = await asyncio.wait_for(
            get_unsubscribed_channels(context.bot, user_id),
            timeout=6.0
        )
    except asyncio.TimeoutError:
        await query.answer("⚠️ تأخر الاتصال، حاول مجدداً", show_alert=True)
        return

    if not missing_channels:
        await query.edit_message_text("✅ تم التحقق من اشتراكك بنجاح")
        await query.message.reply_text("اختر من القائمة:", reply_markup=main_menu(user_id))
    else:
        await query.answer("❌ لسا ما اشتركت بكل القنوات المطلوبة", show_alert=True)

async def recharge_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "syriatel_cash":
        context.user_data["recharge_method"] = "Syriatel Cash"
        context.user_data["recharge_step"] = "payment_txid"
        text = (
            "🟢 شحن رصيد عبر Syriatel Cash\n\n"
            "ارسل الى احد الارقام التالية بطريقة *التحويل اليدوي*.\n\n"
            "اقل قيمة للشحن هي 200 ليرة سورية جديدة\n\n"
            "`89785573`\n"
            "`92766033`\n"
            "`20409170`\n"
            "`39843402`\n\n"
            "📌 بعد إتمام التحويل أرسل *رقم العملية فقط*.\n"
            "🤖 سيتم التحقق من العملية تلقائياً.\n\n"
            
        )
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif query.data == "sham_cash":
        context.user_data["recharge_method"] = "Sham Cash"
        context.user_data["recharge_step"] = "payment_txid"
        text = (
            "عملائنا المحترمين …\n\n"
            " … أقل قيمة إيداع 200 ل.س جديدة …\n"
            "شكراً لثقتكم 💯\n\n"
            "⚡ ارسل الى العنوان …\n"
            "♦️ Scarface@1 ♦️\n\n"
            "من فضلك لا تقم بأخفاء هوية حساب شام كاش الذي تقوم بالشحن منه …\n"
            "*1 ShamCash USD = 13500*\n\n"
            "`8ac1cfc8b8139f6924d72aaa0314b1bf`\n\n"
            "📌 بعد إتمام التحويل أرسل *رقم العملية فقط*.\n"
            "🤖 سيتم التحقق من العملية تلقائياً.\n\n"
        )
        try:
            with open("shamcash_qr.png", "rb") as photo:
                await query.message.reply_photo(photo=photo, caption=text, parse_mode="Markdown", reply_markup=cancel_keyboard())
        except Exception:
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif query.data == "crypto":
        context.user_data["recharge_method"] = "USDT"
        context.user_data["recharge_step"] = "usdt_amount"
        USDT_WALLET = "0x022c4d1e65fa15af2a383981b38617fc5e7dcf7f"
        rate = get_usdt_rate()
        usdt_bonus_percent = get_bonus_percent("usdt")
        text = (
            "💰 شحن رصيد عبر USDT (ERC20/BEP20)\n\n"
            f"🎁 بونص {usdt_bonus_percent * 100:.0f}% على كل شحنة!\n\n"
            "📋 عنوان المحفظة (ERC20/BEP20):\n"
            f"`{USDT_WALLET}`\n\n"
            f"💱 سعر الصرف: 1 USDT = {rate:,} ل.س\n\n"
            "⚠️ تأكد من إرسال على شبكة ERC20 أو BEP20 فقط\n\n"
            "❗️ أدخل قيمة الشحن بالدولار (USDT):"
        )
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=cancel_keyboard())

    elif query.data == "back_to_menu":
        await query.message.reply_text("👋 عدنا للقائمة الرئيسية:", reply_markup=main_menu(user_id))

async def withdraw_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data.startswith("wd_"):
        method_names = {
            "wd_syriatel": "Syriatel Cash",
            "wd_sham": "Sham Cash",
            "wd_usdt": "USDT"
        }
        context.user_data["withdraw_method"] = method_names.get(query.data, query.data)
        context.user_data["withdraw_step"] = "amount"
        await query.edit_message_text(
            f"⚠️ تنبيه: يتم حسم 10% من المبلغ كرسوم سحب\n\n"
            f"مثال: إذا أدخلت 10,000 {CURRENCY_LABEL} → ستستلم 9,000 {CURRENCY_LABEL}\n\n"
            f"💰 أرسل مبلغ السحب بالليرة السورية:"
        )
        await query.message.reply_text("👇 أدخل المبلغ:", reply_markup=cancel_keyboard())

    elif query.data == "back_to_menu":
        await query.message.reply_text("👋 عدنا للقائمة الرئيسية:", reply_markup=main_menu(user_id))

async def admin_recharge_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("approve_"):
        parts = data.split("_")
        user_id = int(parts[1])
        amount = float(parts[2])

        recharges = get_user_recharges(user_id)
        method = recharges[0][1] if recharges else "غير محدد"

        bonus_key = _bonus_key_for_method(method)
        bonus = int(amount * get_bonus_percent(bonus_key)) if bonus_key else 0

        final_amount = amount + bonus

        update_balance(user_id, final_amount)

        # =====================================================
        # تفعيل الإحالة (حالة نشطة) + تسجيل عمولة الإحالة المستمرة
        # =====================================================
        activate_referral_after_recharge(referred_user_id=user_id, reward_amount=0)

        referrer_id = get_referrer(user_id)
        if referrer_id:
            commission_percent = get_referral_commission_percent()
            if commission_percent > 0:
                commission_amount = int(final_amount * commission_percent)
                if commission_amount > 0:
                    log_referral_commission(referrer_id, user_id, final_amount, commission_amount)

        update_recharge_status(user_id, amount, "approved")

        bonus_text = f"\n🎁 بونص: +{bonus:,} {CURRENCY_LABEL}" if bonus > 0 else ""
        await query.edit_message_text(
            f"✅ تم شحن رصيد البوت\n\n"
            f"👤 المستخدم: {user_id}\n"
            f"💰 المبلغ الأصلي: {amount:,} {CURRENCY_LABEL}{bonus_text}\n"
            f"💵 المجموع المضاف: {final_amount:,} {CURRENCY_LABEL}"
        )

        bonus_line = f"🎁 بونص {method}: +{bonus:,} {CURRENCY_LABEL}\n" if bonus > 0 else ""
        await context.bot.send_message(
            user_id,
            f"🎉 تم شحن رصيد البوت بنجاح!\n\n"
            f"💰 المبلغ الأصلي: {amount:,} {CURRENCY_LABEL}\n"
            f"{bonus_line}"
            f"💵 رصيدك داخل البوت: {final_amount:,} {CURRENCY_LABEL}\n"
            #f"🎮 ما يعادله بالإيشانسي: {ls_to_nsp(final_amount):.2f} {ICHANCY_CURRENCY}\n\n"
            f"⚡ يمكنك الآن شحن حساب iChancy من رصيد البوت"
        )

    elif data.startswith("reject_"):
        parts = data.split("_")
        user_id = int(parts[1])
        amount = float(parts[2])
        update_recharge_status(user_id, amount, "rejected")
        await query.edit_message_text(f"❌ تم رفض طلب الشحن للمستخدم {user_id}")
        await context.bot.send_message(
            user_id,
            "❌ تم رفض طلب الشحن الخاص بك\n"
            "تواصل مع الدعم إذا كان هناك خطأ"
        )
async def handle_callback_query(update, context):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # ==========================================
    # 💰 شحن كامل الرصيد
    # ==========================================
    if data == "ichancy_charge_all":

        user = get_user(user_id)

        if not user:
            await query.message.reply_text(
                "❌ لم يتم العثور على حسابك."
            )
            return

        balance = user["balance"]

        if balance <= 0:
            await query.message.reply_text(
                "❌ رصيدك في البوت غير كافي للشحن.",
                reply_markup=main_menu(user_id)
            )
            return

        ichancy_username = user.get("ichancy_username")

        if not ichancy_username:
            await query.message.reply_text(
                "❌ لا يوجد حساب Ichancy مربوط.\n"
                "أنشئ حساباً أولاً من القائمة.",
                reply_markup=main_menu(user_id)
            )
            return

        player = get_player_by_username(ichancy_username)

        if not player:
            await query.message.reply_text(
                "❌ فشل الوصول لحساب Ichancy، تواصل مع الدعم.",
                reply_markup=main_menu(user_id)
            )
            return

        await query.message.reply_text(
            f"⏳ جاري شحن كامل رصيدك...\n\n"
            f"💰 المبلغ: {balance:,} {CURRENCY_LABEL}"
        )

        # تحويل الليرة إلى NSP
        nsp_amount = ls_to_nsp(balance)

        # تنفيذ الشحن في Ichancy
        success = deposit_to_player(
            player.get("playerId"),
            nsp_amount,
            comment="Full balance charge from bot wallet"
        )

        if success:

            # خصم الرصيد فقط بعد نجاح الشحن
            update_balance(user_id, -balance)
            log_ichancy_transaction(user_id, "in", nsp_amount)

            await query.message.reply_text(
                f"✅ تم شحن كامل رصيدك بنجاح!\n\n"
                f"💰 المبلغ المشحون: {balance:,} {CURRENCY_LABEL}\n"
                f"💳 رصيد البوت المتبقي: 0 {CURRENCY_LABEL}",
                reply_markup=main_menu(user_id)
            )

        else:

            await query.message.reply_text(
                "❌ أقل قيمة للشحن هي 200 ل.س جديدة\n"
                "لم يتم خصم أي رصيد من حسابك.",
                reply_markup=main_menu(user_id)
            )

        return
    


    # ==========================================
    # ✏️ إدخال مبلغ محدد
    # ==========================================
    elif data == "ichancy_charge_custom":

        user = get_user(user_id)

        if not user:
            await query.message.reply_text(
                "❌ لم يتم العثور على حسابك."
            )
            return

        context.user_data["ichancy_charge"] = True

        await query.message.reply_text(
            f"💰 أدخل المبلغ بالليرة السورية الذي تريد شحنه:\n\n"
            f"💳 رصيدك الحالي: "
            f"{user['balance']:,} {CURRENCY_LABEL}",
            reply_markup=cancel_keyboard()
        )

        return


    # ==========================================
    # ❌ إلغاء شحن Ichancy
    # ==========================================
    elif data == "cancel_ichancy_charge":

        context.user_data["ichancy_charge"] = None
        context.user_data["ichancy_charge_amount"] = None

        await query.message.reply_text(
            "❌ تم إلغاء عملية الشحن.",
            reply_markup=main_menu(user_id)
        )

        return
    # ==================================================
    # 📤 سحب كامل رصيد Ichancy إلى البوت
    # ==================================================
    elif data == "ichancy_withdraw_all":

        user = get_user(user_id)

        if not user:
            await query.message.reply_text(
                "❌ لم يتم العثور على حسابك."
            )
            return

        ichancy_username = user.get("ichancy_username")

        if not ichancy_username:
            await query.message.reply_text(
                "❌ لا يوجد حساب Ichancy مربوط.",
                reply_markup=main_menu(user_id)
            )
            return

        player = get_player_by_username(ichancy_username)

        if not player:
            await query.message.reply_text(
                "❌ فشل الوصول إلى حساب Ichancy.",
                reply_markup=main_menu(user_id)
            )
            return

        player_id = player.get("playerId")

        if not player_id:
            await query.message.reply_text(
                "❌ لم يتم العثور على Player ID للحساب.",
                reply_markup=main_menu(user_id)
            )
            return

        # جلب الرصيد الحقيقي من Ichancy
        current_balance_nsp = get_player_balance(player_id)

        if current_balance_nsp is None:
            await query.message.reply_text(
                "❌ تعذر معرفة رصيد حساب Ichancy.",
                reply_markup=main_menu(user_id)
            )
            return

        if current_balance_nsp <= 0:
            await query.message.reply_text(
                "❌ لا يوجد رصيد متاح للسحب في حساب Ichancy.",
                reply_markup=main_menu(user_id)
            )
            return

        # تحويل NSP إلى الليرة السورية
        amount = nsp_to_ls(current_balance_nsp)

        if amount <= 0:
            await query.message.reply_text(
                "❌ الرصيد غير كافٍ للسحب.",
                reply_markup=main_menu(user_id)
            )
            return

        await query.message.reply_text(
            f"⏳ جاري سحب كامل رصيدك من Ichancy...\n\n"
            f"💰 المبلغ: {amount:,} {CURRENCY_LABEL}"
        )

        # تنفيذ السحب
        api_success = withdraw_from_player(
            player_id,
            current_balance_nsp,
            comment="Full balance withdrawal to bot wallet"
        )

        if not api_success:
            await query.message.reply_text(
                "❌ فشل السحب.\n"
                "لم تتم إضافة أي رصيد إلى البوت.",
                reply_markup=main_menu(user_id)
            )
            return

        # إضافة الرصيد للبوت بعد نجاح API فقط
        update_balance(user_id, amount)
        log_ichancy_transaction(user_id, "out", current_balance_nsp)

        updated_user = get_user(user_id)
        new_balance = updated_user.get("balance", 0)

        await query.message.reply_text(
            f"✅ تم سحب كامل رصيدك من Ichancy بنجاح!\n\n"
            f"💰 المبلغ المضاف لرصيد البوت: "
            f"{amount:,} {CURRENCY_LABEL}\n"
            f"💳 رصيدك الجديد في البوت: "
            f"{new_balance:,} {CURRENCY_LABEL}",
            reply_markup=main_menu(user_id)
        )

        return


    # ==================================================
    # ✏️ سحب مبلغ محدد
    # ==================================================
    elif data == "ichancy_withdraw_custom":

        user = get_user(user_id)

        if not user:
            await query.message.reply_text(
                "❌ لم يتم العثور على حسابك."
            )
            return

        context.user_data["ichancy_withdraw"] = True

        await query.message.reply_text(
            "💰 أدخل المبلغ بالليرة السورية الذي تريد "
            "سحبه من Ichancy إلى رصيد البوت:",
            reply_markup=cancel_keyboard()
        )

        return


    # ==================================================
    # ❌ إلغاء شحن Ichancy
    # ==================================================
    elif data == "cancel_ichancy_charge":

        context.user_data["ichancy_charge"] = None

        await query.message.reply_text(
            "❌ تم إلغاء عملية الشحن.",
            reply_markup=main_menu(user_id)
        )

        return


    # ==================================================
    # ❌ إلغاء سحب Ichancy
    # ==================================================
    elif data == "cancel_ichancy_withdraw":

        context.user_data["ichancy_withdraw"] = None

        await query.message.reply_text(
            "❌ تم إلغاء عملية السحب.",
            reply_markup=main_menu(user_id)
        )

        return

# ======================================================
# ✅ التعديل: معالج زر "تعديل المبلغ"
# ======================================================
async def admin_edit_amount_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    # callback_data: edit_amount_{user_id}_{original_amount}
    parts = query.data.split("_")
    target_user_id = int(parts[2])
    original_amount = float(parts[3])

    # حفظ الحالة في user_data الخاص بالأدمن
    context.user_data["admin_edit_step"] = "new_amount"
    context.user_data["admin_edit_target_user"] = target_user_id
    context.user_data["admin_edit_original_amount"] = original_amount

    await query.message.reply_text(
        f"✏️ تعديل مبلغ الشحن\n\n"
        f"👤 المستخدم: {target_user_id}\n"
        f"💰 المبلغ الذي أرسله: {original_amount}\n\n"
        f"أرسل المبلغ الجديد الذي تريد إضافته للمستخدم:"
    )

async def admin_withdraw_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("wdapprove_"):
        parts = data.split("_", 3)
        user_id = int(parts[1])
        amount = int(parts[2])
        account = parts[3]

        update_withdraw_status(user_id, amount, "approved")
        await query.edit_message_text(
            f"✅ تم تأكيد السحب\n\n"
            f"👤 المستخدم: {user_id}\n"
            f"💸 المبلغ: {amount:,} {CURRENCY_LABEL}\n"
            f"🏦 إلى: {account}"
        )
        await context.bot.send_message(user_id, f"✅ تم تنفيذ طلب السحب بنجاح!\n💸 المبلغ المحوّل: {amount:,} {CURRENCY_LABEL}")

    elif data.startswith("wdreject_"):
        parts = data.split("_", 3)
        user_id = int(parts[1])
        amount = int(parts[2])

        update_balance(user_id, amount)
        update_withdraw_status(user_id, amount, "rejected")
        await query.edit_message_text(f"❌ تم رفض طلب السحب للمستخدم {user_id}\n💰 تم إرجاع رصيده")
        await context.bot.send_message(
            user_id,
            "❌ تم رفض طلب السحب\n💰 تم إرجاع رصيدك كاملاً\nتواصل مع الدعم للمزيد"
        )

async def gift_admin_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("gift_accept"):
        parts = data.split("_")
        sender_id = int(parts[2])
        target_id = int(parts[3])
        amount = int(parts[4])

        update_balance(sender_id, -amount)
        update_balance(target_id, amount)

        await query.edit_message_text("✅ تم تنفيذ عملية الاهداء")
        await context.bot.send_message(sender_id, f"✅ تم اهداء {amount:,} {CURRENCY_LABEL} بنجاح")
        await context.bot.send_message(target_id, f"🎉 تم استلام {amount:,} {CURRENCY_LABEL} كهدية")

    elif data.startswith("gift_reject"):
        parts = data.split("_")
        sender_id = int(parts[2])
        await query.edit_message_text("❌ تم رفض طلب الإهداء")
        await context.bot.send_message(sender_id, "❌ تم رفض طلب الإهداء الخاص بك.")

async def faq_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    text = None

    if data == "faq_what":
        text = "🎮 *ما هو موقع Ichancy؟*\n\nIchancy هو موقع ألعاب أونلاين\nيمكنك الشحن، اللعب، والسحب."

    elif data == "faq_recharge":
        text = (
            "📥 *كيف أشحن رصيد البوت؟*\n\n"
            "1️⃣ اختر شحن رصيد\n"
            "2️⃣ اختر طريقة الدفع\n"
            "3️⃣ أرسل المبلغ ورقم العملية\n"
            "4️⃣ انتظر تأكيد الكاشيرة\n\n"
            "💡 ثم اشحن حساب iChancy من رصيد البوت"
        )

    elif data == "faq_withdraw":
        text = (
            "📤 *كيف أسحب رصيدي؟*\n\n"
            "1️⃣ اختر سحب رصيد\n"
            "2️⃣ أدخل المبلغ\n"
            "3️⃣ أدخل الحساب\n"
            "⚠️ يتم حسم 10% كرسوم سحب"
        )

    elif data == "faq_spin":
        text = "🎰 *اللفة المجانية*\n\n🔒 متاحة فقط بعد شحن الرصيد\n🎉 قد تربح رصيد مجاني"

    elif data == "faq_back":
        await query.edit_message_text("📚 *الأسئلة الشائعة*", reply_markup=faq_menu(), parse_mode="Markdown")
        return

    if text:
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع للأسئلة", callback_data="faq_back")]])
        )

async def history_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "history_recharge":
        recharges = get_user_recharges(user_id)
        if not recharges:
            await query.edit_message_text("❌ لا يوجد عمليات شحن بعد")
            return
        text = "📥 آخر عمليات الشحن:\n\n"
        for r in recharges:
            amount, method, txid, date = r
            text += f"💰 {amount}\n💳 {method}\n🔢 {txid}\n📅 {date}\n\n"
        await query.edit_message_text(text)

    elif query.data == "history_withdraw":
        withdraws = get_user_withdraws(user_id)
        if not withdraws:
            await query.edit_message_text("❌ لا يوجد عمليات سحب بعد")
            return
        text = "📤 آخر عمليات السحب:\n\n"
        for w in withdraws:
            amount, account, date = w
            text += f"💸 {amount}\n🪙 {account}\n📅 {date}\n\n"
        await query.edit_message_text(text)

async def ichancy_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "back_to_menu":
        await query.message.reply_text("👋 عدنا للقائمة الرئيسية:", reply_markup=main_menu(user_id))


async def admin_set_rate_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    context.user_data["admin_set_rate"] = True
    rate = get_usdt_rate()
    await query.message.reply_text(
        f"💱 سعر الصرف الحالي: 1 USDT = {rate:,} ل.س\n\n"
        f"أرسل السعر الجديد (بالليرة السورية):\n"
        f"مثال: 15000",
        reply_markup=cancel_keyboard()
    )


async def admin_bonus_menu_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    percents = get_all_bonus_percents()

    text = "🎁 نسب بونص الشحن الحالية:\n\n"
    for key, label in BONUS_METHOD_LABELS.items():
        text += f"{label}: {percents.get(key, 0.0) * 100:.1f}%\n"
    text += "\nاختر طريقة الشحن التي تريد تعديل نسبتها:"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✏️ {label}", callback_data=f"admin_set_bonus_{key}")]
        for key, label in BONUS_METHOD_LABELS.items()
    ] + [
        [InlineKeyboardButton("⬅️ رجوع للوحة التحكم", callback_data="admin_panel")]
    ])

    await query.edit_message_text(text, reply_markup=keyboard)


async def admin_set_bonus_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    key = query.data.replace("admin_set_bonus_", "")

    if key not in BONUS_METHOD_LABELS:
        return

    context.user_data["admin_set_bonus_key"] = key
    current = get_bonus_percent(key) * 100

    await query.message.reply_text(
        f"{BONUS_METHOD_LABELS[key]}\n"
        f"🎁 النسبة الحالية: {current:.1f}%\n\n"
        f"أرسل النسبة الجديدة (رقم فقط، مثال: 8 لتعني 8%):",
        reply_markup=cancel_keyboard()
    )


# ============================
# الاسترداد الأسبوعي (Cashback) — المنطق الأساسي
# ============================

async def process_weekly_cashback(bot):
    """
    ينفّذ جولة استرداد أسبوعي واحدة لكل المستخدمين الذين لديهم حساب
    iChancy مربوط، بناءً على نسبة من صافي خسارتهم في الكازينو خلال
    الفترة منذ آخر تنفيذ.

    صافي الخسارة = (الرصيد القديم في iChancy + كل ما تم شحنه للحساب
    خلال الفترة) - (الرصيد الحالي + كل ما تم سحبه خلال نفس الفترة).
    """

    percent = get_cashback_percent()

    if percent <= 0:
        return {"processed": 0, "paid": 0, "total_cashback": 0}

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    users = get_users_with_ichancy()

    processed = 0
    paid = 0
    total_cashback = 0

    for user_id, ichancy_username in users:

        processed += 1

        try:
            player = get_player_by_username(ichancy_username)
            if not player:
                continue

            player_id = player.get("playerId")
            if not player_id:
                continue

            current_balance_nsp = get_player_balance(player_id)
            if current_balance_nsp is None:
                continue

            # أول مرة فقط: تسجيل نقطة مرجعية بدون احتساب استرداد
            init_cashback_snapshot_if_missing(user_id, current_balance_nsp)
            snapshot = get_cashback_snapshot(user_id)

            last_balance_nsp = snapshot["last_balance_nsp"]
            period_start = snapshot["last_run_at"]

            deposits_nsp, withdrawals_nsp = get_ichancy_movement_since(user_id, period_start)

            net_loss_nsp = (last_balance_nsp + deposits_nsp) - (current_balance_nsp + withdrawals_nsp)

            if net_loss_nsp > 0:
                loss_amount = int(nsp_to_ls(net_loss_nsp))
                cashback_amount = int(loss_amount * percent)

                if cashback_amount > 0:
                    update_balance(user_id, cashback_amount)
                    record_cashback_payout(
                        user_id, loss_amount, cashback_amount,
                        period_start, now_str
                    )
                    paid += 1
                    total_cashback += cashback_amount

                    try:
                        await bot.send_message(
                            user_id,
                            "🎁 تم صرف استردادك الأسبوعي (Cashback)!\n\n"
                            f"📉 صافي خسارتك هذا الأسبوع: {loss_amount:,} {CURRENCY_LABEL}\n"
                            f"💸 نسبة الاسترداد: {percent * 100:.1f}%\n"
                            f"💰 المبلغ المسترد: {cashback_amount:,} {CURRENCY_LABEL}\n\n"
                            f"💳 رصيدك الحالي: {get_user_balance(user_id):,} {CURRENCY_LABEL}"
                        )
                    except Exception:
                        pass

            update_cashback_snapshot(user_id, current_balance_nsp)

        except Exception as e:
            print(f"⚠️ خطأ أثناء معالجة الاسترداد للمستخدم {user_id}: {e}")

    return {"processed": processed, "paid": paid, "total_cashback": total_cashback}


async def weekly_cashback_loop(application):
    """
    حلقة خلفية تعمل طوال عمر البوت وتُشغّل جولة الاسترداد الأسبوعي
    تلقائياً كل 7 أيام (بدون الحاجة لأي تدخل من الأدمن).
    """

    await asyncio.sleep(CASHBACK_INITIAL_DELAY_SECONDS)

    while True:
        try:
            result = await process_weekly_cashback(application.bot)
            if result["paid"] > 0:
                await notify_admins(
                    application.bot,
                    "💸 تم تنفيذ جولة الاسترداد الأسبوعي\n\n"
                    f"👥 تم فحص: {result['processed']} مستخدم\n"
                    f"✅ تم صرف استرداد لـ: {result['paid']} مستخدم\n"
                    f"💰 إجمالي المسترد: {result['total_cashback']:,} {CURRENCY_LABEL}"
                )
        except Exception as e:
            print(f"⚠️ خطأ أثناء تنفيذ جولة الاسترداد الأسبوعي: {e}")

        await asyncio.sleep(CASHBACK_INTERVAL_SECONDS)


async def admin_cashback_menu_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    percent = get_cashback_percent()

    text = (
        "💸 الاسترداد الأسبوعي (Cashback)\n\n"
        f"📊 النسبة الحالية: {percent * 100:.1f}%\n"
        "📌 الأساس: نسبة من صافي خسارة المستخدم في iChancy خلال الأسبوع\n"
        "🤖 الصرف: تلقائي بالكامل، كل 7 أيام\n\n"
        + ("⚠️ النسبة 0% حالياً، يعني النظام متوقف مؤقتاً.\n\n" if percent <= 0 else "")
        + "اختر إجراء:"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل النسبة", callback_data="admin_set_cashback_percent")],
        [InlineKeyboardButton("▶️ تنفيذ الاسترداد الآن", callback_data="admin_run_cashback_now")],
        [InlineKeyboardButton("📊 آخر العمليات", callback_data="admin_cashback_history")],
        [InlineKeyboardButton("⬅️ رجوع للوحة التحكم", callback_data="admin_panel")]
    ])

    await query.edit_message_text(text, reply_markup=keyboard)


async def admin_set_cashback_percent_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    context.user_data["admin_set_cashback_percent"] = True
    current = get_cashback_percent() * 100

    await query.message.reply_text(
        f"💸 نسبة الاسترداد الأسبوعي الحالية: {current:.1f}%\n\n"
        f"أرسل النسبة الجديدة (رقم فقط، مثال: 10 لتعني 10%):\n"
        f"أرسل 0 لإيقاف الاسترداد الأسبوعي.",
        reply_markup=cancel_keyboard()
    )


async def admin_run_cashback_now_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    await query.message.reply_text("⏳ جاري تنفيذ جولة الاسترداد الأسبوعي يدوياً...")

    result = await process_weekly_cashback(context.bot)

    await query.message.reply_text(
        "✅ انتهى التنفيذ اليدوي للاسترداد الأسبوعي\n\n"
        f"👥 تم فحص: {result['processed']} مستخدم\n"
        f"✅ تم صرف استرداد لـ: {result['paid']} مستخدم\n"
        f"💰 إجمالي المسترد: {result['total_cashback']:,} {CURRENCY_LABEL}"
    )


async def admin_cashback_history_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    payouts = get_recent_cashback_payouts(limit=15)

    if not payouts:
        await query.edit_message_text(
            "📊 لا يوجد أي عمليات استرداد منفذة بعد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_cashback_menu")]
            ])
        )
        return

    text = "📊 آخر عمليات الاسترداد الأسبوعي:\n\n"
    for p in payouts:
        text += (
            f"🆔 {p['user_id']} | "
            f"📉 خسارة: {p['loss_amount']:,} | "
            f"💰 استرداد: {p['cashback_amount']:,} {CURRENCY_LABEL}\n"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_cashback_menu")]
    ])

    await query.edit_message_text(text, reply_markup=keyboard)


# ============================
# عمولة الإحالة المستمرة (Referral Commission) — المنطق الأساسي
# ============================

async def process_referral_payouts(bot):
    """
    يفحص كل المُحيلين (referrers)، ولمن استحقت دورته (مرّ عدد أيام
    الدورة المحدد منذ آخر توزيع)، يصرف له كل العمولات المتراكمة
    غير المدفوعة دفعة واحدة، ثم يبدأ له دورة جديدة.
    """

    period_days = get_referral_period_days()

    if period_days <= 0:
        return {"checked": 0, "paid_count": 0, "total_paid": 0}

    now = datetime.utcnow()
    referrer_ids = get_all_referrer_ids()

    paid_count = 0
    total_paid = 0

    for referrer_id in referrer_ids:

        try:
            init_referral_cycle_if_missing(referrer_id)
            cycle_start_raw = get_referral_cycle_start(referrer_id)

            if not cycle_start_raw:
                continue

            cycle_start_dt = datetime.strptime(cycle_start_raw, "%Y-%m-%d %H:%M:%S")
            elapsed_days = (now - cycle_start_dt).total_seconds() / 86400

            if elapsed_days < period_days:
                continue

            pending = get_pending_commission_total(referrer_id)

            if pending > 0:
                update_balance(referrer_id, pending)
                mark_referral_commissions_paid(referrer_id)
                paid_count += 1
                total_paid += pending

                try:
                    await bot.send_message(
                        referrer_id,
                        "💰 تم توزيع أرباح الإحالة الخاصة بك!\n\n"
                        f"💵 المبلغ: {pending:,} {CURRENCY_LABEL}\n"
                        f"💳 رصيدك الحالي: {get_user_balance(referrer_id):,} {CURRENCY_LABEL}\n\n"
                        f"🔄 بدأت دورة أرباح جديدة مدتها {period_days} يوم/أيام."
                    )
                except Exception:
                    pass

            reset_referral_cycle(referrer_id)

        except Exception as e:
            print(f"⚠️ خطأ أثناء معالجة عمولة الإحالة للمستخدم {referrer_id}: {e}")

    return {"checked": len(referrer_ids), "paid_count": paid_count, "total_paid": total_paid}


async def referral_payout_loop(application):
    """
    حلقة خلفية تعمل طوال عمر البوت وتفحص دورياً أي المُحيلين استحقوا
    توزيع أرباح الإحالة، وتصرف لهم تلقائياً بدون أي تدخل من الأدمن.
    """

    await asyncio.sleep(REFERRAL_CHECK_INITIAL_DELAY_SECONDS)

    while True:
        try:
            result = await process_referral_payouts(application.bot)
            if result["paid_count"] > 0:
                await notify_admins(
                    application.bot,
                    "💰 تم تنفيذ جولة توزيع أرباح الإحالة\n\n"
                    f"👥 تم فحص: {result['checked']} محيل\n"
                    f"✅ تم الصرف لـ: {result['paid_count']} محيل\n"
                    f"💵 إجمالي الموزّع: {result['total_paid']:,} {CURRENCY_LABEL}"
                )
        except Exception as e:
            print(f"⚠️ خطأ أثناء تنفيذ جولة توزيع أرباح الإحالة: {e}")

        await asyncio.sleep(REFERRAL_CHECK_INTERVAL_SECONDS)


async def admin_referral_menu_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    percent = get_referral_commission_percent()
    period_days = get_referral_period_days()

    text = (
        "🎯 نظام الإحالة (عمولة مستمرة)\n\n"
        f"📊 نسبة العمولة: {percent * 100:.1f}%\n"
        f"⏱️ مدة دورة الأرباح: {period_days} يوم/أيام\n"
        "📌 الأساس: نسبة من كل عمليات شحن المُحالين\n"
        "🤖 الصرف: تلقائي بالكامل عند اكتمال كل دورة\n\n"
        + ("⚠️ النسبة 0% حالياً، يعني النظام متوقف مؤقتاً.\n\n" if percent <= 0 else "")
        + "اختر إجراء:"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل نسبة العمولة", callback_data="admin_set_referral_percent")],
        [InlineKeyboardButton("⏱️ تعديل مدة الدورة (أيام)", callback_data="admin_set_referral_period")],
        [InlineKeyboardButton("▶️ تنفيذ التوزيع الآن", callback_data="admin_run_referral_now")],
        [InlineKeyboardButton("📊 آخر العمليات", callback_data="admin_referral_history")],
        [InlineKeyboardButton("⬅️ رجوع للوحة التحكم", callback_data="admin_panel")]
    ])

    await query.edit_message_text(text, reply_markup=keyboard)


async def admin_set_referral_percent_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    context.user_data["admin_set_referral_percent"] = True
    current = get_referral_commission_percent() * 100

    await query.message.reply_text(
        f"🎯 نسبة عمولة الإحالة الحالية: {current:.1f}%\n\n"
        f"أرسل النسبة الجديدة (رقم فقط، مثال: 5 لتعني 5%):\n"
        f"أرسل 0 لإيقاف نظام العمولة.",
        reply_markup=cancel_keyboard()
    )


async def admin_set_referral_period_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    context.user_data["admin_set_referral_period"] = True
    current = get_referral_period_days()

    await query.message.reply_text(
        f"⏱️ مدة دورة الأرباح الحالية: {current} يوم/أيام\n\n"
        f"أرسل عدد الأيام الجديد (رقم صحيح، مثال: 10):",
        reply_markup=cancel_keyboard()
    )


async def admin_run_referral_now_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    await query.message.reply_text("⏳ جاري تنفيذ جولة توزيع أرباح الإحالة يدوياً...")

    result = await process_referral_payouts(context.bot)

    await query.message.reply_text(
        "✅ انتهى التنفيذ اليدوي لتوزيع أرباح الإحالة\n\n"
        f"👥 تم فحص: {result['checked']} محيل\n"
        f"✅ تم الصرف لـ: {result['paid_count']} محيل\n"
        f"💵 إجمالي الموزّع: {result['total_paid']:,} {CURRENCY_LABEL}"
    )


async def admin_referral_history_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    payouts = get_recent_referral_payouts(limit=15)

    if not payouts:
        await query.edit_message_text(
            "📊 لا يوجد أي عمليات توزيع أرباح إحالة منفذة بعد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_referral_menu")]
            ])
        )
        return

    text = "📊 آخر عمليات توزيع أرباح الإحالة:\n\n"
    for p in payouts:
        text += (
            f"🆔 {p['referrer_id']} | "
            f"💰 {p['total']:,} {CURRENCY_LABEL}\n"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ رجوع", callback_data="admin_referral_menu")]
    ])

    await query.edit_message_text(text, reply_markup=keyboard)


# ============================
# إدارة عجلة الحظ (Spin Wheel Admin)
# ============================

async def _render_admin_spin_menu(query):
    cooldown_hours = get_spin_cooldown_hours()
    prizes = get_all_spin_prizes()

    text = (
        "🎡 إدارة عجلة الحظ\n\n"
        f"⏱️ مدة الانتظار بين اللفات: {cooldown_hours} ساعة\n\n"
        "🎁 الجوائز الحالية:\n\n"
    )

    keyboard_rows = []

    if not prizes:
        text += "لا توجد جوائز حالياً."
    else:
        for i, p in enumerate(prizes, 1):
            status_icon = "✅" if p["active"] else "⛔"
            extra = f" — {p['amount']:,} {CURRENCY_LABEL}" if p["prize_type"] == "cash" else ""
            text += f"{i}. {status_icon} {p['label']}{extra} (وزن: {p['weight']})\n"

            toggle_label = f"⛔ تعطيل #{i}" if p["active"] else f"✅ تفعيل #{i}"
            keyboard_rows.append([
                InlineKeyboardButton(toggle_label, callback_data=f"admin_spin_toggle_{p['id']}"),
                InlineKeyboardButton(f"⚖️ وزن #{i}", callback_data=f"admin_spin_editweight_{p['id']}"),
                InlineKeyboardButton(f"🗑️ حذف #{i}", callback_data=f"admin_spin_delete_{p['id']}")
            ])

    keyboard_rows.append([InlineKeyboardButton("➕ إضافة جائزة جديدة", callback_data="admin_spin_add")])
    keyboard_rows.append([InlineKeyboardButton("⏱️ تعديل مدة الانتظار", callback_data="admin_set_spin_cooldown")])
    keyboard_rows.append([InlineKeyboardButton("⬅️ رجوع للوحة التحكم", callback_data="admin_panel")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard_rows))


async def admin_spin_menu_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    await _render_admin_spin_menu(query)


async def admin_spin_toggle_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    prize_id = int(query.data.replace("admin_spin_toggle_", ""))
    prize = get_spin_prize(prize_id)

    if prize:
        set_spin_prize_active(prize_id, not prize["active"])

    await _render_admin_spin_menu(query)


async def admin_spin_delete_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    prize_id = int(query.data.replace("admin_spin_delete_", ""))
    delete_spin_prize(prize_id)

    await _render_admin_spin_menu(query)


async def admin_spin_editweight_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    prize_id = int(query.data.replace("admin_spin_editweight_", ""))
    prize = get_spin_prize(prize_id)

    if not prize:
        await query.answer("❌ الجائزة غير موجودة", show_alert=True)
        return

    context.user_data["admin_spin_edit_weight_id"] = prize_id

    await query.message.reply_text(
        f"⚖️ تعديل وزن الجائزة: {prize['label']}\n\n"
        f"الوزن الحالي: {prize['weight']}\n\n"
        f"أرسل الوزن الجديد (رقم صحيح أكبر من صفر — كلما زاد الرقم زادت فرصة الربح بها):",
        reply_markup=cancel_keyboard()
    )


async def admin_spin_add_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    context.user_data["admin_spin_add_step"] = "label"

    await query.message.reply_text(
        "➕ إضافة جائزة جديدة لعجلة الحظ\n\n"
        "1️⃣ أرسل الآن نص الجائزة كما سيظهر على العجلة (مثال: 💰 5,000 ل.س):\n"
        "💡 يفضّل نص قصير (كلمة أو كلمتين) حتى يظهر مرتب على العجلة.",
        reply_markup=cancel_keyboard()
    )


async def admin_spin_type_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    prize_type = query.data.replace("admin_spin_type_", "")
    context.user_data["admin_spin_new_type"] = prize_type

    if prize_type == "cash":
        context.user_data["admin_spin_add_step"] = "amount"
        await query.message.reply_text(
            "3️⃣ أرسل المبلغ (رقم صحيح، مثال: 5000):",
            reply_markup=cancel_keyboard()
        )
    else:
        context.user_data["admin_spin_new_amount"] = 0
        context.user_data["admin_spin_add_step"] = "weight"
        await query.message.reply_text(
            "3️⃣ أرسل وزن الجائزة (رقم صحيح — كلما زاد الرقم زادت فرصة الربح بها، مثال: 10):",
            reply_markup=cancel_keyboard()
        )


async def admin_set_spin_cooldown_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    context.user_data["admin_set_spin_cooldown"] = True
    current = get_spin_cooldown_hours()

    await query.message.reply_text(
        f"⏱️ مدة الانتظار الحالية: {current} ساعة\n\n"
        f"أرسل عدد الساعات الجديد (رقم صحيح، مثال: 24):",
        reply_markup=cancel_keyboard()
    )

# ============================
# معالج الرسائل الرئيسي
# ============================
async def admin_users_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    page = int(query.data.split("_")[-1])
    page_size = 10

    users = get_all_users()
    total = len(users)

    if total == 0:
        await query.edit_message_text("❌ لا يوجد مستخدمين بعد")
        return

    total_balance = sum(u[1] for u in users)
    start = (page - 1) * page_size
    end = start + page_size
    page_users = users[start:end]
    total_pages = (total + page_size - 1) // page_size

    text = f"👥 مستخدمو البوت — صفحة {page}/{total_pages}\n"
    text += f"📊 الإجمالي: {total} مستخدم | 💰 مجموع الأرصدة: {total_balance:,} {CURRENCY_LABEL}\n"
    text += "─" * 30 + "\n\n"

    for i, (uid, balance, ichancy_username) in enumerate(page_users, start=start + 1):
        ichancy = ichancy_username or "❌ لا يوجد"
        text += f"{i}. 🆔 `{uid}`\n"
        text += f"   💰 الرصيد: {balance:,} {CURRENCY_LABEL}\n"
        text += f"   🎮 iChancy: {ichancy}\n\n"

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("◀️ السابق", callback_data=f"admin_users_{page - 1}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("التالي ▶️", callback_data=f"admin_users_{page + 1}"))

    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🔄 تحديث", callback_data=f"admin_users_{page}")])
    keyboard.append([InlineKeyboardButton("⬅️ رجوع للوحة التحكم", callback_data="admin_panel")])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def ichancy_players_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    page_size = 10
    offset = int(query.data.split("_")[-1])

    await query.edit_message_text("⏳ جاري جلب البيانات من iChancy...")

    players = get_all_players(start=offset, limit=page_size)

    if not players:
        await query.edit_message_text("❌ فشل الاتصال بـ iChancy API")
        return

    if len(players) == 0 and offset == 0:
        await query.edit_message_text("❌ لا يوجد لاعبون في الكاشيرة بعد")
        return

    text = f"🎮 لاعبو iChancy\n"
    text += f"📋 يعرض {offset + 1} – {offset + len(players)}\n"
    text += "─" * 30 + "\n\n"

    for i, player in enumerate(players, start=offset + 1):
        login   = player.get("login", "—")
        balance = player.get("balance", 0)
        text += f"{i}. 🎮 `{login}`\n"
        text += f"   💰 {balance} NSP\n\n"

    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ السابق", callback_data=f"ichancy_players_{offset - page_size}"))
    if len(players) == page_size:
        nav_buttons.append(InlineKeyboardButton("التالي ▶️", callback_data=f"ichancy_players_{offset + page_size}"))

    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🔄 تحديث", callback_data=f"ichancy_players_{offset}")])
    keyboard.append([InlineKeyboardButton("⬅️ رجوع للوحة التحكم", callback_data="admin_panel")])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_panel_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    rate = get_usdt_rate()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 مستخدمو البوت",
                callback_data="admin_users_1"
            )
        ],
        [
            InlineKeyboardButton(
                "🎮 لاعبو iChancy",
                callback_data="ichancy_players_0"
            )
        ],
        [
            InlineKeyboardButton(
                f"💱 سعر الصرف: 1 USDT = {rate:,} ل.س",
                callback_data="admin_set_rate"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 نسب بونص الشحن",
                callback_data="admin_bonus_menu"
            )
        ],
        [
            InlineKeyboardButton(
                "💸 الاسترداد الأسبوعي (Cashback)",
                callback_data="admin_cashback_menu"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 عمولة نظام الإحالة",
                callback_data="admin_referral_menu"
            )
        ],
        [
            InlineKeyboardButton(
                "🎡 إدارة عجلة الحظ",
                callback_data="admin_spin_menu"
            )
        ],
        [
            InlineKeyboardButton(
                "💎إنشاء كود هدية",
                callback_data="admin_create_gift"
            )
        ]
    ])

    await query.edit_message_text(
        "🛠️ لوحة تحكم الأدمن",
        reply_markup=keyboard
    )


async def menu_handler(update, context):
    user_id = update.effective_user.id
    text = update.message.text
    

    # ============================
    # ✅ زر التراجع — يعمل في أي مرحلة
    # ============================
    if text == "❌ تراجع عن العملية":
        context.user_data.clear()
        await update.message.reply_text(
            "↩️ تم إلغاء العملية والرجوع للقائمة الرئيسية",
            reply_markup=main_menu(user_id)
        )
        return

    # ======================================================
    # 🛡️ شبكة أمان عامة: إذا كان في عملية معلّقة (البوت بانتظار
    # رقم أو نص معيّن من الأدمن/المستخدم) وضغط بدل هيك على أي زر
    # حقيقي من القائمة، نعتبرها إلغاء ضمني للعملية المعلّقة ونكمل
    # تنفيذ الزر الجديد عادي — بدل ما يضل البوت طالب نفس القيمة
    # إلى الأبد.
    # ======================================================
    KNOWN_MENU_TEXTS = {
        "🧾  حساب Ichancy", "💰 اعرف رصيدي",
        "📥 شحن رصيد", "📤 سحب رصيد",
        "شحن حسابي ichancy من رصيد البوت", "سحب من حسابي ichancy لرصيد البوت",
        "🎁 إهداء رصيد", "🤝نظام الإحالات",
        "💎كود هدية", "🎰 اللفة المجانية",
        "✉️ رسالة للإدمن", "📞 تواصل معنا",
        "📜 السجل", "☁️ الشروحات",
        "📱 ichancy apk", "📌 الشروط والأحكام",
        "🛠️ لوحة تحكم الأدمن",
    }

    if context.user_data and text in KNOWN_MENU_TEXTS:
        context.user_data.clear()

    # ======================================================
    # ✅ التعديل: استقبال المبلغ الجديد من الأدمن
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_set_rate"):

        if not text.isdigit():
            await update.message.reply_text(
                "❌ السعر يجب أن يكون رقماً فقط.\n\n"
                "مثال:\n"
                "15000"
            )
            return

        new_rate = int(text)

        if new_rate <= 0:
            await update.message.reply_text(
                "❌ يجب أن يكون سعر الصرف أكبر من صفر."
            )
            return

        # حفظ السعر الجديد في قاعدة البيانات
        set_usdt_rate(new_rate)

        # حذف حالة تعديل السعر
        context.user_data.pop("admin_set_rate", None)

        await update.message.reply_text(
            f"✅ تم تحديث سعر الصرف بنجاح!\n\n"
            f"💱 السعر الجديد:\n"
            f"1 USDT = {new_rate:,} ل.س",
            reply_markup=main_menu(user_id)
        )

        return

    # ======================================================
    # 🎁 تعديل نسبة بونص إحدى طرق الشحن
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_set_bonus_key"):

        bonus_key = context.user_data["admin_set_bonus_key"]

        try:
            new_percent = float(text.replace("%", "").strip())
        except ValueError:
            await update.message.reply_text(
                "❌ أرسل رقماً فقط (مثال: 8 لتعني 8%)."
            )
            return

        if new_percent < 0 or new_percent > 100:
            await update.message.reply_text(
                "❌ النسبة يجب أن تكون بين 0 و 100."
            )
            return

        set_bonus_percent(bonus_key, new_percent / 100)
        context.user_data.pop("admin_set_bonus_key", None)

        await update.message.reply_text(
            f"✅ تم تحديث نسبة البونص بنجاح!\n\n"
            f"{BONUS_METHOD_LABELS.get(bonus_key, bonus_key)}\n"
            f"🎁 النسبة الجديدة: {new_percent:.1f}%",
            reply_markup=main_menu(user_id)
        )

        return

    # ======================================================
    # 💸 تعديل نسبة الاسترداد الأسبوعي (Cashback)
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_set_cashback_percent"):

        try:
            new_percent = float(text.replace("%", "").strip())
        except ValueError:
            await update.message.reply_text(
                "❌ أرسل رقماً فقط (مثال: 10 لتعني 10%)."
            )
            return

        if new_percent < 0 or new_percent > 100:
            await update.message.reply_text(
                "❌ النسبة يجب أن تكون بين 0 و 100."
            )
            return

        set_cashback_percent(new_percent / 100)
        context.user_data.pop("admin_set_cashback_percent", None)

        status = "✅ تم تفعيل الاسترداد الأسبوعي" if new_percent > 0 else "⏸️ تم إيقاف الاسترداد الأسبوعي"

        await update.message.reply_text(
            f"{status}\n\n"
            f"💸 النسبة الجديدة: {new_percent:.1f}%",
            reply_markup=main_menu(user_id)
        )

        return

    # ======================================================
    # 🎯 تعديل نسبة عمولة الإحالة
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_set_referral_percent"):

        try:
            new_percent = float(text.replace("%", "").strip())
        except ValueError:
            await update.message.reply_text(
                "❌ أرسل رقماً فقط (مثال: 5 لتعني 5%)."
            )
            return

        if new_percent < 0 or new_percent > 100:
            await update.message.reply_text(
                "❌ النسبة يجب أن تكون بين 0 و 100."
            )
            return

        set_referral_commission_percent(new_percent / 100)
        context.user_data.pop("admin_set_referral_percent", None)

        status = "✅ تم تفعيل عمولة الإحالة" if new_percent > 0 else "⏸️ تم إيقاف عمولة الإحالة"

        await update.message.reply_text(
            f"{status}\n\n"
            f"🎯 النسبة الجديدة: {new_percent:.1f}%",
            reply_markup=main_menu(user_id)
        )

        return

    # ======================================================
    # ⏱️ تعديل مدة دورة أرباح الإحالة
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_set_referral_period"):

        if not text.strip().isdigit():
            await update.message.reply_text(
                "❌ أرسل رقماً صحيحاً فقط (عدد الأيام، مثال: 10)."
            )
            return

        new_days = int(text.strip())

        if new_days <= 0 or new_days > 365:
            await update.message.reply_text(
                "❌ عدد الأيام يجب أن يكون بين 1 و 365."
            )
            return

        set_referral_period_days(new_days)
        context.user_data.pop("admin_set_referral_period", None)

        await update.message.reply_text(
            f"✅ تم تحديث مدة دورة الأرباح بنجاح!\n\n"
            f"⏱️ المدة الجديدة: {new_days} يوم/أيام",
            reply_markup=main_menu(user_id)
        )

        return

    # ======================================================
    # ⏱️ تعديل مدة الانتظار بين لفات عجلة الحظ
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_set_spin_cooldown"):

        if not text.strip().isdigit():
            await update.message.reply_text(
                "❌ أرسل رقماً صحيحاً فقط (عدد الساعات، مثال: 24)."
            )
            return

        hours = int(text.strip())

        if hours <= 0 or hours > 720:
            await update.message.reply_text(
                "❌ عدد الساعات يجب أن يكون بين 1 و 720."
            )
            return

        set_spin_cooldown_hours(hours)
        context.user_data.pop("admin_set_spin_cooldown", None)

        await update.message.reply_text(
            f"✅ تم تحديث مدة الانتظار بنجاح!\n\n"
            f"⏱️ المدة الجديدة: {hours} ساعة",
            reply_markup=main_menu(user_id)
        )

        return

    # ======================================================
    # ➕ إضافة جائزة جديدة لعجلة الحظ — المرحلة 1: النص
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_spin_add_step") == "label":

        label = text.strip()

        if not label:
            await update.message.reply_text("❌ الرجاء إرسال نص صحيح.")
            return

        context.user_data["admin_spin_new_label"] = label
        context.user_data["admin_spin_add_step"] = "type"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 مبلغ نقدي", callback_data="admin_spin_type_cash")],
            [InlineKeyboardButton("🔄 لفة إضافية مجانية", callback_data="admin_spin_type_respin")],
            [InlineKeyboardButton("😔 بلا جائزة (حظ أوفر)", callback_data="admin_spin_type_none")],
        ])

        await update.message.reply_text("2️⃣ اختر نوع الجائزة:", reply_markup=keyboard)
        return

    # ======================================================
    # ➕ إضافة جائزة جديدة لعجلة الحظ — المرحلة 2: المبلغ (نقدي فقط)
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_spin_add_step") == "amount":

        if not text.strip().isdigit():
            await update.message.reply_text("❌ أرسل رقماً صحيحاً فقط.")
            return

        context.user_data["admin_spin_new_amount"] = int(text.strip())
        context.user_data["admin_spin_add_step"] = "weight"

        await update.message.reply_text(
            "4️⃣ أرسل وزن الجائزة (رقم صحيح — كلما زاد الرقم زادت فرصة الربح بها، مثال: 10):",
            reply_markup=cancel_keyboard()
        )
        return

    # ======================================================
    # ➕ إضافة جائزة جديدة لعجلة الحظ — المرحلة 3: الوزن (الحفظ)
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_spin_add_step") == "weight":

        if not text.strip().isdigit() or int(text.strip()) <= 0:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً أكبر من صفر.")
            return

        weight = int(text.strip())
        label = context.user_data.get("admin_spin_new_label", "جائزة")
        prize_type = context.user_data.get("admin_spin_new_type", "none")
        amount = context.user_data.get("admin_spin_new_amount", 0)

        add_spin_prize(label, prize_type, amount, weight)

        context.user_data.pop("admin_spin_add_step", None)
        context.user_data.pop("admin_spin_new_label", None)
        context.user_data.pop("admin_spin_new_type", None)
        context.user_data.pop("admin_spin_new_amount", None)

        await update.message.reply_text(
            f"✅ تمت إضافة الجائزة بنجاح!\n\n🎁 {label}\n⚖️ الوزن: {weight}",
            reply_markup=main_menu(user_id)
        )
        return

    # ======================================================
    # ⚖️ تعديل وزن جائزة موجودة على عجلة الحظ
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_spin_edit_weight_id"):

        if not text.strip().isdigit() or int(text.strip()) <= 0:
            await update.message.reply_text("❌ أرسل رقماً صحيحاً أكبر من صفر.")
            return

        prize_id = context.user_data["admin_spin_edit_weight_id"]
        new_weight = int(text.strip())

        update_spin_prize_weight(prize_id, new_weight)
        context.user_data.pop("admin_spin_edit_weight_id", None)

        await update.message.reply_text(
            f"✅ تم تحديث الوزن بنجاح!\n\n⚖️ الوزن الجديد: {new_weight}",
            reply_markup=main_menu(user_id)
        )
        return

        # ======================================================
# 🎁 إنشاء كود هدية - المرحلة الأولى: قيمة الهدية
# ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("gift_admin_step") == "amount":

        if not text.isdigit():
            await update.message.reply_text(
                "❌ قيمة الهدية يجب أن تكون رقماً فقط.\n\n"
                "مثال:\n"
                "5000"
            )
            return

        amount = int(text)

        if amount <= 0:
            await update.message.reply_text(
                "❌ قيمة الهدية يجب أن تكون أكبر من صفر."
            )
            return

        context.user_data["gift_amount"] = amount
        context.user_data["gift_admin_step"] = "uses"

        await update.message.reply_text(
            f"🎁 قيمة الهدية: {amount:,} {CURRENCY_LABEL}\n\n"
            "🔢 الآن أرسل عدد مرات استخدام الكود:\n\n"
            "مثال:\n"
            "1 = شخص واحد\n"
            "10 = عشرة أشخاص\n"
            "100 = مئة شخص"
        )

        return


# ======================================================
# 🎁 إنشاء كود هدية - المرحلة الثانية: عدد الاستخدامات
# ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("gift_admin_step") == "uses":
 
        if not text.isdigit():
            await update.message.reply_text(
                "❌ عدد الاستخدامات يجب أن يكون رقماً فقط."
            )
            return

        max_uses = int(text)

        if max_uses <= 0:
            await update.message.reply_text(
                "❌ عدد الاستخدامات يجب أن يكون أكبر من صفر."
            )
            return

        amount = context.user_data.get("gift_amount")

        if not amount:
            context.user_data.clear()

            await update.message.reply_text(
                "❌ حدث خطأ، أعد إنشاء الكود من جديد.",
                reply_markup=main_menu(user_id)
            )
            return

    # إنشاء كود عشوائي
        code = generate_gift_code()

    # حفظ الكود في قاعدة البيانات
        created = create_gift_code(
            code=code,
            amount=amount,
            max_uses=max_uses,
            created_by=user_id
        )

        if not created:
            context.user_data.clear()

            await update.message.reply_text(
                "❌ حدث خطأ أثناء إنشاء كود الهدية.",
                reply_markup=main_menu(user_id)
            )
            return

        context.user_data.pop("gift_admin_step", None)
        context.user_data.pop("gift_amount", None)

        await update.message.reply_text(
            "🎉 تم إنشاء كود الهدية بنجاح!\n\n"
            f"🎁 الكود:\n"
            f"`{code}`\n\n"
            f"💰 قيمة الهدية: {amount:,} {CURRENCY_LABEL}\n"
            f"🔢 عدد الاستخدامات: {max_uses}\n"
            f"📊 الاستخدامات الحالية: 0/{max_uses}\n\n"
            "📌 أرسل هذا الكود للزبائن.",
            parse_mode="Markdown",
            reply_markup=main_menu(user_id)
        )

        return
        # ======================================================
    # تعديل مبلغ الشحن من الأدمن
    # ======================================================
    if user_id in ADMIN_IDS and context.user_data.get("admin_edit_step") == "new_amount":

        if not text.isdigit():
            await update.message.reply_text(
                "❌ أرسل رقم فقط، حاول مجدداً:"
            )
            return

        new_amount = int(text)

        if new_amount <= 0:
            await update.message.reply_text(
                "❌ المبلغ يجب أن يكون أكبر من صفر."
            )
            return

        # جلب بيانات عملية التعديل
        target_user_id = context.user_data.get("admin_edit_target_user")
        original_amount = context.user_data.get("admin_edit_original_amount")

        # حماية من فقدان البيانات
        if target_user_id is None or original_amount is None:
            context.user_data.pop("admin_edit_step", None)
            context.user_data.pop("admin_edit_target_user", None)
            context.user_data.pop("admin_edit_original_amount", None)

            await update.message.reply_text(
                "❌ حدث خطأ: لم يتم العثور على بيانات عملية الشحن.\n"
                "يرجى إعادة العملية من البداية.",
                reply_markup=main_menu(user_id)
            )
            return

        target_user_id = int(target_user_id)
        original_amount = int(original_amount)

        # ==========================================
        # معرفة طريقة الدفع
        # ==========================================
        recharges = get_user_recharges(target_user_id)
        method = recharges[0][1] if recharges else "غير محدد"

        # ==========================================
        # حساب البونص
        # ==========================================
        bonus_key = _bonus_key_for_method(method)
        bonus = int(new_amount * get_bonus_percent(bonus_key)) if bonus_key else 0

        final_amount = new_amount + bonus

        # ==========================================
        # إضافة الرصيد للمستخدم
        # ==========================================
        update_balance(
            target_user_id,
            final_amount
        )

        # ==========================================
        # اعتماد عملية الشحن
        # ==========================================
        update_recharge_status(
            target_user_id,
            original_amount,
            "approved"
        )

        # ==========================================
        # تفعيل الإحالة (حالة نشطة) + تسجيل عمولة الإحالة المستمرة
        # ==========================================
        activate_referral_after_recharge(
            referred_user_id=target_user_id,
            reward_amount=0
        )

        referrer_id = get_referrer(target_user_id)
        if referrer_id:
            commission_percent = get_referral_commission_percent()
            if commission_percent > 0:
                commission_amount = int(final_amount * commission_percent)
                if commission_amount > 0:
                    log_referral_commission(referrer_id, target_user_id, final_amount, commission_amount)

        # ==========================================
        # تجهيز رسالة البونص
        # ==========================================
        bonus_text = (
            f"\n🎁 بونص: +{bonus:,} {CURRENCY_LABEL}"
            if bonus > 0
            else ""
        )

        # ==========================================
        # رسالة للأدمن
        # ==========================================
        await update.message.reply_text(
            f"✅ تم شحن الرصيد بالمبلغ المعدّل\n\n"
            f"👤 المستخدم: {target_user_id}\n"
            f"💰 المبلغ الأصلي: "
            f"{original_amount:,} {CURRENCY_LABEL}\n"
            f"✏️ المبلغ المعدّل: "
            f"{new_amount:,} {CURRENCY_LABEL}"
            f"{bonus_text}\n"
            f"💵 المجموع المضاف للمستخدم: "
            f"{final_amount:,} {CURRENCY_LABEL}",
            reply_markup=main_menu(user_id)
        )

        # ==========================================
        # رسالة للمستخدم
        # ==========================================
        bonus_line = (
            f"🎁 بونص: +{bonus:,} {CURRENCY_LABEL}\n"
            if bonus > 0
            else ""
        )

        try:
            await context.bot.send_message(
                target_user_id,
                f"🎉 تم شحن رصيد البوت بنجاح!\n\n"
                f"💰 المبلغ المضاف: "
                f"{new_amount:,} {CURRENCY_LABEL}\n"
                f"{bonus_line}"
                f"💵 الإجمالي المضاف لرصيدك: "
                f"{final_amount:,} {CURRENCY_LABEL}\n\n"
                f"⚡ يمكنك الآن شحن حساب iChancy من رصيد البوت"
            )
        except Exception:
            pass

        # ==========================================
        # تنظيف حالة التعديل بعد انتهاء العملية
        # ==========================================
        context.user_data.pop("admin_edit_step", None)
        context.user_data.pop("admin_edit_target_user", None)
        context.user_data.pop("admin_edit_original_amount", None)

        return

    # ============================
    # زر لوحة تحكم الأدمن
    # ============================
    if text == "🛠️ لوحة تحكم الأدمن":
        if user_id not in ADMIN_IDS:
            return

        rate = get_usdt_rate()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👥 مستخدمو البوت",
                    callback_data="admin_users_1"
                )
            ],
            [
                InlineKeyboardButton(
                    "🎮 لاعبو iChancy",
                    callback_data="ichancy_players_0"
                )
            ],
            [
                InlineKeyboardButton(
                    f"💱 سعر الصرف: 1 USDT = {rate:,} ل.س",
                    callback_data="admin_set_rate"
                )
            ],
            [
                InlineKeyboardButton(
                    "🎁 نسب بونص الشحن",
                    callback_data="admin_bonus_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    "💸 الاسترداد الأسبوعي (Cashback)",
                    callback_data="admin_cashback_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    "🎯 عمولة نظام الإحالة",
                    callback_data="admin_referral_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    "🎡 إدارة عجلة الحظ",
                    callback_data="admin_spin_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    "💎إنشاء كود هدية",
                    callback_data="admin_create_gift"
                )
            ]
        ])

        await update.message.reply_text(
            "🛠️ لوحة تحكم الأدمن",
            reply_markup=keyboard
        )

        return
    # ============================
    # شحن iChancy من رصيد البوت
    # ============================
    if text == "شحن حسابي ichancy من رصيد البوت":

        context.user_data["ichancy_charge"] = True

        user = get_user(user_id)
        balance = user["balance"]

        keyboard = [
           [
               InlineKeyboardButton(
                    "💰 شحن كامل الرصيد",
                    callback_data="ichancy_charge_all"
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ إدخال مبلغ محدد",
                    callback_data="ichancy_charge_custom"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ إلغاء",
                    callback_data="cancel_ichancy_charge"
                )
            ]
        ]

        await update.message.reply_text(
            f"💰 اختر طريقة الشحن:\n\n"
            f"رصيدك الحالي: {balance:,} {CURRENCY_LABEL}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    elif context.user_data.get("ichancy_charge"):
        if not text.isdigit():
            await update.message.reply_text("❌ أرسل رقم فقط", reply_markup=cancel_keyboard())
            return

        amount = int(text)
        context.user_data["ichancy_charge"] = None
        user = get_user(user_id)

        if amount > user["balance"]:
            await update.message.reply_text("❌ رصيدك داخل البوت غير كافي", reply_markup=main_menu(user_id))
            return

        ichancy_username = user.get("ichancy_username")
        if not ichancy_username:
            await update.message.reply_text("❌ لا يوجد حساب Ichancy مربوط\nأنشئ حساباً أولاً من القائمة", reply_markup=main_menu(user_id))
            return

        player = get_player_by_username(ichancy_username)
        if not player:
            await update.message.reply_text("❌ فشل الوصول لحساب Ichancy، تواصل مع الدعم", reply_markup=main_menu(user_id))
            return

        await update.message.reply_text("⏳ جاري شحن حسابك...", reply_markup=main_menu(user_id))

        nsp_amount = ls_to_nsp(amount)
        success = deposit_to_player(player.get("playerId"), nsp_amount, comment="Charge from bot wallet")

        if success:
            update_balance(user_id, -amount)
            log_ichancy_transaction(user_id, "in", nsp_amount)
            await update.message.reply_text(
                f"✅ تم شحن حسابك في Ichancy بنجاح!\n"
                f"💰 المبلغ المشحون: {amount:,} {CURRENCY_LABEL}\n"
                f"💳 رصيد البوت المتبقي: {user['balance'] - amount:,} {CURRENCY_LABEL}"
            )
        else:
            await update.message.reply_text("❌ فشل الشحن، تواصل مع الدعم")
        return

    # ============================
    # سحب من iChancy إلى رصيد البوت
    # ============================
    if text == "سحب من حسابي ichancy لرصيد البوت":

        context.user_data["ichancy_withdraw"] = True

        keyboard = [
            [
                InlineKeyboardButton(
                    "📤 سحب كامل الرصيد",
                    callback_data="ichancy_withdraw_all"
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ إدخال مبلغ محدد",
                    callback_data="ichancy_withdraw_custom"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ إلغاء",
                    callback_data="cancel_ichancy_withdraw"
                )
            ]
        ]

        await update.message.reply_text( 
                "📤 اختر طريقة السحب:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return


    elif context.user_data.get("ichancy_withdraw"):

        if not text.isdigit():
            await update.message.reply_text(
                "❌ أرسل رقم فقط",
                reply_markup=cancel_keyboard()
            )
            return

        amount = int(text)

        if amount <= 0:
            await update.message.reply_text(
                "❌ يجب أن يكون المبلغ أكبر من صفر",
                reply_markup=cancel_keyboard()
            )
            return

        context.user_data["ichancy_withdraw"] = None

        user = get_user(user_id)
        ichancy_username = user.get("ichancy_username")

        if not ichancy_username:
            await update.message.reply_text(
                "❌ لا يوجد حساب Ichancy مربوط",
                reply_markup=main_menu(user_id)
            )
            return

        player = get_player_by_username(ichancy_username)

        if not player:
            await update.message.reply_text(
                "❌ فشل الوصول لحساب Ichancy",
                reply_markup=main_menu(user_id)
            )
            return

        player_id = player.get("playerId")

    # التحقق من رصيد Ichancy قبل تنفيذ السحب
        current_balance_nsp = get_player_balance(player_id)

        if current_balance_nsp is None:
            await update.message.reply_text(
                "❌ تعذر معرفة رصيد حساب Ichancy.",
                reply_markup=main_menu(user_id)
            )
            return

        requested_nsp = ls_to_nsp(amount)

        if requested_nsp > current_balance_nsp:
            await update.message.reply_text(
                f"❌ رصيدك في Ichancy غير كافٍ.\n\n"
                f"💰 رصيدك الحالي: {current_balance_nsp} NSP",
                reply_markup=main_menu(user_id)
            )
            return

        await update.message.reply_text(
            "⏳ جاري السحب من Ichancy...",
            reply_markup=main_menu(user_id)
        )

        api_success = withdraw_from_player(
            player_id,
            requested_nsp,
            comment="Withdraw to bot wallet"
        )

        if not api_success:
            await update.message.reply_text(
                "❌ فشل السحب، تأكد من رصيدك على iChancy.",
                reply_markup=main_menu(user_id)
            )
            return

    # إضافة الرصيد للبوت فقط بعد نجاح API
        update_balance(user_id, amount)
        log_ichancy_transaction(user_id, "out", requested_nsp)

    # جلب الرصيد الجديد من قاعدة البيانات
        updated_user = get_user(user_id)

        await update.message.reply_text(
            f"✅ تم السحب من iChancy بنجاح!\n\n"
            f"💰 المسحوب والمضاف لرصيد البوت: "
            f"{amount:,} {CURRENCY_LABEL}\n"
            f"💳 رصيدك الجديد: "
            f"{updated_user['balance']:,} {CURRENCY_LABEL}",
            reply_markup=main_menu(user_id)
        )

        return

    # ============================
    # بيانات واردة من واجهة العجلة (WebApp)
    # ============================
    # ملاحظة أمان: لا نثق بأي نتيجة/جائزة تُرسل من الواجهة (WebApp)،
    # لأن الطرف الأمامي (متصفح المستخدم) غير موثوق ويمكن التلاعب به.
    # القرار الفعلي للجائزة يُتخذ ويُطبَّق بالكامل من السيرفر لحظة
    # الضغط على زر "🆓 اللفة المجانية" (قبل حتى فتح الواجهة). لذلك
    # نتجاهل أي بيانات واردة من الواجهة هنا بأمان.
    if update.message.web_app_data:
        return

    # التحقق من الموافقة على الشروط
    user = get_user(user_id)
    if user.get("agreed") != 1:
        await update.message.reply_text("⚠️ يجب الموافقة على الشروط أولًا /start")
        return

    # ============================
    # إنشاء حساب Ichancy
    # ============================
    if context.user_data.get("ichancy_step") == "username":
        base_username = text.strip()

        if not base_username.endswith("@scarface.ichancy"):
            ichancy_username = f"{base_username}@scarface.ichancy"
        else:
            ichancy_username = base_username

        context.user_data["ichancy_step"] = None

        await update.message.reply_text("⏳ جاري إنشاء حسابك في iChancy...", reply_markup=main_menu(user_id))

        password = generate_password()
        success = register_player(ichancy_username, password)

        if success:
            update_ichancy_account(user_id, ichancy_username, password)
            await update.message.reply_text(
                f"🎉 تم إنشاء حساب Ichancy بنجاح!\n\n"
                f"👤 Username: `{ichancy_username}`\n"
                f"🔑 Password: `{password}`\n\n"
                f"⚠️ احتفظ بالمعلومات جيدًا\n"
                f"🌐 الموقع: https://www.ichancy100.com"
                f"🌐 الموقع: https://www.ichancy200.com",
                parse_mode="Markdown"
            )
            user_info = update.effective_user
            user_display = f"@{user_info.username}" if user_info.username else user_info.first_name
            await notify_admins(context.bot,
                f"🧾 حساب Ichancy جديد تم إنشاؤه تلقائياً\n"
                f"👤 {user_display} | 🆔 {user_id}\n"
                f"🔑 {ichancy_username}"
            )
        else:
            await update.message.reply_text(
                f"❌ فشل إنشاء الحساب\n\n"
                f"السبب المحتمل: اسم المستخدم ({ichancy_username}) مكرر\n"
                f"جرب اسم مستخدم مختلف"
            )
        return

    # ============================
    # شحن USDT — المرحلة 1: المبلغ بالدولار
    # ============================
    if context.user_data.get("recharge_step") == "usdt_amount":
        try:
            usdt_amount = float(text.replace(",", "."))
            if usdt_amount <= 0:
                raise ValueError
        except:
            await update.message.reply_text("❌ أرسل مبلغاً صحيحاً بالدولار (مثال: 10 أو 10.5)", reply_markup=cancel_keyboard())
            return
        rate = get_usdt_rate()
        ls_amount = int(usdt_amount * rate)
        usdt_bonus_percent = get_bonus_percent("usdt")
        bonus = int(ls_amount * usdt_bonus_percent)
        total_ls = ls_amount + bonus
        context.user_data["recharge_usdt_amount"] = usdt_amount
        context.user_data["recharge_ls_amount"] = ls_amount
        context.user_data["recharge_step"] = "usdt_txid"
        await update.message.reply_text(
            f"✅ المبلغ: {usdt_amount} USDT\n"
            f"💱 سعر الصرف: 1 USDT = {rate:,} ل.س\n"
            f"💰 يعادل: {ls_amount:,} ل.س\n"
            f"🎁 بونص {usdt_bonus_percent * 100:.0f}%: +{bonus:,} ل.س\n"
            f"💵 الإجمالي الذي سيُضاف: {total_ls:,} ل.س\n\n"
            "📌 الآن أرسل هاش (Hash) عملية التحويل من محفظتك:",
            reply_markup=cancel_keyboard()
        )
        return

    # ============================
    # شحن USDT — المرحلة 2: هاش العملية
    # ============================
    if context.user_data.get("recharge_step") == "usdt_txid":
        txid = text.strip()
        usdt_amount = context.user_data.get("recharge_usdt_amount", 0)
        ls_amount = context.user_data.get("recharge_ls_amount", 0)
        method = context.user_data.get("recharge_method", "USDT")
        rate = get_usdt_rate()
        context.user_data["recharge_step"] = None

        usdt_bonus_percent = get_bonus_percent("usdt")
        bonus = int(ls_amount * usdt_bonus_percent)
        total_ls = ls_amount + bonus

        # نحفظ المبلغ بالليرة في قاعدة البيانات
        create_recharge(user_id, ls_amount, txid, method)

        await update.message.reply_text(
            f"✅ تم استلام طلب الشحن!\n\n"
            f"💵 المبلغ المرسل: {usdt_amount} USDT\n"
            f"💱 سعر الصرف: 1 USDT = {rate:,} ل.س\n"
            f"💰 يعادل: {ls_amount:,} ل.س\n"
            f"🎁 بونص {usdt_bonus_percent * 100:.0f}%: +{bonus:,} ل.س\n"
            f"💵 الإجمالي الذي سيُضاف: {total_ls:,} ل.س\n"
            f"🔢 هاش العملية: {txid}\n\n"
            f"⏳ بانتظار تأكيد الكاشيرة...",
            reply_markup=main_menu(user_id)
        )

        user_info = update.effective_user
        user = get_user(user_id)
        await notify_admins(context.bot,
            f"📥 طلب شحن USDT\n\n"
            f"👤 الاسم: {user_info.first_name}\n"
            f"📛 اليوزر: @{user_info.username}\n"
            f"🆔 Telegram ID: {user_id}\n\n"
            f"💳 الطريقة: {method}\n"
            f"💵 المبلغ: {usdt_amount} USDT\n"
            f"💱 سعر الصرف: 1 USDT = {rate:,} ل.س\n"
            f"💰 يعادل: {ls_amount:,} ل.س\n"
            f"🎁 البونص ({usdt_bonus_percent * 100:.0f}%): +{bonus:,} ل.س\n"
            f"💵 الإجمالي بالليرة: {total_ls:,} ل.س\n"
            f"🔢 هاش التحويل: `{txid}`\n\n"
            f"🎮 حساب Ichancy: {user.get('ichancy_username')}\n\n"
            f"⚠️ تحقق من الهاش ثم اضغط تأكيد",
            reply_markup=admin_recharge_keyboard(user_id, ls_amount)
        )
        return

    # ============================
    # Syriatel Cash / Sham Cash — تحقق آلي من العملية
    # ============================
    if context.user_data.get("recharge_step") == "payment_txid":
        txid = text.strip()
        method = context.user_data.get("recharge_method")

        if not txid.isdigit() or not 3 <= len(txid) <= 30:
            await update.message.reply_text(
                "❌ رقم العملية غير صالح. أرسل رقم العملية فقط.",
                reply_markup=cancel_keyboard()
            )
            return

        if method not in ("Syriatel Cash", "Sham Cash"):
            context.user_data.clear()
            await update.message.reply_text(
                "❌ طريقة الدفع غير معروفة. ابدأ من جديد.",
                reply_markup=main_menu(user_id)
            )
            return

        await update.message.reply_text(
            "🔎 جاري التحقق من العملية تلقائياً...\n⏳ يرجى الانتظار قليلاً.",
            reply_markup=cancel_keyboard()
        )

        verified, message, payment = await asyncio.to_thread(
            verify_payment, method, txid, None, period="7"
        )

        if not verified or payment is None:
            await update.message.reply_text(
                f"❌ لم يتم قبول العملية.\n\n{message}\n\n"
                "تأكد من رقم العملية والتحويل إلى حسابنا ثم حاول مرة أخرى.",
                reply_markup=cancel_keyboard()
            )
            return

        bonus_key = _bonus_key_for_method(method)
        bonus_percent = get_bonus_percent(bonus_key) if bonus_key else 0.0

        result = approve_verified_recharge(
            user_id=user_id,
            amount=payment.amount*100,
            txid=payment.transaction_id,
            method=method,
            bonus_percent=bonus_percent,
        )

        if result["status"] == "already_used":
            context.user_data.clear()
            await update.message.reply_text(
                "❌ هذه العملية مستخدمة مسبقاً ولا يمكن استخدامها مرة ثانية.",
                reply_markup=main_menu(user_id)
            )
            return

        if not result["ok"]:
            await update.message.reply_text(
                "❌ حدث خطأ أثناء تسجيل العملية. لم يتم إضافة الرصيد.",
                reply_markup=cancel_keyboard()
            )
            return
        bonus = result["bonus"]
        total = result["total"]

        # =====================================================
        # تفعيل الإحالة (حالة نشطة) + تسجيل عمولة الإحالة المستمرة
        # =====================================================
        activation = activate_referral_after_recharge(
            referred_user_id=user_id,
            reward_amount=0
        )

        if activation.get("status") == "activated_no_reward":
            ref_id = activation["referrer_id"]
            try:
                await context.bot.send_message(
                    ref_id,
                    "🎉 أصبح لديك إحالة نشطة جديدة!\n\n"
                    "بمجرد ما يشحن رصيده رح تبلش تاخد عمولة على شحناته القادمة تلقائياً."
                )
            except Exception:
                pass

        referrer_id = get_referrer(user_id)
        if referrer_id:
            commission_percent = get_referral_commission_percent()
            if commission_percent > 0:
                commission_amount = int(total * commission_percent)
                if commission_amount > 0:
                    log_referral_commission(referrer_id, user_id, total, commission_amount)

        context.user_data.clear()
        bonus_msg = f"\n🎁 البونص: +{bonus:,} ل.س" if bonus else ""

        await update.message.reply_text(
            "✅ تم التحقق من عملية الشحن بنجاح!\n\n"
            f"💳 الطريقة: {method}\n"
            f"🔢 رقم العملية: {payment.transaction_id}\n"
            f"💰 المبلغ المحول: {payment.amount:,} ل.س"
            f"{bonus_msg}\n"
            f"💵 تمت إضافة: {total:,} ل.س\n"
            f"💳 رصيدك الجديد: {get_user_balance(user_id):,} ل.س\n\n"
            "🤖 تم تنفيذ الشحن تلقائياً.",
            reply_markup=main_menu(user_id)
        )
        return

    # ============================
    # السحب — حسم 10%
    # ============================
    if context.user_data.get("withdraw_step") == "amount":
        if not text.isdigit():
            await update.message.reply_text("❌ أرسل رقم فقط", reply_markup=cancel_keyboard())
            return
        context.user_data["withdraw_amount"] = int(text)
        context.user_data["withdraw_step"] = "account"
        method = context.user_data.get("withdraw_method", "")
        if method == "USDT":
            await update.message.reply_text(
                "📌 أرسل عنوان محفظة USDT الخاصة بك (شبكة ERC20/BEP20):\n\n"
                "⚠️ تأكد من صحة العنوان — أي خطأ يعني ضياع المبلغ",
                reply_markup=cancel_keyboard()
            )
        else:
            await update.message.reply_text(
                "📌 أرسل الحساب أو المحفظة التي تريد السحب إليها:",
                reply_markup=cancel_keyboard()
            )
        return

    if context.user_data.get("withdraw_step") == "account":
        account = text.strip()
        amount = context.user_data["withdraw_amount"]
        method = context.user_data.get("withdraw_method", "غير محدد")
        context.user_data["withdraw_step"] = None

        user = get_user(user_id)

        if amount > user["balance"]:
            await update.message.reply_text("❌ الرصيد غير كافي", reply_markup=main_menu(user_id))
            return

        fee = int(amount * WITHDRAW_FEE_PERCENT)
        net_amount = amount - fee

        # التحقق من صحة عنوان USDT (ERC20/BEP20 يبدأ بـ 0x)
        if method == "USDT" and not account.startswith("0x"):
            await update.message.reply_text(
                "❌ عنوان محفظة USDT غير صحيح\n"
                "تأكد أن العنوان على شبكة ERC20/BEP20 (يبدأ بـ 0x)",
                reply_markup=cancel_keyboard()
            )
            context.user_data["withdraw_step"] = "account"
            return

        update_balance(user_id, -amount)
        create_withdraw(user_id, amount, account)
        update_withdraw_status(user_id, amount, "pending")

        if method == "USDT":
            user_msg = (
                f"✅ تم إرسال طلب السحب بـ USDT\n\n"
                f"💸 المبلغ المطلوب: {amount:,} {CURRENCY_LABEL}\n"
                f"📉 حسم 10%: -{fee:,} {CURRENCY_LABEL}\n"
                f"💵 المبلغ الذي ستستلمه: {net_amount:,} {CURRENCY_LABEL}\n"
                f"🏦 محفظة USDT (ERC20/BEP20): `{account}`\n\n"
                f"⏳ بانتظار موافقة الأدمن"
            )
            admin_msg = (
                f"📤 طلب سحب USDT\n\n"
                f"👤 الاسم: @{update.effective_user.username or update.effective_user.first_name}\n"
                f"🆔 المعرف: {user_id}\n"
                f"💳 الطريقة: {method}\n"
                f"💰 المبلغ الكامل: {amount:,} {CURRENCY_LABEL}\n"
                f"📉 الحسم (10%): {fee:,} {CURRENCY_LABEL}\n"
                f"💵 يصله: {net_amount:,} {CURRENCY_LABEL}\n"
                f"🏦 عنوان المحفظة (ERC20/BEP20):\n`{account}`\n"
                f"🎮 iChancy: {user.get('ichancy_username')}"
            )
        else:
            user_msg = (
                f"✅ تم إرسال طلب السحب\n\n"
                f"💸 المبلغ المطلوب: {amount:,} {CURRENCY_LABEL}\n"
                f"📉 حسم 10%: -{fee:,} {CURRENCY_LABEL}\n"
                f"💵 المبلغ الذي ستستلمه: {net_amount:,} {CURRENCY_LABEL}\n"
                f"🏦 إلى: {account}\n\n"
                f"⏳ بانتظار موافقة الأدمن"
            )
            user_display = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
            admin_msg = (
                f"📤 طلب سحب جديد\n\n"
                f"👤 الاسم: {user_display}\n"
                f"🆔 المعرف: {user_id}\n"
                f"💳 الطريقة: {method}\n"
                f"💰 المبلغ الكامل: {amount:,} {CURRENCY_LABEL}\n"
                f"📉 الحسم (10%): {fee:,} {CURRENCY_LABEL}\n"
                f"💵 يصله: {net_amount:,} {CURRENCY_LABEL}\n"
                f"🪙 الحساب: {account}\n"
                f"🎮 iChancy: {user.get('ichancy_username')}"
            )

        await update.message.reply_text(user_msg, parse_mode="Markdown", reply_markup=main_menu(user_id))
        await notify_admins(context.bot, admin_msg, reply_markup=admin_withdraw_keyboard(user_id, net_amount, account))
        return

    # ============================
    # إهداء رصيد
    # ============================
    if text == "🎁 إهداء رصيد":
        context.user_data["state"] = "gift_user_id"
        await update.message.reply_text(
            f"🎁 عملية إهداء رصيد\n\n"
            f"ارسل معرف التلغرام للشخص المراد اهداء الرصيد اليه\n\n"
            f"🔹 معرفك هو: {user_id}\n\n"
            f"ارسل الآن معرف تلغرام المستخدم 👇",
            reply_markup=cancel_keyboard()
        )
        return

    elif context.user_data.get("state") == "gift_user_id":
        try:
            target_id = int(text)
        except:
            await update.message.reply_text("❌ الرجاء ارسال رقم معرف صحيح", reply_markup=cancel_keyboard())
            return
        context.user_data["gift_target"] = target_id
        context.user_data["state"] = "gift_amount"
        await update.message.reply_text("💰 ارسل المبلغ الذي تريد اهداؤه:", reply_markup=cancel_keyboard())
        return

    elif context.user_data.get("state") == "gift_amount":
        try:
            amount = int(text)
        except:
            await update.message.reply_text("❌ ارسل رقم صحيح", reply_markup=cancel_keyboard())
            return

        target_id = context.user_data.get("gift_target")
        user_balance = get_user_balance(user_id)

        if amount <= 0:
            await update.message.reply_text("❌ المبلغ غير صالح", reply_markup=cancel_keyboard())
            return
        if amount > user_balance:
            await update.message.reply_text("❌ رصيدك غير كافي", reply_markup=cancel_keyboard())
            return

        update_balance(user_id, -amount)
        update_balance(target_id, amount)
        await update.message.reply_text(f"✅ تم إهداء {amount:,} {CURRENCY_LABEL} بنجاح 🎁", reply_markup=main_menu(user_id))
        await context.bot.send_message(target_id, f"🎉 استلمت {amount:,} {CURRENCY_LABEL} كهدية!")
        user_info = update.effective_user
        user_display = f"@{user_info.username}" if user_info.username else user_info.first_name
        await notify_admins(context.bot, f"🎁 إهداء\n👤 من: {user_display} ({user_id})\n🎯 إلى: {target_id} | 💰 {amount:,} {CURRENCY_LABEL}")
        context.user_data.clear()
        return

    # ============================
    # 🎁 تفعيل كود هدية
    # ============================
    if text == "💎كود هدية":
        context.user_data["state"] = "redeem_gift_code"
        await update.message.reply_text(
            "💎تفعيل كود هدية\n\n"
            "أرسل الآن كود الهدية الذي تملكه 👇",
            reply_markup=cancel_keyboard()
        )
        return

    elif context.user_data.get("state") == "redeem_gift_code":

        code = text.strip()
        result = redeem_gift_code(user_id, code)

        if result["ok"]:
            context.user_data.clear()
            new_balance = get_user_balance(user_id)

            await update.message.reply_text(
                f"✅ تم تفعيل كود الهدية بنجاح! 🎁\n\n"
                f"🎟️ الكود: {result['code']}\n"
                f"💰 المبلغ المضاف: {result['amount']:,} {CURRENCY_LABEL}\n\n"
                f"💳 رصيدك الحالي: {new_balance:,} {CURRENCY_LABEL}",
                reply_markup=main_menu(user_id)
            )

            user_info = update.effective_user
            user_display = f"@{user_info.username}" if user_info.username else user_info.first_name
            await notify_admins(
                context.bot,
                f"💎تم استخدام كود هدية\n"
                f"👤 {user_display} ({user_id})\n"
                f"🎟️ الكود: {result['code']}\n"
                f"💰 المبلغ: {result['amount']:,} {CURRENCY_LABEL}\n"
                f"📊 الاستخدامات: {result['used_count']}/{result['max_uses']}"
            )
            return

        status = result.get("status")

        error_messages = {
            "invalid_code": "❌ الرجاء إرسال كود صحيح.",
            "not_found": "❌ هذا الكود غير موجود، تأكد من كتابته وأعد المحاولة.",
            "inactive": "❌ هذا الكود غير مُفعّل حالياً.",
            "expired": "⌛ انتهت صلاحية هذا الكود.",
            "limit_reached": "❌ تم استنفاد عدد مرات استخدام هذا الكود بالكامل.",
            "already_used": "❌ لقد استخدمت هذا الكود من قبل، لا يمكن استخدامه مرة أخرى.",
        }

        await update.message.reply_text(
            error_messages.get(status, "❌ حدث خطأ أثناء تفعيل الكود، حاول مجدداً.")
            + "\n\nيمكنك إرسال كود آخر، أو الضغط على تراجع:",
            reply_markup=cancel_keyboard()
        )
        return

    # ============================
    # رسالة للأدمن
    # ============================
    if text == "✉️ رسالة للإدمن":
        context.user_data["state"] = "contact_admin"
        await update.message.reply_text("✉️ أرسل استفسارك الآن:", reply_markup=cancel_keyboard())
        return

    elif context.user_data.get("state") == "contact_admin":
        user_info = update.effective_user
        user_display = f"@{user_info.username}" if user_info.username else user_info.first_name
        await notify_admins(context.bot, f"📩 رسالة من مستخدم\n👤 {user_display}\n🆔 {user_id}\n\n📝 {text}")
        await update.message.reply_text("✅ تم إرسال رسالتك للإدمن", reply_markup=main_menu(user_id))
        context.user_data.clear()
        return

    # ============================
    # القوائم الرئيسية
    # ============================
    if text == "🤝نظام الإحالات":
        await referral_menu(update, context)
        return
    if text == "💰 اعرف رصيدي":
        await show_balance(update, context)
        return

    if text == "📥 شحن رصيد":
        bonus_percents = get_all_bonus_percents()

        def _bonus_suffix(key):
            pct = bonus_percents.get(key, 0.0)
            return f" (+{pct * 100:.0f}%)" if pct > 0 else ""

        keyboard = [
            [InlineKeyboardButton(f"🟢 Syriatel Cash{_bonus_suffix('syriatel')}", callback_data="syriatel_cash")],
            [InlineKeyboardButton(f"💰 عملات ومحافظ رقمية (USDT){_bonus_suffix('usdt')}", callback_data="crypto")],
            [InlineKeyboardButton(f"⚡ Sham Cash{_bonus_suffix('shamcash')}", callback_data="sham_cash")],
            [InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="back_to_menu")]
        ]
        await update.message.reply_text("اختر أحد طرق الشحن:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if text == "📤 سحب رصيد":
        fee_example = int(100 * WITHDRAW_FEE_PERCENT)
        keyboard = [
            [InlineKeyboardButton("🟢 Syriatel Cash", callback_data="wd_syriatel"),
             InlineKeyboardButton("⚡ Sham Cash", callback_data="wd_sham")],
            [InlineKeyboardButton("💰 USDT", callback_data="wd_usdt")],
            [InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="back_to_menu")]
        ]
        await update.message.reply_text(
            f"⚠️ تنبيه: يتم حسم 10% كرسوم سحب\n"
            f"مثال: 10,000 {CURRENCY_LABEL} → تستلم {10000 - int(10000 * WITHDRAW_FEE_PERCENT):,} {CURRENCY_LABEL}\n\n"
            f"اختر طريقة السحب:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ============================
    # 🧾 حساب Ichancy
    # ============================
    if text == "🧾  حساب Ichancy":

        user = get_user(user_id)

    # ==========================================
    # المستخدم لديه حساب Ichancy بالفعل
    # ==========================================
        if user["ichancy_username"] is not None:
 
            ichancy_username = user["ichancy_username"]
            ichancy_password = user["ichancy_password"]

        # جلب الحساب من Ichancy لمعرفة الرصيد الحقيقي
            player = get_player_by_username(ichancy_username)

            if player:
                player_id = player.get("playerId")

                if player_id:
                    current_balance = get_player_balance(player_id)

                    if current_balance is not None:
                        balance_text = f"{current_balance:,.2f}"
                    else:
                        balance_text = "تعذر جلب الرصيد"
                else:
                    balance_text = "تعذر جلب الرصيد"
            else:
                balance_text = "تعذر الوصول للحساب"

        # ==========================================
        # أزرار Inline
        # ==========================================
            keyboard = [
                [
                    InlineKeyboardButton(
                        "🔄 تحديث الرصيد",
                        callback_data="refresh_ichancy_account"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🌐 فتح Ichancy",
                        url="https://www.ichancy100.com"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ رجوع",
                        callback_data="back_to_menu"
                    )
                ]
            ]

            await update.message.reply_text(
                f"🧾 *معلومات حسابك في Ichancy*\n\n"
                f"👤 *Username:*\n"
                f"`{ichancy_username}`\n\n"
                f"🔑 *Password:*\n"
                f"`{ichancy_password}`\n\n"
                f"💰 * الرصيد داخل الموقع:*\n"
                f"`{balance_text}`\n\n"
                f"⚠️ احتفظ بمعلومات تسجيل الدخول ولا تشاركها مع أي شخص.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

            return

    # ==========================================
    # المستخدم لا يملك حساب Ichancy
    # ==========================================
        context.user_data["ichancy_step"] = "username"

        await update.message.reply_text(
            "🧾 حساب Ichancy\n\n"
            "✏️ أرسل اسم المستخدم المطلوب فقط\n"
            "(بدون @scarface.ichancy — سيضاف تلقائياً):",
            reply_markup=cancel_keyboard()
        )

        return
    

    if text == "🎰 اللفة المجانية":
        user = get_user(user_id)
        if user["balance"] <= 0:
            await update.message.reply_text("❌ يجب شحن رصيدك أولاً للحصول على اللفة المجانية 🔒")
            return

        prizes = get_active_spin_prizes()

        if not prizes:
            await update.message.reply_text("⚠️ عجلة الحظ غير مهيأة حالياً، حاول لاحقاً.")
            return

        labels = [p["label"] for p in prizes]

        # ==========================================================
        # فحص الأهلية (عد تنازلي حقيقي بالساعات من وقت آخر لفة)
        # ==========================================================
        cooldown_hours = get_spin_cooldown_hours()
        last_spin_at = get_last_spin_at(user_id)

        eligible = True
        remaining_text = ""

        if last_spin_at:
            try:
                last_dt = datetime.strptime(last_spin_at, "%Y-%m-%d %H:%M:%S")
                elapsed_hours = (datetime.utcnow() - last_dt).total_seconds() / 3600

                if elapsed_hours < cooldown_hours:
                    eligible = False
                    remaining = cooldown_hours - elapsed_hours
                    rem_h = int(remaining)
                    rem_m = int(round((remaining - rem_h) * 60))
                    if rem_h > 0:
                        remaining_text = f"{rem_h} ساعة" + (f" و{rem_m} دقيقة" if rem_m > 0 else "")
                    else:
                        remaining_text = f"{max(rem_m, 1)} دقيقة"
            except Exception:
                pass

        land_index = None
        chosen_prize_type = None

        # ==========================================================
        # القرار من السيرفر فقط (آمن 100%) — يُطبَّق فوراً هون قبل
        # حتى ما تنفتح واجهة العجلة. الواجهة تعرض النتيجة فقط.
        # ==========================================================
        if eligible:

            chosen = pick_random_spin_prize()

            if chosen:
                for i, p in enumerate(prizes):
                    if p["id"] == chosen["id"]:
                        land_index = i
                        break

                prize_type = chosen["prize_type"]
                chosen_prize_type = prize_type
                amount = chosen["amount"]
                label = chosen["label"]

                if prize_type == "cash" and amount > 0:
                    update_balance(user_id, amount)
                    update_last_spin_at(user_id)

                    ichancy_username = user.get("ichancy_username")
                    api_success = False
                    if ichancy_username:
                        player = get_player_by_username(ichancy_username)
                        if player:
                            api_success = deposit_to_player(player.get("playerId"), ls_to_nsp(amount), comment="Spin reward")
                            if api_success:
                                log_ichancy_transaction(user_id, "in", ls_to_nsp(amount))

                    # ملاحظة: لا نرسل نص النتيجة بالشات هون عمداً — النتيجة
                    # تنكشف فقط جوا واجهة العجلة بعد ما يلف المستخدم، حتى ما
                    # تنحرق المفاجأة قبل فتح الصفحة.

                    user_info = update.effective_user
                    user_display = f"@{user_info.username}" if user_info.username else user_info.first_name
                    await notify_admins(context.bot, f"🎡 جائزة عجلة\n👤 {user_display} | 🆔 {user_id}\n💰 {amount:,} {CURRENCY_LABEL} ({label})")

                elif prize_type == "respin":
                    update_last_spin_at(user_id, reset=True)

                elif prize_type == "custom_message":
                    update_last_spin_at(user_id)

                    user_info = update.effective_user
                    user_display = f"@{user_info.username}" if user_info.username else user_info.first_name
                    await notify_admins(context.bot, f"🎁 جائزة عجلة تحتاج معالجة يدوية\n👤 {user_display} | 🆔 {user_id}\n🎁 {label}")

                else:
                    update_last_spin_at(user_id)

        spin_url = _build_spin_webapp_url(
            labels=labels,
            eligible=eligible,
            land_index=land_index,
            remaining_text=remaining_text,
            prize_type=chosen_prize_type,
        )

        keyboard = [[InlineKeyboardButton("🎡 فتح عجلة الحظ", web_app={"url": spin_url})]]

        if eligible:
            caption = "🎁 اضغط بالأسفل لمشاهدة نتيجتك على العجلة 🎡"
        else:
            caption = (
                f"❌ ما فيك تلف العجلة هلق.\n"
                f"⏰ اللفة القادمة متاحة خلال {remaining_text}\n\n"
                f"🎡 بإمكانك تجربة العجلة بلفة تجريبية بالأسفل (بدون جائزة حقيقية)"
            )

        await update.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if text == "☁️ الشروحات":
        await update.message.reply_text("📚 *الأسئلة الشائعة*", reply_markup=faq_menu(), parse_mode="Markdown")
        return

    if text == "📌 الشروط والأحكام":
        await update.message.reply_text(TEXT)
        return

    if text == "📞 تواصل معنا":
        await update.message.reply_text(
            "يمكنك التواصل معنا عن طريق (رسالة للأدمن)\n"
            "أو أرسل رسالة لحساب التلغرام: @Scarfacesuperbot"
        )
        return

    if text == "📱 ichancy apk":
        keyboard = [[InlineKeyboardButton("⬇️ تحميل التطبيق", url="https://android.betcoapps.com/novichok/ichancy_com/ichancy_com.apk")]]
        await update.message.reply_text("اضغط على الزر لتحميل التطبيق:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if text == "📜 السجل":
        await update.message.reply_text("📜 اختر نوع السجل:", reply_markup=history_menu())
        return
#--------------------------------------------------
#--------------------------------------------------    
async def refresh_ichancy_account_callback(update, context):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    user = get_user(user_id)

    if not user:
        await query.answer("❌ لم يتم العثور على حسابك.", show_alert=True)
        return

    ichancy_username = user.get("ichancy_username")
    ichancy_password = user.get("ichancy_password")

    if not ichancy_username:
        await query.answer("❌ لا يوجد حساب Ichancy مربوط.", show_alert=True)
        return

    # جلب الحساب من Ichancy
    player = get_player_by_username(ichancy_username)

    if not player:
        await query.answer(
            "❌ تعذر الوصول إلى حساب Ichancy.",
            show_alert=True
        )
        return

    player_id = player.get("playerId")

    if not player_id:
        await query.answer(
            "❌ لم يتم العثور على Player ID.",
            show_alert=True
        )
        return

    # جلب الرصيد الحقيقي
    current_balance = get_player_balance(player_id)

    if current_balance is None:
        await query.answer(
            "❌ تعذر جلب الرصيد حالياً.",
            show_alert=True
        )
        return

    balance_text = f"{current_balance:,.2f}"

    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 تحديث الرصيد",
                callback_data="refresh_ichancy_account"
            )
        ],
        [
            InlineKeyboardButton(
                "🌐 فتح Ichancy",
                url="https://www.ichancy100.com"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_to_menu"
            )
        ]
    ]

    await query.edit_message_text(
        f"🧾 *معلومات حسابك في Ichancy*\n\n"
        f"👤 *Username:*\n"
        f"`{ichancy_username}`\n\n"
        f"🔑 *Password:*\n"
        f"`{ichancy_password}`\n\n"
        f"💰 *الرصيد الحالي:*\n"
        f"`{balance_text}` NSP\n\n"
        f"🔄 تم تحديث الرصيد الآن.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def referral_menu(update, context):
    user_id = update.effective_user.id

    referrals = get_referral_users(user_id)

    active_count = sum(
        1 for r in referrals
        if r["status"] == "active"
    )

    total_count = len(referrals)

    # ضمان وجود دورة أرباح لهذا المستخدم (حتى لو لسا ما عنده إحالات)
    init_referral_cycle_if_missing(user_id)
    cycle_start_raw = get_referral_cycle_start(user_id)
    period_days = get_referral_period_days()

    remaining_days = period_days
    if cycle_start_raw:
        cycle_start_dt = datetime.strptime(cycle_start_raw, "%Y-%m-%d %H:%M:%S")
        elapsed_days = (datetime.utcnow() - cycle_start_dt).total_seconds() / 86400
        remaining_days = max(0, math.ceil(period_days - elapsed_days))

    pending_commission = get_pending_commission_total(user_id)

    message = (
        "🎯 <b>كن وكيلاً معنا بأبسط طريقة</b>\n"
        "احصل على نسبة ثابتة لكل عمليات الشحن والتعبئة القادمة "
        "عن طريق رابط احالتك ضمن البوت\n\n"
        "🔗 رابط الاحالة الخاص بك:\n"
        f"<code>https://t.me/{context.bot.username}?start=ref_{user_id}</code>\n\n"
        f"👤 إجمالي الإحالات: <b>{total_count}</b>\n"
        f"✅ الإحالات النشطة: <b>{active_count}</b>\n\n"
        f"💰 أرباحك المتراكمة هذه الدورة: <b>{pending_commission:,} {CURRENCY_LABEL}</b>\n\n"
        f"⏱️ مدة حساب الارباح: <b>{period_days} يوم/أيام</b>\n"
        f"⏳ المدة المتبقية على توزيع الارباح: <b>{remaining_days} يوم/أيام</b>"
    )

    await update.message.reply_text(
        message,
        parse_mode="HTML",
        reply_markup=main_menu(user_id)
    )


# ============================
# 👨‍💻 أمر التواصل مع المطور
# ============================

async def developer_command(update, context):

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👨‍💻 التواصل مع المطور",
                url="https://t.me/Ehsan_abbas"
            )
        ]
    ])

    await update.message.reply_text(
        "👨‍💻 *مطور البوت*\n\n"
        "إذا كان لديك استفسار أو مشكلة أو تريد التواصل "
        "مع مطور البوت، اضغط على الزر بالأسفل 👇",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
#---------------------------------------
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "بدء البوت"),
        BotCommand("developer", "التواصل مع المطور"),
    ])
    # تشغيل حلقة الاسترداد الأسبوعي التلقائية بالخلفية
    application.create_task(weekly_cashback_loop(application))
    application.create_task(referral_payout_loop(application))
#----------------------------
async def admin_create_gift_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ADMIN_IDS:
        return

    # بداية إنشاء الكود
    context.user_data["gift_admin_step"] = "amount"

    await query.message.reply_text(
        "💎إنشاء كود هدية\n\n"
        "💰 أرسل قيمة الهدية بالليرة السورية:\n\n"
        "مثال:\n"
        "50000",
        reply_markup=cancel_keyboard()
    )
# ============================
# تشغيل البوت
# ============================
if __name__ == "__main__":
    init_api()

    application = (
    ApplicationBuilder()
    .token(TOKEN)
    .post_init(post_init)
    .build()
)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("developer", developer_command))


    application.add_handler(CallbackQueryHandler(admin_users_callback,      pattern="^admin_users_"))
    application.add_handler(CallbackQueryHandler(ichancy_players_callback,   pattern="^ichancy_players_"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback,       pattern="^admin_panel$"))
    application.add_handler(
    CallbackQueryHandler(
        admin_create_gift_callback,
        pattern="^admin_create_gift$"
    )
    )
    application.add_handler(CallbackQueryHandler(admin_set_rate_callback,      pattern="^admin_set_rate$"))
    application.add_handler(CallbackQueryHandler(admin_bonus_menu_callback,    pattern="^admin_bonus_menu$"))
    application.add_handler(CallbackQueryHandler(admin_set_bonus_callback,     pattern="^admin_set_bonus_"))
    application.add_handler(CallbackQueryHandler(admin_cashback_menu_callback, pattern="^admin_cashback_menu$"))
    application.add_handler(CallbackQueryHandler(admin_set_cashback_percent_callback, pattern="^admin_set_cashback_percent$"))
    application.add_handler(CallbackQueryHandler(admin_run_cashback_now_callback,     pattern="^admin_run_cashback_now$"))
    application.add_handler(CallbackQueryHandler(admin_cashback_history_callback,     pattern="^admin_cashback_history$"))
    application.add_handler(CallbackQueryHandler(admin_referral_menu_callback,        pattern="^admin_referral_menu$"))
    application.add_handler(CallbackQueryHandler(admin_set_referral_percent_callback, pattern="^admin_set_referral_percent$"))
    application.add_handler(CallbackQueryHandler(admin_set_referral_period_callback,  pattern="^admin_set_referral_period$"))
    application.add_handler(CallbackQueryHandler(admin_run_referral_now_callback,     pattern="^admin_run_referral_now$"))
    application.add_handler(CallbackQueryHandler(admin_referral_history_callback,     pattern="^admin_referral_history$"))
    application.add_handler(CallbackQueryHandler(admin_spin_menu_callback,        pattern="^admin_spin_menu$"))
    application.add_handler(CallbackQueryHandler(admin_spin_toggle_callback,      pattern="^admin_spin_toggle_"))
    application.add_handler(CallbackQueryHandler(admin_spin_delete_callback,      pattern="^admin_spin_delete_"))
    application.add_handler(CallbackQueryHandler(admin_spin_editweight_callback,  pattern="^admin_spin_editweight_"))
    application.add_handler(CallbackQueryHandler(admin_spin_add_callback,         pattern="^admin_spin_add$"))
    application.add_handler(CallbackQueryHandler(admin_spin_type_callback,        pattern="^admin_spin_type_"))
    application.add_handler(CallbackQueryHandler(admin_set_spin_cooldown_callback, pattern="^admin_set_spin_cooldown$"))
    application.add_handler(CallbackQueryHandler(terms_callback,             pattern="^(agree|disagree)$"))
    application.add_handler(CallbackQueryHandler(check_join_callback,        pattern="^check_join$"))
    application.add_handler(CallbackQueryHandler(faq_callback,               pattern="^faq_"))
    application.add_handler(CallbackQueryHandler(gift_admin_callback,        pattern="^gift_"))
    application.add_handler(CallbackQueryHandler(recharge_callback,          pattern="^(syriatel_cash|crypto|sham_cash|back_to_menu)$"))
    application.add_handler(CallbackQueryHandler(withdraw_callback,          pattern="^wd_"))
    # ✅ التعديل: إضافة handler لزر تعديل المبلغ
    application.add_handler(CallbackQueryHandler(admin_edit_amount_callback, pattern="^edit_amount_"))
    application.add_handler(CallbackQueryHandler(admin_recharge_callback,    pattern="^(approve_|reject_)[0-9]+_[0-9]+$"))
    application.add_handler(CallbackQueryHandler(admin_withdraw_callback,    pattern="^(wdapprove_|wdreject_).*"))
    application.add_handler(CallbackQueryHandler(ichancy_callback,           pattern="^back_to_menu$"))
    application.add_handler(CallbackQueryHandler(history_callback,           pattern="^history_"))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, menu_handler))
    application.add_handler(
    CallbackQueryHandler(handle_callback_query)
    )
    application.add_handler(
    CallbackQueryHandler(
        refresh_ichancy_account_callback,
        pattern="^refresh_ichancy_account$"
    ))
    application.add_handler(CommandHandler("developer", developer_command))
    

    print("✅ البوت يعمل الآن...")
    application.run_polling()
