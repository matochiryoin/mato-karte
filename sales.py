import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import flash, redirect, render_template, request, url_for

from models import (db, Patient, Reservation, Product, Sale, SaleLine, Payment, STAFF_LIST,
                    PRODUCT_CATEGORIES, PAYMENT_METHODS, SALES_TYPES, TAX_TYPES, tax_included, fmt_min, ordered_products,
                    AGE_BRACKETS, SALE_GENDER_OPTIONS)

WEEKDAYS = "月火水木金土日"
SEED_PRODUCTS = [
    # bonbone Answer 設定登録の各マスタ（2026-09-20時点）。(名前, 区分, 単価, 税区分)
    ("マッサージ治療", "技術", 4400, "内税"), ("学生料金", "技術", 3000, "内税"), ("小児はり", "技術", 1000, "内税"),
    ("はり治療", "技術", 4400, "内税"), ("初診料", "技術", 2200, "内税"), ("チャージ君", "技術", 2200, "内税"),
    ("アスリート治療", "技術", 10000, "内税"), ("はり治療（追加）", "技術", 1000, "内税"),
    ("チャージ君（追加）", "技術", 1000, "内税"), ("リハ/リコンディション", "技術", 1000, "内税"),
    ("テーピング 100", "技術", 100, "内税"), ("テーピング 200", "技術", 0, "内税"),
    ("美容はり（追加）", "技術", 1000, "内税"), ("プライロックテープ", "技術", 500, "内税"),
    ("美容はり＋チャージ君", "技術", 2000, "内税"), ("回数券利用 治療", "技術", 0, "内税"),
    ("回数券利用 チャージ君", "技術", 0, "内税"),
    ("治療回数券（11回分）", "回数券", 42000, "内税"), ("治療回数券（5回分）", "回数券", 20000, "内税"),
    ("チャージ君回数券（11回分）", "回数券", 21600, "内税"),
    ("キネシオテープ", "店販", 500, "内税"), ("プライロックテープ（店販）", "店販", 2700, "外税"),
    ("フロッグハンド(ハード)", "店販", 3000, "内税"), ("フロッグハンド(ソフト)", "店販", 3000, "内税"),
    ("フォームソティックス(ミディアム)", "店販", 11000, "外税"), ("フォームソティックス(ハード)", "店販", 11000, "外税"),
    ("VitaNote (生活改善)", "店販", 7500, "外税"), ("VitaNote (ビタミン)", "店販", 3980, "外税"),
    ("VitaNote (ミネラル)", "店販", 3480, "外税"), ("VitaNote (プロテイン)", "店販", 2980, "外税"),
    ("エミューオイルL", "店販", 8700, "外税"), ("エミューオイルM", "店販", 3400, "外税"),
    ("腰コルセット", "店販", 5000, "内税"), ("腰コルセット(メッシュ)", "店販", 5000, "内税"),
    ("美容液マスク(1枚)", "店販", 1800, "外税"), ("美容液マスク(5枚)", "店販", 6500, "外税"),
    ("美容液マスク(10枚)", "店販", 11000, "外税"),
    ("RSHO-X ナチュラルアイソレート 500mg", "店販", 5940, "内税"),
    ("RSHO ゴールドラベル 1000mg CBD", "店販", 17172, "内税"),
    ("アクティブリリーフロールオン 150mg", "店販", 3190, "内税"),
]


# 「◯◯回数券（N回分）」の購入で+N、「回数券利用 ◯◯」の使用で-1する。
# 商品名の付け方（SEED_PRODUCTSと同じ規則）に沿っていれば、新しく追加した回数券商品も自動で対象になる。
TICKET_PRODUCT_RE = re.compile(r"^(.+?)回数券.*?(\d+)回")
TICKET_USE_PREFIX = "回数券利用 "


def all_patient_ticket_balances():
    """全患者ぶんの回数券の残り回数（患者ID→種類→残数）。会計画面の患者選択でまとめて使うため、
    患者ごとに調べるのではなく1回の集計クエリで計算する。"""
    balances = defaultdict(lambda: defaultdict(int))
    rows = (
        db.session.query(Sale.patient_id, SaleLine.name, SaleLine.category, db.func.sum(SaleLine.quantity))
        .join(SaleLine, SaleLine.sale_id == Sale.id)
        .filter(db.or_(SaleLine.category == "回数券", SaleLine.name.like(f"{TICKET_USE_PREFIX}%")))
        .group_by(Sale.patient_id, SaleLine.name, SaleLine.category)
        .all()
    )
    for patient_id, name, category, qty in rows:
        if category == "回数券":
            m = TICKET_PRODUCT_RE.match(name)
            if m:
                balances[patient_id][m.group(1)] += int(m.group(2)) * qty
        elif name.startswith(TICKET_USE_PREFIX):
            balances[patient_id][name[len(TICKET_USE_PREFIX):]] -= qty
    return {pid: dict(fam) for pid, fam in balances.items()}


def seed_products():
    if Product.query.count() == 0:
        for name, category, price, tax_type in SEED_PRODUCTS:
            db.session.add(Product(name=name, category=category, price=price, tax_type=tax_type))
        db.session.commit()


def _parse_date(value, default=None):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default or date.today()


def _to_int(value, default=0):
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _apply_sale_form(sale, form):
    sale.patient_id = int(form["patient_id"])
    sale.sale_date = _parse_date(form.get("sale_date"))
    sale.staff = form.get("staff", "")
    sale.nominated = form.get("nominated") == "1"
    sale.memo = form.get("memo", "").strip()
    tendered = form.get("tendered", "").strip()
    sale.tendered = _to_int(tendered) if tendered else None

    sale.lines.clear()
    names = form.getlist("line_name")
    for i, name in enumerate(names):
        name = name.strip()
        if not name:
            continue
        sale.lines.append(SaleLine(
            name=name,
            sales_type=form.getlist("line_type")[i],
            category=form.getlist("line_category")[i],
            quantity=max(_to_int(form.getlist("line_qty")[i], 1), 1),
            unit_price=_to_int(form.getlist("line_price")[i]),
            discount=_to_int(form.getlist("line_discount")[i]),
            tax_type=form.getlist("line_tax")[i],
            staff=sale.staff,
            nominated=sale.nominated,
        ))

    sale.payments.clear()
    for method, amount in zip(form.getlist("pay_method"), form.getlist("pay_amount")):
        amount = _to_int(amount)
        if method and amount:
            sale.payments.append(Payment(method=method, amount=amount))


def _sale_form_context(sale, patient_id, sale_date, staff, prefill_lines, reservation_id):
    return dict(
        sale=sale, patients=Patient.query.order_by(Patient.last_name_kana, Patient.last_name).all(),
        selected_patient_id=patient_id, sale_date=sale_date, staff=staff, staff_list=STAFF_LIST,
        products=ordered_products(),
        categories=PRODUCT_CATEGORIES, methods=PAYMENT_METHODS, sales_types=SALES_TYPES, tax_types=TAX_TYPES,
        prefill_lines=prefill_lines, reservation_id=reservation_id,
        product_map={p.name: dict(price=p.price, category=p.category, tax=p.tax_type) for p in Product.query.all()},
        patient_tickets=all_patient_ticket_balances(),
    )


def _validate_sale(sale):
    if not sale.lines:
        return "商品を1つ以上入力してください"
    if sale.paid_total != sale.total:
        return f"入金合計（{sale.paid_total:,}円）が合計（{sale.total:,}円）と一致しません"
    return None


def register(app):
    @app.route("/sales")
    def sales_ledger():
        day = _parse_date(request.args.get("date"))
        tab = request.args.get("tab", "sales")
        sales = (Sale.query.filter_by(sale_date=day).order_by(Sale.id).all())
        totals = dict(
            count=len(sales), tech=sum(s.tech_total for s in sales), ticket=sum(s.ticket_total for s in sales),
            shop=sum(s.shop_total for s in sales), discount=sum(s.discount_total for s in sales),
            tax=sum(s.tax for s in sales), total=sum(s.total for s in sales),
        )
        by_method = defaultdict(int)
        payments_by_sale = {}
        for s in sales:
            payments_by_sale[s.id] = defaultdict(int)
            for p in s.payments:
                by_method[p.method] += p.amount
                payments_by_sale[s.id][p.method] += p.amount
        return render_template("sales_ledger.html", day=day, tab=tab, sales=sales, totals=totals,
                               by_method=by_method, payments_by_sale=payments_by_sale, payment_methods=PAYMENT_METHODS,
                               weekdays=WEEKDAYS, today=date.today(),
                               prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1))

    @app.route("/sales/new", methods=["GET", "POST"])
    def sale_new():
        if request.method == "POST":
            sale = Sale()
            _apply_sale_form(sale, request.form)
            reservation_id = request.form.get("reservation_id", type=int)
            sale.reservation_id = reservation_id
            error = _validate_sale(sale)
            if error:
                flash(error)
                db.session.rollback()
                return render_template("sale_form.html", **_sale_form_context(
                    sale, sale.patient_id, sale.sale_date, sale.staff, None, reservation_id)), 400
            db.session.add(sale)
            if reservation_id:
                reservation = db.session.get(Reservation, reservation_id)
                if reservation and reservation.status == "予約":
                    reservation.status = "来院"
            db.session.commit()
            flash("お会計を登録しました")
            return redirect(url_for("sale_complete", sale_id=sale.id))

        reservation = db.session.get(Reservation, request.args.get("reservation_id", type=int) or 0)
        patient_id = request.args.get("patient_id", type=int)
        sale_date = _parse_date(request.args.get("date"))
        staff = STAFF_LIST[0]
        prefill = []
        if reservation:
            patient_id = reservation.patient_id
            sale_date = reservation.reservation_date
            staff = reservation.staff or staff
            prices = {p.name: p for p in Product.query.all()}
            for name in reservation.menu_list:
                product = prices.get(name)
                prefill.append(dict(name=name, category=product.category if product else "技術",
                                    price=product.price if product else 0, type=reservation.sales_type,
                                    tax=product.tax_type if product else "内税"))
        return render_template("sale_form.html", **_sale_form_context(
            None, patient_id, sale_date, staff, prefill, reservation.id if reservation else None))

    @app.route("/sales/<int:sale_id>")
    def sale_detail(sale_id):
        return render_template("sale_detail.html", sale=db.get_or_404(Sale, sale_id))

    @app.route("/sales/<int:sale_id>/complete", methods=["GET", "POST"])
    def sale_complete(sale_id):
        """bonboneの「お会計完了」画面に相当。会計時の性別・年代・来店動機を患者情報へ反映する。"""
        sale = db.get_or_404(Sale, sale_id)
        if request.method == "POST":
            patient = sale.patient
            gender = request.form.get("gender", "")
            if gender and gender != "不明":
                patient.gender = gender
            patient.age_bracket = request.form.get("age_bracket", "") or patient.age_bracket
            patient.visit_motivation = request.form.get("visit_motivation", "").strip() or patient.visit_motivation
            db.session.commit()
            flash("お会計が完了しました")
            return redirect(url_for("sales_ledger", date=sale.sale_date.isoformat()))
        cash_paid = sum(p.amount for p in sale.payments if p.method == "現金")
        return render_template("sale_complete.html", sale=sale, cash_paid=cash_paid,
                               gender_options=SALE_GENDER_OPTIONS, age_brackets=AGE_BRACKETS)

    @app.route("/sales/<int:sale_id>/receipt")
    def sale_receipt(sale_id):
        return render_template("sale_print.html", sale=db.get_or_404(Sale, sale_id), doc_title="領収書", is_receipt=True)

    @app.route("/sales/<int:sale_id>/invoice")
    def sale_invoice(sale_id):
        return render_template("sale_print.html", sale=db.get_or_404(Sale, sale_id), doc_title="レシート", is_receipt=False)

    @app.route("/sales/<int:sale_id>/edit", methods=["GET", "POST"])
    def sale_edit(sale_id):
        sale = db.get_or_404(Sale, sale_id)
        if request.method == "POST":
            _apply_sale_form(sale, request.form)
            error = _validate_sale(sale)
            if error:
                flash(error)
                db.session.rollback()
                return redirect(url_for("sale_edit", sale_id=sale_id))
            db.session.commit()
            flash("お会計を修正しました")
            return redirect(url_for("sale_detail", sale_id=sale.id))
        return render_template("sale_form.html", **_sale_form_context(
            sale, sale.patient_id, sale.sale_date, sale.staff, None, sale.reservation_id))

    @app.route("/sales/<int:sale_id>/delete", methods=["POST"])
    def sale_delete(sale_id):
        sale = db.get_or_404(Sale, sale_id)
        day = sale.sale_date.isoformat()
        db.session.delete(sale)
        db.session.commit()
        flash("お会計を削除しました")
        return redirect(url_for("sales_ledger", date=day))

    @app.route("/products", methods=["GET", "POST"])
    def products():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if not name:
                flash("商品名を入力してください")
            elif Product.query.filter_by(name=name).first():
                flash("同じ名前の商品がすでにあります")
            else:
                db.session.add(Product(name=name, category=request.form.get("category", "技術"),
                                       price=_to_int(request.form.get("price")),
                                       tax_type=request.form.get("tax_type", "内税")))
                db.session.commit()
                flash("商品を追加しました")
            return redirect(url_for("products"))
        return render_template("products.html", items=ordered_products(active_only=False),
                               categories=PRODUCT_CATEGORIES, tax_types=TAX_TYPES)

    @app.route("/products/<int:product_id>", methods=["POST"])
    def product_update(product_id):
        product = db.get_or_404(Product, product_id)
        product.price = _to_int(request.form.get("price"), product.price)
        product.category = request.form.get("category", product.category)
        product.tax_type = request.form.get("tax_type", product.tax_type)
        product.active = request.form.get("active") == "1"
        db.session.commit()
        flash(f"「{product.name}」を更新しました")
        return redirect(url_for("products"))

    # ---- 集計 ----
    def _sums(sales):
        return dict(count=len(sales), tech=sum(s.tech_total for s in sales), ticket=sum(s.ticket_total for s in sales),
                    shop=sum(s.shop_total for s in sales), discount=sum(s.discount_total for s in sales),
                    tax=sum(s.tax for s in sales), total=sum(s.total for s in sales))

    def _parse_month(value):
        try:
            return datetime.strptime(value, "%Y-%m").date().replace(day=1)
        except (TypeError, ValueError):
            return date.today().replace(day=1)

    def _month_range(first):
        nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        return first, nxt

    @app.route("/reports/monthly")
    def report_monthly():
        """bonboneの「営業日別売上集計」に相当。10日ごとの小計と月合計・1日平均・客単価を出す
        （客数の新規/再来/固定等の内訳、天気、目標達成率はまことさんの申告により対象外）。"""
        first = _parse_month(request.args.get("month"))
        start, end = _month_range(first)
        sales = Sale.query.filter(Sale.sale_date >= start, Sale.sale_date < end).all()
        per_day = defaultdict(list)
        for s in sales:
            per_day[s.sale_date].append(s)

        days = []
        d = start
        while d < end:
            days.append(d)
            d += timedelta(days=1)

        blocks = []
        for i in range(0, len(days), 10):
            chunk = days[i:i + 10]
            rows = [(day, _sums(per_day.get(day, []))) for day in chunk]
            chunk_sales = [s for day in chunk for s in per_day.get(day, [])]
            blocks.append((rows, _sums(chunk_sales)))

        totals = _sums(sales)
        avg_per_day = totals["total"] // len(days) if days else 0
        avg_per_customer = totals["total"] // totals["count"] if totals["count"] else 0
        prev_month = (start - timedelta(days=1)).replace(day=1)
        return render_template("report_monthly.html", first=first, blocks=blocks, totals=totals,
                               avg_per_day=avg_per_day, avg_per_customer=avg_per_customer,
                               weekdays=WEEKDAYS, prev_month=prev_month, next_month=end)

    @app.route("/reports/menu")
    def report_menu():
        first = _parse_month(request.args.get("month"))
        start, end = _month_range(first)
        lines = (SaleLine.query.join(Sale).filter(Sale.sale_date >= start, Sale.sale_date < end).all())
        agg = defaultdict(lambda: dict(category="", quantity=0, gross=0, discount=0, amount=0))
        for l in lines:
            a = agg[l.name]
            a["category"] = l.category
            a["quantity"] += l.quantity
            a["gross"] += l.gross
            a["discount"] += l.discount
            a["amount"] += l.amount
        rows = sorted(agg.items(), key=lambda kv: -kv[1]["amount"])
        prev_month = (start - timedelta(days=1)).replace(day=1)
        return render_template("report_menu.html", first=first, rows=rows,
                               total_amount=sum(a["amount"] for _, a in rows), prev_month=prev_month, next_month=end)

    @app.route("/reports/yearly")
    def report_yearly():
        year = request.args.get("year", type=int) or date.today().year
        sales = Sale.query.filter(Sale.sale_date >= date(year, 1, 1), Sale.sale_date < date(year + 1, 1, 1)).all()
        per_month = defaultdict(list)
        for s in sales:
            per_month[s.sale_date.month].append(s)
        rows = [(m, _sums(per_month.get(m, []))) for m in range(1, 13)]
        return render_template("report_yearly.html", year=year, rows=rows, totals=_sums(sales))
