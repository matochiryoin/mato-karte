"""bonbone Answerからの「カルテ全データ抽出」を取り込むスクリプト（ひな形・未完成）。

現状：ダイヤ工業へ全抽出を依頼中で、実際のファイルはまだ届いていない。
ファイル形式・列名が分かり次第、下の COLUMN MAP と各 build_* 関数を実物に合わせて直す。

設計方針：
- 患者の突き合わせは「カルテNo.」を主キーにする。ただし2026-09-20の患者抽出時点で
  カルテNo.が別人と重複していた38組は、登録日の早い方をそのまま、後の人に
  「-2」のような枝番を付けて取り込み済み（import_bonbone.py参照）。
  今回もカルテNo.だけでは一意に決まらない場合があるので、
  同じカルテNo.が複数ヒットしたら患者名（フリガナ）で絞り込む match_patient() を使う。
- 同じ来院・会計を何度でも安全に取り込めるよう、bonbone側の元IDを
  Visit.external_id / Sale.external_id に保存し、二重登録を防ぐ（idempotent）。
- 既定は --commit を付けない限り書き込まない（件数だけ表示するドライラン）。
- 写真は同梱のファイル名とカルテ・来院を対応づけて static/uploads/ にコピーする想定
  （ファイルの受け渡し方法が分かってから実装する）。

使い方（実物が届いてから）：
    ./venv/bin/python import_bonbone_history.py <ファイルパス> --commit
"""
import argparse
import sys

from app import app, db
from models import Patient, Visit, Sale, SaleLine, Payment

# TODO: 実際のファイルの列名が分かったらここを直す
COLUMN_MAP = {
    "chart_no": "カルテNo.",       # 仮
    "visit_date": "来院日",         # 仮
    "staff": "担当",               # 仮
    "chief_complaint": "主訴",      # 仮
    "diagnosis": "傷病名",          # 仮
    "treatment_memo": "施術メモ",   # 仮
    "content": "内容",             # 仮
    "external_id": "ID",           # 仮（bonbone側のカルテ/来院ID。無ければ日付+カルテNo.で代用）
}


def match_patient(chart_no, kana_hint=None):
    """カルテNo.（枝番なし）で患者を探す。重複していたら患者名のフリガナで絞り込む。"""
    candidates = Patient.query.filter(
        db.or_(Patient.chart_no == chart_no, Patient.chart_no.like(f"{chart_no}-%"))
    ).all()
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    if kana_hint:
        narrowed = [p for p in candidates if kana_hint in p.full_name_kana]
        if len(narrowed) == 1:
            return narrowed[0]
    return None  # 一意に決まらない → 手動確認が必要


def build_visit(patient, row):
    """1行分の来院・問診データからVisitを組み立てる（列名は届いてから直す）。"""
    return Visit(
        patient_id=patient.id,
        visit_date=row["visit_date"],
        staff=row.get("staff", ""),
        diagnosis=row.get("diagnosis", ""),
        chief_complaint_1=row.get("chief_complaint", ""),
        content=row.get("content", ""),
        treatment_memo=row.get("treatment_memo", ""),
        external_source="bonbone_history",
        external_id=row.get("external_id", ""),
    )


def run(path, commit):
    with app.app_context():
        # TODO: ファイル形式に合わせて読み込む（CSV/Excel等）。ここではまだ読み込み処理がない。
        print("このスクリプトはまだファイルの読み込み処理を実装していません。")
        print("実物のファイル（形式・列名）が届いたら、COLUMN MAPとbuild_visit()等を直してから使う。")
        print(f"対象ファイル: {path}")
        print(f"モード: {'書き込みあり' if commit else 'ドライラン（件数確認のみ、書き込みなし）'}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--commit", action="store_true", help="実際にデータベースへ書き込む")
    args = parser.parse_args()
    run(args.path, args.commit)
