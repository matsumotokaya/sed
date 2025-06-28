#!/bin/bash

# 仮想環境が存在しない場合は作成
if [ ! -d "venv" ]; then
    echo "仮想環境を作成しています..."
    python3 -m venv venv
fi

# 仮想環境を有効化
source venv/bin/activate

# 依存関係をインストール
echo "依存パッケージをインストールしています..."
pip install -r requirements.txt

# APIを起動（メモリ最適化オプション付き）
echo "Sound Event Detection APIを起動しています（ポート:8004）..."
# メモリ不足を防ぐためにガベージコレクタを積極的に実行
PYTHONUNBUFFERED=1 PYTHONMALLOC=malloc python -X faulthandler main.py 