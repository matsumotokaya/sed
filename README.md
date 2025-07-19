# Sound Event Detection (SED) API - 音声処理APIのリファレンス実装

YamNetモデルを使用して音声ファイルからサウンドイベントを検出するAPI。**このAPIはWhisper APIに続く音声処理APIのリファレンス実装です。**

## 🎯 重要：このAPIがリファレンス実装である理由

このAPIは、WatchMeエコシステムにおける音声ファイル処理の標準的な実装パターンを継承しています：

1. **file_pathベースの処理**: Whisper APIと同じく`file_path`を主キーとして使用
2. **ステータス管理**: 処理完了後に`audio_files`テーブルの`behavior_features_status`を更新
3. **シンプルな責務分離**: 音響イベント検出に特化し、ファイル管理はVault APIに委譲
4. **統一されたエラーハンドリング**: Whisper APIと同じパターンでエラー処理

## 🔄 最新アップデート (2025-12-19)

### ⚡ 重要な設計改善: Whisper APIパターンの採用

#### 変更内容
1. **file_pathsベースのインターフェース追加**
   - **新エンドポイント**: `/fetch-and-process-paths`
   - **リクエスト形式**: Whisper APIと同じ`file_paths`配列
   - **レスポンス形式**: 統一されたレスポンス構造
   
2. **audio_filesテーブルとの連携**
   - **ステータス更新**: `behavior_features_status`を`completed`に更新
   - **S3直接アクセス**: Vault API経由ではなく、S3から直接音声ファイルを取得
   
3. **リファレンス実装の確立**
   - Whisper APIの成功パターンを音響イベント検出に適用
   - 他の音声処理APIが参照できる標準実装

### 🏗️ アーキテクチャのベストプラクティス

```python
# ✅ 新しいfile_pathsベースの処理
@app.post("/fetch-and-process-paths")
async def fetch_and_process_paths(request: FetchAndProcessPathsRequest):
    # file_pathsを受け取る
    for file_path in request.file_paths:
        # S3から直接ダウンロード
        s3_client.download_file(bucket, file_path, temp_file)
        
        # 音響イベント検出を実行
        result = process_audio_data(audio_content, threshold)
        
        # 結果をbehavior_yamnetテーブルに保存
        await save_to_supabase(device_id, date, time_block, events)
        
        # ステータスを更新（重要！）
        await update_audio_files_status(file_path)
```

## 📋 Whisper APIパターンの実装ガイド

### 1. 基本的な処理フロー（統一パターン）

```python
# Step 1: file_pathsを受け取る
request.file_paths = ["files/device_id/date/time/audio.wav", ...]

# Step 2: 各ファイルを処理
for file_path in request.file_paths:
    # S3からダウンロード
    s3_client.download_file(bucket, file_path, temp_file)
    
    # 音声処理を実行（API固有の処理）
    result = process_audio_data(temp_file, threshold)  # 音響イベント検出
    
    # 結果をSupabaseに保存
    await save_to_supabase(device_id, date, time_block, events)
    
    # ステータスを更新（重要！）
    await update_audio_files_status(file_path)
```

### 2. ステータスフィールドの命名規則

各APIは`audio_files`テーブルの専用ステータスフィールドを更新します：

- `transcriptions_status`: Whisper API
- `behavior_features_status`: Sound Event Detection API（このAPI）
- `emotion_features_status`: 感情分析API
- など、`{feature}_status`の形式で命名

### 3. エラーハンドリング（統一パターン）

```python
try:
    # ステータス更新
    update_response = supabase.table('audio_files') \
        .update({'behavior_features_status': 'completed'}) \
        .eq('file_path', file_path) \
        .execute()
    
    if update_response.data:
        print(f"✅ ステータス更新成功: {file_path}")
    else:
        print(f"⚠️ 対象レコードが見つかりません: {file_path}")
        
except Exception as e:
    print(f"❌ ステータス更新エラー: {str(e)}")
    # エラーでも処理は継続
```

## 🚀 APIエンドポイント仕様

### 新：POST /fetch-and-process-paths（推奨）

Whisper APIパターンに合わせた新しいエンドポイント

#### リクエスト
```json
{
  "file_paths": [
    "files/d067d407-cf73-4174-a9c1-d91fb60d64d0/2025-07-19/14-30/audio.wav"
  ],
  "threshold": 0.2
}
```

#### レスポンス
```json
{
  "status": "success",
  "summary": {
    "total_files": 1,
    "pending_processed": 1,
    "errors": 0
  },
  "processed_files": ["files/.../audio.wav"],
  "processed_time_blocks": ["14-30"],
  "error_files": null,
  "execution_time_seconds": 8.7,
  "message": "1件中1件を正常に処理しました"
}
```

### 従来：POST /fetch-and-process（互換性維持）

従来のdevice_id/dateベースのエンドポイント（既存システムとの互換性のため維持）

#### リクエスト
```json
{
  "device_id": "d067d407-cf73-4174-a9c1-d91fb60d64d0",
  "date": "2025-07-19",
  "threshold": 0.2
}
```

## 💾 データベース設計

### audio_filesテーブル（共通）
```sql
CREATE TABLE audio_files (
  device_id text NOT NULL,
  recorded_at timestamp WITH TIME ZONE NOT NULL,
  file_path text UNIQUE NOT NULL,  -- 主キーとして使用
  transcriptions_status text DEFAULT 'pending',
  behavior_features_status text DEFAULT 'pending',  -- このAPIが更新
  emotion_features_status text DEFAULT 'pending',
  -- 他のステータスフィールド
);
```

### behavior_yamnetテーブル（このAPI固有）
```sql
CREATE TABLE behavior_yamnet (
  device_id text NOT NULL,
  date date NOT NULL,
  time_block text NOT NULL,
  events jsonb NOT NULL,
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

## 🛠️ 開発環境セットアップ

### 1. 環境変数の設定
```bash
# .envファイルを作成
cat > .env << EOF
# Supabase設定
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key

# AWS S3設定
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key
S3_BUCKET_NAME=watchme-vault
AWS_REGION=us-east-1
EOF
```

### 2. 仮想環境のセットアップ
```bash
# 仮想環境を作成
python -m venv venv
source venv/bin/activate  # Windowsの場合: venv\Scripts\activate

# 依存関係をインストール
pip install -r requirements.txt
```

### 3. ローカル起動
```bash
# 仮想環境で起動（重要！）
source venv/bin/activate
python main.py
# APIは http://localhost:8004 で起動
```

## ⚠️ 重要な注意事項

### 仮想環境での実行が必須
このAPIは**仮想環境(venv)**で実行する必要があります。TensorFlow、YamNetなどの依存関係は仮想環境内にインストールされています。

### 正しい起動方法
```bash
# ✅ 正解: 仮想環境で実行
source venv/bin/activate && python main.py

# ❌ 間違い: システムPythonで実行
python3 main.py  # → TensorFlowが見つからないエラー
```

### YamNetモデルについて
- **使用モデル**: Google YamNet
- **初回起動時**: モデルの自動ダウンロード（数分）
- **キャッシュ**: `~/.cache/tensorflow_hub/`に保存

## 🔍 トラブルシューティング

### ステータスが更新されない場合
1. `file_path`が正確に一致しているか確認
2. `audio_files`テーブルにレコードが存在するか確認
3. ログでエラーメッセージを確認

### TensorFlow Hubキャッシュエラー
```bash
# キャッシュをクリア
curl -X POST http://localhost:8004/debug/clear-cache

# キャッシュ状態確認
curl http://localhost:8004/debug/cache-status
```

### メモリ不足エラー
```bash
# 他のプロセスを停止
pkill -f python

# APIを再起動
source venv/bin/activate && python main.py
```

## 🌐 本番環境

**本番環境URL**: `https://api.hey-watch.me/behavior-features/`

### 使用例
```bash
# 新しいfile_pathsベースのエンドポイント
curl -X POST "https://api.hey-watch.me/behavior-features/fetch-and-process-paths" \
  -H "Content-Type: application/json" \
  -d '{
    "file_paths": [
      "files/d067d407-cf73-4174-a9c1-d91fb60d64d0/2025-07-19/14-30/audio.wav"
    ],
    "threshold": 0.2
  }'

# 従来のdevice_id/dateベース（互換性維持）
curl -X POST "https://api.hey-watch.me/behavior-features/fetch-and-process" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "d067d407-cf73-4174-a9c1-d91fb60d64d0",
    "date": "2025-07-19",
    "threshold": 0.2
  }'
```

## 📊 パフォーマンス

### 処理時間目安
- **1分音声**: 約5-10秒で処理
- **YamNetモデル**: Google製の高精度音響イベント検出
- **検出可能イベント**: 521種類の音響イベント

### 検出可能な音声イベント例
- **Speech** (会話・発話)
- **Music** (音楽)
- **Silence** (無音・静寂)
- **Door, Knock** (ドア・ノック音)
- **Hands, Clapping** (手の動作・拍手)
- **Chopping (food)** (料理・切る音)
- **Fire, Crackle** (火・パチパチ音)
- **Inside, small room** (室内環境音)
- **Breathing, Snoring** (呼吸・いびき)

## 📞 関連ドキュメント

- [Whisper API](../api_wisper_v1/README.md) - 音声文字起こし（リファレンス実装）
- [Vault API](../api_vault_v1/README.md) - 音声ファイルのアップロード管理
- [感情分析API](../api_emotion_v1/README.md) - 音声から感情を分析

## 🌟 WatchMeマイクロサービス・エコシステム統合

### 現在稼働中のマイクロサービス

| サービス名 | 外部URL | 機能 | ステータスフィールド |
|-----------|---------|------|-------------------|
| **vibe-transcriber** | `https://api.hey-watch.me/vibe-transcriber/` | 音声転写（Whisper） | `transcriptions_status` |
| **behavior-features** | `https://api.hey-watch.me/behavior-features/` | 音声イベント検出（このAPI） | `behavior_features_status` |
| **vibe-aggregator** | `https://api.hey-watch.me/vibe-aggregator/` | プロンプト生成 | - |
| **vibe-scorer** | `https://api.hey-watch.me/vibe-scorer/` | 心理グラフ生成 | - |

### データフロー統合

```
iOS App → Vault API (S3保存) → 音声処理APIs → Supabase → Dashboard
                                    ↓
                            vibe-transcriber (Whisper)
                            behavior-features (YamNet)
                            emotion-features (未実装)
```

---

**このAPIは、Whisper APIの成功パターンを音響イベント検出に適用したリファレンス実装です。新しい音声処理APIを実装する際は、このパターンを参考にしてください。**