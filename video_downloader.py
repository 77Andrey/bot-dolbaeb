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

        def _download_with_format(fmt: str, need_merge: bool, force_mp4: bool, headers: dict = None):
            ydl_opts = {
                "outtmpl": outtmpl,
                "format": fmt,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 30,
                "retries": 3,
                "fragment_retries": 3,
            }
            # Добавляем headers для обхода блокировки
            if headers:
                ydl_opts["http_headers"] = headers
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

        # Пробуем разные подходы для обхода блокировки
        approaches = [
            ("Стандартный", {}),
            ("Мобильный UA", {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15"}),
            ("Desktop UA", {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        ]
        
        for approach_name, headers in approaches:
            try:
                print(f"Пробуем YouTube: {approach_name}")
                
                # 1) Сначала пытаемся взять сразу mp4 с H.264 + AAC
                progressive_fmt = "best[ext=mp4][vcodec^=avc1][acodec^=mp4a]/best[ext=mp4][vcodec!=none][acodec!=none]"
                p = _download_with_format(progressive_fmt, need_merge=False, force_mp4=True, headers=headers)
                if p:
                    print(f"YouTube ({approach_name}): {p}")
                    return p
                
                # 2) Fallback: bestvideo + bestaudio
                merge_fmt = "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo+bestaudio"
                p = _download_with_format(merge_fmt, need_merge=True, force_mp4=True, headers=headers)
                if p:
                    print(f"YouTube ({approach_name}): {p}")
                    return p
                    
            except Exception as e:
                print(f"YouTube ({approach_name}): ошибка - {e}")
                continue

        return None

    @staticmethod
    def download_tiktok(url: str):
        """Скачивает TikTok видео через yt-dlp с несколькими попытками."""

        os.makedirs("downloads", exist_ok=True)
        
        # На macOS/Python 3.13 иногда не подтягиваются корневые сертификаты.
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
        
        # Пробуем несколько форматов от простого к сложному
        formats = [
            "best",                        # лучший доступный (самый надежный)
            "worst",                       # худший (если лучший не работает)
            "best[height<=720]",          # любой до 720p
            "best[ext=mp4]",               # любой MP4
        ]
        
        for fmt in formats:
            try:
                print(f"Пробуем формат {fmt} для {url}")
                
                outtmpl = os.path.join("downloads", "tiktok_%(id)s.%(ext)s")
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                
                ydl_opts = {
                    "outtmpl": outtmpl,
                    "format": fmt,
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "socket_timeout": 30,
                    "retries": 2,
                    "fragment_retries": 2,
                    "ffmpeg_location": ffmpeg_path,
                    # Убираем postprocessors для надежности
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        print(f"Формат {fmt}: не удалось получить информацию")
                        continue
                    
                    # Ищем скачанный файл
                    path = ydl.prepare_filename(info)
                    base, _ = os.path.splitext(path)
                    mp4_path = base + ".mp4"
                    
                    if os.path.exists(mp4_path):
                        print(f"Успешно загружено через yt-dlp ({fmt}): {mp4_path}")
                        return mp4_path
                    elif os.path.exists(path):
                        print(f"Успешно загружено через yt-dlp ({fmt}): {path}")
                        return path
                    else:
                        print(f"Формат {fmt}: файл не найден после загрузки")
                        continue
                        
            except Exception as e:
                print(f"Формат {fmt}: ошибка - {e}")
                continue
                
        print("Все форматы TikTok не сработали")
        return None
