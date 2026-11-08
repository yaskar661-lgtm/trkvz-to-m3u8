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
    "trkvz-live.daioncdn.net"
]

def get_headers_for_url(url):
    """İstek atılan URL veya kanala göre uygun Referer ve Origin başlıklarını dinamik olarak belirler."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    
    url_lower = url.lower()
    if "aspor" in url_lower:
        headers["Referer"] = "https://www.aspor.com.tr/"
        headers["Origin"] = "https://www.aspor.com.tr"
    elif "ahaber" in url_lower:
        headers["Referer"] = "https://www.ahaber.com.tr/"
        headers["Origin"] = "https://www.ahaber.com.tr"
    elif "a2tv" in url_lower:
        headers["Referer"] = "https://www.atv.com.tr/"
        headers["Origin"] = "https://www.atv.com.tr"
    elif "minikacocuk" in url_lower or "minikagococuk" in url_lower or "minikagococuk" in url_lower:
        headers["Referer"] = "https://www.minikacocuk.com.tr/"
        headers["Origin"] = "https://www.minikacocuk.com.tr"
    elif "minikago" in url_lower:
        headers["Referer"] = "https://www.minikago.com.tr/"
        headers["Origin"] = "https://www.minikacocuk.com.tr"
    else:
        headers["Referer"] = "https://www.atv.com.tr/"
        headers["Origin"] = "https://www.atv.com.tr"
        
    return headers

# Bellek içi cache ve kanal tanımları
CACHE = {}
CACHE_TTL_DAION = 90       # Daion tokenleri hızlı expire olduğu için 90 saniye
CACHE_TTL_ERCDN = 15 * 60  # ErCDN için 15 dakika

CHANNELS = {
    "ahaberhd": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/ahaberhd/ahaberhd.m3u8"},
    "asporhd": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/asporhd/asporhd.m3u8"},
    "atvhd": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/atvhd/atvhd.m3u8"},
    "atv": {"type": "daion", "url": "https://trkvz.daioncdn.net/atv/atv.m3u8?ce=3&app=d1ce2d40-5256-4550-b02e-e73c185a314e"},
    "aspor": {"type": "daion", "url": "https://trkvz.daioncdn.net/aspor/aspor.m3u8?ce=3&app=45f847c4-04e8-419a-a561-2ebf87084765"},
    "a2tv": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/a2tv/a2tv.m3u8"},
    "minikago": {"type": "ercdn", "url": "https://trkvz-live.ercdn.net/minikago/minikago.m3u8"},
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
    """Daion ve ErCDN için özel token istek yapısı."""
    if channel_key not in CHANNELS:
        return None
    
    ch = CHANNELS[channel_key]
    raw_url = ch["url"]
    
    # ahaberhd ve asporhd ErCDN tarafında tokensizdir
    if ch["type"] == "ercdn" and channel_key in ["ahaberhd", "asporhd"]:
        return raw_url

    rand_num = int(time.time() * 1000) % 1000000
    secure_api = f"https://securevideotoken.tmgrup.com.tr/webtv/secure?{rand_num}"
    target_api_url = f"{secure_api}&url={requests.utils.quote(raw_url)}"

    try:
        headers = get_headers_for_url(raw_url)
        resp = requests.get(target_api_url, headers=headers, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        url_key = next((k for k in data.keys() if k.lower() == 'url'), None)
        if url_key and data[url_key]:
            return data[url_key]
    except Exception as e:
        print(f"[{channel_key}] Token alınamadı: {e}")

    return raw_url

@app.route("/api/<channel_name>")
def api_channel(channel_name):
    now = time.time()
    
    if channel_name not in CHANNELS:
        return f"Kanal bulunamadı: {channel_name}", 404

    ch_type = CHANNELS[channel_name]["type"]
    ttl = CACHE_TTL_DAION if ch_type == "daion" else CACHE_TTL_ERCDN

    if channel_name in CACHE and (now - CACHE[channel_name]["timestamp"] < ttl):
        content = CACHE[channel_name]["content"]
        return Response(content, mimetype="application/vnd.apple.mpegurl")

    resolved_url = fetch_token_for_channel(channel_name)
    if not resolved_url:
        return "Yayın linki çözülemedi", 500

    try:
        headers = get_headers_for_url(resolved_url)
        resp = requests.get(resolved_url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        playlist_content = resp.text
        base_url = re.sub(r"[^/]+$", "", resolved_url)
        host_root = request.host_url.rstrip("/")

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

    matched_channel = None
    for ch_name, ch_info in CHANNELS.items():
        if target_url == ch_info["url"] or ch_info["url"] in target_url or target_url.endswith(f"/{ch_name}.m3u8"):
            matched_channel = ch_name
            resolved = fetch_token_for_channel(ch_name)
            if resolved:
                target_url = resolved
            break

    if not is_allowed_domain(target_url):
        return "Bu domainin proxy'lenmesine izin verilmiyor.", 403

    try:
        headers = get_headers_for_url(target_url)
        req = requests.get(target_url, headers=headers, stream=True, timeout=10)
        
        # 401 veya 403 alınırsa token bayatlamıştır; cache'i temizle ve taze token ile tekrar dene
        if req.status_code in [401, 403] and matched_channel:
            print(f"[{matched_channel}] Yetkilendirme hatası ({req.status_code}), token tazeleniyor...")
            if matched_channel in CACHE:
                del CACHE[matched_channel]
            fresh_resolved = fetch_token_for_channel(matched_channel)
            if fresh_resolved:
                target_url = fresh_resolved
                headers = get_headers_for_url(target_url)
                req = requests.get(target_url, headers=headers, stream=True, timeout=10)

        req.raise_for_status()

        content_type = req.headers.get("Content-Type", "application/octet-stream")

        if "application/vnd.apple.mpegurl" in content_type or "audio/mpegurl" in content_type or target_url.endswith(".m3u8"):
            playlist_content = req.text
            base_url = re.sub(r"[^/]+$", "", target_url)
            host_root = request.host_url.rstrip("/")

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
