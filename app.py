import random
import re
import threading
import time
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template_string

app = Flask(__name__)

# --- 1. DOĞRUDAN M3U8 LİNKLERİ (ErCDN veya DaionCDN) ---
DIRECT_CHANNELS = {
    "atvdai": "https://trkvz.daioncdn.net/atv/atv.m3u8?ce=3&app=d1ce2d40-5256-4550-b02e-e73c185a314e",
    "aspordai": "https://trkvz.daioncdn.net/aspor/aspor.m3u8?ce=3&app=45f847c4-04e8-419a-a561-2ebf87084765",
    "a2tv": "https://trkvz-live.ercdn.net/a2tv/a2tv.m3u8",
    "a2tvdai": "https://trkvz.daioncdn.net/a2tv/a2tv.m3u8?ce=3&app=59363a60-be96-4f73-9eff-355d0ff2c758",
    "minikago": "https://trkvz-live.ercdn.net/minikago/minikago.m3u8",
    "minikagodai": "https://trkvz.daioncdn.net/minikago/minikago.m3u8?app=web&ce=3",
    "minikagococuk": "https://trkvz-live.ercdn.net/minikagococuk/minikagococuk.m3u8",
    "minikagococukdai": "https://trkvz.daioncdn.net/minikago_cocuk/minikago_cocuk.m3u8?app=web&ce=3",
    "atvavrupa": "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa.m3u8",
    "ahaberhd": "https://trkvz-live.ercdn.net/ahaberhd/ahaberhd.m3u8",
    "anewshd": "https://trkvz-live.ercdn.net/anewshd/anewshd.m3u8",
    "aparahd": "https://trkvz-live.ercdn.net/aparahd/aparahd.m3u8",
    "vavtv": "https://trkvz-live.ercdn.net/vavtv/vavtv.m3u8"
}

# --- 2. WEB SAYFASINDAN DİNAMİK ÇEKİLECEK KANALLAR (WEB_CHANNELS) ---
WEB_CHANNELS = {
    "atv": "https://www.atv.com.tr/canli-yayin",
    "asporhd": "https://trkvz-live.ercdn.net/asporhd/asporhd.m3u8",
}

# Tüm kanal listesini arayüz için birleştiriyoruz
ALL_CHANNELS = {**DIRECT_CHANNELS, **WEB_CHANNELS}

# Streamlink statik mapping mantığının birebir uyarlaması
_MAPPING_WEBSITEID_HLSURL = {
    "9BBE055A-4CF6-4BC3-A675-D40E89B55B91": "https://trkvz.daioncdn.net/aspor/aspor.m3u8?ce=3&app=45f847c4-04e8-419a-a561-2ebf87084765",
    "0C1BC8FF-C3B1-45BE-A95B-F7BB9C8B03ED": "https://trkvz.daioncdn.net/a2tv/a2tv.m3u8?ce=3&app=59363a60-be96-4f73-9eff-355d0ff2c758",
    "AAE2E325-4EAE-45B7-B017-26FD7DDB6CE4": "https://trkvz.daioncdn.net/minikago/minikago.m3u8?app=web&ce=3",
    "01ED59F2-4067-4945-8204-45F6C6DB4045": "https://trkvz.daioncdn.net/minikago_cocuk/minikago_cocuk.m3u8?app=web&ce=3",
    "45D4CD69-814C-4E2E-BDAD-11DE9E4B9AFD": "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa.m3u8",
}

_VIDEOID_LIVE = "00000000-0000-0000-0000-000000000000"

# Bellek içi cache ve thread kilidi
stream_cache = {}
cache_lock = threading.Lock()

def get_turkuvaz_stream_onweb(url, channel_slug):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    hls_url = None
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            player_div = soup.find(attrs={"data-videoid": True, "data-websiteid": True})
            
            video_id, website_id = None, None
            if player_div:
                video_id = player_div.get("data-videoid")
                website_id = player_div.get("data-websiteid")
            else:
                script_match = re.search(r'var\s+tmdPlayer\s*=\s*(["\'])(.*?)\1', response.text)
                if script_match:
                    inner_soup = BeautifulSoup(script_match.group(2), 'html.parser')
                    inner_div = inner_soup.find(attrs={"data-videoid": True, "data-websiteid": True})
                    if inner_div:
                        video_id = inner_div.get("data-videoid")
                        website_id = inner_div.get("data-websiteid")

            if video_id and website_id:
                api_url = f"https://videojs.tmgrup.com.tr/getvideo/{website_id}/{video_id}"
                api_res = requests.get(api_url, headers=headers, timeout=10).json()
                if api_res.get("success"):
                    hls_url = api_res["video"]["VideoSmilUrl"]
                    if video_id == _VIDEOID_LIVE and website_id.upper() in _MAPPING_WEBSITEID_HLSURL:
                        hls_url = _MAPPING_WEBSITEID_HLSURL[website_id.upper()]
    except Exception:
        pass

    # VideoJS üzerinden hls_url alınamadıysa channel slug ile ercdn m3u8 yapısına düşülür
    clean_slug = channel_slug.replace("_web", "")
    if not hls_url:
        hls_url = f"https://trkvz-live.ercdn.net/{clean_slug}/{clean_slug}.m3u8"
        print(f"[*] [{channel_slug}] VideoJS'den HLS alınamadı, slug tabanlı fallback kullanılıyor: {hls_url}")

    # --- AKILLI CDN & SECURE TOKEN (ErCDN veya DaionCDN Ayrımı) ---
    is_daion = "daioncdn" in hls_url.lower() or "app=" in hls_url
    
    try:
        if is_daion:
            # DaionCDN için JS mantığı (Rastgele sayı + X-isApp + X-Rand)
            rand_num = random.randint(1, 1000000)
            timestamp = str(int(time.time() * 1000))
            
            secure_api = f"https://securevideotoken.tmgrup.com.tr/webtv/secure?{rand_num}"
            secure_headers = {
                "X-isApp": "false",
                "X-Rand": timestamp,
                "Referer": url,
                "User-Agent": headers["User-Agent"],
                "Origin": "https://" + requests.utils.urlparse(url).netloc
            }
            print(f"[*] [{channel_slug}] DaionCDN secure token isteniyor...")
            secure_res = requests.get(secure_api, params={"url": hls_url}, headers=secure_headers, timeout=10).json()
        else:
            # ErCDN için standart secure token mantığı
            secure_api = "https://securevideotoken.tmgrup.com.tr/webtv/secure"
            print(f"[*] [{channel_slug}] ErCDN secure token isteniyor...")
            secure_res = requests.get(secure_api, params={"url": hls_url}, headers={"Referer": url}, timeout=10).json()
            
        # Yanıt kontrolü (Büyük/küçük harf duyarsız)
        success_key = next((k for k in secure_res if k.lower() == 'success'), None)
        url_key = next((k for k in secure_res if k.lower() == 'url'), None)
        
        if success_key and secure_res[success_key] and url_key:
            return secure_res[url_key]
        elif url_key and secure_res[url_key]:
            return secure_res[url_key]
            
    except Exception as e:
        print(f"[-] Secure token isteği başarısız ({channel_slug}): {e}")
        
    return hls_url

def get_direct_stream(raw_url, channel_name):
    """Doğrudan m3u8 linkleri için secure token yöneticisi"""
    is_daion = "daioncdn" in raw_url.lower() or "app=" in raw_url
    
    try:
        if is_daion:
            rand_num = random.randint(1, 1000000)
            timestamp = str(int(time.time() * 1000))
            secure_api = f"https://securevideotoken.tmgrup.com.tr/webtv/secure?{rand_num}"
            headers = {
                "X-isApp": "false",
                "X-Rand": timestamp,
                "Referer": "https://www.atv.com.tr/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Origin": "https://www.atv.com.tr"
            }
            print(f"[*] [{channel_name}] Doğrudan DaionCDN token isteniyor...")
            response = requests.get(secure_api, params={"url": raw_url}, headers=headers, timeout=10).json()
        else:
            secure_api = "https://securevideotoken.tmgrup.com.tr/webtv/secure"
            print(f"[*] [{channel_name}] Doğrudan ErCDN token isteniyor...")
            response = requests.get(secure_api, params={"url": raw_url}, headers={"Referer": "https://www.atv.com.tr/"}, timeout=10).json()
            
        success_key = next((k for k in response if k.lower() == 'success'), None)
        url_key = next((k for k in response if k.lower() == 'url'), None)
        
        if success_key and response[success_key] and url_key:
            return response[url_key]
        elif url_key and response[url_key]:
            return response[url_key]
    except Exception as e:
        print(f"[-] Doğrudan secure token isteği başarısız ({channel_name}): {e}")
        
    return raw_url

def update_channel_stream(channel_name):
    final_m3u8 = None
    
    if channel_name in DIRECT_CHANNELS:
        raw_url = DIRECT_CHANNELS[channel_name]
        final_m3u8 = get_direct_stream(raw_url, channel_name)
    elif channel_name in WEB_CHANNELS:
        web_url = WEB_CHANNELS[channel_name]
        final_m3u8 = get_turkuvaz_stream_onweb(web_url, channel_name)
        
    if not final_m3u8:
        return None

    try:
        m3u8_res = requests.get(final_m3u8, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if m3u8_res.status_code == 200:
            raw_content = m3u8_res.text
            base_url = re.sub(r'/[^/]+\.m3u8.*$', '/', final_m3u8)
            
            updated_lines = []
            for line in raw_content.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    if not line.startswith('http://') and not line.startswith('https://'):
                        line = base_url + line
                updated_lines.append(line)
            
            final_content = "\n".join(updated_lines)
            
            with cache_lock:
                stream_cache[channel_name] = {
                    "m3u8_url": final_m3u8,
                    "content": final_content,
                    "timestamp": time.time()
                }
            return final_content
    except Exception as e:
        print(f"[-] M3U8 içerik çekme hatası ({channel_name}): {e}")
    return None

# --- ARKA PLAN GÜNCELLEME (1 Saatte Bir) ---
def background_updater():
    while True:
        time.sleep(3600)
        print("[*] Arka plan zamanlayıcısı tetiklendi: Tüm kanallar güncelleniyor...")
        for ch in ALL_CHANNELS:
            try:
                update_channel_stream(ch)
            except Exception:
                pass

threading.Thread(target=background_updater, daemon=True).start()

# --- FLASK ROUTE'LARI ---

@app.route('/')
def index():
    html = """
    <h2>Turkuvaz IPTV Proxy (Hibrit: Direct + Web Scrape Destekli)</h2>
    <ul>
    {% for ch in channels %}
        <li><a href="/stream/{{ ch }}">{{ ch.upper() }} M3U8 Linki</a> (<code>/stream/{{ ch }}</code>)</li>
    {% endfor %}
    </ul>
    <p><a href="/refresh">🔄 Kanalları Şimdi Yenile (Restart Olmadan)</a></p>
    """
    return render_template_string(html, channels=ALL_CHANNELS.keys())

@app.route('/stream/<channel_name>')
def stream_route(channel_name):
    if channel_name not in ALL_CHANNELS:
        return "Kanal bulunamadı", 404
    
    with cache_lock:
        cached = stream_cache.get(channel_name)
        is_expired = not cached or (time.time() - cached["timestamp"] > 3600)

    if is_expired:
        content = update_channel_stream(channel_name)
        if not content and cached:
            content = cached["content"]
        elif not content:
            return "Yayın linki alınamadı", 500
    else:
        content = cached["content"]

    return Response(content, mimetype='application/vnd.apple.mpegurl')

@app.route('/refresh')
def refresh_streams():
    success_list = []
    fail_list = []
    for ch in ALL_CHANNELS:
        res = update_channel_stream(ch)
        if res:
            success_list.append(ch)
        else:
            fail_list.append(ch)
            
    return jsonify({
        "status": "success",
        "refreshed": success_list,
        "failed": fail_list,
        "timestamp": time.time()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
