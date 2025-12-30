#!/usr/bin/env python3
"""
Тестовый скрипт для проверки TikTok API
"""
import requests
import re

def test_tiktok_apis(url):
    """Тестируем разные API для TikTok"""
    
    apis = [
        {
            "name": "tikwm",
            "url": "https://tikwm.com/api/",
            "method": "GET"
        },
        {
            "name": "tikmate", 
            "url": "https://tikmate.online/download",
            "method": "GET"
        }
    ]
    
    for api in apis:
        try:
            print(f"\n=== Тест API: {api['name']} ===")
            
            if api["name"] == "tikwm":
                r = requests.get(api["url"], params={"url": url}, timeout=15)
                print(f"Status: {r.status_code}")
                
                if r.status_code == 200:
                    data = r.json()
                    print(f"Response keys: {list(data.keys())}")
                    
                    play_url = (
                        data.get("data", {}).get("play")
                        or data.get("data", {}).get("wmplay") 
                        or data.get("data", {}).get("hdplay")
                    )
                    
                    if play_url:
                        print(f"✅ Найден видео URL: {play_url[:50]}...")
                    else:
                        print("❌ Видео URL не найден")
                else:
                    print(f"❌ Ошибка запроса: {r.status_code}")
                    
            elif api["name"] == "tikmate":
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                r = requests.get(api["url"], params={"url": url}, headers=headers, timeout=20)
                print(f"Status: {r.status_code}")
                
                if r.status_code == 200:
                    # Ищем видео URL в HTML
                    video_match = re.search(r'href="(https://[^"]+\.mp4)"', r.text)
                    if video_match:
                        print(f"✅ Найден видео URL: {video_match.group(1)[:50]}...")
                    else:
                        print("❌ Видео URL не найден в HTML")
                        print(f"Response length: {len(r.text)}")
                else:
                    print(f"❌ Ошибка запроса: {r.status_code}")
                    
        except Exception as e:
            print(f"❌ Ошибка API {api['name']}: {e}")

if __name__ == "__main__":
    # Тестовая ссылка TikTok
    test_url = "https://www.tiktok.com/@test/video/1234567890123456789"
    
    print("Тестирование TikTok API...")
    print(f"Тестовая URL: {test_url}")
    
    test_tiktok_apis(test_url)
