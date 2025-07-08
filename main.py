import os
import numpy as np
import tensorflow as tf
from scipy import signal
import shutil
import glob
import time
from supabase import create_client, Client
from dotenv import load_dotenv

# 環境変数を読み込み
load_dotenv()

# TensorFlowのメモリ使用量を制限
gpus = tf.config.list_physical_devices('GPU')
if gpus:
    try:
        # GPUメモリの成長を制限する
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)
    except RuntimeError as e:
        print(f"GPUの設定中にエラーが発生しました: {e}")

# CPUのみ使用する場合
tf.config.set_visible_devices([], 'GPU')
print("TensorFlow: CPUモードで実行します")

import tensorflow_hub as hub
import csv
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import io
import soundfile as sf
import aiohttp
import asyncio
from datetime import datetime

# Supabaseクライアントの初期化
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    raise ValueError("SUPABASE_URLおよびSUPABASE_KEYが設定されていません")

supabase: Client = create_client(supabase_url, supabase_key)
print(f"Supabase接続設定完了: {supabase_url}")

# FastAPIアプリケーションの初期化
app = FastAPI(
    title="Sound Event Detection API",
    description="YamNetモデルを使用して音声ファイルからサウンドイベントを検出するAPI（v1.2.0: Supabase統合機能搭載）",
    version="1.2.0"
)

# CORSミドルウェアの設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# モデルの初期化
print("YamNetモデルをロード中...")
model = None  # 初期化時には読み込まず、必要時に遅延ロードする

# クラスマップの読み込み
class_map_path = tf.keras.utils.get_file('yamnet_class_map.csv',
                                         'https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv')
class_names = []
with open(class_map_path, 'r') as f:
    reader = csv.reader(f)
    next(reader)  # ヘッダーをスキップ
    for row in reader:
        class_names.append(row[2])

def clear_tfhub_cache():
    """
    TensorFlow Hubキャッシュをクリア
    
    🔥 キャッシュ破損はTensorFlow Hubでよく発生する問題です
    症状: 'saved_model.pb' nor 'saved_model.pbtxt' エラー
    対処: この関数でキャッシュを完全削除して再ダウンロードします
    """
    print("🔧 TensorFlow Hubキャッシュのクリアを開始...")
    cleared_count = 0
    
    try:
        # 💡 キャッシュの一般的な場所
        cache_paths = [
            os.path.expanduser('~/tfhub_modules'),
            '/tmp/tfhub_modules',
            os.environ.get('TFHUB_CACHE_DIR', ''),  # 環境変数指定のパス
        ]
        
        # 🔍 macOSの一時フォルダ内のキャッシュも検索
        cache_paths.extend(glob.glob('/var/folders/*/T/tfhub_modules*'))
        cache_paths.extend(glob.glob('/var/folders/*/*/T/tfhub_modules*'))
        
        # 空文字列を除去
        cache_paths = [path for path in cache_paths if path]
        
        print(f"📁 検索対象パス: {len(cache_paths)}個")
        for path in cache_paths:
            print(f"   - {path}")
        
        for path in cache_paths:
            if os.path.exists(path):
                try:
                    shutil.rmtree(path)
                    cleared_count += 1
                    print(f"✅ キャッシュクリア成功: {path}")
                except Exception as e:
                    print(f"❌ キャッシュクリア失敗: {path} - {e}")
            else:
                print(f"⏭️ パス存在せず: {path}")
                
        if cleared_count > 0:
            print(f"🎯 {cleared_count}個のキャッシュディレクトリを削除しました")
            print("💡 次回のモデルロード時に自動的に再ダウンロードされます")
        else:
            print("ℹ️ クリア対象のキャッシュは見つかりませんでした")
            
    except Exception as e:
        print(f"🚨 キャッシュクリア処理で予期しないエラー: {e}")
        import traceback
        traceback.print_exc()

def validate_model_cache():
    """
    モデルキャッシュの整合性を確認
    
    🔍 TensorFlow Hubキャッシュが破損していないかチェックします
    破損の特徴: saved_model.pb ファイルが存在しない
    """
    print("🔍 TensorFlow Hubキャッシュの整合性チェックを開始...")
    
    try:
        cache_dir = os.environ.get('TFHUB_CACHE_DIR', '/tmp/tfhub_modules')
        
        # 🔍 一般的なキャッシュディレクトリをチェック
        check_dirs = [
            cache_dir,
            os.path.expanduser('~/tfhub_modules'),
        ]
        check_dirs.extend(glob.glob('/var/folders/*/T/tfhub_modules*'))
        check_dirs.extend(glob.glob('/var/folders/*/*/T/tfhub_modules*'))
        
        # 空文字列を除去
        check_dirs = [d for d in check_dirs if d]
        
        checked_models = 0
        corrupted_models = 0
        
        for cache_dir in check_dirs:
            if os.path.exists(cache_dir):
                print(f"📁 チェック中: {cache_dir}")
                
                try:
                    for model_dir in os.listdir(cache_dir):
                        model_path = os.path.join(cache_dir, model_dir)
                        if os.path.isdir(model_path):
                            checked_models += 1
                            saved_model_path = os.path.join(model_path, 'saved_model.pb')
                            
                            if not os.path.exists(saved_model_path):
                                corrupted_models += 1
                                print(f"🚨 破損キャッシュ発見: {model_path}")
                                print(f"   原因: saved_model.pb が存在しません")
                                try:
                                    shutil.rmtree(model_path)
                                    print(f"✅ 破損キャッシュを自動削除: {model_path}")
                                except Exception as e:
                                    print(f"❌ キャッシュ削除失敗: {e}")
                                    return False
                            else:
                                print(f"✅ 正常なキャッシュ: {model_dir}")
                except PermissionError as e:
                    print(f"⚠️ アクセス権限エラー: {cache_dir} - {e}")
                except Exception as e:
                    print(f"❌ ディレクトリ読み取りエラー: {cache_dir} - {e}")
            else:
                print(f"⏭️ ディレクトリ存在せず: {cache_dir}")
        
        if checked_models == 0:
            print("ℹ️ キャッシュされたモデルは見つかりませんでした")
        elif corrupted_models > 0:
            print(f"🔧 {corrupted_models}/{checked_models} 個の破損キャッシュを修復しました")
            return False
        else:
            print(f"✅ すべてのキャッシュ ({checked_models}個) が正常です")
        
        return True
    except Exception as e:
        print(f"🚨 キャッシュ検証で予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        return False

def startup_diagnostics():
    """起動時診断"""
    checks = []
    
    # TensorFlow動作確認
    try:
        tf.constant([1.0])
        checks.append("✅ TensorFlow: 正常")
    except Exception as e:
        checks.append(f"❌ TensorFlow: {e}")
    
    # TensorFlow Hub動作確認
    try:
        import tensorflow_hub as hub
        checks.append("✅ TensorFlow Hub: 正常")
    except Exception as e:
        checks.append(f"❌ TensorFlow Hub: {e}")
    
    # キャッシュ整合性確認
    if validate_model_cache():
        checks.append("✅ モデルキャッシュ: 正常")
    else:
        checks.append("⚠️ モデルキャッシュ: 要クリア")
    
    # 診断結果を出力
    print("\n=== 起動時診断結果 ===")
    for check in checks:
        print(check)
    print("=" * 25)
    
    return checks

def load_model_if_needed():
    """
    YamNetモデルの遅延ロード（自動回復機能付き）
    
    🔥 TensorFlow Hubキャッシュ破損対策:
    1. キャッシュ整合性チェック
    2. 破損時の自動クリア
    3. 最大3回の自動リトライ
    4. 詳細なエラー情報の表示
    """
    global model
    if model is None:
        print("🎯 YamNetモデルを必要に応じてロードします...")
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                print(f"\n📋 モデルロード試行 {attempt + 1}/{max_attempts}")
                
                # 🔍 Step 1: キャッシュ整合性チェック
                if not validate_model_cache():
                    print("🔧 キャッシュが破損していました。自動修復を実行...")
                    clear_tfhub_cache()
                
                # 🧹 Step 2: メモリクリア
                tf.keras.backend.clear_session()
                print("🧹 TensorFlowメモリをクリアしました")
                
                # 📥 Step 3: モデルダウンロード・ロード
                print("📥 YamNetモデルをダウンロード中...")
                os.environ['TFHUB_DOWNLOAD_PROGRESS'] = '1'
                model = hub.load('https://tfhub.dev/google/yamnet/1')
                print("✅ モデルダウンロード完了")
                
                # 🧪 Step 4: 動作テスト
                print("🧪 モデル動作テストを実行中...")
                dummy_waveform = np.zeros(16000, dtype=np.float32)
                _ = model(dummy_waveform)
                print("✅ モデル動作テスト成功")
                
                print("🎉 YamNetモデルのロード完了！")
                break
                
            except ValueError as e:
                error_msg = str(e)
                if 'saved_model.pb' in error_msg or 'saved_model.pbtxt' in error_msg:
                    print(f"🚨 TensorFlow Hubキャッシュ破損エラー検出!")
                    print(f"   エラー詳細: {error_msg}")
                    print(f"   原因: キャッシュディレクトリ内のモデルファイルが不完全")
                    print(f"   対処: キャッシュを削除して再ダウンロードします")
                else:
                    print(f"❌ ValueError: {error_msg}")
                
                if attempt < max_attempts - 1:
                    print(f"🔄 {5}秒後に再試行します...")
                    time.sleep(5)
                    clear_tfhub_cache()
                else:
                    print("🚨 全ての試行が失敗しました")
                    model = None
                    raise Exception(f"🚨 YamNetモデルロードに失敗しました（{max_attempts}回試行）\n"
                                  f"最後のエラー: {error_msg}\n"
                                  f"💡 対処法: READMEのトラブルシューティングセクションを確認してください")
                    
            except Exception as e:
                error_msg = str(e)
                print(f"❌ 予期しないエラー: {error_msg}")
                
                if attempt < max_attempts - 1:
                    print(f"🔄 {5}秒後に再試行します...")
                    time.sleep(5)
                    clear_tfhub_cache()
                else:
                    print("🚨 全ての試行が失敗しました")
                    import traceback
                    traceback.print_exc()
                    model = None
                    raise Exception(f"🚨 YamNetモデルロードに失敗しました（{max_attempts}回試行）\n"
                                  f"最後のエラー: {error_msg}\n"
                                  f"💡 対処法: READMEのトラブルシューティングセクションを確認してください")
    
    return model

def generate_time_slots():
    """24時間分の30分単位スロットを生成（48個）"""
    slots = []
    for hour in range(24):
        for minute in [0, 30]:
            slot = f"{hour:02d}-{minute:02d}"
            slots.append(slot)
    return slots

def convert_to_new_format(device_id: str, date: str, time_block: str, timeline_events: List[Dict], slot_timeline: List[Dict]):
    """
    現在のタイムラインデータを新しいテーブル構造に変換する
    
    Args:
        device_id: デバイスID
        date: 日付（YYYY-MM-DD）
        time_block: 時間ブロック（HH-MM）
        timeline_events: 元のタイムラインイベント
        slot_timeline: 元のスロットタイムライン
    
    Returns:
        新しい構造のevents配列
    """
    # 全てのイベントを統合して、重複を除去
    all_events = {}
    
    # timeline_eventsから抽出
    for event in timeline_events:
        label = event['label']
        prob = event['prob']
        
        # 同じラベルがあった場合は最大確率を採用
        if label in all_events:
            all_events[label] = max(all_events[label], prob)
        else:
            all_events[label] = prob
    
    # slot_timelineからも抽出（念のため）
    for slot in slot_timeline:
        for event in slot['events']:
            label = event['label']
            prob = event['prob']
            
            if label in all_events:
                all_events[label] = max(all_events[label], prob)
            else:
                all_events[label] = prob
    
    # 新しい形式のevents配列を生成
    events = [
        {"label": label, "prob": prob}
        for label, prob in sorted(all_events.items(), key=lambda x: x[1], reverse=True)
    ]
    
    return events

async def save_to_supabase(device_id: str, date: str, time_block: str, events: List[Dict]):
    """
    Supabaseのbehavior_yamnetテーブルに保存（UPSERT）
    
    Args:
        device_id: デバイスID
        date: 日付（YYYY-MM-DD）
        time_block: 時間ブロック（HH-MM）
        events: イベント配列
    
    Returns:
        bool: 保存成功/失敗
    """
    try:
        supabase_data = {
            "device_id": device_id,
            "date": date,
            "time_block": time_block,
            "events": events
        }
        
        # UPSERTでデータを保存
        result = supabase.table('behavior_yamnet').upsert(supabase_data).execute()
        
        if result.data:
            print(f"💾 Supabase保存成功: {time_block} ({len(events)}件のイベント)")
            return True
        else:
            print(f"❌ Supabase保存失敗: {time_block}")
            return False
            
    except Exception as e:
        print(f"❌ Supabase保存エラー: {time_block} - {str(e)}")
        return False


async def download_audio_file(session: aiohttp.ClientSession, device_id: str, date: str, slot: str):
    """
    EC2サーバーから音声ファイルをダウンロードする
    """
    url = f"https://api.hey-watch.me/download"
    params = {
        "device_id": device_id,
        "date": date,
        "slot": slot
    }
    
    try:
        print(f"ダウンロード開始: {slot}")
        async with session.get(url, params=params) as response:
            if response.status == 200:
                content = await response.read()
                print(f"ダウンロード成功: {slot} ({len(content)} bytes)")
                return content
            elif response.status == 404:
                print(f"ファイルが存在しません: {slot}")
                return None
            else:
                print(f"ダウンロードエラー: {slot} (status: {response.status})")
                return None
    except Exception as e:
        print(f"ダウンロード例外: {slot} - {str(e)}")
        return None

def process_audio_data(audio_content: bytes, threshold: float = 0.2):
    """
    音声データを処理してタイムライン結果を生成する
    （既存のtimelineエンドポイントの処理ロジックを抽出）
    """
    try:
        # ファイルの読み込み
        try:
            audio_data, sample_rate = sf.read(io.BytesIO(audio_content))
            print(f"ファイルを読み込みました: サンプルレート {sample_rate}Hz, 形状 {audio_data.shape}")
        except Exception as e:
            print(f"音声ファイルの読み込みに失敗しました: {str(e)}")
            return None
        
        # モノラルに変換
        if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
            audio_data = np.mean(audio_data, axis=1)
            print(f"ステレオからモノラルに変換しました: 新しい形状 {audio_data.shape}")
        
        # YamNetの入力要件に合わせてサンプルレートを変換（必要な場合）
        if sample_rate != 16000:
            print(f"サンプルレートが16kHzではありません: {sample_rate}Hz、リサンプリングを行います...")
            # scipyのsignalモジュールを使用してリサンプリング
            number_of_samples = round(len(audio_data) * 16000 / sample_rate)
            audio_data = signal.resample(audio_data, number_of_samples)
            print(f"リサンプリング完了: {sample_rate}Hz → 16000Hz, 新しい形状 {audio_data.shape}")
            # サンプルレートを16000に設定
            sample_rate = 16000
        
        # データ型を確認し、必要に応じて変換
        if audio_data.dtype != np.float32:
            print(f"データ型を変換: {audio_data.dtype} → float32")
            audio_data = audio_data.astype(np.float32)
        
        # 振幅を適切な範囲に正規化（-1.0 〜 1.0）
        max_abs = np.max(np.abs(audio_data))
        if max_abs > 1.0:
            print(f"オーディオデータを正規化します。最大振幅: {max_abs}")
            audio_data = audio_data / max_abs
        
        # 最大60秒までに制限（1分間だけを処理対象）
        MAX_AUDIO_LENGTH = 60 * 16000  # 最大60秒まで処理
        if len(audio_data) > MAX_AUDIO_LENGTH:
            print(f"オーディオファイルが長すぎるため60秒に切り詰めます: {len(audio_data)/16000:.2f}秒 → 60秒")
            audio_data = audio_data[:MAX_AUDIO_LENGTH]
        
        # モデルを必要時にロード
        try:
            print("モデルをロードします...")
            current_model = load_model_if_needed()
            print("モデルのロードに成功しました")
        except Exception as e:
            print(f"モデルのロードに失敗しました: {str(e)}")
            return None
        
        # YamNetでの推論
        try:
            print("推論を実行します...")
            scores, embeddings, log_mel_spectrogram = current_model(audio_data)
            print(f"推論に成功しました: スコアの形状 {scores.shape}")
        except Exception as e:
            print(f"推論の実行に失敗しました: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
        
        # タイムラインの作成
        try:
            print("タイムラインを作成しています...")
            
            # YamNetのフレーム時間（通常約0.96秒）を計算
            # スコアの形状から推定：scores.shape[0]はフレーム数
            n_frames = scores.shape[0]
            audio_duration = len(audio_data) / sample_rate
            frame_duration = audio_duration / n_frames
            
            timeline_events = []
            
            # スロットタイムライン用のデータ構造
            slot_events = {}  # time -> events[]
            
            for frame_idx in range(n_frames):
                # 現在のフレームのスコア
                frame_scores = scores[frame_idx].numpy()
                
                # フレームの開始時間を計算
                start_time = frame_idx * frame_duration
                
                # スロットタイムライン用の時間（開始時間をキーとする）
                slot_time = round(start_time, 2)
                
                # スロット用のイベントリスト初期化
                if slot_time not in slot_events:
                    slot_events[slot_time] = []
                
                # 閾値以上のイベントを抽出
                for class_idx in range(len(frame_scores)):
                    prob = float(frame_scores[class_idx])
                    if prob >= threshold:
                        # 該当フレームの開始・終了時間を計算
                        start_time = frame_idx * frame_duration
                        end_time = (frame_idx + 1) * frame_duration
                        
                        # 通常のタイムラインイベントを追加
                        timeline_events.append({
                            "start": round(start_time, 2),
                            "end": round(end_time, 2),
                            "label": class_names[class_idx],
                            "prob": round(prob, 2)
                        })
                        
                        # スロットタイムラインにイベントを追加
                        slot_events[slot_time].append({
                            "label": class_names[class_idx],
                            "prob": round(prob, 2)
                        })
            
            # スロットタイムラインを時系列順に整列
            slot_timeline = [
                {"time": time, "events": events}
                for time, events in sorted(slot_events.items())
            ]
            
            print(f"タイムライン作成完了: {len(timeline_events)}件のイベント、{len(slot_timeline)}個のタイムスロット")
            return {
                "timeline": timeline_events,
                "slot_timeline": slot_timeline
            }
        except Exception as e:
            print(f"タイムラインの作成に失敗しました: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
        
    except Exception as e:
        print(f"音声処理中に予期しないエラーが発生しました: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

class SEDResult(BaseModel):
    sed: List[Dict[str, Any]]

class TimelineEvent(BaseModel):
    start: float
    end: float
    label: str
    prob: float

class EventItem(BaseModel):
    label: str
    prob: float

class TimeSlot(BaseModel):
    time: float
    events: List[EventItem]

class TimelineResult(BaseModel):
    timeline: List[TimelineEvent]
    slot_timeline: List[TimeSlot]

class SummaryItem(BaseModel):
    start: float
    end: float
    labels: List[str]

class SummaryResult(BaseModel):
    summary: List[SummaryItem]

# timeline-v2用のモデル
class TimelineV2Request(BaseModel):
    device_id: str
    date: str  # YYYY-MM-DD形式

# fetch-and-process用のモデル
class FetchAndProcessRequest(BaseModel):
    device_id: str
    date: str
    threshold: float = 0.2

class SlotTimelineData(BaseModel):
    slot: str  # HH-MM形式
    timeline: List[TimelineEvent]
    slot_timeline: List[TimeSlot]

class TimelineV2Result(BaseModel):
    device_id: str
    date: str
    total_processed_slots: int
    total_available_slots: int
    processed_slots: List[SlotTimelineData]

@app.post("/analyze/sed", response_model=SEDResult)
async def analyze_sed(file: UploadFile = File(...), top_n: int = 20):
    # ファイル形式の確認
    if not file.filename.endswith('.wav'):
        raise HTTPException(status_code=400, detail="WAVファイル形式のみサポートしています")
    
    try:
        # ファイルの読み込み
        content = await file.read()
        try:
            audio_data, sample_rate = sf.read(io.BytesIO(content))
            print(f"ファイルを読み込みました: サンプルレート {sample_rate}Hz, 形状 {audio_data.shape}")
        except Exception as e:
            print(f"音声ファイルの読み込みに失敗しました: {str(e)}")
            raise HTTPException(status_code=400, detail=f"音声ファイルの読み込みに失敗しました: {str(e)}")
        
        # モノラルに変換
        if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
            audio_data = np.mean(audio_data, axis=1)
            print(f"ステレオからモノラルに変換しました: 新しい形状 {audio_data.shape}")
        
        # YamNetの入力要件に合わせてサンプルレートを変換（必要な場合）
        if sample_rate != 16000:
            print(f"サンプルレートが16kHzではありません: {sample_rate}Hz、リサンプリングを行います...")
            # scipyのsignalモジュールを使用してリサンプリング
            number_of_samples = round(len(audio_data) * 16000 / sample_rate)
            audio_data = signal.resample(audio_data, number_of_samples)
            print(f"リサンプリング完了: {sample_rate}Hz → 16000Hz, 新しい形状 {audio_data.shape}")
            # サンプルレートを16000に設定
            sample_rate = 16000
        
        # データ型を確認し、必要に応じて変換
        if audio_data.dtype != np.float32:
            print(f"データ型を変換: {audio_data.dtype} → float32")
            audio_data = audio_data.astype(np.float32)
        
        # 振幅を適切な範囲に正規化（-1.0 〜 1.0）
        max_abs = np.max(np.abs(audio_data))
        if max_abs > 1.0:
            print(f"オーディオデータを正規化します。最大振幅: {max_abs}")
            audio_data = audio_data / max_abs
        
        # 長すぎるオーディオファイルを処理するための対応
        MAX_AUDIO_LENGTH = 10 * 16000  # 最大10秒まで処理
        if len(audio_data) > MAX_AUDIO_LENGTH:
            print(f"オーディオファイルが長すぎるため切り詰めます: {len(audio_data)/16000:.2f}秒 → 10秒")
            audio_data = audio_data[:MAX_AUDIO_LENGTH]
        
        # モデルを必要時にロード
        try:
            print("モデルをロードします...")
            current_model = load_model_if_needed()
            print("モデルのロードに成功しました")
        except Exception as e:
            print(f"モデルのロードに失敗しました: {str(e)}")
            raise HTTPException(status_code=500, detail=f"モデルのロードに失敗しました: {str(e)}")
        
        # YamNetでの推論
        try:
            print("推論を実行します...")
            scores, embeddings, log_mel_spectrogram = current_model(audio_data)
            print("推論に成功しました")
        except Exception as e:
            print(f"推論の実行に失敗しました: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"推論の実行に失敗しました: {str(e)}")
        
        # スコアの平均を計算して上位のイベントを取得
        try:
            print("結果を処理しています...")
            class_scores = tf.reduce_mean(scores, axis=0).numpy()
            top_indices = np.argsort(class_scores)[-top_n:][::-1]
        
            # 結果の生成
            results = []
            for i in top_indices:
                results.append({
                    "label": class_names[i],
                    "prob": float(class_scores[i])
                })
            print(f"処理に成功しました: {len(results)}件の結果")
            return {"sed": results}
        except Exception as e:
            print(f"結果の処理に失敗しました: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"結果の処理に失敗しました: {str(e)}")
        
    except HTTPException:
        # 既に適切なHTTPExceptionが発生している場合はそのまま再発生
        raise
    except Exception as e:
        print(f"予期しないエラーが発生しました: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"音声分析中に予期しないエラーが発生しました: {str(e)}")

@app.post("/analyze/sed/timeline", response_model=TimelineResult)
async def analyze_sed_timeline(file: UploadFile = File(...), threshold: Optional[float] = 0.2):
    """
    アップロードされたWAV音声ファイルの中から、冒頭1分間だけを使用し、
    YamNetモデルによって検出された音響イベントを時系列でリスト出力する。
    
    Args:
        file: WAVオーディオファイル
        threshold: 確信度の閾値（デフォルト: 0.2）
    
    Returns:
        タイムライン形式とスロットタイムライン形式のサウンドイベント検出結果
    """
    # ファイル形式の確認
    if not file.filename.endswith('.wav'):
        raise HTTPException(status_code=400, detail="WAVファイル形式のみサポートしています")
    
    try:
        # ファイルの読み込み
        content = await file.read()
        try:
            audio_data, sample_rate = sf.read(io.BytesIO(content))
            print(f"ファイルを読み込みました: サンプルレート {sample_rate}Hz, 形状 {audio_data.shape}")
        except Exception as e:
            print(f"音声ファイルの読み込みに失敗しました: {str(e)}")
            raise HTTPException(status_code=400, detail=f"音声ファイルの読み込みに失敗しました: {str(e)}")
        
        # モノラルに変換
        if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
            audio_data = np.mean(audio_data, axis=1)
            print(f"ステレオからモノラルに変換しました: 新しい形状 {audio_data.shape}")
        
        # YamNetの入力要件に合わせてサンプルレートを変換（必要な場合）
        if sample_rate != 16000:
            print(f"サンプルレートが16kHzではありません: {sample_rate}Hz、リサンプリングを行います...")
            # scipyのsignalモジュールを使用してリサンプリング
            number_of_samples = round(len(audio_data) * 16000 / sample_rate)
            audio_data = signal.resample(audio_data, number_of_samples)
            print(f"リサンプリング完了: {sample_rate}Hz → 16000Hz, 新しい形状 {audio_data.shape}")
            # サンプルレートを16000に設定
            sample_rate = 16000
        
        # データ型を確認し、必要に応じて変換
        if audio_data.dtype != np.float32:
            print(f"データ型を変換: {audio_data.dtype} → float32")
            audio_data = audio_data.astype(np.float32)
        
        # 振幅を適切な範囲に正規化（-1.0 〜 1.0）
        max_abs = np.max(np.abs(audio_data))
        if max_abs > 1.0:
            print(f"オーディオデータを正規化します。最大振幅: {max_abs}")
            audio_data = audio_data / max_abs
        
        # 最大60秒までに制限（1分間だけを処理対象）
        MAX_AUDIO_LENGTH = 60 * 16000  # 最大60秒まで処理
        if len(audio_data) > MAX_AUDIO_LENGTH:
            print(f"オーディオファイルが長すぎるため60秒に切り詰めます: {len(audio_data)/16000:.2f}秒 → 60秒")
            audio_data = audio_data[:MAX_AUDIO_LENGTH]
        
        # モデルを必要時にロード
        try:
            print("モデルをロードします...")
            current_model = load_model_if_needed()
            print("モデルのロードに成功しました")
        except Exception as e:
            print(f"モデルのロードに失敗しました: {str(e)}")
            raise HTTPException(status_code=500, detail=f"モデルのロードに失敗しました: {str(e)}")
        
        # YamNetでの推論
        try:
            print("推論を実行します...")
            scores, embeddings, log_mel_spectrogram = current_model(audio_data)
            print(f"推論に成功しました: スコアの形状 {scores.shape}")
        except Exception as e:
            print(f"推論の実行に失敗しました: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"推論の実行に失敗しました: {str(e)}")
        
        # タイムラインの作成
        try:
            print("タイムラインを作成しています...")
            
            # YamNetのフレーム時間（通常約0.96秒）を計算
            # スコアの形状から推定：scores.shape[0]はフレーム数
            n_frames = scores.shape[0]
            audio_duration = len(audio_data) / sample_rate
            frame_duration = audio_duration / n_frames
            
            timeline_events = []
            
            # スロットタイムライン用のデータ構造
            slot_events = {}  # time -> events[]
            
            for frame_idx in range(n_frames):
                # 現在のフレームのスコア
                frame_scores = scores[frame_idx].numpy()
                
                # フレームの開始時間を計算
                start_time = frame_idx * frame_duration
                
                # スロットタイムライン用の時間（開始時間をキーとする）
                slot_time = round(start_time, 2)
                
                # スロット用のイベントリスト初期化
                if slot_time not in slot_events:
                    slot_events[slot_time] = []
                
                # 閾値以上のイベントを抽出
                for class_idx in range(len(frame_scores)):
                    prob = float(frame_scores[class_idx])
                    if prob >= threshold:
                        # 該当フレームの開始・終了時間を計算
                        start_time = frame_idx * frame_duration
                        end_time = (frame_idx + 1) * frame_duration
                        
                        # 通常のタイムラインイベントを追加
                        timeline_events.append({
                            "start": round(start_time, 2),
                            "end": round(end_time, 2),
                            "label": class_names[class_idx],
                            "prob": round(prob, 2)
                        })
                        
                        # スロットタイムラインにイベントを追加
                        slot_events[slot_time].append({
                            "label": class_names[class_idx],
                            "prob": round(prob, 2)
                        })
            
            # スロットタイムラインを時系列順に整列
            slot_timeline = [
                {"time": time, "events": events}
                for time, events in sorted(slot_events.items())
            ]
            
            print(f"タイムライン作成完了: {len(timeline_events)}件のイベント、{len(slot_timeline)}個のタイムスロット")
            return {
                "timeline": timeline_events,
                "slot_timeline": slot_timeline
            }
        except Exception as e:
            print(f"タイムラインの作成に失敗しました: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"タイムラインの作成に失敗しました: {str(e)}")
        
    except HTTPException:
        # 既に適切なHTTPExceptionが発生している場合はそのまま再発生
        raise
    except Exception as e:
        print(f"予期しないエラーが発生しました: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"音声分析中に予期しないエラーが発生しました: {str(e)}")

@app.post("/analyze/sed/timeline-v2", response_model=TimelineV2Result)
async def analyze_sed_timeline_v2(request: TimelineV2Request, threshold: Optional[float] = 0.2):
    """
    EC2上の音声ファイルを逐次処理してタイムライン分析を実行する。
    24時間分の30分単位スロット（48個）を処理対象とし、
    存在しないファイルは無視する。
    
    Args:
        request: ユーザーIDと日付を含むリクエストデータ
        threshold: 確信度の閾値（デフォルト: 0.2）
    
    Returns:
        各スロットのタイムライン分析結果
    """
    print(f"🎯 timeline-v2 処理開始: device_id={request.device_id}, date={request.date}")
    
    # 日付形式の検証
    try:
        datetime.strptime(request.date, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=400, detail="日付はYYYY-MM-DD形式で指定してください")
    
    # 24時間分のスロットを生成
    all_slots = generate_time_slots()
    print(f"📋 処理対象スロット数: {len(all_slots)}")
    
    processed_slots = []
    
    # HTTP接続セッションを作成
    timeout = aiohttp.ClientTimeout(total=30)  # 30秒タイムアウト
    async with aiohttp.ClientSession(timeout=timeout) as session:
        
        # 各スロットを順次処理
        for slot in all_slots:
            print(f"🕒 処理中のスロット: {slot}")
            
            # 音声ファイルをダウンロード
            audio_content = await download_audio_file(session, request.device_id, request.date, slot)
            
            if audio_content is None:
                print(f"⏭️ スキップ: {slot}")
                continue
            
            # 音声データを処理
            result = process_audio_data(audio_content, threshold)
            
            if result is None:
                print(f"❌ 処理失敗: {slot}")
                continue
            
            # 新しいデータ構造に変換
            events = convert_to_new_format(request.device_id, request.date, slot, result["timeline"], result["slot_timeline"])
            
            # Supabaseに保存
            supabase_success = await save_to_supabase(request.device_id, request.date, slot, events)
            if supabase_success:
                print(f"💾 Supabase保存成功: {slot}")
            else:
                print(f"⚠️ Supabase保存失敗（処理は継続）: {slot}")
            
            # 結果を追加
            slot_data = SlotTimelineData(
                slot=slot,
                timeline=result["timeline"],
                slot_timeline=result["slot_timeline"]
            )
            processed_slots.append(slot_data)
            print(f"✅ 処理完了: {slot} ({len(result['timeline'])}件のイベント)")
    
    print(f"🎉 全体処理完了: {len(processed_slots)}/{len(all_slots)} スロット処理済み")
    print(f"💾 すべてSupabaseに直接保存されました")
    
    return TimelineV2Result(
        device_id=request.device_id,
        date=request.date,
        total_processed_slots=len(processed_slots),
        total_available_slots=len(all_slots),
        processed_slots=processed_slots
    )

@app.post("/analyze/sed/summary", response_model=SummaryResult)
async def analyze_sed_summary(file: UploadFile = File(...), threshold: Optional[float] = 0.2, segment_seconds: Optional[float] = 3.0):
    """
    アップロードされたWAV音声ファイルの中から、冒頭1分間だけを使用し、
    約3秒（デフォルト）ごとに要約されたイベントラベルのリストを出力する。
    
    Args:
        file: WAVオーディオファイル
        threshold: 確信度の閾値（デフォルト: 0.2）
        segment_seconds: セグメントの長さ（秒単位、デフォルト: 3.0）
    
    Returns:
        約3秒ごとに要約された音響イベントラベルのリスト
    """
    # ファイル形式の確認
    if not file.filename.endswith('.wav'):
        raise HTTPException(status_code=400, detail="WAVファイル形式のみサポートしています")
    
    try:
        # ファイルの読み込み
        content = await file.read()
        try:
            audio_data, sample_rate = sf.read(io.BytesIO(content))
            print(f"ファイルを読み込みました: サンプルレート {sample_rate}Hz, 形状 {audio_data.shape}")
        except Exception as e:
            print(f"音声ファイルの読み込みに失敗しました: {str(e)}")
            raise HTTPException(status_code=400, detail=f"音声ファイルの読み込みに失敗しました: {str(e)}")
        
        # モノラルに変換
        if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
            audio_data = np.mean(audio_data, axis=1)
            print(f"ステレオからモノラルに変換しました: 新しい形状 {audio_data.shape}")
        
        # YamNetの入力要件に合わせてサンプルレートを変換（必要な場合）
        if sample_rate != 16000:
            print(f"サンプルレートが16kHzではありません: {sample_rate}Hz、リサンプリングを行います...")
            # scipyのsignalモジュールを使用してリサンプリング
            number_of_samples = round(len(audio_data) * 16000 / sample_rate)
            audio_data = signal.resample(audio_data, number_of_samples)
            print(f"リサンプリング完了: {sample_rate}Hz → 16000Hz, 新しい形状 {audio_data.shape}")
            # サンプルレートを16000に設定
            sample_rate = 16000
        
        # データ型を確認し、必要に応じて変換
        if audio_data.dtype != np.float32:
            print(f"データ型を変換: {audio_data.dtype} → float32")
            audio_data = audio_data.astype(np.float32)
        
        # 振幅を適切な範囲に正規化（-1.0 〜 1.0）
        max_abs = np.max(np.abs(audio_data))
        if max_abs > 1.0:
            print(f"オーディオデータを正規化します。最大振幅: {max_abs}")
            audio_data = audio_data / max_abs
        
        # 最大60秒までに制限（1分間だけを処理対象）
        MAX_AUDIO_LENGTH = 60 * 16000  # 最大60秒まで処理
        if len(audio_data) > MAX_AUDIO_LENGTH:
            print(f"オーディオファイルが長すぎるため60秒に切り詰めます: {len(audio_data)/16000:.2f}秒 → 60秒")
            audio_data = audio_data[:MAX_AUDIO_LENGTH]
        
        # モデルを必要時にロード
        try:
            print("モデルをロードします...")
            current_model = load_model_if_needed()
            print("モデルのロードに成功しました")
        except Exception as e:
            print(f"モデルのロードに失敗しました: {str(e)}")
            raise HTTPException(status_code=500, detail=f"モデルのロードに失敗しました: {str(e)}")
        
        # YamNetでの推論
        try:
            print("推論を実行します...")
            scores, embeddings, log_mel_spectrogram = current_model(audio_data)
            print(f"推論に成功しました: スコアの形状 {scores.shape}")
        except Exception as e:
            print(f"推論の実行に失敗しました: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"推論の実行に失敗しました: {str(e)}")
        
        # 要約結果の作成
        try:
            print("要約結果を作成しています...")
            
            # YamNetのフレーム時間（通常約0.48秒）を計算
            n_frames = scores.shape[0]
            audio_duration = len(audio_data) / sample_rate
            frame_duration = audio_duration / n_frames
            
            print(f"フレーム時間: {frame_duration:.2f}秒、全フレーム数: {n_frames}")
            
            # 何フレームで一つのセグメントとするかを計算
            frames_per_segment = int(segment_seconds / frame_duration)
            print(f"セグメントあたりのフレーム数: {frames_per_segment}（約{segment_seconds}秒）")
            
            # 要約セグメントを格納するリスト
            summary_segments = []
            
            # 各セグメントごとに処理
            for segment_idx in range(0, n_frames, frames_per_segment):
                segment_start_frame = segment_idx
                segment_end_frame = min(segment_idx + frames_per_segment, n_frames)
                
                if segment_end_frame <= segment_start_frame:
                    break
                
                # セグメントの開始・終了時間
                start_time = segment_start_frame * frame_duration
                end_time = segment_end_frame * frame_duration
                
                # セグメント内のすべてのフレームのラベルを収集
                segment_labels = []
                
                for frame_idx in range(segment_start_frame, segment_end_frame):
                    # 現在のフレームのスコア
                    frame_scores = scores[frame_idx].numpy()
                    
                    # 各フレームで最も確率の高いラベルを1つだけ選択
                    top_class_idx = np.argmax(frame_scores)
                    top_prob = float(frame_scores[top_class_idx])
                    
                    if top_prob >= threshold:
                        segment_labels.append(class_names[top_class_idx])
                
                # セグメントの情報を追加
                if segment_labels:  # 空のセグメントは追加しない
                    summary_segments.append({
                        "start": round(start_time, 2),
                        "end": round(end_time, 2),
                        "labels": segment_labels
                    })
            
            print(f"要約結果作成完了: {len(summary_segments)}個のセグメント")
            return {"summary": summary_segments}
        except Exception as e:
            print(f"要約結果の作成に失敗しました: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"要約結果の作成に失敗しました: {str(e)}")
        
    except HTTPException:
        # 既に適切なHTTPExceptionが発生している場合はそのまま再発生
        raise
    except Exception as e:
        print(f"予期しないエラーが発生しました: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"音声分析中に予期しないエラーが発生しました: {str(e)}")

@app.post("/fetch-and-process")
async def fetch_and_process(request: FetchAndProcessRequest):
    """
    指定されたデバイス・日付の.wavファイルをAPIから取得し、一括音響イベント検出を行い、
    結果をSupabaseのbehavior_yamnetテーブルに保存する
    """
    device_id = request.device_id
    date = request.date
    threshold = request.threshold
    
    print(f"Supabaseへの直接保存モードで実行中")
    print(f"\n=== 一括取得・音響イベント検出開始 ===")
    print(f"デバイスID: {device_id}")
    print(f"対象日付: {date}")
    print(f"閾値: {threshold}")
    print(f"保存先: Supabase behavior_yamnet テーブル")
    print(f"=" * 50)
    
    # 24時間分のスロットを生成
    all_slots = generate_time_slots()
    print(f"📋 処理対象スロット数: {len(all_slots)}")
    
    fetched = []
    processed = []
    skipped = []
    errors = []
    saved_to_supabase = []
    
    # HTTP接続セッションを作成
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        
        # 各スロットを順次処理
        for slot in all_slots:
            try:
                print(f"📝 処理開始: {slot}")
                
                # 音声ファイルをダウンロード
                audio_content = await download_audio_file(session, device_id, date, slot)
                
                if audio_content is None:
                    print(f"⏭️ データなし: {slot}")
                    skipped.append(slot)
                    continue
                
                print(f"📥 取得: {slot}.wav")
                fetched.append(f"{slot}.wav")
                
                # 音声データを処理
                result = process_audio_data(audio_content, threshold)
                
                if result is None:
                    print(f"❌ 処理失敗: {slot}")
                    errors.append(slot)
                    continue
                
                # 新しいデータ構造に変換
                events = convert_to_new_format(device_id, date, slot, result["timeline"], result["slot_timeline"])
                
                # Supabaseに保存
                supabase_success = await save_to_supabase(device_id, date, slot, events)
                if supabase_success:
                    saved_to_supabase.append(slot)
                    processed.append(slot)
                    print(f"✅ 完了: {slot} ({len(events)}件のイベント)")
                else:
                    errors.append(slot)
                    
            except Exception as e:
                print(f"❌ エラー: {slot} - {str(e)}")
                errors.append(slot)
    
    print(f"\n=== 一括取得・音響イベント検出・Supabase保存完了 ===")
    print(f"📥 音声取得成功: {len(fetched)} ファイル")
    print(f"📝 処理対象: {len(processed)} ファイル")
    print(f"💾 Supabase保存成功: {len(saved_to_supabase)} ファイル")
    print(f"⏭️ スキップ: {len(skipped)} ファイル (データなし)")
    print(f"❌ エラー: {len(errors)} ファイル")
    print(f"=" * 50)
    
    return {
        "status": "success",
        "fetched": fetched,
        "processed": processed,
        "saved_to_supabase": saved_to_supabase,
        "skipped": skipped,
        "errors": errors,
        "summary": {
            "total_time_blocks": len(all_slots),
            "audio_fetched": len(fetched),
            "supabase_saved": len(saved_to_supabase),
            "skipped_no_data": len(skipped),
            "errors": len(errors)
        }
    }

@app.get("/")
def read_root():
    return {"message": "Sound Event Detection API is running"}

@app.get("/test")
def test_api():
    """
    APIの動作テスト用のエンドポイント。
    TensorFlowが正常に動作しているかを確認します。
    """
    try:
        # TensorFlowの基本的な操作をテスト
        tf_version = tf.__version__
        test_tensor = tf.constant([[1.0, 2.0], [3.0, 4.0]])
        test_result = tf.reduce_mean(test_tensor).numpy().tolist()
        
        # soundfileの動作テスト
        sf_version = sf.__version__
        
        # NumPyの動作テスト
        np_version = np.__version__
        
        return {
            "status": "ok",
            "tensorflow_version": tf_version,
            "tensorflow_test": test_result,
            "soundfile_version": sf_version,
            "numpy_version": np_version,
            "model_loaded": model is not None
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(e)
        }

@app.post("/debug/clear-cache")
def clear_cache_endpoint():
    """
    🔧 TensorFlow Hubキャッシュを手動でクリアするデバッグエンドポイント
    
    用途: 
    - キャッシュ破損問題のトラブルシューティング
    - モデルロードエラーの解決
    
    使用方法:
    curl -X POST http://localhost:8004/debug/clear-cache
    """
    try:
        print("🔧 手動キャッシュクリアが要求されました")
        clear_tfhub_cache()
        
        # グローバルモデルもリセット
        global model
        model = None
        print("🔄 モデルインスタンスもリセットしました")
        
        return {
            "status": "success",
            "message": "TensorFlow Hubキャッシュをクリアしました",
            "note": "次回のモデルロード時に自動的に再ダウンロードされます",
            "model_reset": True
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(e),
            "message": "キャッシュクリアに失敗しました"
        }

@app.get("/debug/cache-status")
def cache_status_endpoint():
    """
    🔍 TensorFlow Hubキャッシュの状態を確認するデバッグエンドポイント
    
    用途:
    - キャッシュの健全性チェック
    - 破損キャッシュの事前検出
    
    使用方法:
    curl http://localhost:8004/debug/cache-status
    """
    try:
        print("🔍 キャッシュ状態の確認が要求されました")
        is_valid = validate_model_cache()
        
        return {
            "status": "success",
            "cache_valid": is_valid,
            "model_loaded": model is not None,
            "message": "正常なキャッシュです" if is_valid else "キャッシュに問題があります",
            "recommendation": "問題なし" if is_valid else "POST /debug/clear-cache でキャッシュをクリアしてください"
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(e),
            "message": "キャッシュ状態の確認に失敗しました"
        }

if __name__ == "__main__":
    # 起動時診断を実行
    startup_diagnostics()
    uvicorn.run("main:app", host="0.0.0.0", port=8004, reload=True) 