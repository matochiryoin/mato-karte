"""患者・カルテをCSVで取り込む／書き出す（バックアップ・Excelでの一括編集用）。
自分がエクスポートしたCSVと同じ列で取り込む。列に id があればその患者・カルテを更新し、
無ければ chart_no（患者）／patient_chart_no（カルテ）で照合し、それも無ければ新規登録する。
"""
import csv
import io
from datetime import datetime

from flask import Response, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from models import db, Patient, Visit

PATIENT_CSV_FIELDS = [
    "id", "chart_no", "last_name", "first_name", "last_name_kana", "first_name_kana",
    "phone", "mobile", "email", "postal_code", "prefecture", "city", "town", "street", "building",
    "gender", "marital_status", "blood_type", "occupation", "birth_date", "memo",
    "registered_date", "first_visit_date", "last_visit_date",
]

VISIT_CSV_FIELDS = [
    "id", "patient_chart_no", "visit_date", "staff", "base_service", "additional_service", "ticket",
    "diagnosis", "chief_complaint_1", "chief_complaint_2", "chief_complaint_3", "content", "memo",
    "ticket_use_11", "ticket_use_5",
]


def _cell(row, key):
    return (row.get(key) or "").strip()


def _read_csv_rows(file_storage):
    raw = file_storage.read()
    for encoding in ("utf-8-sig", "cp932"):
        try:
            # Excel等で開き直すと先頭のBOMが文字として残ったまま再保存され、
            # utf-8-sigの1回のデコードでは剥がしきれず列名がずれることがあるため、念のためもう一度剥がす
            text = raw.decode(encoding).lstrip("﻿")
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    return list(csv.DictReader(io.StringIO(text)))


def _parse_date(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _csv_response(fields, rows, filename):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    # 先頭にBOMを付けて、Excelで開いても文字化けしないようにする
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment; filename={filename}"})


def register(app):
    @app.route("/data")
    def data_transfer():
        return render_template("data_transfer.html",
                               patient_count=Patient.query.count(), visit_count=Visit.query.count())

    @app.route("/data/export/patients.csv")
    def data_export_patients():
        rows = [{
            "id": p.id, "chart_no": p.chart_no, "last_name": p.last_name, "first_name": p.first_name,
            "last_name_kana": p.last_name_kana or "", "first_name_kana": p.first_name_kana or "",
            "phone": p.phone or "", "mobile": p.mobile or "", "email": p.email or "",
            "postal_code": p.postal_code or "", "prefecture": p.prefecture or "", "city": p.city or "",
            "town": p.town or "", "street": p.street or "", "building": p.building or "",
            "gender": p.gender or "", "marital_status": p.marital_status or "", "blood_type": p.blood_type or "",
            "occupation": p.occupation or "", "birth_date": p.birth_date.isoformat() if p.birth_date else "",
            "memo": p.memo or "",
            "registered_date": p.registered_date.isoformat() if p.registered_date else "",
            "first_visit_date": p.first_visit_date.isoformat() if p.first_visit_date else "",
            "last_visit_date": p.last_visit_date.isoformat() if p.last_visit_date else "",
        } for p in Patient.query.order_by(Patient.chart_no).all()]
        return _csv_response(PATIENT_CSV_FIELDS, rows, f"patients_{datetime.now():%Y%m%d}.csv")

    @app.route("/data/export/visits.csv")
    def data_export_visits():
        rows = [{
            "id": v.id, "patient_chart_no": v.patient.chart_no, "visit_date": v.visit_date.isoformat(),
            "staff": v.staff or "", "base_service": v.base_service or "",
            "additional_service": v.additional_service or "", "ticket": v.ticket or "",
            "diagnosis": v.diagnosis or "", "chief_complaint_1": v.chief_complaint_1 or "",
            "chief_complaint_2": v.chief_complaint_2 or "", "chief_complaint_3": v.chief_complaint_3 or "",
            "content": v.content or "", "memo": v.memo or "",
            "ticket_use_11": v.ticket_use_11 or "", "ticket_use_5": v.ticket_use_5 or "",
        } for v in Visit.query.order_by(Visit.id).all()]
        return _csv_response(VISIT_CSV_FIELDS, rows, f"visits_{datetime.now():%Y%m%d}.csv")

    def _load_rows_or_redirect(required_column):
        file = request.files.get("file")
        if not file or not file.filename:
            flash("CSVファイルを選んでください")
            return None
        rows = _read_csv_rows(file)
        if rows is None:
            flash("CSVの文字コードを読み取れませんでした（UTF-8で保存し直してください）")
            return None
        if rows and required_column not in rows[0]:
            flash(f"CSVの列が正しくありません（{required_column} 列が見つかりません）")
            return None
        return rows

    @app.route("/data/import/patients", methods=["POST"])
    def data_import_patients():
        rows = _load_rows_or_redirect("chart_no")
        if rows is None:
            return redirect(url_for("data_transfer"))

        created = updated = skipped = 0
        for row in rows:
            chart_no = _cell(row, "chart_no")
            last_name = _cell(row, "last_name")
            if not chart_no or not last_name:
                skipped += 1
                continue
            row_id = _cell(row, "id")
            patient = Patient.query.get(int(row_id)) if row_id.isdigit() else None
            if patient is None:
                patient = Patient.query.filter_by(chart_no=chart_no).first()
            is_new = patient is None
            if is_new:
                patient = Patient(chart_no=chart_no)
                db.session.add(patient)
            else:
                patient.chart_no = chart_no
            patient.last_name = last_name
            patient.first_name = _cell(row, "first_name")
            patient.last_name_kana = _cell(row, "last_name_kana")
            patient.first_name_kana = _cell(row, "first_name_kana")
            patient.phone = _cell(row, "phone")
            patient.mobile = _cell(row, "mobile")
            patient.email = _cell(row, "email")
            patient.postal_code = _cell(row, "postal_code")
            patient.prefecture = _cell(row, "prefecture")
            patient.city = _cell(row, "city")
            patient.town = _cell(row, "town")
            patient.street = _cell(row, "street")
            patient.building = _cell(row, "building")
            patient.gender = _cell(row, "gender")
            patient.marital_status = _cell(row, "marital_status")
            patient.blood_type = _cell(row, "blood_type")
            patient.occupation = _cell(row, "occupation")
            patient.birth_date = _parse_date(row.get("birth_date"))
            patient.memo = _cell(row, "memo")
            patient.registered_date = _parse_date(row.get("registered_date"))
            patient.first_visit_date = _parse_date(row.get("first_visit_date"))
            patient.last_visit_date = _parse_date(row.get("last_visit_date"))
            created += is_new
            updated += not is_new
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("取込に失敗しました（カルテNo.が他の患者と重複している可能性があります）")
            return redirect(url_for("data_transfer"))
        flash(f"患者CSV取込：新規 {created} 件・更新 {updated} 件" + (f"・スキップ {skipped} 件" if skipped else ""))
        return redirect(url_for("data_transfer"))

    @app.route("/data/import/visits", methods=["POST"])
    def data_import_visits():
        rows = _load_rows_or_redirect("patient_chart_no")
        if rows is None:
            return redirect(url_for("data_transfer"))

        created = updated = skipped = 0
        for row in rows:
            chart_no = _cell(row, "patient_chart_no")
            visit_date = _parse_date(row.get("visit_date"))
            patient = Patient.query.filter_by(chart_no=chart_no).first() if chart_no else None
            if not patient or not visit_date:
                skipped += 1
                continue
            row_id = _cell(row, "id")
            visit = Visit.query.get(int(row_id)) if row_id.isdigit() else None
            is_new = visit is None
            if is_new:
                visit = Visit(patient_id=patient.id)
                db.session.add(visit)
            else:
                visit.patient_id = patient.id
            visit.visit_date = visit_date
            visit.staff = _cell(row, "staff")
            visit.base_service = _cell(row, "base_service")
            visit.additional_service = _cell(row, "additional_service")
            visit.ticket = _cell(row, "ticket")
            visit.diagnosis = _cell(row, "diagnosis")
            visit.chief_complaint_1 = _cell(row, "chief_complaint_1")
            visit.chief_complaint_2 = _cell(row, "chief_complaint_2")
            visit.chief_complaint_3 = _cell(row, "chief_complaint_3")
            visit.content = _cell(row, "content")
            visit.memo = _cell(row, "memo")
            visit.ticket_use_11 = _cell(row, "ticket_use_11")
            visit.ticket_use_5 = _cell(row, "ticket_use_5")
            created += is_new
            updated += not is_new
        db.session.commit()
        flash(f"カルテCSV取込：新規 {created} 件・更新 {updated} 件" + (f"・スキップ {skipped} 件" if skipped else ""))
        return redirect(url_for("data_transfer"))
