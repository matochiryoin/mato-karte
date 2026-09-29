"""bonbone Answer「販促アプローチ > 患者抽出 > CSV出力」のCSV(cp932)を患者として取り込む。
使い方: ./venv/bin/python import_bonbone.py import/bonbone_patients.csv
個人情報は画面に出さず、件数だけを表示する。患者が1件でもいる状態では実行しない。
"""
import collections
import csv
import io
import re
import sys
import unicodedata
from datetime import datetime

from app import app, db
from models import Patient

MOBILE_PREFIXES = ("070", "080", "090")


def to_katakana(text):
    text = unicodedata.normalize("NFKC", text)
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


def split_name(text):
    text = text.strip()
    parts = re.split(r"[ 　]+", text, maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (text, "")


def parse_date(text):
    text = text.strip()
    if not text:
        return None
    try:
        d = datetime.strptime(text, "%Y/%m/%d").date()
    except ValueError:
        return None
    return d if d.year >= 1900 else None


def format_phone(text):
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return text.strip()


def main(path):
    text = open(path, "rb").read().decode("cp932")
    rows = list(csv.DictReader(io.StringIO(text)))

    with app.app_context():
        if Patient.query.count() != 0:
            sys.exit("患者がすでに登録されているため中止しました")

        rows.sort(key=lambda r: (r["登録日"], r["カルテNo."]))
        seen = collections.Counter()
        stats = collections.Counter()
        for r in rows:
            base_no = r["カルテNo."].strip()
            seen[base_no] += 1
            chart_no = base_no if seen[base_no] == 1 else f"{base_no}-{seen[base_no]}"
            if seen[base_no] > 1:
                stats["chart_no_suffixed"] += 1

            last, first = split_name(r["患者名"])
            last_kana, first_kana = split_name(to_katakana(r["フリガナ"]))
            phone = format_phone(r["電話番号"])
            is_mobile = phone.replace("-", "").startswith(MOBILE_PREFIXES)
            postal = re.sub(r"\D", "", r["郵便番号"])
            birth = parse_date(r["誕生日"])
            if r["誕生日"].strip() and not birth:
                stats["birth_unparsed"] += 1

            patient = Patient(
                chart_no=chart_no, last_name=last, first_name=first,
                last_name_kana=last_kana, first_name_kana=first_kana,
                mobile=phone if (phone and is_mobile) else "", phone="" if is_mobile else phone,
                email=r["メールアドレス"].strip(),
                postal_code=f"{postal[:3]}-{postal[3:]}" if len(postal) == 7 else postal,
                prefecture=r["都道府県名"].strip(), city=r["市区郡名"].strip(), town=r["町域"].strip(),
                street=r["番地"].strip(), building=r["建物名等"].strip(),
                gender=r["性別"].strip() if r["性別"].strip() in ("女性", "男性") else "",
                occupation=r["職業"].strip(), birth_date=birth,
                registered_date=parse_date(r["登録日"]), first_visit_date=parse_date(r["初回来院日"]),
                last_visit_date=parse_date(r["最終来院日"]),
            )
            db.session.add(patient)
            for key, value in (("phone", phone), ("email", patient.email), ("address", patient.prefecture or patient.city),
                               ("birth", birth), ("gender", patient.gender), ("no_first_name", not first)):
                if value:
                    stats[key] += 1
        db.session.commit()
        print("取り込み件数:", Patient.query.count())
        print("内訳:", dict(stats))
        print("うち携帯番号:", Patient.query.filter(Patient.mobile != "").count(),
              "／固定電話ほか:", Patient.query.filter(Patient.phone != "").count())


if __name__ == "__main__":
    main(sys.argv[1])
