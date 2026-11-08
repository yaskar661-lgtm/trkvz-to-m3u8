from flask import Flask, Response, request
import re
import requests
import os
import time
from urllib.parse import urlparse

app = Flask(__name__)

ALLOWED_DOMAINS = [
    "securevideotoken.tmgrup.com.tr",
    "trkvz-live.ercdn.net",
    "trkvz.daioncdn.net",
    "trkvz-live.daioncdn.net",
    "trkvz-to-m3u8-index.onrender.com",
    "rnttwmjcin.turknet.ercdn.net"
]

TARGET_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.atv.com.tr/",
    "Origin": "https://www.atv.com.tr",
}

# Bellek içi cache ve kanal tanımları
CACHE = {}
CACHE_TTL = 15 * 60  # 15 dakika

CHANNELS = {
    "ahaber": {"type": "daion", "url": "https://trkvz.daioncdn.net/ahaber/ahaber.m3u8?app=mobile_web"},
    "ahaberhd": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/ahaberhd/ahaberhd.m3u8"},
    "asporhd": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/asporhd/asporhd.m3u8"},
    "atvhd": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/atvhd/atvhd.m3u8"},
    "atv": {"type": "daion", "url": "https://trkvz.daioncdn.net/atv/atv.m3u8?ce=3&app=866e32e3-9fea-477f-a5ef-64ebe32956f3"},
    "atvmob": {"type": "daion", "url": "https://trkvz.daioncdn.net/atv/atv.m3u8?ce=3&app=d5eb593f-39d9-4b01-9cfd-4748e8332cf0"},
    "atvdesk": {"type": "daion", "url": "https://trkvz.daioncdn.net/atv/atv.m3u8?ce=3&app=d1ce2d40-5256-4550-b02e-e73c185a314e"},
    "atvoverflow": {"type": "daion", "url": "https://trkvz.daioncdn.net/atv-overflow/atv-overflow.m3u8?ce=3&app=web"},
    "aspor": {"type": "daion", "url": "https://trkvz.daioncdn.net/aspor/aspor.m3u8?ce=3&app=45f847c4-04e8-419a-a561-2ebf87084765"},
    "a2tv": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/a2tv/a2tv.m3u8"},
    "a2tvdai": {"type": "daion", "url": "https://trkvz.daioncdn.net/a2tv/a2tv.m3u8?ce=3&app=59363a60-be96-4f73-9eff-355d0ff2c758"},
    "minikago": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/minikago/minikago.m3u8"},
    "minikagodai": {"type": "daion", "url": "https://trkvz.daioncdn.net/minikago/minikago.m3u8?app=web&ce=3"},
    "minikagococuk": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/minikagococuk/minikagococuk.m3u8"},
    "minikagococukdai": {"type": "daion", "url": "https://trkvz.daioncdn.net/minikago_cocuk/minikago_cocuk.m3u8?app=web&ce=3"},
    "atvavrupa": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa.m3u8"},
    "atvavrupahd": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/atvavrupahd/atvavrupahd.m3u8"},
    "anewshd": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/anewshd/anewshd.m3u8"},
    "aparahd": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/aparahd/aparahd.m3u8"},
    "apara": {"type": "daion", "url": "https://trkvz.daioncdn.net/apara/apara.m3u8?app=mobile_web"},
    "vavtv": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/vavtv/vavtv.m3u8"},
    "vavtvndvr": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/vavtvndvr/vavtvndvr.m3u8"},
}

def is_allowed_domain(url):
    return any(domain in url for domain in ALLOWED_DOMAINS)

def fix_url(target_url):
    if not target_url:
        return target_url
    target_url = target_url.strip()
    if not target_url.startswith("http://") and not target_url.startswith("https://"):
        if any(d in target_url for d in ALLOWED_DOMAINS):
            target_url = "https://" + target_url.lstrip("/")
    return target_url

def fetch_token_for_channel(channel_key):
    if channel_key not in CHANNELS:
        return None
    
    ch = CHANNELS[channel_key]
    raw_url = ch["url"]
    
    if ch["type"] == "ercdn" and channel_key in ["ahaberhd", "asporhd"]:
        return raw_url

    rand_num = int(time.time() * 1000) % 1000000
    secure_api = f"https://securevideotoken.tmgrup.com.tr/webtv/secure?{rand_num}"
    target_api_url = f"{secure_api}&url={requests.utils.quote(raw_url)}"

    try:
        resp = requests.get(target_api_url, headers=TARGET_HEADERS, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        url_key = next((k for k in data.keys() if k.lower() == 'url'), None)
        if url_key and data[url_key]:
            return data[url_key]
    except Exception as e:
        print(f"[{channel_key}] Token alınamadı: {e}")

    return raw_url

@app.route("/stream/<channel_name>")
def api_channel(channel_name):
    now = time.time()
    
    if channel_name not in CHANNELS:
        return f"Kanal bulunamadı: {channel_name}", 404

    if channel_name in CACHE and (now - CACHE[channel_name]["timestamp"] < CACHE_TTL):
        content = CACHE[channel_name]["content"]
        return Response(content, mimetype="application/vnd.apple.mpegurl")

    resolved_url = fetch_token_for_channel(channel_name)
    if not resolved_url:
        return "Yayın linki çözülemedi", 500

    try:
        resp = requests.get(resolved_url, headers=TARGET_HEADERS, timeout=10)
        resp.raise_for_status()
        
        playlist_content = resp.text
        base_url = re.sub(r"[^/]+$", "", resolved_url)
        host_root = request.host_url.rstrip("/")  # Düzeltildi

        new_lines = []
        for line in playlist_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                if line.startswith("http://") or line.startswith("https://"):
                    seg_url = line
                elif line.startswith("/"):
                    parsed_base = urlparse(resolved_url)
                    seg_url = f"{parsed_base.scheme}://{parsed_base.netloc}{line}"
                else:
                    seg_url = base_url + line

                proxied_seg = f"{host_root}/proxy?url={requests.utils.quote(seg_url, safe=':/')}"
                new_lines.append(proxied_seg)
            else:
                new_lines.append(line)

        final_content = "\n".join(new_lines)

        CACHE[channel_name] = {
            "content": final_content,
            "timestamp": now,
            "resolved_url": resolved_url
        }

        return Response(final_content, mimetype="application/vnd.apple.mpegurl")

    except Exception as e:
        return f"Kanal akışı alınırken hata oluştu: {str(e)}", 500

@app.route("/proxy")
def proxy_media():
    raw_target = (
        request.args.get("url") or 
        request.args.get("URL") or 
        request.args.get("uri") or 
        request.args.get("URI")
    )
    
    target_url = fix_url(raw_target)
    if not target_url:
        return "URL/URI belirtilmedi", 400

    # İstek yapılan hedef bir atv daion kanalı mı kontrol et
    is_atv_daion = False
    for ch_name, ch_info in CHANNELS.items():
        if ("atv" in ch_name) and ch_info["type"] == "daion":
            if target_url == ch_info["url"] or ch_info["url"] in target_url or target_url.endswith(f"/{ch_name}.m3u8"):
                is_atv_daion = True
                break

    # Eğer istek atv daion kanalına aitse özel dış servisi kontrol et
    if is_atv_daion:
        try:
            external_resp = requests.get("https://trkvz-to-m3u8-index.onrender.com/stream/atv", headers=TARGET_HEADERS, timeout=8)
            if external_resp.status_code == 200:
                target_url = external_resp.text.strip()
        except Exception as e:
            print(f"Dış atv stream servisine bağlanırken hata: {e}")

    for ch_name, ch_info in CHANNELS.items():
        if target_url == ch_info["url"] or ch_info["url"] in target_url or target_url.endswith(f"/{ch_name}.m3u8"):
            resolved = fetch_token_for_channel(ch_name)
            if resolved:
                target_url = resolved
            break

    for ch_data in CACHE.values():
        cached_res_url = ch_data.get("resolved_url", "")
        if cached_res_url and (target_url in cached_res_url or cached_res_url in target_url):
            target_url = cached_res_url

    if not is_allowed_domain(target_url):
        return "Bu domainin proxy'lenmesine izin verilmiyor.", 403

    try:
        req = requests.get(target_url, headers=TARGET_HEADERS, stream=True, timeout=10)
        req.raise_for_status()

        content_type = req.headers.get("Content-Type", "application/octet-stream")

        if "application/vnd.apple.mpegurl" in content_type or "audio/mpegurl" in content_type or target_url.endswith(".m3u8"):
            playlist_content = req.text
            base_url = re.sub(r"[^/]+$", "", target_url)
            host_root = request.host_url.rstrip("/")  # Düzeltildi

            new_lines = []
            for line in playlist_content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    if line.startswith("http://") or line.startswith("https://"):
                        seg_url = line
                    elif line.startswith("/"):
                        parsed_target = urlparse(target_url)
                        seg_url = f"{parsed_target.scheme}://{parsed_target.netloc}{line}"
                    else:
                        seg_url = base_url + line

                    if "atv" in target_url.lower():
                        if "crea" not in seg_url:
                            ts_match = re.search(r'atv_([a-zA-Z0-9_-]+)-(\d+)\.ts', seg_url)
                            if ts_match:
                                quality_name = ts_match.group(1)
                                segment_timestamp = ts_match.group(2)
                                seg_url = f"https://rnttwmjcin.turknet.ercdn.net/lcpmvefbyo/atv/atv_{quality_name}-{segment_timestamp}.ts"

                    proxied_seg = f"{host_root}/proxy?url={requests.utils.quote(seg_url, safe=':/')}"
                    new_lines.append(proxied_seg)
                else:
                    new_lines.append(line)

            updated_playlist = "\n".join(new_lines)
            return Response(updated_playlist, mimetype="application/vnd.apple.mpegurl")

        return Response(
            req.iter_content(chunk_size=8192),
            status=req.status_code,
            mimetype=content_type,
        )

    except Exception as e:
        return f"Medya aktarım hatası: {str(e)}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
