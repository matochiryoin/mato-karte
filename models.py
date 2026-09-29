from datetime import date, datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    chart_no = db.Column(db.String(20), unique=True, nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name_kana = db.Column(db.String(50))
    first_name_kana = db.Column(db.String(50))
    phone = db.Column(db.String(20))
    mobile = db.Column(db.String(20))
    preferred_contact = db.Column(db.String(10))
    email = db.Column(db.String(120))
    postal_code = db.Column(db.String(10))
    prefecture = db.Column(db.String(20))
    city = db.Column(db.String(50))
    town = db.Column(db.String(50))
    street = db.Column(db.String(50))
    building = db.Column(db.String(50))
    gender = db.Column(db.String(10))
    marital_status = db.Column(db.String(10))
    blood_type = db.Column(db.String(10))
    occupation = db.Column(db.String(50))
    birth_date = db.Column(db.Date)
    memo = db.Column(db.Text)
    registered_date = db.Column(db.Date)
    first_visit_date = db.Column(db.Date)
    last_visit_date = db.Column(db.Date)
    bonbone_customer_id = db.Column(db.String(30))
    age_bracket = db.Column(db.String(10))
    visit_motivation = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def address(self):
        parts = [self.prefecture, self.city, self.town, self.street, self.building]
        text = "".join(p for p in parts if p)
        return f"〒{self.postal_code} {text}" if self.postal_code and text else (text or "")

    visits = db.relationship(
        "Visit", back_populates="patient", order_by="Visit.visit_date.desc()", cascade="all, delete-orphan"
    )
    reservations = db.relationship("Reservation", back_populates="patient", cascade="all, delete-orphan")
    sales = db.relationship("Sale", back_populates="patient", cascade="all, delete-orphan")

    @property
    def full_name(self):
        return f"{self.last_name} {self.first_name}"

    @property
    def full_name_kana(self):
        if self.last_name_kana or self.first_name_kana:
            return f"{self.last_name_kana or ''} {self.first_name_kana or ''}".strip()
        return ""

    @property
    def last_visit(self):
        return self.visits[0] if self.visits else None


class Visit(db.Model):
    __tablename__ = "visits"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    visit_date = db.Column(db.Date, nullable=False, default=date.today)
    staff = db.Column(db.String(50))

    base_service = db.Column(db.String(50))
    additional_service = db.Column(db.String(50))
    ticket = db.Column(db.String(50))

    diagnosis = db.Column(db.String(200))
    chief_complaint_1 = db.Column(db.String(200))
    chief_complaint_2 = db.Column(db.String(200))
    chief_complaint_3 = db.Column(db.String(200))
    content = db.Column(db.Text)
    memo = db.Column(db.Text)
    ticket_use_11 = db.Column(db.String(100))
    ticket_use_5 = db.Column(db.String(100))

    # bonboneの全カルテ抽出で来る可能性がある項目。日々の問診入力フォームでは使わないが、
    # 過去データの取り込みで消さずに残すための保管場所。
    treatment_memo = db.Column(db.Text)
    pain_scale = db.Column(db.Integer)
    disease_category = db.Column(db.String(200))
    custom_field_1 = db.Column(db.Text)
    custom_field_2 = db.Column(db.Text)
    external_source = db.Column(db.String(20))
    external_id = db.Column(db.String(40))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = db.relationship("Patient", back_populates="visits")
    photos = db.relationship("Photo", back_populates="visit", cascade="all, delete-orphan")


class Reservation(db.Model):
    __tablename__ = "reservations"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    reservation_date = db.Column(db.Date, nullable=False)
    start_min = db.Column(db.Integer, nullable=False)
    end_min = db.Column(db.Integer, nullable=False)
    staff = db.Column(db.String(50), nullable=False, default="")
    nominated = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(10), nullable=False, default="予約")
    cancel_reason = db.Column(db.Text)
    memo = db.Column(db.Text)
    reservation_type = db.Column(db.String(10), nullable=False, default="通常予約")
    sales_type = db.Column(db.String(10), nullable=False, default="売上")
    menu = db.Column(db.String(300), default="")
    arrival_min = db.Column(db.Integer)
    treatment_start_min = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("Patient", back_populates="reservations")
    sales = db.relationship("Sale", back_populates="reservation")

    @property
    def paid(self):
        return bool(self.sales)

    @property
    def menu_list(self):
        return [x for x in (self.menu or "").split(",") if x]

    @property
    def is_new_patient(self):
        earlier = [r for r in self.patient.reservations if r.status not in CANCELLED_STATUSES
                   and (r.reservation_date, r.start_min, r.id) < (self.reservation_date, self.start_min, self.id)]
        return not earlier and not self.patient.visits

    @property
    def time_range(self):
        return f"{fmt_min(self.start_min)}〜{fmt_min(self.end_min)}"


PRODUCT_CATEGORIES = ["技術", "回数券", "店販"]
PAYMENT_METHODS = ["現金", "クレジット", "電子マネー", "商品券", "売掛"]
SALES_TYPES = ["売上", "お直し"]
TAX_TYPES = ["内税", "外税"]
TAX_RATE_PERCENT = 10


def tax_included(total):
    """内税額（税込金額から逆算、四捨五入）"""
    return (total * TAX_RATE_PERCENT + (100 + TAX_RATE_PERCENT) // 2) // (100 + TAX_RATE_PERCENT)


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    category = db.Column(db.String(10), nullable=False, default="技術")
    price = db.Column(db.Integer, nullable=False, default=0)
    tax_type = db.Column(db.String(4), nullable=False, default="内税")
    active = db.Column(db.Boolean, nullable=False, default=True)


def ordered_products(active_only=True):
    query = Product.query.filter_by(active=True) if active_only else Product.query
    return sorted(query.order_by(Product.id).all(), key=lambda p: PRODUCT_CATEGORIES.index(p.category))


class Sale(db.Model):
    __tablename__ = "sales"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    reservation_id = db.Column(db.Integer, db.ForeignKey("reservations.id"))
    sale_date = db.Column(db.Date, nullable=False)
    staff = db.Column(db.String(50), default="")
    nominated = db.Column(db.Boolean, default=False)
    tendered = db.Column(db.Integer)
    memo = db.Column(db.Text)
    external_id = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("Patient", back_populates="sales")
    reservation = db.relationship("Reservation", back_populates="sales")
    lines = db.relationship("SaleLine", back_populates="sale", cascade="all, delete-orphan", order_by="SaleLine.id")
    payments = db.relationship("Payment", back_populates="sale", cascade="all, delete-orphan", order_by="Payment.id")

    def gross(self, category):
        return sum(l.gross for l in self.lines if l.category == category)

    @property
    def tech_total(self):
        return self.gross("技術")

    @property
    def ticket_total(self):
        return self.gross("回数券")

    @property
    def shop_total(self):
        return self.gross("店販")

    @property
    def discount_total(self):
        return sum(l.discount for l in self.lines)

    @property
    def exclusive_tax(self):
        """外税商品の消費税（税抜小計×10%、四捨五入）"""
        base = sum(l.amount for l in self.lines if l.tax_type == "外税")
        return (base * TAX_RATE_PERCENT + 50) // 100

    @property
    def inclusive_tax(self):
        return tax_included(sum(l.amount for l in self.lines if l.tax_type != "外税"))

    @property
    def total(self):
        return sum(l.amount for l in self.lines) + self.exclusive_tax

    @property
    def tax(self):
        return self.inclusive_tax + self.exclusive_tax

    @property
    def paid_total(self):
        return sum(p.amount for p in self.payments)

    @property
    def change(self):
        cash = sum(p.amount for p in self.payments if p.method == "現金")
        if self.tendered is None or not cash:
            return 0
        return max(self.tendered - cash, 0)


class SaleLine(db.Model):
    __tablename__ = "sale_lines"

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), nullable=False)
    sales_type = db.Column(db.String(10), nullable=False, default="売上")
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(10), nullable=False, default="技術")
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Integer, nullable=False, default=0)
    discount = db.Column(db.Integer, nullable=False, default=0)
    tax_type = db.Column(db.String(4), nullable=False, default="内税")
    staff = db.Column(db.String(50), default="")
    nominated = db.Column(db.Boolean, default=False)

    sale = db.relationship("Sale", back_populates="lines")

    @property
    def gross(self):
        return self.quantity * self.unit_price

    @property
    def amount(self):
        return self.gross - self.discount


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), nullable=False)
    method = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Integer, nullable=False, default=0)

    sale = db.relationship("Sale", back_populates="payments")


class StoreSchedule(db.Model):
    """予約グラフの「お店の予定」行。スタッフに紐づかない店舗全体の予定（休み・イベント等）。"""
    __tablename__ = "store_schedules"

    id = db.Column(db.Integer, primary_key=True)
    schedule_date = db.Column(db.Date, nullable=False)
    start_min = db.Column(db.Integer, nullable=False)
    end_min = db.Column(db.Integer, nullable=False)
    message = db.Column(db.String(200), default="")
    color = db.Column(db.String(7), nullable=False, default="#ef9245")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def time_range(self):
        return f"{fmt_min(self.start_min)}〜{fmt_min(self.end_min)}"


class StoreScheduleTemplate(db.Model):
    """よく使う「お店の予定」の名前と色をワンタップで選べるようにする定型（例：夏休み、休診日）。"""
    __tablename__ = "store_schedule_templates"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(50), nullable=False, unique=True)
    color = db.Column(db.String(7), nullable=False, default="#ef9245")


class Photo(db.Model):
    __tablename__ = "photos"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    visit = db.relationship("Visit", back_populates="photos")


def fmt_min(minutes):
    return f"{minutes // 60}:{minutes % 60:02d}"


STAFF_LIST = ["尾崎 誠"]
DAY_START_MIN = 9 * 60
DAY_END_MIN = 21 * 60
SLOT_MIN = 15
RESERVATION_STATUSES = ["予約", "来院", "キャンセル", "無断キャンセル"]
CANCELLED_STATUSES = ("キャンセル", "無断キャンセル")

AGE_BRACKETS = ["10代未満", "10代", "20代", "30代", "40代", "50代", "60代", "70代以上", "不明"]
GENDER_OPTIONS = ["女性", "男性", "ユニセックス"]
MARITAL_OPTIONS = ["未婚", "既婚"]
BLOOD_OPTIONS = ["不明", "A", "B", "O", "AB"]
CONTACT_OPTIONS = ["携帯番号", "電話番号"]
SALE_GENDER_OPTIONS = ["不明", "女性", "男性", "ユニセックス"]

BASE_SERVICE_OPTIONS = [
    "はり治療", "マッサージ治療コース", "小児はり", "チーム学生", "学生料金",
    "フォームソティックス", "リハビリコンディショニング", "テープ100", "テープ200",
    "プライロックテープ", "チャージ君",
]
ADDITIONAL_SERVICE_OPTIONS = ["はり(追加)", "美容鍼(追加)", "チャージ君(追加)"]
TICKET_OPTIONS = ["治療11回分回数券", "治療5回分回数券", "チャージ君11回分回数券", "11回分美脚"]
