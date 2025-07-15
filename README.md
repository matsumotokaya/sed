# Sound Event Detection (SED) API

YamNetモデルを使用して音声ファイルからサウンドイベントを検出するAPIです。  
**WatchMeライフログサービスの行動グラフダッシュボード**で使用される音声分析エンジンです。

## 🌐 外部公開URL

**本番環境URL**: `https://api.hey-watch.me/behavior-features/`

- マイクロサービスとして外部から利用可能
- SSL/HTTPS対応
- CORS設定済み

## 📝 **リポジトリ変更履歴**

**2025-07-15 - Version 1.3.0**:
- **🆕 外部URL公開**: `https://api.hey-watch.me/behavior-features/` で外部アクセス可能
- **✅ Nginxリバースプロキシ設定**: SSL/HTTPS対応、CORS設定完了
- **✅ マイクロサービス統合**: 他のWatchMeサービスとの統合が容易に
- **🧪 実運用テスト完了**: 2025-07-15データでの動作確認済み
- **📚 ドキュメント更新**: 外部URL対応、統合方法、APIドキュメントを拡充

**2025-07-13**: 
- リポジトリ名を `sed.git` から `watchme-behavior-yamnet.git` に変更しました。  
- Docker化による本番環境デプロイを実施しました。
- AWS EC2 (3.24.16.82) に正常デプロイ完了。
- systemdサービス化により常時稼働を実現。

## 🎯 **メイン機能**

このAPIは**EC2上の24時間ライフログ音声データ**を自動処理し、行動グラフダッシュボードに表示するための時系列サウンドイベントデータを生成します。

## 技術仕様

- **使用モデル**: Google YamNet
- **言語環境**: Python 3.11.8 (仮想環境必須)
- **実行方式**: FastAPI + venv仮想環境
- **ポート番号**: 8004
- **本番環境URL**: `https://api.hey-watch.me/behavior-features/`
- **デプロイ方式**: Docker + systemd + Nginx reverse proxy

## ⚠️ 重要: 仮想環境での実行が必須

このAPIは**仮想環境(venv)**で実行する必要があります。必要な依存関係（TensorFlow、YamNetなど）は仮想環境内にインストールされています。

### 正しい起動方法
```bash
# 方法1: 起動スクリプトを使用（推奨）
./start_sed_api.sh

# 方法2: 手動で仮想環境を有効化
source venv/bin/activate
python main.py
```

### 🚨 よくある間違い
```bash
# ❌ 間違い: システムPythonで実行
python3 main.py  # → TensorFlowが見つからないエラー

# ✅ 正解: 仮想環境で実行
source venv/bin/activate && python main.py
```
- **バージョン**: v1.2.0（Supabase統合機能搭載）
- **対応フォーマット**: WAV形式（任意のサンプルレート・チャンネル数）
- **処理時間**: 最大60秒（それ以上は自動切り詰め）

## エンドポイント一覧

### 🚀 **1. fetch-and-process - `/fetch-and-process` (POST) [新メイン機能]**

**Supabase統合エンドポイント**  
指定されたデバイス・日付の.wavファイルをAPIから取得し、一括音響イベント検出を行い、結果をSupabaseのbehavior_yamnetテーブルに直接保存します。

#### 用途
- **WatchMe行動グラフダッシュボード**: リアルタイムデータベース連携
- **自動データ処理**: 音声取得から分析、保存まで一括処理
- **統合システム**: 他のAPIとの連携によるデータ統合

#### リクエスト
```bash
# ローカル環境
curl -X POST -H "Content-Type: application/json" \
  -d '{"device_id": "device123", "date": "2025-07-08", "threshold": 0.2}' \
  "http://localhost:8004/fetch-and-process"

# 本番環境（外部URL）
curl -X POST -H "Content-Type: application/json" \
  -d '{"device_id": "device123", "date": "2025-07-08", "threshold": 0.2}' \
  "https://api.hey-watch.me/behavior-features/fetch-and-process"
```

#### パラメータ
- `device_id` (必須): デバイスID
- `date` (必須): 日付（YYYY-MM-DD形式）
- `threshold` (オプション): 確信度の閾値（デフォルト: 0.2）

#### レスポンス例
```json
{
  "status": "success",
  "fetched": ["18-00.wav", "18-30.wav"],
  "processed": ["18-00", "18-30"],
  "saved_to_supabase": ["18-00", "18-30"],
  "skipped": ["00-00", "00-30", "01-00"],
  "errors": [],
  "summary": {
    "total_time_blocks": 48,
    "audio_fetched": 2,
    "supabase_saved": 2,
    "skipped_no_data": 46,
    "errors": 0
  }
}
```

#### Supabaseテーブル構造 (behavior_yamnet)
```sql
CREATE TABLE behavior_yamnet (
  device_id     text NOT NULL,
  date          date NOT NULL,
  time_block    text NOT NULL CHECK (time_block ~ '^[0-2][0-9]-[0-5][0-9]$'),
  events        jsonb NOT NULL,
  PRIMARY KEY (device_id, date, time_block)
);
```

#### 保存されるeventsデータ例
```json
[
  {"label": "Speech", "prob": 0.98},
  {"label": "Silence", "prob": 1.0},
  {"label": "Inside, small room", "prob": 0.31}
]
```

### 🚀 **2. タイムライン検出v2 - `/analyze/sed/timeline-v2` (POST) [従来機能]**

**行動グラフダッシュボード専用エンドポイント**  
EC2上の音声ファイルを逐次処理してタイムライン分析を実行します。24時間分の30分単位スロット（48個）を対象とし、存在しないファイルは無視します。

#### 用途
- **WatchMe行動グラフダッシュボード**: 24時間のライフログ音声を可視化
- **日次バッチ処理**: 指定日の全音声データを自動処理
- **プロファイリング分析**: 生活パターンと音声イベントの相関分析

#### リクエスト
```bash
# ローカル環境
curl -X POST -H "Content-Type: application/json" \
  -d '{"device_id": "device123", "date": "2025-06-21"}' \
  "http://localhost:8004/analyze/sed/timeline-v2?threshold=0.2"

# 本番環境（外部URL）
curl -X POST -H "Content-Type: application/json" \
  -d '{"device_id": "device123", "date": "2025-06-21"}' \
  "https://api.hey-watch.me/behavior-features/analyze/sed/timeline-v2?threshold=0.2"
```

#### パラメータ
- `device_id` (必須): デバイスID
- `date` (必須): 日付（YYYY-MM-DD形式）
- `threshold` (オプション): 確信度の閾値（デフォルト: 0.2）

#### レスポンス例
```json
{
  "device_id": "device123",
  "date": "2025-06-21",
  "total_processed_slots": 15,
  "total_available_slots": 48,
  "processed_slots": [
    {
      "slot": "14-00",
      "timeline": [
        {"start": 0.0, "end": 0.48, "label": "Speech", "prob": 0.93}
      ],
      "slot_timeline": [
        {
          "time": 0.0,
          "events": [{"label": "Speech", "prob": 0.93}]
        }
      ]
    }
  ]
}
```

#### 処理フロー（完全自動化）
1. **EC2ダウンロード**: `https://api.hey-watch.me/download` からWAVファイル取得
2. **音声解析**: YamNetモデルでSound Event Detection実行
3. **ローカル保存**: `/Users/kaya.matsumoto/data/data_accounts/{device_id}/{date}/sed/{slot}.json`
4. **EC2アップロード**: `https://api.hey-watch.me/upload/analysis/sed-timeline` に結果をアップロード

#### 特徴
- **リモートファイル処理**: EC2上の音声ファイルをHTTPS経由でダウンロード
- **デュアル保存**: ローカルとEC2の両方に結果を保存
- **バッチ処理**: 24時間分（48スロット）の音声を逐次処理
- **エラーハンドリング**: 存在しないファイルは自動的にスキップ
- **詳細ログ**: 各スロットの処理状況をリアルタイム出力

#### 検出可能な音声イベント例
- **Speech** (会話・発話)
- **Music** (音楽)
- **Silence** (無音・静寂)
- **Door, Knock** (ドア・ノック音)
- **Hands, Clapping** (手の動作・拍手)
- **Chopping (food)** (料理・切る音)
- **Fire, Crackle** (火・パチパチ音)
- **Inside, small room** (室内環境音)
- **Breathing, Snoring** (呼吸・いびき)

#### 出力ファイル
- **ローカル**: `/Users/kaya.matsumoto/data/data_accounts/{device_id}/{date}/sed/`
  - `{slot}.json` - 各スロットの処理結果
  - `processing_summary.json` - 処理サマリー  
- **EC2**: `/home/ubuntu/data/data_accounts/{device_id}/{date}/sed/{slot}.json`

### 2. **タイムライン検出** - `/analyze/sed/timeline` (POST)

フレーム単位（約0.48秒）でのサウンドイベントの時系列データを出力します。

#### リクエスト
```bash
curl -X POST -F "file=@audio.wav" \
  "http://localhost:8004/analyze/sed/timeline?threshold=0.2"
```

#### パラメータ
- `file` (必須): WAVファイル
- `threshold` (オプション): 確信度の閾値（デフォルト: 0.2）

#### レスポンス例
```json
{
  "timeline": [
    {"start": 0.0, "end": 0.48, "label": "Speech", "prob": 0.93},
    {"start": 0.48, "end": 0.96, "label": "Music", "prob": 0.67}
  ],
  "slot_timeline": [
    {
      "time": 0.0,
      "events": [
        {"label": "Speech", "prob": 0.93},
        {"label": "Music", "prob": 0.45}
      ]
    }
  ]
}
```

### 3. **基本検出** - `/analyze/sed` (POST)

音声ファイル全体の上位N件のサウンドイベントを検出します。

#### リクエスト
```bash
curl -X POST -F "file=@audio.wav" -F "top_n=20" http://localhost:8004/analyze/sed
```

#### パラメータ
- `file` (必須): WAVファイル
- `top_n` (オプション): 上位何件を返すか（デフォルト: 20）

#### レスポンス例
```json
{
  "sed": [
    {"label": "Dog", "prob": 0.72},
    {"label": "Keyboard typing", "prob": 0.55},
    {"label": "Speech", "prob": 0.49}
  ]
}
```

### 4. **要約検出** - `/analyze/sed/summary` (POST)

約3秒ごとにセグメント化し、各セグメント内のイベントラベルを要約して出力します。

#### リクエスト
```bash
curl -X POST -F "file=@audio.wav" \
  "http://localhost:8004/analyze/sed/summary?threshold=0.2&segment_seconds=3.0"
```

#### パラメータ
- `file` (必須): WAVファイル
- `threshold` (オプション): 確信度の閾値（デフォルト: 0.2）
- `segment_seconds` (オプション): セグメントの長さ（秒）（デフォルト: 3.0）

#### レスポンス例
```json
{
  "summary": [
    {
      "start": 0.0,
      "end": 2.88,
      "labels": ["Music", "Singing", "Child singing"]
    },
    {
      "start": 2.88,
      "end": 5.76,
      "labels": ["Hands", "Music", "Singing"]
    }
  ]
}
```

### 5. **ヘルスチェック** - `/` (GET)

APIの動作確認用エンドポイント

#### リクエスト
```bash
# ローカル環境
curl http://localhost:8004/

# 本番環境（外部URL）
curl https://api.hey-watch.me/behavior-features/
```

#### レスポンス
```json
{"message": "Sound Event Detection API is running"}
```

### 6. **テストエンドポイント** - `/test` (GET)

依存ライブラリとモデルの状態確認用

#### リクエスト
```bash
# ローカル環境
curl http://localhost:8004/test

# 本番環境（外部URL）
curl https://api.hey-watch.me/behavior-features/test
```

## セットアップと実行方法

### 推奨：スクリプトを使った実行（macOS/Linux）

```bash
# 実行権限を付与（初回のみ）
chmod +x start_sed_api.sh

# 実行
./start_sed_api.sh
```

### 手動でのセットアップと実行

```bash
# 仮想環境を作成
python -m venv venv
source venv/bin/activate  # Windowsの場合: venv\Scripts\activate

# 依存関係をインストール
pip install -r requirements.txt

# aiohttpが含まれていない場合は追加インストール
pip install aiohttp==3.9.0

# APIの実行
python main.py
```

## 🔧 **トラブルシューティング**

### 🚨 **TensorFlow Hubキャッシュ破損エラー (最頻出問題)**

**症状:**
```
ValueError: Trying to load a model of incompatible/unknown type. 
'/var/folders/.../tfhub_modules/...' contains neither 'saved_model.pb' nor 'saved_model.pbtxt'.
```

**原因:** TensorFlow Hubのモデルキャッシュが破損しています。これは**頻繁に発生する既知の問題**です。

**🆕 v1.2.0 強化された自動回復機能:**
- **詳細診断**: キャッシュ破損の具体的な原因特定
- **自動検出**: 起動時とモデルロード時の二重チェック
- **完全修復**: 破損キャッシュの自動削除と再ダウンロード
- **分かりやすいログ**: 絵文字とステップ表示でエラー原因を明確化

**解決法 (自動):**
```bash
# APIには自動回復機能が組み込まれています
# エラー発生時に自動的にキャッシュをクリアして再試行されます

# ログ例:
🚨 TensorFlow Hubキャッシュ破損エラー検出!
   エラー詳細: contains neither 'saved_model.pb' nor 'saved_model.pbtxt'
   原因: キャッシュディレクトリ内のモデルファイルが不完全
   対処: キャッシュを削除して再ダウンロードします
🔄 5秒後に再試行します...
```

**解決法 (手動):**
```bash
# 方法1: デバッグエンドポイントを使用 (推奨)
curl -X POST http://localhost:8004/debug/clear-cache

# 方法2: 手動でキャッシュ削除
rm -rf /var/folders/*/T/tfhub_modules*
rm -rf ~/tfhub_modules
rm -rf /tmp/tfhub_modules

# 方法3: 仮想環境でスクリプト実行
source venv/bin/activate
python3 -c "
import shutil, glob, os
for path in glob.glob('/var/folders/*/T/tfhub_modules*'):
    if os.path.exists(path): shutil.rmtree(path)
print('キャッシュクリア完了')
"
```

**予防策:**
```bash
# キャッシュ状態の事前チェック
curl http://localhost:8004/debug/cache-status
```

### 🚨 **仮想環境エラー**

**症状:**
```
ModuleNotFoundError: No module named 'tensorflow'
```

**解決法:**
```bash
# 必ず仮想環境で実行
source venv/bin/activate
python main.py

# または起動スクリプトを使用
./start_sed_api.sh
```

### 🚨 **メモリ不足エラー**

**症状:**
```
OutOfMemoryError: CUDA out of memory
```

**解決法:**
```bash
# 他のプロセスを停止
pkill -f python

# APIを再起動
source venv/bin/activate && python main.py
```

### 🚨 **ポート競合エラー**

**症状:**
```
Address already in use: 8004
```

**解決法:**
```bash
# ポート使用状況確認
lsof -i :8004

# プロセス終了
kill -9 <PID>

# API再起動
source venv/bin/activate && python main.py
```

### 🔍 **新しいデバッグエンドポイント**

**キャッシュ状態確認:**
```bash
curl http://localhost:8004/debug/cache-status
```

**キャッシュ手動クリア:**
```bash
curl -X POST http://localhost:8004/debug/clear-cache
```

**API基本動作確認:**
```bash
curl http://localhost:8004/test
```

### 💡 **プロアクティブ対策**

1. **定期的なキャッシュチェック**: 週1回程度 `debug/cache-status` で確認
2. **仮想環境の確認**: 起動前に `which python` で確認
3. **メモリ監視**: 長時間稼働時は定期的な再起動
4. **ログ監視**: エラーログの定期確認

### **診断ログの読み方**

**正常起動時:**
```
=== 起動時診断結果 ===
✅ TensorFlow: 正常
✅ TensorFlow Hub: 正常
✅ モデルキャッシュ: 正常
=========================
```

**キャッシュ破損検出時:**
```
🔍 TensorFlow Hubキャッシュの整合性チェックを開始...
🚨 破損キャッシュ発見: /var/folders/.../tfhub_modules/xxx
   原因: saved_model.pb が存在しません
✅ 破損キャッシュを自動削除: /var/folders/.../tfhub_modules/xxx
🔧 1/1 個の破損キャッシュを修復しました
```

**手動解決方法**（自動回復が効かない場合）:
```bash
# 1. TensorFlow Hubキャッシュを完全クリア
rm -rf /var/folders/*/T/tfhub_modules*
rm -rf ~/tfhub_modules

# 2. APIサーバーを停止
pkill -f "python.*main.py"

# 3. APIサーバーを再起動（モデルが自動再ダウンロードされる）
source venv/bin/activate
python main.py
```

### **よくある問題と解決方法**

#### 1. **ポート競合エラー**
```
ERROR: [Errno 48] Address already in use
```

**解決方法**:
```bash
# 既存プロセスを終了
pkill -f "python.*main.py"

# ポート使用状況確認
lsof -i :8004

# APIサーバー再起動
python main.py
```

#### 2. **依存関係エラー**
```
ModuleNotFoundError: No module named 'tensorflow'
```

**解決方法**:
```bash
# 仮想環境が有効化されているか確認
source venv/bin/activate

# 依存関係を再インストール
pip install -r requirements.txt

# Apple Silicon Macの場合
pip install tensorflow-macos==2.13.0
```

#### 3. **メモリ不足エラー**

**解決方法**:
- 長時間音声ファイルは自動的に60秒に切り詰められます
- 同時処理を避け、数分間隔を空ける
- APIサーバーを定期的に再起動

#### 4. **EC2接続エラー**

**確認項目**:
```bash
# EC2 Vault APIの動作確認
curl https://api.hey-watch.me/

# ネットワーク接続確認
ping api.hey-watch.me
```

### **ログの確認**

APIのログは標準出力に表示されます。以下の情報が出力されます：
- ファイル読み込み状況
- サンプルレート変換の詳細
- モデルロード状況
- 推論結果の統計
- EC2ダウンロード/アップロード状況

**重要なログメッセージ**:
- `✅ 処理完了` - 正常処理
- `❌ 処理失敗` - エラー発生
- `⏭️ スキップ` - ファイル不存在（正常）
- `☁️ EC2アップロード開始` - アップロード開始
- **🆕 v1.1.0 診断ログ**:
  - `✅ TensorFlow: 正常` - TensorFlow正常動作
  - `✅ TensorFlow Hub: 正常` - TensorFlow Hub正常動作
  - `✅ モデルキャッシュ: 正常` - YamNetキャッシュ正常
  - `キャッシュクリア: {path}` - 破損キャッシュの自動削除
  - `モデルロード試行 {回数}/3` - 自動リトライ状況

## 技術的特徴

### オーディオ処理の最適化
- **自動リサンプリング**: 任意のサンプルレートを16kHzに変換
- **ステレオ→モノラル変換**: 自動で実行
- **振幅正規化**: 適切な範囲（-1.0〜1.0）に調整
- **長時間音声対応**: 60秒を超える音声は自動切り詰め

### メモリ最適化
- **遅延ロード**: 必要時のみYamNetモデルをロード
- **CPUモード**: GPUメモリ使用量を制限
- **セッションクリア**: メモリリークを防止

### エラーハンドリング
- 詳細なエラーログ出力
- ステップ別のエラー分離
- HTTPステータスコードの適切な設定
- **🆕 v1.1.0** 自動回復機能（TensorFlow Hubキャッシュ破損の自動修復）
- **🆕 v1.1.0** 起動時診断とヘルスチェック
- **🆕 v1.1.0** モデル読み込み失敗時の自動リトライ（最大3回）

## 🎯 **WatchMe行動グラフダッシュボード連携**

### **Streamlit実装例**

```python
import streamlit as st
import requests
from datetime import datetime

def call_sed_timeline_v2(device_id: str, date: str):
    """行動グラフ用SED分析を実行"""
    
    # 本番環境URL（外部アクセス）
    url = "https://api.hey-watch.me/behavior-features/analyze/sed/timeline-v2"
    payload = {"device_id": device_id, "date": date}
    
    try:
        with st.spinner("🎵 音声イベント分析中..."):
            response = requests.post(
                url, 
                json=payload,
                params={"threshold": 0.2},
                timeout=300  # 5分タイムアウト
            )
            
        if response.status_code == 200:
            result = response.json()
            st.success(f"✅ 分析完了: {result['total_processed_slots']}/{result['total_available_slots']} スロット処理")
            
            # 行動グラフ表示用データ処理
            for slot_data in result['processed_slots']:
                st.subheader(f"⏰ {slot_data['slot']}")
                events = [event['label'] for event in slot_data['slot_timeline'] if event['events']]
                st.write(f"検出イベント: {', '.join(events)}")
                
            return result
        else:
            st.error(f"❌ API呼び出しエラー: {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        st.warning("⏰ タイムアウトが発生しましたが、サーバー側では処理が継続されています")
        return None

# Streamlitアプリ部分
st.title("🎵 WatchMe 行動グラフ - Sound Event Detection")

with st.form("sed_form"):
    device_id = st.text_input("デバイスID", value="device123")
    date = st.date_input("分析対象日", value=datetime.now().date())
    
    submitted = st.form_submit_button("🚀 音声イベント分析実行")
    
    if submitted:
        if device_id and date:
            result = call_sed_timeline_v2(device_id, str(date))
        else:
            st.error("デバイスIDと日付を入力してください")
```

## 🚀 本番環境設定（AWS EC2）

### 本番環境情報
- **サーバー**: AWS EC2 (Ubuntu)
- **IPアドレス**: 3.24.16.82
- **ディレクトリ**: `/home/ubuntu/watchme-behavior-yamnet`
- **ポート**: 8004
- **コンテナ名**: sed_api

### 本番環境へのデプロイ手順（Docker使用）

#### 1️⃣ Dockerイメージのビルド（ローカル環境）
```bash
# requirements-docker.txtを作成（Linux用に調整）
# tensorflow-macosをtensorflowに変更
# バージョン制約を緩める

# Dockerイメージをビルド
docker build -t watchme-behavior-yamnet:latest .

# イメージをtar形式で保存
docker save watchme-behavior-yamnet:latest | gzip > watchme-behavior-yamnet.tar.gz
```

#### 2️⃣ 本番環境への転送
```bash
# SSHキーを使用してイメージを転送
scp -i ~/watchme-key.pem watchme-behavior-yamnet.tar.gz ubuntu@3.24.16.82:/home/ubuntu/

# 本番環境にSSH接続
ssh -i ~/watchme-key.pem ubuntu@3.24.16.82
```

#### 3️⃣ 本番環境でのセットアップ
```bash
# Dockerイメージをロード
gunzip -c /home/ubuntu/watchme-behavior-yamnet.tar.gz | docker load

# ディレクトリ作成
mkdir -p /home/ubuntu/watchme-behavior-yamnet

# .envファイルを作成（Supabase接続情報）
cat > /home/ubuntu/watchme-behavior-yamnet/.env << 'EOF'
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
EOF

# Dockerコンテナとして起動（テスト）
docker run -d --restart unless-stopped -p 8004:8004 \
  --env-file /home/ubuntu/watchme-behavior-yamnet/.env \
  --name sed_api watchme-behavior-yamnet:latest
```

### systemdサービス設定（自動起動）

#### 1️⃣ サービスファイルの作成
```bash
sudo vi /etc/systemd/system/watchme-behavior-yamnet.service
```

以下の内容を記載：
```ini
[Unit]
Description=WatchMe Behavior YamNet (Sound Event Detection) API Service
After=docker.service
Requires=docker.service

[Service]
Type=simple
RemainAfterExit=yes
ExecStartPre=-/usr/bin/docker stop sed_api
ExecStartPre=-/usr/bin/docker rm sed_api
ExecStart=/usr/bin/docker run --rm --name sed_api -p 8004:8004 --env-file /home/ubuntu/watchme-behavior-yamnet/.env watchme-behavior-yamnet:latest
ExecStop=/usr/bin/docker stop sed_api
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### 2️⃣ サービスの有効化と起動
```bash
# systemdのリロード
sudo systemctl daemon-reload

# サービスを有効化（自動起動設定）
sudo systemctl enable watchme-behavior-yamnet.service

# サービスを起動
sudo systemctl start watchme-behavior-yamnet.service
```

#### 3️⃣ サービス管理コマンド
```bash
# サービス状態確認
sudo systemctl status watchme-behavior-yamnet.service

# サービス再起動
sudo systemctl restart watchme-behavior-yamnet.service

# サービス停止
sudo systemctl stop watchme-behavior-yamnet.service

# ログ確認（systemd）
sudo journalctl -u watchme-behavior-yamnet.service -f

# ログ確認（Docker）
docker logs sed_api
```

### 本番環境での動作確認

#### APIヘルスチェック
```bash
# サーバー内から
curl http://localhost:8004/

# 外部から（ポートが開放されている場合）
curl http://3.24.16.82:8004/
```

#### 音声イベント検出テスト
```bash
# ローカル環境でのテスト
curl -X POST http://localhost:8004/fetch-and-process \
  -H "Content-Type: application/json" \
  -d '{"device_id": "d067d407-cf73-4174-a9c1-d91fb60d64d0", "date": "2025-07-10", "threshold": 0.2}'

# 本番環境（外部URL）でのテスト
curl -X POST https://api.hey-watch.me/behavior-features/fetch-and-process \
  -H "Content-Type: application/json" \
  -d '{"device_id": "d067d407-cf73-4174-a9c1-d91fb60d64d0", "date": "2025-07-15", "threshold": 0.2}'
```

### トラブルシューティング

#### Dockerイメージのビルドエラー
```bash
# 依存関係の競合が発生した場合
# requirements-docker.txtでバージョン制約を緩める
# 例: tensorflow>=2.16.0,<2.20.0
#     numpy>=1.26.0
#     scipy>=1.11.0
```

#### systemdサービスが起動しない場合
```bash
# エラーログを確認
sudo journalctl -u watchme-behavior-yamnet.service -n 50 --no-pager

# Dockerコンテナの状態確認
docker ps -a | grep sed_api

# 手動でDockerコンテナを起動してエラー確認
docker run --rm -p 8004:8004 --env-file /home/ubuntu/watchme-behavior-yamnet/.env watchme-behavior-yamnet:latest
```

#### TensorFlow Hubキャッシュエラー
```bash
# コンテナ内のキャッシュをクリア
docker exec sed_api rm -rf /tmp/tfhub_modules*
docker restart sed_api
```

## 注意事項

- **対応フォーマット**: 現在はWAVファイル形式のみサポート
- **処理時間**: ファイルサイズと長さに依存（スロットあたり10-20秒）
- **メモリ使用量**: 大きなファイルでは一時的にメモリを多く消費
- **同時接続**: 同時に複数のリクエストを処理可能
- **安全な運用**: 同じデバイス・日付の同時処理は避ける（ファイル競合リスク）

## 🔗 マイクロサービス統合

### 外部サービスからの利用方法

```python
import requests
import asyncio
import aiohttp

# 同期版
def analyze_sound_events(device_id: str, date: str):
    url = "https://api.hey-watch.me/behavior-features/fetch-and-process"
    data = {"device_id": device_id, "date": date, "threshold": 0.2}
    
    response = requests.post(url, json=data)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API Error: {response.text}")

# 非同期版
async def analyze_sound_events_async(device_id: str, date: str):
    url = "https://api.hey-watch.me/behavior-features/fetch-and-process"
    data = {"device_id": device_id, "date": date, "threshold": 0.2}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise Exception(f"API Error: {await response.text()}")

# 使用例
result = analyze_sound_events("d067d407-cf73-4174-a9c1-d91fb60d64d0", "2025-07-15")
print(result)
```

### 利用可能なエンドポイント

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/` | GET | ヘルスチェック |
| `/test` | GET | 依存関係確認 |
| `/fetch-and-process` | POST | Supabase統合処理 |
| `/analyze/sed/timeline-v2` | POST | タイムライン分析 |
| `/analyze/sed/timeline` | POST | フレーム単位分析 |
| `/analyze/sed` | POST | 基本検出 |
| `/analyze/sed/summary` | POST | 要約検出 |

### APIドキュメント

- **Base URL**: `https://api.hey-watch.me/behavior-features/`
- **認証**: 不要
- **CORS**: 有効化済み

### セキュリティ設定

- ✅ HTTPS対応（SSL証明書あり）
- ✅ CORS設定済み
- ✅ 適切なヘッダー設定
- ✅ レート制限対応（Nginxレベル）

## 🧪 テスト実績

### 2025年7月15日テスト結果（外部URL経由）

**テストデバイス**: `d067d407-cf73-4174-a9c1-d91fb60d64d0`

```bash
# ✅ 外部URL経由でのテスト
curl -X POST "https://api.hey-watch.me/behavior-features/fetch-and-process" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "d067d407-cf73-4174-a9c1-d91fb60d64d0", "date": "2025-07-15", "threshold": 0.2}'
```

**処理結果**:
```json
{
  "status": "success",
  "fetched": ["14-00.wav", "15-30.wav"],
  "processed": ["14-00", "15-30"],
  "saved_to_supabase": ["14-00", "15-30"],
  "skipped": [...],
  "errors": [],
  "summary": {
    "total_time_blocks": 48,
    "audio_fetched": 2,
    "supabase_saved": 2,
    "skipped_no_data": 46,
    "errors": 0
  }
}
```

**テスト結果**:
- ✅ **外部アクセス**: HTTPS経由で正常動作
- ✅ **音声データ取得**: 2ファイル（14:00, 15:30）正常処理
- ✅ **YamNet分析**: 音声イベント検出正常実行
- ✅ **Supabaseデータ保存**: behavior_yamnetテーブルに正常保存
- ✅ **エラーハンドリング**: 欠損データ（46個）を適切にスキップ
- ✅ **処理時間**: 即座にレスポンス返却

### 2025年7月13日テスト結果（初回デプロイ）

**Docker化デプロイ**:
- ✅ EC2 (3.24.16.82) に正常デプロイ完了
- ✅ systemdサービス化により24時間稼働
- ✅ TensorFlow Hub自動回復機能が正常動作

---

## 🌟 WatchMeマイクロサービス・エコシステム統合

### 現在稼働中のマイクロサービス

| サービス名 | 外部URL | 機能 |
|-----------|---------|------|
| **vibe-transcriber** | `https://api.hey-watch.me/vibe-transcriber/` | 音声転写（Whisper） |
| **vibe-aggregator** | `https://api.hey-watch.me/vibe-aggregator/` | プロンプト生成 |
| **vibe-scorer** | `https://api.hey-watch.me/vibe-scorer/` | 心理グラフ生成 |
| **behavior-features** | `https://api.hey-watch.me/behavior-features/` | 音声イベント検出 |

### データフロー統合

```
iOS App → vibe-transcriber → vibe-aggregator → vibe-scorer
             ↓
     behavior-features → Dashboard
```

1. **音声収録**: iOSアプリで30分毎に音声を録音
2. **音声転写**: vibe-transcriber（Whisper）で音声をテキスト化
3. **プロンプト生成**: vibe-aggregatorで1日分のプロンプトを生成
4. **心理分析**: vibe-scorerでChatGPTによる心理グラフを生成
5. **行動分析**: behavior-featuresでYamNetによる音声イベント検出
6. **統合表示**: ダッシュボードで心理状態と行動パターンを可視化

## ライセンス

このプロジェクトで使用している主要コンポーネント：
- **YamNet**: Google Research（Apache 2.0 License）
- **TensorFlow**: Google（Apache 2.0 License）
- **FastAPI**: Sebastian Ramirez（MIT License） 