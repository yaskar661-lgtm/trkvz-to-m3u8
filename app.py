import random
import re
import threading
import time
import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template_string, request, has_request_context
from urllib.parse import urlparse

app = Flask(__name__)

ALLOWED_DOMAINS = [
    "securevideotoken.tmgrup.com.tr",
    "trkvz-live.ercdn.net",
    "trkvz.daioncdn.net",
    "trkvz-live.daioncdn.net",
    "videojs.tmgrup.com.tr",
    "atv.com.tr",
    "aspor.com.tr"
]

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

# --- KANAL LİSTELERİ ---
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
    "vavtv": "https://trkvz-live.ercdn.net/vavtv/vavtv.m3u8",
    "atvhd": "https://trkvz-live.ercdn.net/atvhd/atvhd.m3u8"
}

WEB_CHANNELS = {
    "atv": "https://www.atv.com.tr/canli-yayin",
    "asporhd": "https://trkvz-live.ercdn.net/asporhd/asporhd.m3u8",
}

ALL_CHANNELS = {**DIRECT_CHANNELS, **WEB_CHANNELS}

stream_cache = {}
cache_lock = threading.Lock()

def get_direct_stream(raw_url, channel_name):
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
            response = requests.get(secure_api, params={"url": raw_url}, headers=headers, timeout=10).json()
        else:
            secure_api = "https://securevideotoken.tmgrup.com.tr/webtv/secure"
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
    
    # Özel atvdai yönetimi: Doğrudan HTML içindeki JS mantığıyla token'ı çözebiliriz
    if channel_name == "atvdai":
        raw_url = DIRECT_CHANNELS["atvdai"]
        final_m3u8 = get_direct_stream(raw_url, channel_name)
    elif channel_name in DIRECT_CHANNELS:
        raw_url = DIRECT_CHANNELS[channel_name]
        final_m3u8 = get_direct_stream(raw_url, channel_name)
    elif channel_name in WEB_CHANNELS:
        # Web channels için basitleştirilmiş fallback
        final_m3u8 = f"https://trkvz-live.ercdn.net/{channel_name}/{channel_name}.m3u8"
        
    if not final_m3u8:
        return None

    try:
        m3u8_res = requests.get(final_m3u8, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if m3u8_res.status_code == 200:
            raw_content = m3u8_res.text
            base_url = re.sub(r'/[^/]+\.m3u8.*$', '/', final_m3u8)
            host_root = request.host_url.rstrip("/") if has_request_context() else "http://127.0.0.1:5000"
            
            updated_lines = []
            for line in raw_content.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    if line.startswith('http://') or line.startswith('https://'):
                        seg_url = line
                    elif line.startswith('/'):
                        parsed_base = urlparse(final_m3u8)
                        seg_url = f"{parsed_base.scheme}://{parsed_base.netloc}{line}"
                    else:
                        seg_url = base_url + line
                    
                    line = f"{host_root}/proxy?url={requests.utils.quote(seg_url, safe=':/')}"
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

# --- FLASK ROUTE'LARI ---

@app.route('/daion/index.html')
def daion_player_page():
    # İstediğin HTML kodu, Daion m3u8 linkini ekranda gösterecek şekilde güncellendi
    html_template = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <title>Turkuvaz Çoklu Kanal HLS Oynatıcı (ErCDN & Daion Destekli)</title>
  <style>
    body { font-family: sans-serif; background: #111; color: #fff; padding: 20px; }
    select, button { padding: 10px; font-size: 16px; margin-bottom: 15px; border-radius: 5px; background: #222; color: #fff; border: 1px solid #444; }
    button { cursor: pointer; }
    button:hover { background: #333; }
    video { width: 100%; max-width: 900px; background: #000; border-radius: 8px; }
    .container { max-width: 900px; margin: 0 auto; }
    #status { font-size: 14px; color: #aaa; margin-bottom: 10px; }
    #linkBox { font-size: 12px; color: #0ff; word-break: break-all; background: #222; padding: 8px; border-radius: 4px; margin-top: 10px; }
  </style>
</head>
<body>
  <div class="container">
    <h2>Turkuvaz Çoklu Kanal Canlı Yayın Oynatıcı</h2>
    <div id="status">Durum: Başlatılıyor...</div>
    <div id="linkBox">Aktif M3U8 Linki: Bekleniyor...</div><br>
    
    <label for="channelSelect">Kanal Seçin:</label><br>
    <select id="channelSelect" onchange="changeChannel()">
      <option value="atvdai">ATV (Daion)</option>
      <option value="aspordai">A Spor (Daion)</option>
      <option value="a2tvdai">A2 TV (Daion)</option>
      <option value="minikagodai">Minika GO (Daion)</option>
      <option value="minikagococukdai">Minika Çocuk (Daion)</option>
      <option value="a2tv">A2 TV (ErCDN)</option>
      <option value="minikago">Minika GO (ErCDN)</option>
      <option value="minikagococuk">Minika Çocuk (ErCDN)</option>
      <option value="atvavrupa">ATV Avrupa (ErCDN)</option>
      <option value="ahaberhd">A Haber HD (ErCDN)</option>
      <option value="anewshd">A News HD (ErCDN)</option>
      <option value="aparahd">A Para HD (ErCDN)</option>
      <option value="vavtv">Vav TV (ErCDN)</option>
    </select>
    <button onclick="forceRefreshCurrentChannel()">Seçili Kanalı Yenile</button>
    <br>

    <video id="video" controls autoplay playsinline></video>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  
  <script>
    const channels = {
      "atvdai": "https://trkvz.daioncdn.net/atv/atv.m3u8?ce=3&app=d1ce2d40-5256-4550-b02e-e73c185a314e",
      "aspordai": "https://trkvz.daioncdn.net/aspor/aspor.m3u8?ce=3&app=45f847c4-04e8-419a-a561-2ebf87084765",
      "a2tvdai": "https://trkvz.daioncdn.net/a2tv/a2tv.m3u8?ce=3&app=59363a60-be96-4f73-9eff-355d0ff2c758",
      "minikagodai": "https://trkvz.daioncdn.net/minikago/minikago.m3u8?app=web&ce=3",
      "minikagococukdai": "https://trkvz.daioncdn.net/minikago_cocuk/minikago_cocuk.m3u8?app=web&ce=3",
      "a2tv": "https://trkvz-live.ercdn.net/a2tv/a2tv.m3u8",
      "minikago": "https://trkvz-live.ercdn.net/minikago/minikago.m3u8",
      "minikagococuk": "https://trkvz-live.ercdn.net/minikagococuk/minikagococuk.m3u8",
      "atvavrupa": "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa.m3u8",
      "ahaberhd": "https://trkvz-live.ercdn.net/ahaberhd/ahaberhd.m3u8",
      "anewshd": "https://trkvz-live.ercdn.net/anewshd/anewshd.m3u8",
      "aparahd": "https://trkvz-live.ercdn.net/aparahd/aparahd.m3u8",
      "vavtv": "https://trkvz-live.ercdn.net/vavtv/vavtv.m3u8"
    };

    const video = document.getElementById('video');
    const channelSelect = document.getElementById('channelSelect');
    const statusDiv = document.getElementById('status');
    const linkBox = document.getElementById('linkBox');
    
    let hls = null;
    const streamCache = {};
    const CACHE_DURATION = 15 * 60 * 1000; 

    async function fetchSecureStreamUrl(rawUrl, channelName) {
      if (rawUrl.includes("ercdn.net")) {
        return rawUrl;
      }
      const isDaion = rawUrl.toLowerCase().includes("daioncdn") || rawUrl.includes("app=");
      const randNum = Math.floor(Math.random() * 1000000);
      const secureApi = `https://securevideotoken.tmgrup.com.tr/webtv/secure?${randNum}`;
      const targetUrl = `${secureApi}&url=${encodeURIComponent(rawUrl)}`;

      try {
        const response = await fetch(targetUrl, {
          method: 'GET',
          headers: { "Referer": "https://www.atv.com.tr/" }
        });
        const responseData = await response.json();
        const urlKey = Object.keys(responseData).find(k => k.toLowerCase() === 'url');
        if (urlKey && responseData[urlKey]) {
          return responseData[urlKey];
        }
      } catch (err) {
        console.warn(`[${channelName}] Doğrudan token alınamadı, ham linke düşülüyor.`);
      }
      return rawUrl; 
    }

    async function getCachedOrFreshStreamUrl(channelName, forceRefresh = false) {
      const now = Date.now();
      const cached = streamCache[channelName];

      if (!forceRefresh && cached && (now - cached.timestamp < CACHE_DURATION)) {
        return cached.url;
      }

      statusDiv.innerText = `Durum: [${channelName}] hazırlanıyor...`;
      const rawUrl = channels[channelName];
      const freshUrl = await fetchSecureStreamUrl(rawUrl, channelName);

      streamCache[channelName] = {
        url: freshUrl,
        timestamp: now
      };

      return freshUrl;
    }

    async function loadPlayer() {
      const selectedKey = channelSelect.value;
      if (!channels[selectedKey]) return;

      statusDiv.innerText = `Durum: [${selectedKey}] yükleniyor...`;
      const finalVideoSrc = await getCachedOrFreshStreamUrl(selectedKey, false);

      linkBox.innerText = "Aktif M3U8 Linki: " + finalVideoSrc;

      if (Hls.isSupported()) {
        if (hls) {
          hls.destroy();
        }
        
        hls = new Hls();
        hls.loadSource(finalVideoSrc);
        hls.attachMedia(video);
        statusDiv.innerText = `Durum: [${selectedKey}] Oynatılıyor.`;

        hls.on(Hls.Events.ERROR, async function (event, data) {
          if (data.fatal) {
            switch (data.fatal) {
              case Hls.ErrorTypes.NETWORK_ERROR:
                statusDiv.innerText = `Durum: Ağ hatası, yenileniyor...`;
                await forceRefreshCurrentChannel();
                break;
              case Hls.ErrorTypes.MEDIA_ERROR:
                hls.recoverMediaError();
                break;
              default:
                hls.destroy();
                loadPlayer();
                break;
            }
          }
        });
      } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = finalVideoSrc;
      }
    }

    async function forceRefreshCurrentChannel() {
      const selectedKey = channelSelect.value;
      statusDiv.innerText = `Durum: [${selectedKey}] önbelleği temizleniyor...`;
      await getCachedOrFreshStreamUrl(selectedKey, true);
      loadPlayer();
    }

    function changeChannel() {
      loadPlayer();
    }

    window.onload = async () => {
      loadPlayer();
    };
  </script>
</body>
</html>
    """
    return render_template_string(html_template)

@app.route('/stream/<channel_name>')
def stream_route(channel_name):
    if channel_name == "atvdai":
        try:
            # /daion/index.html sayfasını dahili olarak istek atıp çekiyoruz
            host_root = request.host_url.rstrip("/")
            page_res = requests.get(f"{host_root}/daion/index.html", timeout=5)
            if page_res.status_code == 200:
                # HTML içinden veya JS çalışması sonucu üretilecek Daion linkini regex ile yakalama mantığı
                # Alternatif olarak doğrudan backend'de atvdai token'ını üretebiliriz:
                resolved_url = get_direct_stream(DIRECT_CHANNELS["atvdai"], "atvdai")
                if resolved_url:
                    # Bu linkin içeriğini çekip proxy üzerinden rewrite edelim
                    m3u8_res = requests.get(resolved_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    if m3u8_res.status_code == 200:
                        raw_content = m3u8_res.text
                        base_url = re.sub(r'/[^/]+\.m3u8.*$', '/', resolved_url)
                        
                        updated_lines = []
                        for line in raw_content.splitlines():
                            line = line.strip()
                            if line and not line.startswith('#'):
                                if line.startswith('http://') or line.startswith('https://'):
                                    seg_url = line
                                elif line.startswith('/'):
                                    parsed_base = urlparse(resolved_url)
                                    seg_url = f"{parsed_base.scheme}://{parsed_base.netloc}{line}"
                                else:
                                    seg_url = base_url + line
                                
                                line = f"{host_root}/proxy?url={requests.utils.quote(seg_url, safe=':/')}"
                            updated_lines.append(line)
                        return Response("\n".join(updated_lines), mimetype='application/vnd.apple.mpegurl')
        except Exception as e:
            print(f"[-] atvdai stream route hatası: {e}")

    # Diğer daion ve ercdn kanalları kendi token yöntemiyle devam eder
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

@app.route('/proxy')
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

    if not is_allowed_domain(target_url):
        return "Bu domainin proxy'lenmesine izin verilmiyor.", 403

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.atv.com.tr/"
        }
        req = requests.get(target_url, headers=headers, stream=True, timeout=10)
        req.raise_for_status()

        content_type = req.headers.get("Content-Type", "application/octet-stream")

        if "application/vnd.apple.mpegurl" in content_type or "audio/mpegurl" in content_type or target_url.endswith(".m3u8"):
            playlist_content = req.text
            base_url = re.sub(r'/[^/]+\.m3u8.*$', '/', target_url)
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

            return Response("\n".join(new_lines), mimetype="application/vnd.apple.mpegurl")

        return Response(
            req.iter_content(chunk_size=8192),
            status=req.status_code,
            mimetype=content_type,
        )
    except Exception as e:
        return f"Medya aktarım hatası: {str(e)}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
