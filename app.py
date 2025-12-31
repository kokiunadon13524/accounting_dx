import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="会計DXアプリ", layout="centered")
st.title("会計DXアプリ")
st.write("試算表CSVをアップロードしてください。")

uploaded_file = st.file_uploader(
    "CSVファイルを選択（ドラッグ＆ドロップ可）",
    type=["csv"]
)

# =========================
# 基本ユーティリティ
# =========================
def is_number_like(x: str) -> bool:
    if x is None:
        return False
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return False
    s = s.replace(",", "").replace("▲", "-")
    if re.fullmatch(r"\(\s*-?\d+(\.\d+)?\s*\)", s):
        return True
    return re.fullmatch(r"-?\d+(\.\d+)?", s) is not None


def to_number(x: str):
    if x is None:
        return pd.NA
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return pd.NA
    s = s.replace(",", "").replace("▲", "-")
    if re.fullmatch(r"\(\s*-?\d+(\.\d+)?\s*\)", s):
        s = s.strip()[1:-1].strip()
        if s.startswith("-"):
            s = s[1:]
        s = "-" + s
    try:
        return float(s)
    except Exception:
        return pd.NA


def detect_subject_candidates(df: pd.DataFrame):
    keywords = ["売上", "原価", "利益", "費用", "経費", "収益", "販管", "人件", "外注", "租税", "減価"]
    scores = {}
    for col in df.columns:
        s = df[col].astype(str)
        kw_hits = s.str.contains("|".join(keywords), regex=True).sum()
        jp_hits = s.str.contains(r"[ぁ-んァ-ン一-龥]").sum()
        len_ok = s.str.len().fillna(0).between(1, 40).sum()
        scores[col] = kw_hits * 3 + jp_hits * 1 + len_ok * 0.2
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def detect_amount_candidates(df: pd.DataFrame):
    scores = {}
    for col in df.columns:
        s = df[col].astype(str)
        num_like = s.apply(is_number_like).sum()
        non_empty = (s.str.strip() != "").sum()
        scores[col] = num_like * 2 + non_empty * 0.1
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def sum_by_keywords(df: pd.DataFrame, keywords: list[str]) -> float:
    mask = df["科目"].astype(str).apply(lambda x: any(k in x for k in keywords))
    s = df.loc[mask, "金額"].sum()
    return float(s) if pd.notna(s) else 0.0


def yen(x: float) -> str:
    return f"{int(round(float(x))):,}"


# =========================
# メイン
# =========================
if uploaded_file is not None:
    try:
        df_raw = pd.read_csv(
            uploaded_file,
            encoding="cp932",
            header=None,
            engine="python",
            skiprows=1,
            on_bad_lines="skip"
        )

        st.success("CSVの読み込みに成功しました。")
        df_raw = df_raw.dropna(how="all").reset_index(drop=True)

        st.write("### ① 列の意味づけ（推定 → 選択）")

        subject_candidates = detect_subject_candidates(df_raw)
        amount_candidates = detect_amount_candidates(df_raw)

        suggested_subject = subject_candidates[0][0] if subject_candidates else df_raw.columns[0]
        suggested_amount = amount_candidates[0][0] if amount_candidates else df_raw.columns[-1]

        col1, col2 = st.columns(2)
        with col1:
            subject_col = st.selectbox(
                "科目列（勘定科目）が入っている列を選んでください",
                options=list(df_raw.columns),
                index=list(df_raw.columns).index(suggested_subject)
            )
            st.caption(f"推定候補TOP3: {[c[0] for c in subject_candidates[:3]]}")

        with col2:
            amount_col = st.selectbox(
                "金額列（当期など）が入っている列を選んでください",
                options=list(df_raw.columns),
                index=list(df_raw.columns).index(suggested_amount)
            )
            st.caption(f"推定候補TOP3: {[c[0] for c in amount_candidates[:3]]}")

        # 正規化
        df_norm = pd.DataFrame({
            "科目": df_raw[subject_col].where(df_raw[subject_col].notna(), ""),
            "金額": df_raw[amount_col].apply(to_number)
        })
        df_norm["科目"] = df_norm["科目"].astype(str).str.strip()
        df_norm = df_norm[(df_norm["科目"] != "") & (df_norm["科目"].str.lower() != "nan")]
        df_norm = df_norm[df_norm["金額"].notna()]
        df_norm["金額"] = pd.to_numeric(df_norm["金額"], errors="coerce")
        df_norm = df_norm[df_norm["金額"].notna()]

        st.write("### 正規化プレビュー（科目＋金額）")
        st.dataframe(df_norm.head(20), use_container_width=True)

        # =========================
        # ② 利益サマリー
        # =========================
        st.write("### ② 利益サマリー（再計算）")

        sales = sum_by_keywords(df_norm, ["売上高"])
        cogs = sum_by_keywords(df_norm, ["売上原価"])
        sga = sum_by_keywords(df_norm, [
            "販売管理計", "販売管理費計", "販売管理費 計",
            "販管費計", "販管費 計",
            "販売費及び一般管理費計", "販売費及び一般管理費 計"
        ])
        nonop_income = sum_by_keywords(df_norm, ["営業外収益"])
        nonop_exp = sum_by_keywords(df_norm, ["営業外費用"])
        special_gain = sum_by_keywords(df_norm, ["特別利益", "特別収益"])
        special_loss = sum_by_keywords(df_norm, ["特別損失"])

        gross_profit = sales - cogs
        operating_profit = gross_profit - sga
        ordinary_profit = operating_profit + nonop_income - nonop_exp
        pretax_profit = ordinary_profit + special_gain - special_loss

        colA, colB = st.columns(2)
        with colA:
            st.metric("売上高", yen(sales))
            st.metric("売上原価", yen(cogs))
            st.metric("売上総利益", yen(gross_profit))
            st.metric("販管費", yen(sga))
        with colB:
            st.metric("営業利益", yen(operating_profit))
            st.metric("経常利益", yen(ordinary_profit))
            st.metric("税引前利益（概算）", yen(pretax_profit))

        # =========================
        # ③ 納税予測（欠損金・中間納税を反映）
        # =========================
        st.write("### ③ 納税予測（欠損金・中間納税を反映 / 概算）")

        effective_tax_rate = st.number_input(
            "想定実効税率（%）",
            min_value=0.0,
            max_value=70.0,
            value=30.0,
            step=0.5
        )

        # 初期値（1回だけ）
        if "loss_carryforward" not in st.session_state:
            st.session_state["loss_carryforward"] = 0
        if "interim_tax_paid" not in st.session_state:
            st.session_state["interim_tax_paid"] = 0

        loss_carryforward = st.number_input(
            "欠損金（繰越控除）※手動入力（円）",
            min_value=0,
            step=100000,
            key="loss_carryforward"
        )

        interim_tax_paid = st.number_input(
            "中間納税（すでに支払った額）※手動入力（円）",
            min_value=0,
            step=100000,
            key="interim_tax_paid"
        )

        st.caption(f"入力値：欠損金 {loss_carryforward:,} 円 / 中間納税 {interim_tax_paid:,} 円")


        taxable_income = max(0.0, pretax_profit - float(loss_carryforward))
        estimated_tax = taxable_income * (effective_tax_rate / 100.0)

        estimated_additional_payment = max(0.0, estimated_tax - float(interim_tax_paid))
        estimated_refund = max(0.0, float(interim_tax_paid) - estimated_tax)

        st.write("#### 計算結果（概算）")
        colT1, colT2, colT3 = st.columns(3)
        with colT1:
            st.metric("課税所得（概算）", yen(taxable_income))
        with colT2:
            st.metric("法人税等（概算）", yen(estimated_tax))
        with colT3:
            st.metric("追加で払う見込み", yen(estimated_additional_payment))

        if estimated_refund > 0:
            st.info(f"中間納税が概算税額を上回っています。還付見込み（概算）：{yen(estimated_refund)} 円")
        else:
            st.caption("※あくまで概算です（地方税・事業税の内訳、税効果、調整項目などは未反映）。")

    except Exception as e:
        st.error("CSVの読み込みまたは処理でエラーが発生しました。")
        st.exception(e)
