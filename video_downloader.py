import os
import re
import requests
import time
from urllib.parse import urlparse, parse_qs

import certifi
import yt_dlp
import imageio_ffmpeg


def extract_youtube_id(url: str) -> str | None:
    p = urlparse(url)

    # youtu.be/<id>
    if p.netloc in ("youtu.be", "www.youtu.be"):
        vid = p.path.strip("/").split("/")[0]
        return vid or None

    # youtube.com/shorts/<id>
    if p.path.startswith("/shorts/"):
        parts = p.path.split("/")
        return parts[2] if len(parts) > 2 and parts[2] else None

    # youtube.com/watch?v=<id>
    qs = parse_qs(p.query)
    if "v" in qs and qs["v"]:
        return qs["v"][0]

    return None


class VideoDownloader:
    @staticmethod
    def is_tiktok(url):
        return 'tiktok.com' in url

    @staticmethod
    def is_youtube_shorts(url):
        u = url.lower()
        return 'youtube.com/shorts/' in u or 'youtu.be/' in u or 'youtube.com/watch' in u

    @staticmethod
    def download_youtube_shorts(url: str):
        # На macOS/Python 3.13 иногда не подтягиваются корневые сертификаты.
        # Пытаемся явно указать CA bundle из certifi.
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

        os.makedirs("downloads", exist_ok=True)

        # yt-dlp намного стабильнее pytube.
        # Проблема "только звук" возникает, когда выбран аудио-only формат.
        # Поэтому:
        # 1) сначала пробуем progressive MP4 (видео+аудио в одном файле) — ffmpeg не нужен
        # 2) если не получилось — пробуем bestvideo+bestaudio (нужен ffmpeg для склейки)

        outtmpl = os.path.join("downloads", "%(id)s.%(ext)s")
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

        def _download_with_format(fmt: str, need_merge: bool, force_mp4: bool):
            ydl_opts = {
                "outtmpl": outtmpl,
                "format": fmt,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 30,  # Таймаут сетевых операций
                "retries": 3,  # Количество попыток
                "fragment_retries": 3,  # Повторы для фрагментов
            }
            # Подкладываем ffmpeg без Homebrew
            ydl_opts["ffmpeg_location"] = ffmpeg_path

            if need_merge:
                ydl_opts["merge_output_format"] = "mp4"

            # Важно для Telegram: иногда mp4 с VP9/AV1 ведёт себя как "только звук".
            # Поэтому принудительно ремаксим/перекодируем в mp4 (H.264/AAC).
            if force_mp4:
                ydl_opts["postprocessors"] = [
                    {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
                    {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
                ]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    return None

                # Когда формат составной (v+a), после merge расширение обычно mp4.
                path = ydl.prepare_filename(info)

                # После postprocessors итоговый файл почти всегда .mp4
                base, _ = os.path.splitext(path)
                mp4_path = base + ".mp4"
                if force_mp4 and os.path.exists(mp4_path):
                    return mp4_path
                if need_merge:
                    merged = mp4_path
                    # Если merge не произошёл (обычно из-за отсутствия ffmpeg),
                    # НЕ возвращаем аудио-файл — иначе в Telegram будет "только звук".
                    return merged if os.path.exists(merged) else None

                return path if path and os.path.exists(path) else None

        # 1) Сначала пытаемся взять сразу mp4 с H.264 + AAC (максимально совместимо с Telegram)
        try:
            progressive_fmt = "best[ext=mp4][vcodec^=avc1][acodec^=mp4a]/best[ext=mp4][vcodec!=none][acodec!=none]"
            p = _download_with_format(progressive_fmt, need_merge=False, force_mp4=True)
            if p:
                return p
        except Exception:
            pass

        # 2) Fallback: bestvideo + bestaudio (склейка + перекодирование в mp4)
        try:
            merge_fmt = "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo+bestaudio"
            p = _download_with_format(merge_fmt, need_merge=True, force_mp4=True)
            if p:
                return p
        except Exception:
            return None

        return None

    @staticmethod
    def download_tiktok(url: str):
        """Скачивает TikTok видео через публичный API (без TikTokApi).

        Важно: это не гарантированно стабильный способ — публичные сервисы могут
        менять API/ограничивать запросы.
        """

        os.makedirs("downloads", exist_ok=True)

        # Пробуем несколько API сервисов
        apis = [
            {
                "name": "tikmate",
                "url": "https://tikmate.online/download",
                "method": "POST"
            },
            {
                "name": "tikwm",
                "url": "https://tikwm.com/api/",
                "method": "GET"
            },
            {
                "name": "snaptik",
                "url": "https://snaptik.app/abc",
                "method": "POST"
            }
        ]
        
        for api in apis:
            try:
                print(f"Пробую API: {api['name']}")
                
                if api["name"] == "tikwm":
                    # tikwm API
                    r = requests.get(api["url"], params={"url": url}, timeout=15)
                    r.raise_for_status()
                    data = r.json()
                    
                    play_url = (
                        data.get("data", {}).get("play")
                        or data.get("data", {}).get("wmplay")
                        or data.get("data", {}).get("hdplay")
                    )
                    
                elif api["name"] == "tikmate":
                    # tikmate API
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                    r = requests.get(api["url"], params={"url": url}, headers=headers, timeout=20)
                    r.raise_for_status()
                    
                    # Ищем видео URL в HTML ответе
                    import re
                    video_match = re.search(r'href="(https://[^"]+\.mp4)"', r.text)
                    if video_match:
                        play_url = video_match.group(1)
                    else:
                        print(f"API {api['name']}: не найден URL видео в HTML")
                        continue
                        
                else:
                    # Другие API пока пропускаем
                    continue
                    
                if not play_url:
                    print(f"API {api['name']}: не найден URL видео")
                    continue
                    
                print(f"API {api['name']}: найден URL {play_url[:50]}...")
                
                out_path = os.path.join("downloads", f"tiktok_{int(time.time())}.mp4")
                # Уменьшаем таймаут и увеличиваем chunk_size для более быстрой загрузки
                with requests.get(play_url, stream=True, timeout=45) as vid:
                    vid.raise_for_status()
                    with open(out_path, "wb") as f:
                        for chunk in vid.iter_content(chunk_size=1024 * 512):  # 512KB chunks
                            if chunk:
                                f.write(chunk)

                if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    print(f"Успешно загружено через {api['name']}: {out_path}")
                    return out_path
                else:
                    print(f"Файл не сохранен через {api['name']}")
                    
            except Exception as e:
                print(f"Ошибка API {api['name']}: {e}")
                continue
                
        print("Все API TikTok не сработали")
        return None
