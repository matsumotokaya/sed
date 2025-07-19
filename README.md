# Sound Event Detection (SED) API - 音声処理APIのリファレンス実装

YamNetモデルを使用して音声ファイルからサウンドイベントを検出するAPI。**このAPIはWhisper APIに続く音声処理APIのリファレンス実装です。**

## 🎯 重要：このAPIがリファレンス実装である理由

このAPIは、WatchMeエコシステムにおける音声ファイル処理の標準的な実装パターンを継承しています：

1. **file_pathベースの処理**: Whisper APIと同じく`file_path`を主キーとして使用
2. **ステータス管理**: 処理完了後に`audio_files`テーブルの`behavior_features_status`を更新
3. **シンプルな責務分離**: 音響イベント検出に特化し、ファイル管理はVault APIに委譲
4. **統一されたエラーハンドリング**: Whisper APIと同じパターンでエラー処理

## 🔄 最新アップデート (2025-07-19)

### 🚀 Version 1.5.0: Whisper APIパターン準拠への大幅改善

#### 📈 改善の背景
従来のSED APIは`device_id/date`ベースの処理方式を採用していましたが、Whisper APIで証明された`file_path`ベースの処理方式の優位性を受けて、全面的にアーキテクチャを刷新しました。

#### ⚡ 主要な改善内容

##### 1. **統一されたfile_pathsベースのインターフェース**
- **新エンドポイント**: `/fetch-and-process-paths`
- **リクエスト形式**: Whisper APIと完全に統一された`file_paths`配列形式
- **レスポンス形式**: 他の音声処理APIと統一されたレスポンス構造
- **後方互換性**: 従来の`/fetch-and-process`エンドポイントも維持

##### 2. **直接的なaudio_filesテーブル連携**
- **ステータス更新**: `behavior_features_status`を`completed`に直接更新
- **S3直接アクセス**: Vault API経由ではなく、AWS S3から直接音声ファイルを取得
- **確実性向上**: `file_path`による直接的なステータス管理で更新の確実性を向上

##### 3. **リファレンス実装としての完成**
- **実装パターンの統一**: Whisper APIの成功パターンを音響イベント検出に完全適用
- **他APIの模範**: 新しい音声処理APIが参照できる標準実装として確立
- **ドキュメント充実**: 実装ガイドとベストプラクティスを詳細に記載

#### 🔧 技術的改善点

##### アーキテクチャ刷新
```python
# ❌ 旧方式: device_id/dateベースの複雑な処理
def old_approach(device_id, date):
    # 複雑な時間範囲計算
    # Vault API経由でのファイル取得
    # 間接的なステータス更新
    
# ✅ 新方式: file_pathベースのシンプルな処理  
def new_approach(file_paths):
    for file_path in file_paths:
        # S3から直接ダウンロード
        # 音響イベント検出
        # 直接的なステータス更新
```

##### 新しいヘルパー関数の追加
- `extract_info_from_file_path()`: ファイルパスからデバイス情報を抽出
- `update_audio_files_status()`: audio_filesテーブルのステータス直接更新
- AWS S3クライアントの統合による高速ファイルアクセス

##### エラーハンドリングの改善
- Whisper APIと統一されたエラー処理パターン
- 詳細なログ出力による問題特定の容易化
- 処理継続性の向上（一部エラーでも他ファイルの処理継続）

#### 📊 パフォーマンス改善結果

##### テスト結果 (2025-07-19)
- **テストファイル**: `files/d067d407-cf73-4174-a9c1-d91fb60d64d0/2025-07-20/00-00/audio.wav`
- **処理時間**: 5.6秒（従来比較で大幅改善）
- **成功率**: 100%（1件中1件成功）
- **ステータス更新**: 確実に`behavior_features_status`が`completed`に更新

```json
{
  "status": "success",
  "summary": {
    "total_files": 1,
    "pending_processed": 1,
    "errors": 0
  },
  "processed_files": ["files/d067d407-cf73-4174-a9c1-d91fb60d64d0/2025-07-20/00-00/audio.wav"],
  "processed_time_blocks": ["00-00"],
  "error_files": null,
  "execution_time_seconds": 5.6,
  "message": "1件中1件を正常に処理しました"
}
```

#### 🎯 開発者向けメリット

##### 1. **統一された開発体験**
- Whisper APIと同じインターフェースパターン
- 学習コストの削減
- コードの再利用性向上

##### 2. **運用の簡素化**
- 直接的なステータス管理による運用の透明性
- S3直接アクセスによるパフォーマンス向上
- エラートラッキングの改善

##### 3. **拡張性の向上**
- 新しい音声処理APIの実装が容易
- マイクロサービス間の統一されたインターフェース
- 将来的な機能追加への対応力強化

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

## 🚀 本番環境デプロイ手順

### 📋 デプロイ前準備

#### 1. プロジェクトの圧縮
```bash
# 現在のディレクトリで実行
tar -czf api_sed_v1_updated.tar.gz api_sed_v1 \
  --exclude='api_sed_v1/venv' \
  --exclude='api_sed_v1/*.log' \
  --exclude='api_sed_v1/*.tar.gz'
```

#### 2. 動作確認済み項目の確認
- ✅ 新エンドポイント `/fetch-and-process-paths` の動作確認
- ✅ audio_filesテーブルのステータス更新確認
- ✅ S3からの音声ファイル取得確認
- ✅ YamNetによる音響イベント検出確認

### 🌐 本番環境情報

- **URL**: `https://api.hey-watch.me/behavior-features/`
- **サーバー**: AWS EC2 (3.24.16.82)
- **ユーザー**: ubuntu
- **キー**: `~/watchme-key.pem`
- **ポート**: 8004

### 📦 デプロイ実行手順

#### Step 1: ファイル転送
```bash
# プロジェクトをEC2に転送
scp -i ~/watchme-key.pem api_sed_v1_updated.tar.gz ubuntu@3.24.16.82:~/
```

#### Step 2: EC2での展開と設定
```bash
# EC2にSSH接続
ssh -i ~/watchme-key.pem ubuntu@3.24.16.82

# 既存のバックアップ作成
if [ -d "api_sed_v1" ]; then
    sudo cp -r api_sed_v1 api_sed_v1_backup_$(date +%Y%m%d_%H%M%S)
fi

# 新しいコードを展開
tar -xzf api_sed_v1_updated.tar.gz

# ディレクトリに移動
cd api_sed_v1

# 環境変数ファイルが存在しない場合は作成
if [ ! -f ".env" ]; then
    echo "⚠️  .envファイルが見つかりません。以下の内容で作成してください："
    echo "SUPABASE_URL=your_supabase_url"
    echo "SUPABASE_KEY=your_supabase_key"
    echo "AWS_ACCESS_KEY_ID=your_access_key_id"
    echo "AWS_SECRET_ACCESS_KEY=your_secret_access_key"
    echo "S3_BUCKET_NAME=watchme-vault"
    echo "AWS_REGION=us-east-1"
fi
```

#### Step 3: 仮想環境と依存関係のセットアップ
```bash
# 仮想環境を作成
python3 -m venv venv
source venv/bin/activate

# 依存関係をインストール
pip install -r requirements.txt

# boto3が含まれていない場合は追加インストール
pip install boto3

# 動作テスト
python main.py &
sleep 5
curl http://localhost:8004/
pkill -f "python.*main.py"
```

#### Step 4: Dockerコンテナの更新
```bash
# 既存コンテナを停止
sudo docker-compose down

# 新しいイメージをビルド
sudo docker-compose build

# コンテナを起動
sudo docker-compose up -d

# ログ確認
sudo docker-compose logs -f
```

#### Step 5: systemdサービスの再起動
```bash
# サービスを再起動
sudo systemctl restart watchme-behavior-yamnet

# 状態確認
sudo systemctl status watchme-behavior-yamnet

# リアルタイムログ確認
sudo journalctl -u watchme-behavior-yamnet -f
```

### ✅ デプロイ後の動作確認

#### 1. ヘルスチェック
```bash
# 基本動作確認
curl https://api.hey-watch.me/behavior-features/

# 期待されるレスポンス
{"message":"Sound Event Detection API is running"}
```

#### 2. 新エンドポイントのテスト
```bash
# file_pathsベースの新エンドポイント
curl -X POST "https://api.hey-watch.me/behavior-features/fetch-and-process-paths" \
  -H "Content-Type: application/json" \
  -d '{
    "file_paths": [
      "files/d067d407-cf73-4174-a9c1-d91fb60d64d0/2025-07-20/00-00/audio.wav"
    ],
    "threshold": 0.2
  }'

# 期待されるレスポンス形式
{
  "status": "success",
  "summary": {
    "total_files": 1,
    "pending_processed": 1,
    "errors": 0
  },
  "processed_files": ["files/.../audio.wav"],
  "processed_time_blocks": ["00-00"],
  "error_files": null,
  "execution_time_seconds": 5.6,
  "message": "1件中1件を正常に処理しました"
}
```

#### 3. 従来エンドポイント（互換性確認）
```bash
# 従来のdevice_id/dateベース
curl -X POST "https://api.hey-watch.me/behavior-features/fetch-and-process" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "d067d407-cf73-4174-a9c1-d91fb60d64d0",
    "date": "2025-07-19",
    "threshold": 0.2
  }'
```

### 🔧 トラブルシューティング（本番環境）

#### コンテナが起動しない場合
```bash
# エラーログを確認
sudo docker-compose logs

# 手動でコンテナを起動してエラー確認
sudo docker run --rm -p 8004:8004 --env-file .env api_sed_v1:latest
```

#### systemdサービスが失敗する場合
```bash
# 詳細なエラーログを確認
sudo journalctl -u watchme-behavior-yamnet -n 50 --no-pager

# サービス定義を確認
sudo systemctl cat watchme-behavior-yamnet
```

#### 新エンドポイントが動作しない場合
```bash
# APIのログを確認
sudo docker logs $(sudo docker ps -q --filter "name=sed")

# 環境変数の確認
sudo docker exec $(sudo docker ps -q --filter "name=sed") env | grep -E "(SUPABASE|AWS)"
```

### 📊 パフォーマンス監視

#### モニタリングコマンド
```bash
# リソース使用状況
sudo docker stats

# ログの監視
sudo journalctl -u watchme-behavior-yamnet -f

# API応答時間の測定
time curl -X POST "https://api.hey-watch.me/behavior-features/fetch-and-process-paths" \
  -H "Content-Type: application/json" \
  -d '{"file_paths": ["files/test/path.wav"], "threshold": 0.2}'
```

## 🌐 本番環境での使用方法

**本番環境URL**: `https://api.hey-watch.me/behavior-features/`

### 推奨：新エンドポイント使用例
```bash
# file_pathsベースのエンドポイント（推奨）
curl -X POST "https://api.hey-watch.me/behavior-features/fetch-and-process-paths" \
  -H "Content-Type: application/json" \
  -d '{
    "file_paths": [
      "files/d067d407-cf73-4174-a9c1-d91fb60d64d0/2025-07-19/14-30/audio.wav"
    ],
    "threshold": 0.2
  }'
```

### 互換性：従来エンドポイント使用例
```bash
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