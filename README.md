# Sound Event Detection (SED) API

YamNetモデルを使用して音声ファイルからサウンドイベントを検出するAPIです。  
**WatchMeライフログサービスの行動グラフダッシュボード**で使用される音声分析エンジンです。

## 🎯 **メイン機能**

このAPIは**EC2上の24時間ライフログ音声データ**を自動処理し、行動グラフダッシュボードに表示するための時系列サウンドイベントデータを生成します。

## 技術仕様

- **使用モデル**: Google YamNet
- **言語環境**: Python 3.11.8
- **実行方式**: FastAPI + 仮想環境
- **ポート番号**: 8004
- **バージョン**: v1.1.0（自動回復機能搭載）
- **対応フォーマット**: WAV形式（任意のサンプルレート・チャンネル数）
- **処理時間**: 最大60秒（それ以上は自動切り詰め）

## エンドポイント一覧

### 🚀 **1. タイムライン検出v2 - `/analyze/sed/timeline-v2` (POST) [メイン機能]**

**行動グラフダッシュボード専用エンドポイント**  
EC2上の音声ファイルを逐次処理してタイムライン分析を実行します。24時間分の30分単位スロット（48個）を対象とし、存在しないファイルは無視します。

#### 用途
- **WatchMe行動グラフダッシュボード**: 24時間のライフログ音声を可視化
- **日次バッチ処理**: 指定日の全音声データを自動処理
- **プロファイリング分析**: 生活パターンと音声イベントの相関分析

#### リクエスト
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"user_id": "user123", "date": "2025-06-21"}' \
  "http://localhost:8004/analyze/sed/timeline-v2?threshold=0.2"
```

#### パラメータ
- `user_id` (必須): ユーザーID
- `date` (必須): 日付（YYYY-MM-DD形式）
- `threshold` (オプション): 確信度の閾値（デフォルト: 0.2）

#### レスポンス例
```json
{
  "user_id": "user123",
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
3. **ローカル保存**: `/Users/kaya.matsumoto/data/data_accounts/{user_id}/{date}/sed/{slot}.json`
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
- **ローカル**: `/Users/kaya.matsumoto/data/data_accounts/{user_id}/{date}/sed/`
  - `{slot}.json` - 各スロットの処理結果
  - `processing_summary.json` - 処理サマリー  
- **EC2**: `/home/ubuntu/data/data_accounts/{user_id}/{date}/sed/{slot}.json`

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
curl http://localhost:8004/
```

#### レスポンス
```json
{"message": "Sound Event Detection API is running"}
```

### 6. **テストエンドポイント** - `/test` (GET)

依存ライブラリとモデルの状態確認用

#### リクエスト
```bash
curl http://localhost:8004/test
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

### **YamNetモデルロード失敗（最重要）**

**症状**: 
```
ValueError: Trying to load a model of incompatible/unknown type. 
'/var/folders/.../tfhub_modules/...' contains neither 'saved_model.pb' nor 'saved_model.pbtxt'.
```

**原因**: TensorFlow Hubキャッシュファイルの破損

**🆕 v1.1.0 自動回復機能**:
APIに以下の自動回復機能が実装されました：
- **起動時診断**: API起動時に全コンポーネントの正常性を自動チェック
- **キャッシュ検証**: モデルキャッシュの整合性を自動確認
- **自動リトライ**: モデル読み込み失敗時の自動キャッシュクリア＆再試行（最大3回）
- **診断ログ**: 起動時に以下が表示されます
  ```
  === 起動時診断結果 ===
  ✅ TensorFlow: 正常
  ✅ TensorFlow Hub: 正常
  ✅ モデルキャッシュ: 正常
  =========================
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

def call_sed_timeline_v2(user_id: str, date: str):
    """行動グラフ用SED分析を実行"""
    
    url = "http://localhost:8004/analyze/sed/timeline-v2"
    payload = {"user_id": user_id, "date": date}
    
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
    user_id = st.text_input("ユーザーID", value="user123")
    date = st.date_input("分析対象日", value=datetime.now().date())
    
    submitted = st.form_submit_button("🚀 音声イベント分析実行")
    
    if submitted:
        if user_id and date:
            result = call_sed_timeline_v2(user_id, str(date))
        else:
            st.error("ユーザーIDと日付を入力してください")
```

## 注意事項

- **対応フォーマット**: 現在はWAVファイル形式のみサポート
- **処理時間**: ファイルサイズと長さに依存（スロットあたり10-20秒）
- **メモリ使用量**: 大きなファイルでは一時的にメモリを多く消費
- **同時接続**: 同時に複数のリクエストを処理可能
- **安全な運用**: 同じユーザー・日付の同時処理は避ける（ファイル競合リスク）

## ライセンス

このプロジェクトで使用している主要コンポーネント：
- **YamNet**: Google Research（Apache 2.0 License）
- **TensorFlow**: Google（Apache 2.0 License）
- **FastAPI**: Sebastian Ramirez（MIT License） 