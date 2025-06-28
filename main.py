import os
import numpy as np
import tensorflow as tf
from scipy import signal
import shutil
import glob
import time

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
import json
from pathlib import Path

# FastAPIアプリケーションの初期化
app = FastAPI(
    title="Sound Event Detection API",
    description="YamNetモデルを使用して音声ファイルからサウンドイベントを検出するAPI（v1.1.0: 自動回復機能搭載）",
    version="1.1.0"
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
    """TensorFlow Hubキャッシュをクリア"""
    try:
        # 一般的なキャッシュパス
        cache_paths = [
            os.path.expanduser('~/tfhub_modules'),
            '/tmp/tfhub_modules',
        ]
        
        # /var/folders以下のキャッシュも検索
        cache_paths.extend(glob.glob('/var/folders/*/T/tfhub_modules*'))
        
        for path in cache_paths:
            if os.path.exists(path):
                try:
                    shutil.rmtree(path)
                    print(f"キャッシュクリア: {path}")
                except Exception as e:
                    print(f"キャッシュクリア失敗: {path} - {e}")
    except Exception as e:
        print(f"キャッシュクリア処理でエラー: {e}")

def validate_model_cache():
    """モデルキャッシュの整合性を確認"""
    try:
        cache_dir = os.environ.get('TFHUB_CACHE_DIR', '/tmp/tfhub_modules')
        
        # 一般的なキャッシュディレクトリをチェック
        check_dirs = [
            cache_dir,
            os.path.expanduser('~/tfhub_modules'),
        ]
        check_dirs.extend(glob.glob('/var/folders/*/T/tfhub_modules*'))
        
        for cache_dir in check_dirs:
            if os.path.exists(cache_dir):
                for model_dir in os.listdir(cache_dir):
                    model_path = os.path.join(cache_dir, model_dir)
                    if os.path.isdir(model_path):
                        saved_model_path = os.path.join(model_path, 'saved_model.pb')
                        
                        if not os.path.exists(saved_model_path):
                            print(f"破損したキャッシュを発見: {model_path}")
                            try:
                                shutil.rmtree(model_path)
                                print(f"破損したキャッシュを削除: {model_path}")
                            except Exception as e:
                                print(f"キャッシュ削除失敗: {e}")
                            return False
        return True
    except Exception as e:
        print(f"キャッシュ検証でエラー: {e}")
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
    global model
    if model is None:
        print("YamNetモデルを必要に応じてロードします...")
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                # キャッシュ検証
                if not validate_model_cache():
                    print("キャッシュが破損しています。クリアします...")
                    clear_tfhub_cache()
                
                # メモリを節約するためにTensorFlowの設定を最適化
                tf.keras.backend.clear_session()
                
                # モデルのロード（タイムアウト付き）
                print(f"モデルロード試行 {attempt + 1}/{max_attempts}")
                
                # 環境変数でダウンロード進捗を表示
                os.environ['TFHUB_DOWNLOAD_PROGRESS'] = '1'
                model = hub.load('https://tfhub.dev/google/yamnet/1')
                
                # 小さなダミーデータで最初の推論を実行してモデルを初期化
                dummy_waveform = np.zeros(16000, dtype=np.float32)
                _ = model(dummy_waveform)
                
                print("YamNetモデルのロード完了")
                break
                
            except Exception as e:
                print(f"モデルロード試行 {attempt + 1} 失敗: {str(e)}")
                if attempt < max_attempts - 1:
                    print(f"5秒後に再試行します...")
                    time.sleep(5)
                    # キャッシュをクリアして再試行
                    clear_tfhub_cache()
                else:
                    print("全ての試行が失敗しました")
                    import traceback
                    traceback.print_exc()
                    model = None
                    raise Exception(f"モデルロードに失敗しました（{max_attempts}回試行）: {str(e)}")
    
    return model

def generate_time_slots():
    """24時間分の30分単位スロットを生成（48個）"""
    slots = []
    for hour in range(24):
        for minute in [0, 30]:
            slot = f"{hour:02d}-{minute:02d}"
            slots.append(slot)
    return slots

def create_output_directory(user_id: str, date: str):
    """
    ローカル出力ディレクトリを作成する
    例: /Users/kaya.matsumoto/data/data_accounts/user123/2025-06-18/sed/
    """
    base_path = Path("/Users/kaya.matsumoto/data/data_accounts")
    output_dir = base_path / user_id / date / "sed"
    
    # ディレクトリを作成（親ディレクトリも含めて）
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 出力ディレクトリを作成/確認: {output_dir}")
    
    return output_dir

def save_slot_result(output_dir: Path, slot: str, timeline_data: dict):
    """
    スロットの処理結果をJSONファイルとして保存する
    """
    output_file = output_dir / f"{slot}.json"
    
    # タイムライン結果をファイルに保存
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(timeline_data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 保存完了: {output_file}")
    return output_file

async def upload_sed_json_to_ec2(user_id: str, date: str, slot: str, json_file_path: Path):
    """
    ローカルのSED JSONファイルをEC2にアップロードする
    
    Args:
        user_id: ユーザーID
        date: 日付（YYYY-MM-DD）
        slot: スロット（HH-MM）
        json_file_path: ローカルJSONファイルのパス
    
    Returns:
        bool: アップロード成功/失敗
    """
    upload_url = "https://api.hey-watch.me/upload/analysis/sed-timeline"
    
    try:
        print(f"☁️ EC2アップロード開始: {slot}")
        
        async with aiohttp.ClientSession() as session:
            # ファイルを読み込み
            with open(json_file_path, 'rb') as f:
                file_content = f.read()
            
            # FormDataを作成
            data = aiohttp.FormData()
            data.add_field('user_id', user_id)
            data.add_field('date', date)
            data.add_field('time_block', slot)  # EC2側で期待されるフィールド名に変更
            data.add_field('file', file_content, filename=f"{slot}.json", content_type='application/json')
            
            # アップロードリクエスト送信
            async with session.post(upload_url, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ EC2アップロード成功: {slot} → {result.get('path', 'N/A')}")
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ EC2アップロード失敗: {slot} (ステータス: {response.status})")
                    print(f"   エラー詳細: {error_text}")
                    return False
                    
    except Exception as e:
        print(f"❌ EC2アップロード中にエラー: {slot} - {str(e)}")
        return False

async def download_audio_file(session: aiohttp.ClientSession, user_id: str, date: str, slot: str):
    """
    EC2サーバーから音声ファイルをダウンロードする
    """
    url = f"https://api.hey-watch.me/download"
    params = {
        "user_id": user_id,
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
    user_id: str
    date: str  # YYYY-MM-DD形式

class SlotTimelineData(BaseModel):
    slot: str  # HH-MM形式
    timeline: List[TimelineEvent]
    slot_timeline: List[TimeSlot]

class TimelineV2Result(BaseModel):
    user_id: str
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
    print(f"🎯 timeline-v2 処理開始: user_id={request.user_id}, date={request.date}")
    
    # 日付形式の検証
    try:
        datetime.strptime(request.date, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=400, detail="日付はYYYY-MM-DD形式で指定してください")
    
    # 24時間分のスロットを生成
    all_slots = generate_time_slots()
    print(f"📋 処理対象スロット数: {len(all_slots)}")
    
    # ローカル出力ディレクトリを作成
    output_dir = create_output_directory(request.user_id, request.date)
    
    processed_slots = []
    
    # HTTP接続セッションを作成
    timeout = aiohttp.ClientTimeout(total=30)  # 30秒タイムアウト
    async with aiohttp.ClientSession(timeout=timeout) as session:
        
        # 各スロットを順次処理
        for slot in all_slots:
            print(f"🕒 処理中のスロット: {slot}")
            
            # 音声ファイルをダウンロード
            audio_content = await download_audio_file(session, request.user_id, request.date, slot)
            
            if audio_content is None:
                print(f"⏭️ スキップ: {slot}")
                continue
            
            # 音声データを処理
            result = process_audio_data(audio_content, threshold)
            
            if result is None:
                print(f"❌ 処理失敗: {slot}")
                continue
            
            # 結果をローカルファイルに保存
            timeline_data = {
                "slot": slot,
                "timeline": result["timeline"],
                "slot_timeline": result["slot_timeline"]
            }
            json_file_path = save_slot_result(output_dir, slot, timeline_data)
            
            # EC2にアップロード
            upload_success = await upload_sed_json_to_ec2(request.user_id, request.date, slot, json_file_path)
            if upload_success:
                print(f"📤 EC2アップロード成功: {slot}")
            else:
                print(f"⚠️ EC2アップロード失敗（処理は継続）: {slot}")
            
            # 結果を追加
            slot_data = SlotTimelineData(
                slot=slot,
                timeline=result["timeline"],
                slot_timeline=result["slot_timeline"]
            )
            processed_slots.append(slot_data)
            print(f"✅ 処理完了: {slot} ({len(result['timeline'])}件のイベント)")
    
    print(f"🎉 全体処理完了: {len(processed_slots)}/{len(all_slots)} スロット処理済み")
    print(f"📂 保存先ディレクトリ: {output_dir}")
    
    # 処理サマリーもJSONファイルに保存
    summary_data = {
        "user_id": request.user_id,
        "date": request.date,
        "total_processed_slots": len(processed_slots),
        "total_available_slots": len(all_slots),
        "processed_slot_names": [slot.slot for slot in processed_slots],
        "processing_timestamp": datetime.now().isoformat()
    }
    
    summary_file = output_dir / "processing_summary.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)
    print(f"📋 処理サマリーを保存: {summary_file}")
    
    return TimelineV2Result(
        user_id=request.user_id,
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

if __name__ == "__main__":
    # 起動時診断を実行
    startup_diagnostics()
    uvicorn.run("main:app", host="0.0.0.0", port=8004, reload=True) 