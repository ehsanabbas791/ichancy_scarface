import requests
import sqlite3
import time
from datetime import datetime, timedelta
from threading import Lock

# =============================
# إعدادات الـ API
# =============================
BASE_URL = "https://agents.ichancy300.com/global/api/UserApi"  # ضع الدومين هنا
AGENT_EMAIL = "botscarface@agent.com"                      # إيميل الأيجنت
AGENT_PASSWORD = "Aaa@1234"                # باسورد الأيجنت
AGENT_ID = "2782583"                            # ID الأيجنت
CURRENCY = "NSP"


# =============================
# إدارة التوكن (مع Thread Safety)
# =============================
_token_lock = Lock()

# تخزين التوكن في الذاكرة
_token_store = {
    "access_token": None,
    "refresh_token": None,
    "access_token_expires_at": None,  # وقت انتهاء الـ access token
}


def _save_tokens(access_token: str, refresh_token: str):
    """حفظ التوكن في الذاكرة مع وقت الانتهاء"""
    _token_store["access_token"] = access_token
    _token_store["refresh_token"] = refresh_token
    # access token ينتهي بعد ساعة، نجدد قبلها بـ 5 دقائق
    _token_store["access_token_expires_at"] = time.time() + 3600 - 300


def _is_access_token_valid() -> bool:
    """التحقق من صلاحية الـ access token"""
    if not _token_store["access_token"]:
        return False
    return time.time() < _token_store["access_token_expires_at"]


# =============================
# المصادقة - Authentication
# =============================
def sign_in() -> bool:
    """
    تسجيل الدخول والحصول على التوكن
    Returns: True إذا نجح، False إذا فشل
    """
    try:
        response = requests.post(
            f"{BASE_URL}/signin",
            json={"username": AGENT_EMAIL, "password": AGENT_PASSWORD},
            timeout=15
        )
        data = response.json()

        if data.get("status") and data.get("result"):
            result = data["result"]
            _save_tokens(result["accessToken"], result["refreshToken"])
            print("✅ تم تسجيل الدخول بنجاح")
            return True
        else:
            error = _extract_error(data)
            print(f"❌ فشل تسجيل الدخول: {error}")
            return False

    except Exception as e:
        print(f"❌ خطأ في تسجيل الدخول: {e}")
        return False


def refresh_access_token() -> bool:
    """
    تجديد الـ access token باستخدام الـ refresh token
    Returns: True إذا نجح، False إذا فشل
    """
    if not _token_store["refresh_token"]:
        return sign_in()

    try:
        response = requests.post(
            f"{BASE_URL}/refreshToken",
            json={"refreshToken": _token_store["refresh_token"]},
            timeout=15
        )
        data = response.json()

        if data.get("status") and data.get("result"):
            result = data["result"]
            _save_tokens(result["accessToken"], result["refreshToken"])
            print("🔄 تم تجديد التوكن بنجاح")
            return True
        else:
            # الـ refresh token انتهى، نعمل sign in من جديد
            print("⚠️ انتهى الـ refresh token، إعادة تسجيل الدخول...")
            return sign_in()

    except Exception as e:
        print(f"❌ خطأ في تجديد التوكن: {e}")
        return sign_in()


def _get_valid_token() -> str | None:
    """
    الحصول على access token صالح (مع تجديد تلقائي)
    """
    with _token_lock:
        if _is_access_token_valid():
            return _token_store["access_token"]

        # محاولة التجديد
        if refresh_access_token():
            return _token_store["access_token"]

        return None


def _make_request(endpoint: str, body: dict) -> dict | None:
    """
    إرسال طلب مصادق عليه مع معالجة تلقائية لانتهاء التوكن
    """
    token = _get_valid_token()
    if not token:
        print("❌ لا يوجد توكن صالح")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            f"{BASE_URL}/{endpoint}",
            json=body,
            headers=headers,
            timeout=15
        )

        # معالجة 403 Unauthorized
        if response.status_code == 403 or (
            response.status_code == 201 and "unauthorized" in response.text.lower()
        ):
            print("⚠️ التوكن منتهي، إعادة المصادقة...")
            _token_store["access_token"] = None  # إجبار التجديد
            token = _get_valid_token()
            if not token:
                return None
            headers["Authorization"] = f"Bearer {token}"
            response = requests.post(
                f"{BASE_URL}/{endpoint}",
                json=body,
                headers=headers,
                timeout=15
            )

        return response.json()

    except Exception as e:
        print(f"❌ خطأ في الطلب ({endpoint}): {e}")
        return None


def _extract_error(data: dict) -> str:
    """استخراج رسالة الخطأ من الـ response"""
    notifications = data.get("notification", [])
    if notifications:
        return notifications[0].get("content", "خطأ غير معروف")
    return "خطأ غير معروف"


# =============================
# Agent Endpoints
# =============================
def get_agent_wallets() -> dict | None:
    """
    جلب معلومات محفظة الأيجنت (الرصيد وغيره)
    Returns: dict يحتوي على بيانات المحفظة أو None
    """
    data = _make_request("getAgentAllWallets", {})
    if not data:
        return None

    if data.get("status") and data.get("result"):
        return data["result"][0]  # أول محفظة (NSP)

    print(f"❌ فشل جلب محفظة الأيجنت: {_extract_error(data)}")
    return None


def deposit_to_agent(agent_id: str, amount: float, comment: str = "") -> bool:
    """
    إيداع رصيد لأيجنت فرعي
    Args:
        agent_id: ID الأيجنت المستهدف
        amount: المبلغ (موجب)
        comment: تعليق اختياري
    Returns: True إذا نجح
    """
    body = {
        "amount": amount,
        "comment": comment,
        "affiliateId": agent_id,
        "moneyStatus": 3,
        "currencyCode": CURRENCY
    }
    data = _make_request("depositToAgent", body)
    if not data:
        return False

    if data.get("status") and data.get("result") is not False:
        return True

    print(f"❌ فشل الإيداع للأيجنت: {_extract_error(data)}")
    return False


def withdraw_from_agent(agent_id: str, amount: float, comment: str = "") -> dict | None:
    """
    سحب رصيد من أيجنت فرعي
    Args:
        agent_id: ID الأيجنت
        amount: المبلغ (سيتم تحويله لسالب تلقائياً)
    Returns: dict يحتوي على الرصيد الجديد أو None
    """
    body = {
        "amount": -abs(amount),  # يجب أن يكون سالباً
        "comment": comment,
        "affiliateId": agent_id,
        "moneyStatus": 3,
        "currencyCode": CURRENCY
    }
    data = _make_request("withdrawFromAgent", body)
    if not data:
        return None

    if data.get("status") and data.get("result"):
        return data["result"]

    print(f"❌ فشل السحب من الأيجنت: {_extract_error(data)}")
    return None


def get_children(agent_id: str = None) -> list:
    """
    جلب قائمة الأيجنتات الفرعية
    Args:
        agent_id: ID الأيجنت للفلترة (اختياري)
    Returns: قائمة الأيجنتات
    """
    body = {"start": 0, "limit": 100, "filter": {}}

    if agent_id:
        body["filter"] = {
            "affiliateId": {
                "action": "=",
                "value": agent_id,
                "valueLabel": agent_id
            }
        }

    data = _make_request("getChildren", body)
    if not data:
        return []

    result = data.get("result", {})
    if isinstance(result, dict):
        return result.get("records", [])
    return []


# =============================
# Player Endpoints
# =============================
def register_player(username: str, password: str, email: str = None) -> bool:
    """
    تسجيل لاعب جديد تحت الأيجنت
    Args:
        username: اسم المستخدم (login) - مثال: eeeeqw@Goa.ichancy
        password: كلمة المرور (3 أحرف على الأقل)
        email: الإيميل (اختياري، سيتم توليده تلقائياً إذا لم يُعطَ)
    Returns: True إذا نجح
    """
    if not email:
        # استخراج الجزء النظيف قبل أول @ لتوليد إيميل صالح
        # مثال: "eeeeqw@Goa.ichancy" → base = "eeeeqw"
        base = username.split("@")[0]
        # إزالة أي حروف غير مسموح بها في الإيميل
        import re
        base_clean = re.sub(r"[^a-zA-Z0-9._-]", "", base)
        if not base_clean:
            base_clean = "user"
        # إضافة رقم عشوائي لتجنب التكرار
        import random
        rand = random.randint(1000, 9999)
        email = f"{base_clean}{rand}@bot.ichancy.com"

    body = {
        "player": {
            "email": email,
            "password": password,
            "parentId": AGENT_ID,
            "login": username
        }
    }
    data = _make_request("registerPlayer", body)
    if not data:
        return False

    # نجاح: result = 1
    if data.get("status") and data.get("result") == 1:
        print(f"✅ تم تسجيل اللاعب '{username}' بإيميل: {email}")
        return True

    error = _extract_error(data)
    print(f"❌ فشل تسجيل اللاعب '{username}': {error}")
    return False


def get_all_players(start: int = 0, limit: int = 50) -> list:
    body = {
        "start": start,
        "limit": limit,
        "filter": {}
    }

    data = _make_request("getPlayersForCurrentAgent", body)
    if not data:
        return []

    result = data.get("result", {})
    records = result.get("records", []) if isinstance(result, dict) else []

    players_with_balance = []

    for p in records:
        player_id = p.get("playerId")
        if not player_id:
            continue

        balance = get_player_balance(player_id)

        players_with_balance.append({
            "playerId": player_id,
            "login": p.get("username"),
            "balance": balance
        })

    return players_with_balance


def get_player_by_username(username: str) -> dict | None:
    """
    البحث عن لاعب بالاسم
    Returns: بيانات اللاعب أو None
    """
    body = {
        "start": 0,
        "limit": 1,
        "filter": {
            "userName": {
                "action": "=",
                "value": username,
                "valueLabel": username
            }
        }
    }
    data = _make_request("getPlayersForCurrentAgent", body)
    if not data:
        return None

    result = data.get("result", {})
    records = result.get("records", []) if isinstance(result, dict) else []
    return records[0] if records else None


def get_player_by_id(player_id: str) -> dict | None:
    """
    البحث عن لاعب بالـ ID
    Returns: بيانات اللاعب أو None
    """
    body = {
        "start": 0,
        "limit": 1,
        "filter": {
            "playerId": {
                "action": "=",
                "value": player_id,
                "valueLabel": player_id
            }
        }
    }
    data = _make_request("getPlayersForCurrentAgent", body)
    if not data:
        return None

    result = data.get("result", {})
    records = result.get("records", []) if isinstance(result, dict) else []
    return records[0] if records else None


def get_player_balance(player_id: str) -> float | None:
    """
    جلب رصيد اللاعب من الـ API مباشرة
    Returns: الرصيد كـ float أو None
    """
    data = _make_request("getPlayerBalanceById", {"playerId": player_id})
    if not data:
        return None

    result = data.get("result", [])
    if isinstance(result, list) and result:
        return float(result[0].get("balance", 0))

    return None


def deposit_to_player(player_id: str, amount: float, comment: str = "") -> bool:
    """
    إيداع رصيد للاعب
    Args:
        player_id: ID اللاعب في iChancy
        amount: المبلغ (موجب)
    Returns: True إذا نجح
    """
    body = {
        "amount": float(amount),
        "comment": comment,
        "playerId": player_id,
        "currencyCode": CURRENCY,
        "currency": CURRENCY,
        "moneyStatus": 5
    }
    data = _make_request("depositToPlayer", body)
    if not data:
        return False

    # نجاح: result يحتوي على balance أو result = []
    result = data.get("result")
    if data.get("status") and result is not False:
        return True

    print(f"❌ فشل الإيداع للاعب: {_extract_error(data)}")
    return False


def withdraw_from_player(player_id: str, amount: float, comment: str = "") -> bool:
    """
    سحب رصيد من لاعب
    Args:
        player_id: ID اللاعب في iChancy
        amount: المبلغ (سيتم تحويله لسالب تلقائياً)
    Returns: True إذا نجح
    """
    body = {
        "amount": -abs(float(amount)),  # يجب أن يكون سالباً
        "comment": comment,
        "playerId": player_id,
        "currencyCode": CURRENCY,
        "currency": CURRENCY,
        "moneyStatus": 5
    }
    data = _make_request("withdrawFromPlayer", body)
    if not data:
        return False

    result = data.get("result")
    if data.get("status") and result is not False:
        return True

    print(f"❌ فشل السحب من اللاعب: {_extract_error(data)}")
    return False


# =============================
# دوال مساعدة مدمجة مع database.py
# =============================
def ensure_player_registered(user_id: int, username: str, password: str) -> bool:
    """
    التأكد من تسجيل اللاعب في iChancy أو إنشاء حساب جديد له
    - يبحث أولاً إذا كان موجوداً
    - ينشئ حساباً جديداً إذا لم يكن موجوداً
    Returns: True إذا الحساب جاهز
    """
    # البحث عن اللاعب
    player = get_player_by_username(username)
    if player:
        return True

    # إنشاء حساب جديد
    return register_player(username, password)


def sync_deposit_to_player(player_id: str, amount: float) -> bool:
    """
    إيداع مبلغ للاعب في iChancy
    يُستخدم عند قبول طلب شحن من الأدمن
    """
    return deposit_to_player(player_id, amount, comment="Bot deposit")


def sync_withdraw_from_player(player_id: str, amount: float) -> bool:
    """
    سحب مبلغ من اللاعب في iChancy
    يُستخدم عند قبول طلب سحب من الأدمن
    """
    return withdraw_from_player(player_id, amount, comment="Bot withdraw")


# =============================
# تهيئة عند الاستيراد
# =============================
def init_api():
    """
    تهيئة الـ API عند بدء تشغيل البوت
    استدعِ هذه الدالة مرة واحدة في بداية main.py
    """
    print("🔐 جاري تسجيل الدخول إلى iChancy API...")
    success = sign_in()
    if success:
        wallets = get_agent_wallets()
        if wallets:
            print(f"💰 رصيد الأيجنت: {wallets.get('balance')} {CURRENCY}")
    return success