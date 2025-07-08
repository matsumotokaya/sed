#!/usr/bin/env python3
"""
API SED v1のfetch-and-processエンドポイントのテストスクリプト
"""

import requests
import json
from datetime import datetime, timedelta

# API設定
API_BASE_URL = "http://localhost:8004"
ENDPOINT = "/fetch-and-process"

def test_fetch_and_process():
    """
    fetch-and-processエンドポイントのテスト
    """
    # テスト用のリクエストデータ
    test_request = {
        "device_id": "d067d407-cf73-4174-a9c1-d91fb60d64d0",  # 実際のデバイスID
        "date": "2025-07-05",  # テスト日付
        "threshold": 0.2
    }
    
    print("🧪 fetch-and-processエンドポイントのテスト開始")
    print(f"📋 リクエストデータ: {json.dumps(test_request, indent=2)}")
    print(f"🌐 URL: {API_BASE_URL}{ENDPOINT}")
    print("-" * 50)
    
    try:
        # APIリクエストを送信
        response = requests.post(
            f"{API_BASE_URL}{ENDPOINT}",
            json=test_request,
            timeout=300  # 5分タイムアウト
        )
        
        print(f"📡 ステータスコード: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ リクエスト成功!")
            print(f"📊 処理結果サマリー:")
            print(f"   - 音声取得成功: {result['summary']['audio_fetched']} ファイル")
            print(f"   - Supabase保存成功: {result['summary']['supabase_saved']} ファイル")
            print(f"   - スキップ: {result['summary']['skipped_no_data']} ファイル")
            print(f"   - エラー: {result['summary']['errors']} ファイル")
            
            if result.get('saved_to_supabase'):
                print(f"💾 Supabase保存済みスロット: {result['saved_to_supabase']}")
            
            print(f"📄 完全なレスポンス:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
        else:
            print(f"❌ リクエスト失敗: {response.status_code}")
            print(f"エラー詳細: {response.text}")
            
    except requests.exceptions.Timeout:
        print("⏰ リクエストタイムアウト (5分)")
    except requests.exceptions.ConnectionError:
        print("🔌 接続エラー - APIサーバーが起動していますか？")
    except Exception as e:
        print(f"❌ 予期しないエラー: {str(e)}")

def test_api_health():
    """
    APIの基本的な動作確認
    """
    print("🔍 API健全性チェック")
    
    try:
        # ルートエンドポイントをテスト
        response = requests.get(f"{API_BASE_URL}/", timeout=10)
        if response.status_code == 200:
            print("✅ APIサーバー正常稼働中")
            return True
        else:
            print(f"⚠️ APIサーバー応答異常: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ APIサーバー接続失敗: {str(e)}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 API SED v1.2.0 fetch-and-process テストスクリプト")
    print("=" * 60)
    
    # APIの健全性チェック
    if test_api_health():
        print()
        # メインテスト実行
        test_fetch_and_process()
    else:
        print("🚨 APIサーバーが利用できないため、テストを中止します")
        print("💡 サーバーを起動してください: python3 main.py")
    
    print()
    print("=" * 60)
    print("🏁 テスト完了")
    print("=" * 60)