import os
import secrets
from datetime import date, datetime, timedelta

from flask import Flask, redirect, render_template, request, url_for, flash, session, send_from_directory
from werkzeug.utils import secure_filename

from models import (db, Patient, Visit, Photo, BASE_SERVICE_OPTIONS, ADDITIONAL_SERVICE_OPTIONS, TICKET_OPTIONS,
                    GENDER_OPTIONS, MARITAL_OPTIONS, BLOOD_OPTIONS, CONTACT_OPTIONS,
                    Reservation, ordered_products, fmt_min, STAFF_LIST, DAY_START_MIN, DAY_END_MIN, SLOT_MIN, SALES_TYPES,
                    StoreSchedule, StoreScheduleTemplate, CANCELLED_STATUSES)
from sales import register as register_sales, seed_products
from data_transfer import register as register_data_transfer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# クラウドに置いたとき、ここ（永続ディスクのマウント先）をKARTE_DATA_DIRで指定する。
# ローカルではこのフォルダ自身のまま変わらない。
DATA_DIR = os.environ.get("KARTE_DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(DATA_DIR, 'karte.db')}"
app.config["SECRET_KEY"] = os.environ.get("KARTE_SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB
db.init_app(app)
app.jinja_env.filters["hm"] = fmt_min

with app.app_context():
    db.create_all()
    seed_products()

register_sales(app)
register_data_transfer(app)

# ---- ログイン（まことさん一人だけが使う想定の、共有パスワード1つの簡易ログイン） ----
KARTE_PASSWORD = os.environ.get("KARTE_PASSWORD", "matochiryoin")
PUBLIC_ENDPOINTS = {"login", "static", "uploaded_file"}


@app.before_request
def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if not session.get("logged_in"):
        return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), KARTE_PASSWORD):
            session["logged_in"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("patient_list"))
        flash("パスワードが違います")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


def next_chart_no():
    numbers = [int(p.chart_no) for p in Patient.query.all() if p.chart_no.isdigit() and len(p.chart_no) <= 6]
    return str(max(numbers) + 1) if numbers else "10001"


@app.route("/")
def patient_list():
    q = request.args.get("q", "").strip()
    query = Patient.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Patient.last_name.like(like),
                Patient.first_name.like(like),
                Patient.last_name_kana.like(like),
                Patient.first_name_kana.like(like),
                Patient.phone.like(like),
                Patient.chart_no.like(like),
            )
        )
    per_page = 50
    total = query.count()
    page = min(max(request.args.get("page", 1, type=int), 1), max((total + per_page - 1) // per_page, 1))
    patients = (query.order_by(Patient.last_name_kana, Patient.first_name_kana, Patient.id)
                .offset((page - 1) * per_page).limit(per_page).all())
    return render_template("patient_list.html", patients=patients, q=q, page=page, total=total,
                           pages=max((total + per_page - 1) // per_page, 1))


PATIENT_TEXT_FIELDS = [
    "last_name", "first_name", "last_name_kana", "first_name_kana", "phone", "mobile", "preferred_contact",
    "email", "postal_code", "prefecture", "city", "town", "street", "building", "gender", "marital_status",
    "blood_type", "occupation", "memo",
]


def _apply_patient_form(patient, form):
    for f in PATIENT_TEXT_FIELDS:
        setattr(patient, f, form.get(f, "").strip())
    birth = form.get("birth_date")
    patient.birth_date = datetime.strptime(birth, "%Y-%m-%d").date() if birth else None


def _patient_form_options():
    return dict(gender_options=GENDER_OPTIONS, marital_options=MARITAL_OPTIONS,
                blood_options=BLOOD_OPTIONS, contact_options=CONTACT_OPTIONS)


@app.route("/patients/new", methods=["GET", "POST"])
def patient_new():
    if request.method == "POST":
        patient = Patient(chart_no=request.form.get("chart_no") or next_chart_no())
        _apply_patient_form(patient, request.form)
        db.session.add(patient)
        db.session.commit()
        flash(f"{patient.full_name} 様を登録しました")
        return redirect(url_for("patient_detail", patient_id=patient.id))
    return render_template("patient_form.html", patient=None, next_chart_no=next_chart_no(), **_patient_form_options())


@app.route("/patients/<int:patient_id>")
def patient_detail(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    return render_template("patient_detail.html", patient=patient)


@app.route("/patients/<int:patient_id>/edit", methods=["GET", "POST"])
def patient_edit(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    if request.method == "POST":
        _apply_patient_form(patient, request.form)
        db.session.commit()
        flash("患者情報を更新しました")
        return redirect(url_for("patient_detail", patient_id=patient.id))
    return render_template("patient_form.html", patient=patient, next_chart_no=None, **_patient_form_options())


@app.route("/patients/<int:patient_id>/delete", methods=["GET", "POST"])
def patient_delete(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    if request.method == "POST":
        name = patient.full_name
        photo_files = [p.filename for v in patient.visits for p in v.photos]
        db.session.delete(patient)
        db.session.commit()
        for filename in photo_files:
            path = os.path.join(UPLOAD_DIR, filename)
            if os.path.exists(path):
                os.remove(path)
        flash(f"{name} 様を削除しました")
        return redirect(url_for("patient_list"))
    return render_template("patient_delete.html", patient=patient)


@app.route("/patients/<int:patient_id>/visits/new", methods=["GET", "POST"])
def visit_new(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    if request.method == "POST":
        visit = Visit(patient_id=patient.id, staff=request.form.get("staff", ""))
        _apply_visit_form(visit, request.form)
        db.session.add(visit)
        db.session.commit()
        flash("カルテを保存しました")
        return redirect(url_for("visit_detail", visit_id=visit.id))
    return render_template(
        "visit_form.html",
        patient=patient,
        visit=None,
        prefill=patient.last_visit,
        today=request.args.get("date") or date.today().isoformat(),
        base_service_options=BASE_SERVICE_OPTIONS,
        additional_service_options=ADDITIONAL_SERVICE_OPTIONS,
        ticket_options=TICKET_OPTIONS,
    )


@app.route("/visits/<int:visit_id>")
def visit_detail(visit_id):
    visit = Visit.query.get_or_404(visit_id)
    return render_template("visit_detail.html", visit=visit, patient=visit.patient)


@app.route("/visits/<int:visit_id>/edit", methods=["GET", "POST"])
def visit_edit(visit_id):
    visit = Visit.query.get_or_404(visit_id)
    if request.method == "POST":
        visit.staff = request.form.get("staff", "")
        _apply_visit_form(visit, request.form)
        db.session.commit()
        flash("カルテを更新しました")
        return redirect(url_for("visit_detail", visit_id=visit.id))
    return render_template(
        "visit_form.html",
        patient=visit.patient,
        visit=visit,
        prefill=visit,
        today=visit.visit_date.isoformat(),
        base_service_options=BASE_SERVICE_OPTIONS,
        additional_service_options=ADDITIONAL_SERVICE_OPTIONS,
        ticket_options=TICKET_OPTIONS,
    )


def _apply_visit_form(visit, form):
    visit_date = form.get("visit_date")
    visit.visit_date = datetime.strptime(visit_date, "%Y-%m-%d").date() if visit_date else date.today()
    visit.base_service = form.get("base_service", "")
    visit.additional_service = form.get("additional_service", "")
    visit.ticket = form.get("ticket", "")
    visit.diagnosis = form.get("diagnosis", "")
    visit.chief_complaint_1 = form.get("chief_complaint_1", "")
    visit.chief_complaint_2 = form.get("chief_complaint_2", "")
    visit.chief_complaint_3 = form.get("chief_complaint_3", "")
    visit.content = form.get("content", "")
    visit.memo = form.get("memo", "")
    visit.ticket_use_11 = form.get("ticket_use_11", "")
    visit.ticket_use_5 = form.get("ticket_use_5", "")
    visit.treatment_memo = form.get("treatment_memo", "")
    pain_scale = form.get("pain_scale", "").strip()
    visit.pain_scale = int(pain_scale) if pain_scale else None
    visit.disease_category = form.get("disease_category", "")
    visit.custom_field_1 = form.get("custom_field_1", "")
    visit.custom_field_2 = form.get("custom_field_2", "")


@app.route("/visits/<int:visit_id>/photos", methods=["POST"])
def visit_photo_upload(visit_id):
    visit = Visit.query.get_or_404(visit_id)
    file = request.files.get("photo")
    if file and file.filename:
        filename = secure_filename(f"visit{visit.id}_{datetime.utcnow().timestamp():.0f}_{file.filename}")
        file.save(os.path.join(UPLOAD_DIR, filename))
        photo = Photo(visit_id=visit.id, filename=filename, caption=request.form.get("caption", ""))
        db.session.add(photo)
        db.session.commit()
        flash("写真を追加しました")
    return redirect(url_for("visit_detail", visit_id=visit.id))


@app.route("/photos/<int:photo_id>/delete", methods=["POST"])
def photo_delete(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    visit_id = photo.visit_id
    path = os.path.join(UPLOAD_DIR, photo.filename)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(photo)
    db.session.commit()
    return redirect(url_for("visit_detail", visit_id=visit_id))



WEEKDAYS = "月火水木金土日"


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date.today()


def _day_reservations(day):
    return (Reservation.query.filter_by(reservation_date=day)
            .order_by(Reservation.start_min).all())


def _day_store_schedules(day):
    return (StoreSchedule.query.filter_by(schedule_date=day)
            .order_by(StoreSchedule.start_min).all())


def _find_conflict(day, staff, start_min, end_min, exclude_id=None):
    for r in _day_reservations(day):
        if r.id == exclude_id or r.status in CANCELLED_STATUSES or r.staff != staff:
            continue
        if r.start_min < end_min and start_min < r.end_min:
            return r
    return None


@app.route("/reservations")
def reservation_graph():
    day = _parse_date(request.args.get("date"))
    reservations = _day_reservations(day)
    active = [r for r in reservations if r.status not in CANCELLED_STATUSES]
    store_schedules = _day_store_schedules(day)

    start = DAY_START_MIN
    end = DAY_END_MIN
    for r in active:
        start = min(start, r.start_min // 60 * 60)
        end = max(end, -(-r.end_min // 60) * 60)
    for s in store_schedules:
        start = min(start, s.start_min // 60 * 60)
        end = max(end, -(-s.end_min // 60) * 60)
    slots = (end - start) // SLOT_MIN

    by_staff = {s: [r for r in active if r.staff == s] for s in STAFF_LIST}
    others = [r for r in active if r.staff not in STAFF_LIST]
    if others:
        for r in others:
            by_staff.setdefault(r.staff or "担当なし", []).append(r)

    quick_days = [day + timedelta(days=i) for i in range(1, 6)]
    return render_template(
        "reservation_graph.html", day=day, prev_day=day - timedelta(days=1),
        quick_days=quick_days, weekdays=WEEKDAYS, today=date.today(),
        by_staff=by_staff, start=start, end=end, slots=slots, slot_min=SLOT_MIN,
        hours=list(range(start, end, 60)), reservations=reservations,
        count_active=len(active), count_visited=len([r for r in active if r.status == "来院"]),
        count_paid=len([r for r in active if r.paid]),
        store_schedules=store_schedules,
    )


def _reservation_form_context(reservation, day, start_min, staff, patient_id):
    return dict(
        reservation=reservation, day=day, start_min=start_min, staff=staff,
        patients=Patient.query.order_by(Patient.last_name_kana, Patient.last_name).all(),
        selected_patient_id=patient_id, staff_list=STAFF_LIST,
        time_options=list(range(6 * 60, 22 * 60 + 1, SLOT_MIN)),
        duration_options=list(range(SLOT_MIN, 4 * 60 + 1, SLOT_MIN)),
        products=ordered_products(),
        sales_types=SALES_TYPES, reservation_types=["通常予約", "次回予約"],
        arrival_time=fmt_time_input(reservation.arrival_min) if reservation else "",
        treatment_time=fmt_time_input(reservation.treatment_start_min) if reservation else "",
    )


def fmt_time_input(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}" if minutes is not None else ""


def _time_to_min(value):
    try:
        h, m = value.split(":")
        return int(h) * 60 + int(m)
    except (AttributeError, ValueError):
        return None


def _apply_reservation_form(reservation, form):
    reservation.patient_id = int(form["patient_id"])
    reservation.reservation_date = _parse_date(form.get("reservation_date"))
    reservation.start_min = int(form["start_min"])
    reservation.end_min = reservation.start_min + int(form["duration"])
    reservation.staff = form.get("staff", "")
    reservation.nominated = form.get("nominated") == "1"
    reservation.memo = form.get("memo", "").strip()
    reservation.reservation_type = form.get("reservation_type", "通常予約")
    reservation.sales_type = form.get("sales_type", "売上")
    reservation.menu = ",".join(form.getlist("menu"))
    reservation.arrival_min = _time_to_min(form.get("arrival_time"))
    reservation.treatment_start_min = _time_to_min(form.get("treatment_time"))


def _create_patient_from_reservation_form(form):
    last, first = form.get("new_last_name", "").strip(), form.get("new_first_name", "").strip()
    if not last or not first:
        return None, "新規顧客の場合は姓・名を入力してください"
    patient = Patient(
        chart_no=next_chart_no(), last_name=last, first_name=first,
        last_name_kana=form.get("new_last_name_kana", "").strip(),
        first_name_kana=form.get("new_first_name_kana", "").strip(),
        gender=form.get("new_gender", "") if form.get("new_gender") != "不明" else "",
        memo=form.get("new_notice", "").strip(),
    )
    phone = form.get("new_phone", "").strip()
    if phone:
        if form.get("new_phone_type") == "携帯":
            patient.mobile = phone
        else:
            patient.phone = phone
    db.session.add(patient)
    db.session.flush()
    return patient, None


@app.route("/reservations/new", methods=["GET", "POST"])
def reservation_new():
    if request.method == "POST":
        form = request.form.copy()
        if form.get("customer_type") == "new":
            patient, error = _create_patient_from_reservation_form(form)
            if error:
                db.session.rollback()
                flash(error)
                day = _parse_date(form.get("reservation_date"))
                return render_template("reservation_form.html", **_reservation_form_context(
                    None, day, int(form.get("start_min", DAY_START_MIN)), form.get("staff", STAFF_LIST[0]), None)), 400
            form["patient_id"] = str(patient.id)
        reservation = Reservation()
        _apply_reservation_form(reservation, form)
        conflict = _find_conflict(reservation.reservation_date, reservation.staff,
                                  reservation.start_min, reservation.end_min)
        if conflict:
            flash(f"{conflict.time_range} に別の予約（{conflict.patient.full_name} 様）があるため保存できません")
            return render_template("reservation_form.html", **_reservation_form_context(
                reservation, reservation.reservation_date, reservation.start_min,
                reservation.staff, reservation.patient_id)), 409
        db.session.add(reservation)
        db.session.commit()
        flash("予約を登録しました")
        return redirect(url_for("reservation_graph", date=reservation.reservation_date.isoformat()))
    day = _parse_date(request.args.get("date"))
    start_min = int(request.args.get("time", DAY_START_MIN))
    staff = request.args.get("staff", STAFF_LIST[0])
    patient_id = request.args.get("patient_id", type=int)
    return render_template("reservation_form.html",
                           **_reservation_form_context(None, day, start_min, staff, patient_id))


@app.route("/reservations/<int:reservation_id>")
def reservation_detail(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    return render_template("reservation_detail.html", r=reservation)


@app.route("/reservations/<int:reservation_id>/edit", methods=["GET", "POST"])
def reservation_edit(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if request.method == "POST":
        _apply_reservation_form(reservation, request.form)
        conflict = _find_conflict(reservation.reservation_date, reservation.staff,
                                  reservation.start_min, reservation.end_min, exclude_id=reservation.id)
        if conflict:
            db.session.rollback()
            flash(f"{conflict.time_range} に別の予約（{conflict.patient.full_name} 様）があるため保存できません")
            return redirect(url_for("reservation_edit", reservation_id=reservation.id))
        db.session.commit()
        flash("予約を更新しました")
        return redirect(url_for("reservation_detail", reservation_id=reservation.id))
    return render_template("reservation_form.html", **_reservation_form_context(
        reservation, reservation.reservation_date, reservation.start_min,
        reservation.staff, reservation.patient_id))


@app.route("/reservations/<int:reservation_id>/status", methods=["POST"])
def reservation_status(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    status = request.form.get("status")
    if status in ("予約", "来院"):
        reservation.status = status
        reservation.cancel_reason = ""
        db.session.commit()
        flash(f"予約を「{status}」にしました")
    return redirect(url_for("reservation_detail", reservation_id=reservation.id))


@app.route("/reservations/<int:reservation_id>/cancel", methods=["GET", "POST"])
def reservation_cancel(reservation_id):
    """bonboneの「キャンセル理由」確認画面に相当。無断キャンセルと通常キャンセルを分けて記録する。"""
    reservation = Reservation.query.get_or_404(reservation_id)
    if request.method == "POST":
        action = request.form.get("action")
        if action in ("cancel", "no_show"):
            reservation.status = "無断キャンセル" if action == "no_show" else "キャンセル"
            reservation.cancel_reason = request.form.get("cancel_reason", "").strip()
            db.session.commit()
            flash(f"予約を「{reservation.status}」にしました")
        return redirect(url_for("reservation_detail", reservation_id=reservation.id))
    return render_template("reservation_cancel.html", r=reservation)


@app.route("/reservations/<int:reservation_id>/delete", methods=["POST"])
def reservation_delete(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    day = reservation.reservation_date.isoformat()
    db.session.delete(reservation)
    db.session.commit()
    flash("予約を削除しました")
    return redirect(url_for("reservation_graph", date=day))


def _apply_store_schedule_form(schedule, form):
    schedule.schedule_date = _parse_date(form.get("schedule_date"))
    schedule.start_min = int(form["start_min"])
    schedule.end_min = int(form["end_min"])
    schedule.message = form.get("message", "").strip()
    schedule.color = form.get("color", "#ef9245") or "#ef9245"


def _store_schedule_form_context(schedule, day, start_min):
    end_min = schedule.end_min if schedule else min(start_min + 60, DAY_END_MIN)
    return dict(
        schedule=schedule, day=day, start_min=start_min, end_min=end_min,
        time_options=list(range(6 * 60, 22 * 60 + 1, SLOT_MIN)),
        templates=StoreScheduleTemplate.query.order_by(StoreScheduleTemplate.label).all(),
    )


@app.route("/reservations/store-schedule/new", methods=["GET", "POST"])
def store_schedule_new():
    if request.method == "POST":
        schedule = StoreSchedule()
        _apply_store_schedule_form(schedule, request.form)
        db.session.add(schedule)
        db.session.commit()
        flash("お店の予定を登録しました")
        return redirect(url_for("reservation_graph", date=schedule.schedule_date.isoformat()))
    day = _parse_date(request.args.get("date"))
    start_min = int(request.args.get("time", DAY_START_MIN))
    return render_template("store_schedule_form.html", **_store_schedule_form_context(None, day, start_min))


@app.route("/reservations/store-schedule/<int:schedule_id>/edit", methods=["GET", "POST"])
def store_schedule_edit(schedule_id):
    schedule = StoreSchedule.query.get_or_404(schedule_id)
    if request.method == "POST":
        _apply_store_schedule_form(schedule, request.form)
        db.session.commit()
        flash("お店の予定を更新しました")
        return redirect(url_for("reservation_graph", date=schedule.schedule_date.isoformat()))
    return render_template("store_schedule_form.html",
                           **_store_schedule_form_context(schedule, schedule.schedule_date, schedule.start_min))


@app.route("/reservations/store-schedule/<int:schedule_id>/delete", methods=["POST"])
def store_schedule_delete(schedule_id):
    schedule = StoreSchedule.query.get_or_404(schedule_id)
    day = schedule.schedule_date.isoformat()
    db.session.delete(schedule)
    db.session.commit()
    flash("お店の予定を削除しました")
    return redirect(url_for("reservation_graph", date=day))


@app.route("/reservations/store-schedule-templates", methods=["GET", "POST"])
def store_schedule_templates():
    if request.method == "POST":
        label = request.form.get("label", "").strip()
        if not label:
            flash("名前を入力してください")
        elif StoreScheduleTemplate.query.filter_by(label=label).first():
            flash("同じ名前のテンプレートがすでにあります")
        else:
            db.session.add(StoreScheduleTemplate(label=label, color=request.form.get("color", "#ef9245")))
            db.session.commit()
            flash("テンプレートを追加しました")
        return redirect(url_for("store_schedule_templates"))
    return render_template("store_schedule_templates.html",
                           templates=StoreScheduleTemplate.query.order_by(StoreScheduleTemplate.label).all())


@app.route("/reservations/store-schedule-templates/<int:template_id>/delete", methods=["POST"])
def store_schedule_template_delete(template_id):
    db.session.delete(StoreScheduleTemplate.query.get_or_404(template_id))
    db.session.commit()
    return redirect(url_for("store_schedule_templates"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
