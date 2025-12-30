import streamlit as st
import pandas as pd

# =========================
# タイトル
# =========================
st.title("会計DXアプリ")
st.write("試算表CSVをアップロードしてください。")

# =========================
# CSVアップロード
# =========================
uploaded_file = st.file_uploader(
    "CSVファイルを選択（ドラッグ＆ドロップ可）",
    type=["csv"]
)

# =========================
# CSV処理
# =========================
if uploaded_file is not None:
    try:
        # --- CSVを「壊れにくい設定」で読み込む ---
        df = pd.read_csv(
            uploaded_file,
            encoding="cp932",      # 日本の会計CSV対策
            header=None,           # 見出し行を信用しない
            engine="python",       # 列数不定CSV対策
            skiprows=1,            # タイトル行をスキップ
            on_bad_lines="skip"    # 壊れた行は無視
        )

        st.success("CSVの読み込みに成功しました。")

        # =========================
        # CSV形式チェック
        # =========================
        st.write("### CSV形式チェックを実行します")

        # --- 数値列の検出 ---
        numeric_columns = []

        for col in df.columns:
            converted = pd.to_numeric(df[col], errors="coerce")
            if converted.notna().sum() > 0:
                numeric_columns.append(col)

        # チェック①：金額列が2列以上あるか
        if len(numeric_columns) < 2:
            st.error(
                "❌ 金額と思われる列が2列未満です。"
                "このCSVは試算表として処理できない可能性があります。"
            )
            st.stop()

        st.success(f"✅ 金額と思われる列を {len(numeric_columns)} 列検出しました。")

        # --- 勘定科目っぽい列の検出 ---
        text_columns = [
            col for col in df.columns
            if df[col].astype(str).str.contains(
                "売上|費用|利益|原価|経費|収益",
                regex=True
            ).any()
        ]

        if not text_columns:
            st.warning(
                "⚠ 勘定科目と思われる列を特定できませんでした。"
                "列名や内容を確認してください。"
            )
        else:
            st.success("✅ 勘定科目と思われる列を検出しました。")

        # =========================
        # 結果表示
        # =========================
        st.success("CSV形式チェックを通過しました。")
        st.write("検出された数値列インデックス:", numeric_columns)

        st.write("### CSVデータ（先頭5行）")
        st.dataframe(df.head())

    except Exception as e:
        st.error("CSVの読み込みまたは形式チェックでエラーが発生しました。")
        st.error(e)
