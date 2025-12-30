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

def is_number_like(x: str) -> bool:
    """'1,234' や '(1,234)' や '▲1,234' などの会計っぽい表記を数値候補として扱う"""
    if x is None:
        return False
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return False
    s = s.replace(",", "")
    s = s.replace("▲", "-")
    # (123) 形式も負数扱いにする
    if re.fullmatch(r"\(\s*-?\d+(\.\d+)?\s*\)", s):
        return True
    return re.fullmatch(r"-?\d+(\.\d+)?", s) is not None

def to_number(x: str):
    """会計っぽい表記を数値に寄せる（変換できなければNaN）"""
    if x is None:
        return pd.NA
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return pd.NA
    s = s.replace(",", "").replace("▲", "-")
    # (123) -> -123
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
    """科目列っぽい列をスコアリングして候補を返す"""
    keywords = ["売上", "原価", "利益", "費用", "経費", "収益", "販管", "人件", "外注", "租税", "減価"]
    scores = {}
    for col in df.columns:
        s = df[col].astype(str)
        # キーワードが含まれる行数
        kw_hits = s.str.contains("|".join(keywords), regex=True).sum()
        # 日本語（ひら/カタ/漢字）が含まれる行数（ざっくり）
        jp_hits = s.str.contains(r"[ぁ-んァ-ン一-龥]").sum()
        # 文字列長がそこそこある行（科目は短〜中くらいが多い）
        len_ok = s.str.len().fillna(0).between(1, 40).sum()
        scores[col] = kw_hits * 3 + jp_hits * 1 + len_ok * 0.2
    # スコア順
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)

def detect_amount_candidates(df: pd.DataFrame):
    """金額列っぽい列をスコアリングして候補を返す"""
    scores = {}
    for col in df.columns:
        s = df[col].astype(str)
        num_like = s.apply(is_number_like).sum()
        non_empty = (s.str.strip() != "").sum()
        scores[col] = num_like * 2 + non_empty * 0.1
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)

if uploaded_file is not None:
    try:
        # 壊れにくい読み込み（今回の会計CSV向け）
        df_raw = pd.read_csv(
            uploaded_file,
            encoding="cp932",
            header=None,
            engine="python",
            skiprows=1,
            on_bad_lines="skip"
        )

        st.success("CSVの読み込みに成功しました。")

        # ほぼ空の行を落とす（全列が空/NaNの行）
        df_raw = df_raw.dropna(how="all").reset_index(drop=True)

        st.write("### ① 列の意味づけ（推定 → 選択）")

        # 候補検出
        subject_candidates = detect_subject_candidates(df_raw)
        amount_candidates = detect_amount_candidates(df_raw)

        # 推定トップ
        suggested_subject = subject_candidates[0][0] if subject_candidates else df_raw.columns[0]
        suggested_amount = amount_candidates[0][0] if amount_candidates else df_raw.columns[-1]

        # UI：ユーザーが最終決定
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

        # 整形データを作る（科目＋金額）
        df_norm = pd.DataFrame({
            "科目": df_raw[subject_col].astype(str).str.strip(),
            "金額": df_raw[amount_col].apply(to_number)
        })

        # 科目が空の行や金額が全部NaNの行を落とす
                # ===== 正規化（科目＋金額）=====
        subject_series = df_raw[subject_col]
        amount_series = df_raw[amount_col]

        df_norm = pd.DataFrame({
            "科目": subject_series.where(subject_series.notna(), ""),  # NaN→空文字
            "金額": amount_series.apply(to_number)
        })

        # 前後の空白を削除
        df_norm["科目"] = df_norm["科目"].astype(str).str.strip()

        # 科目が空 or 'nan' の行を除外（nan文字対策）
        df_norm = df_norm[df_norm["科目"] != ""]
        df_norm = df_norm[df_norm["科目"].str.lower() != "nan"]

        # 金額がない行を除外
        df_norm = df_norm[df_norm["金額"].notna()]


        st.write("### 正規化プレビュー（科目＋金額）")
        st.dataframe(df_norm.head(20))

                # =========================
        # ② 利益系（再計算）サマリー
        # =========================
        st.write("### ② 利益サマリー（再計算）")

        def sum_by_keywords(df: pd.DataFrame, keywords: list[str]) -> float:
            """科目にキーワードが含まれる行の金額合計（なければ0）"""
            mask = df["科目"].astype(str).apply(lambda x: any(k in x for k in keywords))
            s = df.loc[mask, "金額"].sum()
            return float(s) if pd.notna(s) else 0.0

        # まずは“あなたのCSVで確認できた大分類”に合わせたキーワード
        sales = sum_by_keywords(df_norm, ["売上高"])
        cogs = sum_by_keywords(df_norm, ["売上原価"])
        sga = sum_by_keywords(df_norm, [
    "販売管理計", "販売管理費計", "販売管理費 計",
    "販管費計", "販管費 計",
    "販売費及び一般管理費計", "販売費及び一般管理費 計"
])


        nonop_income = sum_by_keywords(df_norm, ["営業外収益"])
        nonop_exp    = sum_by_keywords(df_norm, ["営業外費用"])

        special_gain = sum_by_keywords(df_norm, ["特別利益", "特別収益"])
        special_loss = sum_by_keywords(df_norm, ["特別損失"])

        taxes = sum_by_keywords(df_norm, ["法人税等"])
        tax_adj = sum_by_keywords(df_norm, ["法人税等調整額"])

        gross_profit = sales - cogs
        operating_profit = gross_profit - sga
        ordinary_profit = operating_profit + nonop_income - nonop_exp
        pretax_profit = ordinary_profit + special_gain - special_loss

        # 税引後（参考）：税金系を差し引く
        net_profit = pretax_profit - taxes - tax_adj

        # 表示（円で見やすく）
        def yen(x: float) -> str:
            return f"{int(round(x)):,.0f}"

        colA, colB = st.columns(2)
        with colA:
            st.metric("売上高", yen(sales))
            st.metric("売上原価", yen(cogs))
            st.metric("売上総利益", yen(gross_profit))
            st.metric("販管費", yen(sga))
        with colB:
            st.metric("営業利益", yen(operating_profit))
            st.metric("営業外収益", yen(nonop_income))
            st.metric("営業外費用", yen(nonop_exp))
            st.metric("経常利益", yen(ordinary_profit))
            st.metric("税引前利益", yen(pretax_profit))
            st.metric("税引後利益（参考）", yen(net_profit))


        st.info("次はこの正規化データを使って『小計・合計の除外』や『売上/費用/利益の簡易集計』に進めます。")

    except Exception as e:
        st.error("CSVの読み込みまたは意味づけ処理でエラーが発生しました。")
        st.error(e)
