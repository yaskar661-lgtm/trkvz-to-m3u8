import re
import time
import threading
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template_string, redirect

app = Flask(__name__)

CHANNELS = {
    "atvavrupa": "https://www.atvavrupa.tv/canli-yayin",
    "ahaberhd": "https://www.ahaber.com.tr/canli-yayin",
    "anewshd": "https://www.anews.com.tr/canli-yayin",
    "aparahd": "https://www.apara.com.tr/canli-yayin",
    "asporhd": "https://www.aspor.com.tr/canli-yayin",
    "atv": "https://www.atv.com.tr/canli-yayin",
    "minikagococuk": "https://www.minikacocuk.com.tr/canli-yayin",
    "minikago": "https://www.minikago.com.tr/canli-yayin",
    "vavtv": "https://www.vavtv.com.tr/canli-yayin",
    "a2tv": "https://www.a2tv.com.tr/canli-yayin",
}

_MAPPING_WEBSITEID_HLSURL = {
    "9BBE055A-4CF6-4BC3-A675-D40E89B55B91": "https://trkvz.daioncdn.net/aspor/aspor.m3u8?ce=3&app=45f847c4-04e8-419a-a561-2ebf87084765",
    "0C1BC8FF-C3B1-45BE-A95B-F7BB9C8B03ED": "https://trkvz.daioncdn.net/a2tv/a2tv.m3u8?ce=3&app=59363a60-be96-4f73-9eff-355d0ff2c758",
    "AAE2E325-4EAE-45B7-B017-26FD7DDB6CE4": "https://trkvz.daioncdn.net/minikago/minikago.m3u8?app=web&ce=3",
    "01ED59F2-4067-4945-8204-45F6C6DB4045": "https://trkvz.daioncdn.net/minikago_cocuk/minikago_cocuk.m3u8?app=web&ce=3",
    "45d4cd69-814c-4e2e-bdad-11de9e4b9afd": "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa.m3u8",
}

_VIDEOID_LIVE = "00000000-0000-0000-0000-000000000000"

stream_cache = {}
cache_lock = threading.Lock()

def get_turkuvaz_stream(url, channel_slug):
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

    if not hls_url:
        hls_url = f"https://trkvz-live.ercdn.net/{channel_slug}/{channel_slug}.m3u8"

    secure_api = "https://securevideotoken.tmgrup.com.tr/webtv/secure"
    try:
        secure_res = requests.get(secure_api, params={"url": hls_url}, headers={"Referer": url}, timeout=10).json()
        if secure_res.get("Success"):
            return secure_res["Url"]
    except Exception as e:
        print(f"[-] Secure token isteği başarısız ({channel_slug}): {e}")
        
    return None

def update_channel_stream(channel_name):
    target_url = CHANNELS.get(channel_name)
    if not target_url:
        return None
    
    final_m3u8 = get_turkuvaz_stream(target_url, channel_name)
    if not final_m3u8:
        return None

    # Yönlendirme mantığında içeriği proxy etmeye gerek kalmadığı için
    # doğrudan m3u8_url'i cache'e kaydediyoruz.
    with cache_lock:
        stream_cache[channel_name] = {
            "m3u8_url": final_m3u8,
            "timestamp": time.time()
        }
    return final_m3u8

def background_updater():
    while True:
        time.sleep(3600)  # 1 saat
        print("[*] Arka plan zamanlayıcısı tetiklendi: Tüm kanallar güncelleniyor...")
        for ch in CHANNELS:
            try:
                update_channel_stream(ch)
            except Exception:
                pass

threading.Thread(target=background_updater, daemon=True).start()

@app.route('/')
def index():
    html = """
    <h2>Turkuvaz IPTV Proxy (Redirect Destekli)</h2>
    <ul>
    {% for ch in channels %}
        <li><a href="/stream/{{ ch }}">{{ ch.upper() }} M3U8 Linki</a> (<code>/stream/{{ ch }}</code>)</li>
    {% endfor %}
    </ul>
    <p><a href="/refresh">🔄 Kanalları Şimdi Yenile (Restart Olmadan)</a></p>
    """
    return render_template_string(html, channels=CHANNELS.keys())

@app.route('/stream/<channel_name>')
def stream_route(channel_name):
    if channel_name not in CHANNELS:
        return "Kanal bulunamadı", 404
    
    with cache_lock:
        cached = stream_cache.get(channel_name)
        is_expired = not cached or (time.time() - cached["timestamp"] > 3600)

    if is_expired:
        m3u8_url = update_channel_stream(channel_name)
        if not m3u8_url and cached:
            m3u8_url = cached["m3u8_url"]  # Güncelleme başarısızsa eski taze linki kullan
        elif not m3u8_url:
            return "Yayın linki alınamadı", 500
    else:
        m3u8_url = cached["m3u8_url"]

    # İçeriği döndürmek yerine doğrudan taze secure m3u8 adresine yönlendir (HTTP 302)
    return redirect(m3u8_url)

@app.route('/refresh')
def refresh_streams():
    success_list = []
    fail_list = []
    for ch in CHANNELS:
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
