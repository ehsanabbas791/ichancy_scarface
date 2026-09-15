import os
import sqlite3
import random
from contextlib import contextmanager
from typing import Optional

DB_PATH = os.getenv("BOT_DB_PATH", "databa.db")


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =========================================================
# إنشاء / تحديث قاعدة البيانات
# =========================================================

with _db() as conn:

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        spin_used BOOLEAN DEFAULT 0,
        ichancy_username TEXT DEFAULT NULL,
        ichancy_password TEXT DEFAULT NULL,
        agreed INTEGER DEFAULT 0,
        last_spin_date TEXT DEFAULT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS recharge_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        transaction_id TEXT NOT NULL,
        method TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        approved_at TIMESTAMP DEFAULT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        account TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('usdt_rate', '15000')
    """)

    # =====================================================
    # جداول الاسترداد الأسبوعي (Cashback)
    # =====================================================

    conn.execute("""
    CREATE TABLE IF NOT EXISTS ichancy_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        direction TEXT NOT NULL,
        amount_nsp REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_ichancy_tx_user
    ON ichancy_transactions(user_id, created_at)
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS cashback_snapshots (
        user_id INTEGER PRIMARY KEY,
        last_balance_nsp REAL DEFAULT 0,
        last_run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS cashback_payouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        loss_amount INTEGER NOT NULL,
        cashback_amount INTEGER NOT NULL,
        period_start TIMESTAMP,
        period_end TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =====================================================
    # جداول عمولة الإحالة المستمرة (Referral Commission)
    # =====================================================

    conn.execute("""
    CREATE TABLE IF NOT EXISTS referral_commissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER NOT NULL,
        referred_user_id INTEGER NOT NULL,
        recharge_amount INTEGER NOT NULL,
        commission_amount INTEGER NOT NULL,
        paid INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        paid_at TIMESTAMP DEFAULT NULL
    )
    """)

    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_referral_commissions_referrer
    ON referral_commissions(referrer_id, paid)
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS referral_payout_cycles (
        referrer_id INTEGER PRIMARY KEY,
        cycle_start_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =====================================================
    # جدول الإحالات
    # =====================================================

    conn.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        referrer_id INTEGER NOT NULL,

        referred_user_id INTEGER NOT NULL UNIQUE,

        status TEXT DEFAULT 'pending',

        reward INTEGER DEFAULT 0,

        rewarded INTEGER DEFAULT 0,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        activated_at TIMESTAMP DEFAULT NULL,

        UNIQUE(referrer_id, referred_user_id)
    )
    """)

    # =====================================================
    # تحديث recharge_requests القديمة
    # =====================================================

    cols = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(recharge_requests)"
        )
    }

    if "approved_at" not in cols:
        conn.execute("""
            ALTER TABLE recharge_requests
            ADD COLUMN approved_at TIMESTAMP DEFAULT NULL
        """)

    # =====================================================
    # تحديث users: عمود توقيت آخر لفة (لعد تنازلي حقيقي بالساعات)
    # =====================================================

    user_cols = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(users)"
        )
    }

    if "last_spin_at" not in user_cols:
        conn.execute("""
            ALTER TABLE users
            ADD COLUMN last_spin_at TIMESTAMP DEFAULT NULL
        """)

    # =====================================================
    # جدول جوائز عجلة الحظ (قابل للتعديل من لوحة الأدمن)
    # =====================================================

    conn.execute("""
    CREATE TABLE IF NOT EXISTS spin_prizes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        prize_type TEXT NOT NULL,
        amount INTEGER DEFAULT 0,
        weight INTEGER DEFAULT 1,
        active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0
    )
    """)

    existing_prizes = conn.execute("""
        SELECT COUNT(*) FROM spin_prizes
    """).fetchone()[0]

    if existing_prizes == 0:
        default_prizes = [
            ("🔄 لفة إضافية", "respin", 0, 15, 1),
            ("💰 1,000 ل.س", "cash", 1000, 25, 2),
            ("💵 10,000 ل.س", "cash", 10000, 8, 3),
            ("💎 200,000 ل.س", "cash", 200000, 1, 4),
            ("😔 حظ أوفر", "none", 0, 40, 5),
            ("🎁 3,000 ل.س", "cash", 3000, 5, 6),
        ]
        conn.executemany("""
            INSERT INTO spin_prizes (label, prize_type, amount, weight, sort_order)
            VALUES (?, ?, ?, ?, ?)
        """, default_prizes)

    # =====================================================
    # ترقية لمرة واحدة: تقصير نصوص الجوائز الافتراضية الطويلة
    # (فقط إذا لم يعدّلها الأدمن بعد) + استبدال "جائزة مميزة" بـ 3,000 ل.س
    # =====================================================

    already_migrated = conn.execute("""
        SELECT value FROM settings WHERE key='spin_prizes_migrated_v2'
    """).fetchone()

    if not already_migrated:

        conn.execute("""
            UPDATE spin_prizes
            SET label='🔄 لفة إضافية'
            WHERE label='🔄 لفة إضافية مجانية'
        """)

        conn.execute("""
            UPDATE spin_prizes
            SET label='😔 حظ أوفر'
            WHERE label='😔 حظ أوفر - جرب مرة تانية'
        """)

        conn.execute("""
            UPDATE spin_prizes
            SET label='🎁 3,000 ل.س', prize_type='cash', amount=3000
            WHERE label='🎁 جائزة مميزة - تواصل مع الإدارة'
            AND prize_type='custom_message'
        """)

        conn.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES ('spin_prizes_migrated_v2', '1')
        """)

    # =====================================================
    # معالجة عمليات الشحن المكررة القديمة
    # =====================================================

    duplicates = conn.execute("""
        SELECT method, transaction_id, MIN(id) AS keep_id
        FROM recharge_requests
        WHERE transaction_id IS NOT NULL
        AND transaction_id != ''
        GROUP BY method, transaction_id
        HAVING COUNT(*) > 1
    """).fetchall()

    for method, transaction_id, keep_id in duplicates:

        conn.execute("""
            UPDATE recharge_requests
            SET status='duplicate'
            WHERE method=?
            AND transaction_id=?
            AND id<>?
        """, (method, transaction_id, keep_id))

    # =====================================================
    # منع تكرار نفس العملية
    # =====================================================

    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_recharge_method_txid
        ON recharge_requests(method, transaction_id)
    """)


# =========================================================
# USERS
# =========================================================

def get_user(user_id):

    with _db() as conn:

        row = conn.execute("""
            SELECT balance,
                   ichancy_username,
                   ichancy_password,
                   agreed
            FROM users
            WHERE user_id=?
        """, (user_id,)).fetchone()

        if row is None:

            conn.execute("""
                INSERT INTO users (user_id)
                VALUES (?)
            """, (user_id,))

            return {
                "balance": 0,
                "ichancy_username": None,
                "ichancy_password": None,
                "agreed": 0
            }

        return dict(row)


def get_user_recharges(user_id):

    with _db() as conn:

        rows = conn.execute("""
            SELECT amount,
                   method,
                   transaction_id,
                   created_at
            FROM recharge_requests
            WHERE user_id=?
            ORDER BY created_at DESC
        """, (user_id,)).fetchall()

        return [tuple(r) for r in rows]


def get_user_withdraws(user_id):

    with _db() as conn:

        rows = conn.execute("""
            SELECT amount,
                   account,
                   created_at
            FROM withdraw_requests
            WHERE user_id=?
            ORDER BY created_at DESC
        """, (user_id,)).fetchall()

        return [tuple(r) for r in rows]


def update_recharge_status(user_id, amount, status):

    with _db() as conn:

        conn.execute("""
            UPDATE recharge_requests
            SET status=?
            WHERE user_id=?
            AND amount=?
            AND status='pending'
        """, (status, user_id, amount))


def update_withdraw_status(user_id, amount, status):

    with _db() as conn:

        conn.execute("""
            UPDATE withdraw_requests
            SET status=?
            WHERE user_id=?
            AND amount=?
            AND status='pending'
        """, (status, user_id, amount))


def update_ichancy_account(user_id, username, password):

    with _db() as conn:

        conn.execute("""
            UPDATE users
            SET ichancy_username=?,
                ichancy_password=?
            WHERE user_id=?
        """, (username, password, user_id))


def get_user_balance(user_id):

    with _db() as conn:

        row = conn.execute("""
            SELECT balance
            FROM users
            WHERE user_id=?
        """, (user_id,)).fetchone()

        if row is None:

            conn.execute("""
                INSERT INTO users (user_id)
                VALUES (?)
            """, (user_id,))

            return 0

        return int(row[0])


def update_balance(user_id, amount):

    with _db() as conn:

        conn.execute("""
            UPDATE users
            SET balance=balance+?
            WHERE user_id=?
        """, (int(amount), user_id))


def update_user_agreed(user_id, agreed: bool):

    with _db() as conn:

        conn.execute("""
            UPDATE users
            SET agreed=?
            WHERE user_id=?
        """, (1 if agreed else 0, user_id))


# =========================================================
# RECHARGE
# =========================================================

def create_recharge(user_id, amount, txid, method):

    with _db() as conn:

        cur = conn.execute("""
            INSERT INTO recharge_requests
                (user_id, amount, transaction_id, method)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            int(amount),
            str(txid).strip(),
            method
        ))

        return cur.lastrowid


def transaction_already_used(txid, method=None):

    with _db() as conn:

        if method is None:

            row = conn.execute("""
                SELECT id,
                       user_id,
                       amount,
                       method,
                       status
                FROM recharge_requests
                WHERE transaction_id=?
                LIMIT 1
            """, (str(txid).strip(),)).fetchone()

        else:

            row = conn.execute("""
                SELECT id,
                       user_id,
                       amount,
                       method,
                       status
                FROM recharge_requests
                WHERE transaction_id=?
                AND method=?
                LIMIT 1
            """, (
                str(txid).strip(),
                method
            )).fetchone()

        return dict(row) if row else None


# =========================================================
# APPROVE RECHARGE + REFERRAL
# =========================================================

def approve_verified_recharge(
    user_id: int,
    amount: int,
    txid: str,
    method: str,
    bonus_percent: float = 0.0,
):

    txid = str(txid).strip()
    amount = int(amount)
    method = str(method).strip()

    if amount <= 0 or not txid or not method:

        return {
            "ok": False,
            "status": "error",
            "message": "بيانات الشحن غير صالحة."
        }

    bonus = int(amount * float(bonus_percent))
    total = amount + bonus

    with _db() as conn:

        # =================================================
        # منع استخدام العملية مرتين
        # =================================================

        existing = conn.execute("""
            SELECT id,
                   user_id,
                   amount,
                   method,
                   status
            FROM recharge_requests
            WHERE method=?
            AND transaction_id=?
            LIMIT 1
        """, (method, txid)).fetchone()

        if existing:

            return {
                "ok": False,
                "status": "already_used",
                "message": "هذه العملية مستخدمة مسبقاً.",
                "existing": dict(existing)
            }

        # =================================================
        # إنشاء المستخدم إذا لم يكن موجوداً
        # =================================================

        conn.execute("""
            INSERT OR IGNORE INTO users (user_id)
            VALUES (?)
        """, (user_id,))

        # =================================================
        # تسجيل عملية الشحن
        # =================================================

        cur = conn.execute("""
            INSERT INTO recharge_requests
                (
                    user_id,
                    amount,
                    transaction_id,
                    method,
                    status,
                    approved_at
                )
            VALUES (?, ?, ?, ?, 'approved', CURRENT_TIMESTAMP)
        """, (
            user_id,
            amount,
            txid,
            method
        ))

        # =================================================
        # إضافة رصيد الشحن للمستخدم
        # =================================================

        conn.execute("""
            UPDATE users
            SET balance=balance+?
            WHERE user_id=?
        """, (
            total,
            user_id
        ))

        return {
            "ok": True,
            "status": "approved",
            "recharge_id": cur.lastrowid,
            "amount": amount,
            "bonus": bonus,
            "total": total
        }


# =========================================================
# WITHDRAW
# =========================================================

def create_withdraw(user_id, amount, account):

    with _db() as conn:

        cur = conn.execute("""
            INSERT INTO withdraw_requests
                (user_id, amount, account)
            VALUES (?, ?, ?)
        """, (
            user_id,
            int(amount),
            account
        ))

        return cur.lastrowid


# =========================================================
# GIFT CODES - أكواد الهدايا
# =========================================================

with _db() as conn:

    # جدول أكواد الهدايا
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gift_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            code TEXT NOT NULL UNIQUE,

            amount INTEGER NOT NULL,

            max_uses INTEGER NOT NULL DEFAULT 1,

            used_count INTEGER NOT NULL DEFAULT 0,

            active INTEGER NOT NULL DEFAULT 1,

            created_by INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            expires_at TIMESTAMP DEFAULT NULL
        )
    """)

    # جدول الأشخاص الذين استخدموا الأكواد
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gift_code_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            gift_code_id INTEGER NOT NULL,

            user_id INTEGER NOT NULL,

            amount INTEGER NOT NULL,

            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(gift_code_id, user_id),

            FOREIGN KEY(gift_code_id)
                REFERENCES gift_codes(id)
        )
    """)

    # تسريع البحث عن استخدامات الكود
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gift_code_uses_code
        ON gift_code_uses(gift_code_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gift_codes_code
        ON gift_codes(code)
    """)

# =========================================================
# USERS ADMIN
# =========================================================

def get_all_users():

    with _db() as conn:

        rows = conn.execute("""
            SELECT user_id,
                   balance,
                   ichancy_username
            FROM users
            WHERE agreed=1
            ORDER BY balance DESC
        """).fetchall()

        return [tuple(r) for r in rows]


# =========================================================
# SPIN
# =========================================================

def get_last_spin_date(user_id):

    with _db() as conn:

        row = conn.execute("""
            SELECT last_spin_date
            FROM users
            WHERE user_id=?
        """, (user_id,)).fetchone()

        return row[0] if row and row[0] else None


def update_last_spin_date(user_id, date):

    with _db() as conn:

        conn.execute("""
            INSERT OR IGNORE INTO users (user_id)
            VALUES (?)
        """, (user_id,))

        conn.execute("""
            UPDATE users
            SET last_spin_date=?
            WHERE user_id=?
        """, (
            date,
            user_id
        ))


def get_last_spin_at(user_id):
    """
    توقيت آخر لفة (كنص SQLite TIMESTAMP) أو None إذا لم يلف بعد.
    """

    with _db() as conn:

        row = conn.execute("""
            SELECT last_spin_at
            FROM users
            WHERE user_id=?
        """, (int(user_id),)).fetchone()

        return row[0] if row and row[0] else None


def update_last_spin_at(user_id, reset=False):
    """
    تحديث توقيت آخر لفة إلى الآن. إذا reset=True يصفّر التوقيت (None)
    ليصبح المستخدم مؤهلاً للفة فورية (يُستخدم عند ربح لفة إضافية).
    """

    with _db() as conn:

        conn.execute("""
            INSERT OR IGNORE INTO users (user_id)
            VALUES (?)
        """, (int(user_id),))

        if reset:
            conn.execute("""
                UPDATE users
                SET last_spin_at=NULL
                WHERE user_id=?
            """, (int(user_id),))
        else:
            conn.execute("""
                UPDATE users
                SET last_spin_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (int(user_id),))


def get_spin_cooldown_hours() -> int:

    with _db() as conn:

        row = conn.execute("""
            SELECT value
            FROM settings
            WHERE key='spin_cooldown_hours'
        """).fetchone()

        return int(row[0]) if row else 24


def set_spin_cooldown_hours(hours: int):

    with _db() as conn:

        conn.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES ('spin_cooldown_hours', ?)
        """, (str(int(hours)),))


# ---------------------------------------------------------
# جوائز عجلة الحظ
# ---------------------------------------------------------

def get_active_spin_prizes():
    """
    الجوائز الفعّالة فقط، مرتبة لعرضها على العجلة.
    """

    with _db() as conn:

        rows = conn.execute("""
            SELECT id, label, prize_type, amount, weight, sort_order
            FROM spin_prizes
            WHERE active=1
            ORDER BY sort_order, id
        """).fetchall()

        return [dict(r) for r in rows]


def get_all_spin_prizes():
    """
    كل الجوائز (فعّالة وغير فعّالة) لعرضها بلوحة الأدمن.
    """

    with _db() as conn:

        rows = conn.execute("""
            SELECT id, label, prize_type, amount, weight, active, sort_order
            FROM spin_prizes
            ORDER BY sort_order, id
        """).fetchall()

        return [dict(r) for r in rows]


def add_spin_prize(label, prize_type, amount=0, weight=1):

    with _db() as conn:

        max_order = conn.execute("""
            SELECT COALESCE(MAX(sort_order), 0) FROM spin_prizes
        """).fetchone()[0]

        conn.execute("""
            INSERT INTO spin_prizes (label, prize_type, amount, weight, sort_order)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(label),
            str(prize_type),
            int(amount),
            int(weight),
            int(max_order) + 1,
        ))


def set_spin_prize_active(prize_id, active: bool):

    with _db() as conn:

        conn.execute("""
            UPDATE spin_prizes
            SET active=?
            WHERE id=?
        """, (1 if active else 0, int(prize_id)))


def update_spin_prize_weight(prize_id, weight: int):

    with _db() as conn:

        conn.execute("""
            UPDATE spin_prizes
            SET weight=?
            WHERE id=?
        """, (int(weight), int(prize_id)))


def delete_spin_prize(prize_id):

    with _db() as conn:

        conn.execute("""
            DELETE FROM spin_prizes
            WHERE id=?
        """, (int(prize_id),))


def get_spin_prize(prize_id):

    with _db() as conn:

        row = conn.execute("""
            SELECT id, label, prize_type, amount, weight, active, sort_order
            FROM spin_prizes
            WHERE id=?
        """, (int(prize_id),)).fetchone()

        return dict(row) if row else None


def pick_random_spin_prize():
    """
    اختيار جائزة عشوائياً من الجوائز الفعّالة، بالاعتماد على الوزن
    النسبي (weight) لكل جائزة. القرار هنا من السيرفر حصراً — لا يُسمح
    لواجهة العجلة (WebApp) بتحديد النتيجة أبداً.
    """

    prizes = get_active_spin_prizes()

    if not prizes:
        return None

    weights = [max(0, p["weight"]) for p in prizes]

    if sum(weights) <= 0:
        return None

    return random.choices(prizes, weights=weights, k=1)[0]


# =========================================================
# USDT RATE
# =========================================================

def get_usdt_rate() -> int:

    with _db() as conn:

        row = conn.execute("""
            SELECT value
            FROM settings
            WHERE key='usdt_rate'
        """).fetchone()

        return int(row[0]) if row else 15000


def set_usdt_rate(rate: int):

    with _db() as conn:

        conn.execute("""
            INSERT OR REPLACE INTO settings
                (key,value)
            VALUES ('usdt_rate',?)
        """, (
            str(int(rate)),
        ))


# =========================================================
# ================= بونصات الشحن ==========================
# =========================================================

# القيم الافتراضية (تُستخدم فقط إذا لم يتم ضبط نسبة من لوحة الأدمن بعد)
DEFAULT_BONUS_PERCENTS = {
    "syriatel": 0.0,
    "shamcash": 0.05,
    "usdt": 0.08,
}


def get_bonus_percent(method_key: str) -> float:
    """
    جلب نسبة البونص (كنسبة عشرية، مثال: 0.08 = 8%) لطريقة شحن معينة.
    """

    with _db() as conn:

        row = conn.execute("""
            SELECT value
            FROM settings
            WHERE key=?
        """, (f"bonus_percent_{method_key}",)).fetchone()

        if row is not None:
            return float(row[0])

        return DEFAULT_BONUS_PERCENTS.get(method_key, 0.0)


def set_bonus_percent(method_key: str, percent: float):
    """
    حفظ نسبة البونص الجديدة لطريقة شحن معينة (كنسبة عشرية، مثال: 0.08 = 8%).
    """

    with _db() as conn:

        conn.execute("""
            INSERT OR REPLACE INTO settings
                (key, value)
            VALUES (?, ?)
        """, (
            f"bonus_percent_{method_key}",
            str(float(percent)),
        ))


def get_all_bonus_percents() -> dict:
    """
    جلب كل نسب البونص دفعة واحدة (لعرضها في لوحة الأدمن).
    """

    return {
        key: get_bonus_percent(key)
        for key in DEFAULT_BONUS_PERCENTS
    }


# =========================================================
# ============= الاسترداد الأسبوعي (Cashback) =============
# =========================================================

def log_ichancy_transaction(user_id, direction, amount_nsp):
    """
    تسجيل أي حركة شحن/سحب فعلية بين رصيد البوت وحساب iChancy
    الخاص بالمستخدم. هذا السجل هو أساس حساب صافي الخسارة لاحقاً.

    direction: 'in'  → شحن لحساب iChancy (رصيد داخل)
               'out' → سحب من حساب iChancy (رصيد خارج)
    """

    if direction not in ("in", "out"):
        return

    with _db() as conn:

        conn.execute("""
            INSERT INTO ichancy_transactions
                (user_id, direction, amount_nsp)
            VALUES (?, ?, ?)
        """, (
            int(user_id),
            direction,
            float(amount_nsp),
        ))


def get_ichancy_movement_since(user_id, since_ts):
    """
    ترجع (مجموع الشحن, مجموع السحب) بالـ NSP لحساب iChancy
    الخاص بالمستخدم منذ توقيت معين.
    """

    with _db() as conn:

        row = conn.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN direction='in'  THEN amount_nsp ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN direction='out' THEN amount_nsp ELSE 0 END), 0)
            FROM ichancy_transactions
            WHERE user_id=?
            AND created_at > ?
        """, (int(user_id), since_ts)).fetchone()

        return float(row[0]), float(row[1])


def get_cashback_snapshot(user_id):
    """
    جلب آخر نقطة مرجعية (رصيد iChancy + توقيت) للمستخدم.
    ترجع None إذا لم توجد بعد (أول مرة).
    """

    with _db() as conn:

        row = conn.execute("""
            SELECT last_balance_nsp, last_run_at
            FROM cashback_snapshots
            WHERE user_id=?
        """, (int(user_id),)).fetchone()

        return dict(row) if row else None


def init_cashback_snapshot_if_missing(user_id, balance_nsp):
    """
    إنشاء نقطة مرجعية أولى للمستخدم إذا لم تكن موجودة (لا تُستبدل
    نقطة موجودة مسبقاً).
    """

    with _db() as conn:

        conn.execute("""
            INSERT OR IGNORE INTO cashback_snapshots
                (user_id, last_balance_nsp, last_run_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (int(user_id), float(balance_nsp)))


def update_cashback_snapshot(user_id, balance_nsp):
    """
    تحديث نقطة المرجع بعد كل تنفيذ للاسترداد الأسبوعي.
    """

    with _db() as conn:

        conn.execute("""
            INSERT OR REPLACE INTO cashback_snapshots
                (user_id, last_balance_nsp, last_run_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (int(user_id), float(balance_nsp)))


def record_cashback_payout(user_id, loss_amount, cashback_amount, period_start, period_end):
    """
    تسجيل عملية استرداد أسبوعي منفذة (لأغراض السجل والتدقيق).
    """

    with _db() as conn:

        conn.execute("""
            INSERT INTO cashback_payouts
                (user_id, loss_amount, cashback_amount, period_start, period_end)
            VALUES (?, ?, ?, ?, ?)
        """, (
            int(user_id),
            int(loss_amount),
            int(cashback_amount),
            period_start,
            period_end,
        ))


def get_cashback_percent() -> float:
    """
    نسبة الاسترداد الأسبوعي الحالية (كنسبة عشرية، مثال: 0.1 = 10%).
    القيمة الافتراضية 0 (متوقف) حتى يضبطها الأدمن من اللوحة.
    """

    with _db() as conn:

        row = conn.execute("""
            SELECT value
            FROM settings
            WHERE key='cashback_percent'
        """).fetchone()

        return float(row[0]) if row else 0.0


def set_cashback_percent(percent: float):

    with _db() as conn:

        conn.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES ('cashback_percent', ?)
        """, (str(float(percent)),))


def get_users_with_ichancy():
    """
    كل المستخدمين الذين لديهم حساب iChancy مربوط (المرشحون للاسترداد الأسبوعي).
    """

    with _db() as conn:

        rows = conn.execute("""
            SELECT user_id, ichancy_username
            FROM users
            WHERE ichancy_username IS NOT NULL
            AND ichancy_username != ''
        """).fetchall()

        return [tuple(r) for r in rows]


def get_recent_cashback_payouts(limit=15):
    """
    آخر عمليات الاسترداد المنفذة (لعرضها للأدمن).
    """

    with _db() as conn:

        rows = conn.execute("""
            SELECT user_id, loss_amount, cashback_amount, created_at
            FROM cashback_payouts
            ORDER BY created_at DESC
            LIMIT ?
        """, (int(limit),)).fetchall()

        return [dict(row) for row in rows]


# =========================================================
# ================= REFERRAL SYSTEM ======================
# =========================================================


def set_referrer(referred_user_id, referrer_id):

    referred_user_id = int(referred_user_id)
    referrer_id = int(referrer_id)

    # لا يمكن إحالة المستخدم لنفسه
    if referred_user_id == referrer_id:
        return False

    with _db() as conn:

        # تأكد أن الاثنين موجودين
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id)
            VALUES (?)
        """, (referred_user_id,))

        conn.execute("""
            INSERT OR IGNORE INTO users (user_id)
            VALUES (?)
        """, (referrer_id,))

        # لا نسمح بتغيير المحيل لاحقاً
        existing = conn.execute("""
            SELECT id
            FROM referrals
            WHERE referred_user_id=?
            LIMIT 1
        """, (referred_user_id,)).fetchone()

        if existing:
            return False

        conn.execute("""
            INSERT INTO referrals
                (
                    referrer_id,
                    referred_user_id,
                    status
                )
            VALUES (?, ?, 'pending')
        """, (
            referrer_id,
            referred_user_id
        ))

        return True


def get_referral_info(user_id):

    with _db() as conn:

        total = conn.execute("""
            SELECT COUNT(*)
            FROM referrals
            WHERE referrer_id=?
        """, (user_id,)).fetchone()[0]

        active = conn.execute("""
            SELECT COUNT(*)
            FROM referrals
            WHERE referrer_id=?
            AND status='active'
        """, (user_id,)).fetchone()[0]

        earnings = conn.execute("""
            SELECT COALESCE(SUM(reward), 0)
            FROM referrals
            WHERE referrer_id=?
            AND rewarded=1
        """, (user_id,)).fetchone()[0]

        return {
            "total": int(total),
            "active": int(active),
            "earnings": int(earnings)
        }


def get_referrer(user_id):

    with _db() as conn:

        row = conn.execute("""
            SELECT referrer_id
            FROM referrals
            WHERE referred_user_id=?
            LIMIT 1
        """, (user_id,)).fetchone()

        return int(row[0]) if row else None


def activate_referral_after_recharge(
    referred_user_id,
    reward_amount=5000
):

    referred_user_id = int(referred_user_id)
    reward_amount = int(reward_amount)
   

    with _db() as conn:

        # ==============================================
        # لا تفعل الإحالة إلا بعد شحن ناجح فعلياً
        # ==============================================

        successful_recharge = conn.execute("""
            SELECT id
            FROM recharge_requests
            WHERE user_id=?
              AND status='approved'
            LIMIT 1
        """, (referred_user_id,)).fetchone()

        if not successful_recharge:
            return {
                "ok": False,
                "status": "no_successful_recharge"
            }

              

        referral = conn.execute("""
            SELECT id,
                   referrer_id,
                   status,
                   rewarded
            FROM referrals
            WHERE referred_user_id=?
            LIMIT 1
        """, (referred_user_id,)).fetchone()

        # لا يوجد محيل
        if not referral:
            return {
                "ok": False,
                "status": "no_referral"
            }

        # الإحالة مفعلة مسبقاً
        if referral["status"] == "active":
            return {
                "ok": False,
                "status": "already_active",
                "referrer_id": referral["referrer_id"]
            }

        referrer_id = int(referral["referrer_id"])

        # ================================================
        # تفعيل الإحالة
        # ================================================

        conn.execute("""
            UPDATE referrals
            SET status='active',
                activated_at=CURRENT_TIMESTAMP
            WHERE id=?
            AND status='pending'
        """, (referral["id"],))

        # ================================================
        # عدد الإحالات النشطة
        # ================================================

        active_count = conn.execute("""
            SELECT COUNT(*)
            FROM referrals
            WHERE referrer_id=?
            AND status='active'
        """, (referrer_id,)).fetchone()[0]

        # ================================================
        # الشرط: يجب أن يكون لديه 3 إحالات نشطة
        # ================================================

        if active_count < 3:

            return {
                "ok": True,
                "status": "activated_no_reward",
                "referrer_id": referrer_id,
                "active_count": active_count,
                "reward": 0
            }

        # ================================================
        # إعطاء المكافأة لهذه الإحالة فقط
        # ================================================

        if referral["rewarded"] == 0:

            conn.execute("""
                UPDATE users
                SET balance=balance+?
                WHERE user_id=?
            """, (
                reward_amount,
                referrer_id
            ))

            conn.execute("""
                UPDATE referrals
                SET reward=?,
                    rewarded=1
                WHERE id=?
            """, (
                reward_amount,
                referral["id"]
            ))

            return {
                "ok": True,
                "status": "rewarded",
                "referrer_id": referrer_id,
                "active_count": active_count,
                "reward": reward_amount
            }

        return {
            "ok": True,
            "status": "already_rewarded",
            "referrer_id": referrer_id,
            "active_count": active_count,
            "reward": 0
        }


def get_referral_users(user_id):

    with _db() as conn:

        rows = conn.execute("""
            SELECT referred_user_id,
                   status,
                   reward,
                   created_at,
                   activated_at
            FROM referrals
            WHERE referrer_id=?
            ORDER BY created_at DESC
        """, (user_id,)).fetchall()

        return [dict(r) for r in rows]


def get_all_referrals():

    with _db() as conn:

        rows = conn.execute("""
            SELECT referrer_id,
                   referred_user_id,
                   status,
                   reward,
                   created_at,
                   activated_at
            FROM referrals
            ORDER BY created_at DESC
        """).fetchall()

        return [dict(r) for r in rows]


# =========================================================
# ========= عمولة الإحالة المستمرة (Referral Commission) ==
# =========================================================

def get_referral_commission_percent() -> float:
    """
    نسبة عمولة الإحالة المستمرة (كنسبة عشرية، مثال: 0.05 = 5%).
    القيمة الافتراضية 0 (متوقف) حتى يضبطها الأدمن من اللوحة.
    """

    with _db() as conn:

        row = conn.execute("""
            SELECT value
            FROM settings
            WHERE key='referral_commission_percent'
        """).fetchone()

        return float(row[0]) if row else 0.0


def set_referral_commission_percent(percent: float):

    with _db() as conn:

        conn.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES ('referral_commission_percent', ?)
        """, (str(float(percent)),))


def get_referral_period_days() -> int:
    """
    عدد أيام دورة تراكم/توزيع أرباح الإحالة. القيمة الافتراضية 10 أيام.
    """

    with _db() as conn:

        row = conn.execute("""
            SELECT value
            FROM settings
            WHERE key='referral_period_days'
        """).fetchone()

        return int(row[0]) if row else 10


def set_referral_period_days(days: int):

    with _db() as conn:

        conn.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES ('referral_period_days', ?)
        """, (str(int(days)),))


def log_referral_commission(referrer_id, referred_user_id, recharge_amount, commission_amount):
    """
    تسجيل عمولة إحالة متراكمة (لم تُصرف بعد) نتيجة شحن ناجح لمستخدم مُحال.
    """

    with _db() as conn:

        conn.execute("""
            INSERT INTO referral_commissions
                (referrer_id, referred_user_id, recharge_amount, commission_amount)
            VALUES (?, ?, ?, ?)
        """, (
            int(referrer_id),
            int(referred_user_id),
            int(recharge_amount),
            int(commission_amount),
        ))


def get_pending_commission_total(referrer_id) -> int:

    with _db() as conn:

        row = conn.execute("""
            SELECT COALESCE(SUM(commission_amount), 0)
            FROM referral_commissions
            WHERE referrer_id=?
            AND paid=0
        """, (int(referrer_id),)).fetchone()

        return int(row[0])


def mark_referral_commissions_paid(referrer_id):

    with _db() as conn:

        conn.execute("""
            UPDATE referral_commissions
            SET paid=1, paid_at=CURRENT_TIMESTAMP
            WHERE referrer_id=?
            AND paid=0
        """, (int(referrer_id),))


def init_referral_cycle_if_missing(referrer_id):

    with _db() as conn:

        conn.execute("""
            INSERT OR IGNORE INTO referral_payout_cycles (referrer_id)
            VALUES (?)
        """, (int(referrer_id),))


def get_referral_cycle_start(referrer_id):
    """
    ترجع توقيت بداية دورة الأرباح الحالية لهذا المُحيل (نص بصيغة SQLite).
    """

    with _db() as conn:

        row = conn.execute("""
            SELECT cycle_start_at
            FROM referral_payout_cycles
            WHERE referrer_id=?
        """, (int(referrer_id),)).fetchone()

        return row[0] if row else None


def reset_referral_cycle(referrer_id):

    with _db() as conn:

        conn.execute("""
            INSERT OR REPLACE INTO referral_payout_cycles (referrer_id, cycle_start_at)
            VALUES (?, CURRENT_TIMESTAMP)
        """, (int(referrer_id),))


def get_all_referrer_ids():
    """
    كل معرّفات المستخدمين الذين لديهم إحالة واحدة على الأقل (مُحيلين).
    """

    with _db() as conn:

        rows = conn.execute("""
            SELECT DISTINCT referrer_id
            FROM referrals
        """).fetchall()

        return [int(r[0]) for r in rows]


def get_recent_referral_payouts(limit=15):

    with _db() as conn:

        rows = conn.execute("""
            SELECT referrer_id, SUM(commission_amount) as total, MAX(paid_at) as paid_at
            FROM referral_commissions
            WHERE paid=1
            GROUP BY referrer_id, paid_at
            ORDER BY paid_at DESC
            LIMIT ?
        """, (int(limit),)).fetchall()

        return [dict(row) for row in rows]
    # =========================================================
# GIFT CODES FUNCTIONS
# =========================================================

def create_gift_code(code, amount, max_uses, created_by=None, expires_at=None):
    """
    إنشاء كود هدية جديد.

    code        = نص الكود
    amount      = قيمة الهدية
    max_uses    = عدد مرات الاستخدام
    created_by  = ID الأدمن
    expires_at  = تاريخ الانتهاء اختياري
    """

    code = str(code).strip().upper()
    amount = int(amount)
    max_uses = int(max_uses)

    if not code:
        return False

    if amount <= 0:
        return False

    if max_uses <= 0:
        return False

    try:
        with _db() as conn:

            cur = conn.execute("""
                INSERT INTO gift_codes
                (
                    code,
                    amount,
                    max_uses,
                    used_count,
                    active,
                    created_by,
                    expires_at
                )
                VALUES (?, ?, ?, 0, 1, ?, ?)
            """, (
                code,
                amount,
                max_uses,
                created_by,
                expires_at
            ))

            return cur.lastrowid

    except sqlite3.IntegrityError:
        # الكود موجود مسبقاً
        return False


def get_gift_code(code):
    """
    جلب معلومات كود هدية.
    """

    code = str(code).strip().upper()

    with _db() as conn:

        row = conn.execute("""
            SELECT
                id,
                code,
                amount,
                max_uses,
                used_count,
                active,
                created_by,
                created_at,
                expires_at
            FROM gift_codes
            WHERE code=?
            LIMIT 1
        """, (code,)).fetchone()

        return dict(row) if row else None


def get_all_gift_codes():
    """
    جلب جميع أكواد الهدايا للأدمن.
    """

    with _db() as conn:

        rows = conn.execute("""
            SELECT
                id,
                code,
                amount,
                max_uses,
                used_count,
                active,
                created_by,
                created_at,
                expires_at
            FROM gift_codes
            ORDER BY created_at DESC
        """).fetchall()

        return [dict(row) for row in rows]


def deactivate_gift_code(code):
    """
    إيقاف كود هدية.
    """

    code = str(code).strip().upper()

    with _db() as conn:

        cur = conn.execute("""
            UPDATE gift_codes
            SET active=0
            WHERE code=?
        """, (code,))

        return cur.rowcount > 0


def activate_gift_code(code):
    """
    إعادة تفعيل كود هدية.
    """

    code = str(code).strip().upper()

    with _db() as conn:

        cur = conn.execute("""
            UPDATE gift_codes
            SET active=1
            WHERE code=?
        """, (code,))

        return cur.rowcount > 0


def has_user_used_gift_code(user_id, gift_code_id):
    """
    التحقق إذا المستخدم استخدم الكود سابقاً.
    """

    with _db() as conn:

        row = conn.execute("""
            SELECT id
            FROM gift_code_uses
            WHERE gift_code_id=?
            AND user_id=?
            LIMIT 1
        """, (
            int(gift_code_id),
            int(user_id)
        )).fetchone()

        return row is not None


def redeem_gift_code(user_id, code):
    """
    استبدال كود هدية وإضافة الرصيد للمستخدم.

    العملية كلها تتم داخل Transaction واحدة
    لمنع استخدام آخر استخدام للكود مرتين.
    """

    user_id = int(user_id)
    code = str(code).strip().upper()

    if not code:
        return {
            "ok": False,
            "status": "invalid_code"
        }

    with _db() as conn:

        # =====================================================
        # جلب الكود
        # =====================================================

        gift = conn.execute("""
            SELECT
                id,
                code,
                amount,
                max_uses,
                used_count,
                active,
                expires_at
            FROM gift_codes
            WHERE code=?
            LIMIT 1
        """, (code,)).fetchone()

        if not gift:

            return {
                "ok": False,
                "status": "not_found"
            }

        gift = dict(gift)

        # =====================================================
        # التحقق من حالة الكود
        # =====================================================

        if int(gift["active"]) != 1:

            return {
                "ok": False,
                "status": "inactive"
            }

        # =====================================================
        # التحقق من تاريخ الانتهاء
        # =====================================================

        if gift["expires_at"]:

            expired = conn.execute("""
                SELECT
                    CASE
                        WHEN CURRENT_TIMESTAMP > ?
                        THEN 1
                        ELSE 0
                    END
            """, (gift["expires_at"],)).fetchone()[0]

            if expired:

                return {
                    "ok": False,
                    "status": "expired"
                }

        # =====================================================
        # التحقق من عدد الاستخدامات
        # =====================================================

        if int(gift["used_count"]) >= int(gift["max_uses"]):

            return {
                "ok": False,
                "status": "limit_reached"
            }

        # =====================================================
        # التحقق هل المستخدم استخدم الكود سابقاً
        # =====================================================

        already_used = conn.execute("""
            SELECT id
            FROM gift_code_uses
            WHERE gift_code_id=?
            AND user_id=?
            LIMIT 1
        """, (
            gift["id"],
            user_id
        )).fetchone()

        if already_used:

            return {
                "ok": False,
                "status": "already_used"
            }

        # =====================================================
        # إنشاء المستخدم إذا غير موجود
        # =====================================================

        conn.execute("""
            INSERT OR IGNORE INTO users (user_id)
            VALUES (?)
        """, (user_id,))

        # =====================================================
        # تسجيل استخدام الكود
        # =====================================================

        try:

            conn.execute("""
                INSERT INTO gift_code_uses
                (
                    gift_code_id,
                    user_id,
                    amount
                )
                VALUES (?, ?, ?)
            """, (
                gift["id"],
                user_id,
                gift["amount"]
            ))

        except sqlite3.IntegrityError:

            return {
                "ok": False,
                "status": "already_used"
            }

        # =====================================================
        # إضافة الرصيد للمستخدم
        # =====================================================

        conn.execute("""
            UPDATE users
            SET balance = balance + ?
            WHERE user_id=?
        """, (
            int(gift["amount"]),
            user_id
        ))

        # =====================================================
        # زيادة عدد استخدامات الكود
        # =====================================================

        conn.execute("""
            UPDATE gift_codes
            SET used_count = used_count + 1
            WHERE id=?
        """, (gift["id"],))

        # =====================================================
        # عدد الاستخدامات بعد العملية
        # =====================================================

        new_used_count = int(gift["used_count"]) + 1

        # إذا وصل للحد يتم تعطيله تلقائياً
        if new_used_count >= int(gift["max_uses"]):

            conn.execute("""
                UPDATE gift_codes
                SET active=0
                WHERE id=?
            """, (gift["id"],))

        # =====================================================
        # النتيجة
        # =====================================================

        return {
            "ok": True,
            "status": "redeemed",
            "code": gift["code"],
            "amount": int(gift["amount"]),
            "used_count": new_used_count,
            "max_uses": int(gift["max_uses"])
        }


def get_gift_code_uses(code):
    """
    جلب الأشخاص الذين استخدموا كود معين.
    """

    code = str(code).strip().upper()

    with _db() as conn:

        rows = conn.execute("""
            SELECT
                gcu.user_id,
                gcu.amount,
                gcu.used_at
            FROM gift_code_uses gcu
            INNER JOIN gift_codes gc
                ON gc.id = gcu.gift_code_id
            WHERE gc.code=?
            ORDER BY gcu.used_at DESC
        """, (code,)).fetchall()

        return [dict(row) for row in rows]