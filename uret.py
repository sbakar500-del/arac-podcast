#!/usr/bin/env python3
"""metinler/ klasöründeki en yeni metni seslendirir -> cikti/bolum.mp3 + cikti/bolum.json

Metin biçimi: düz Türkçe metin. "## Başlık" satırı yeni konuyu başlatır (okunmaz; launcher'daki
"sonraki konu" düğmesi buraya atlar). Boş satır paragraf arasıdır.

Ortam değişkenleri:
  MOTOR  gemini (Google Gemini TTS; GEMINI_API_KEY ister), edge (varsayılan; Microsoft'un Türkçe sesi)
         ya da seslen (çevrimdışı yedek)
  SES    gemini için Algieba, edge için tr-TR-AhmetNeural, seslen için hasan
  HIZ    edge konuşma hızı, örn. -5% (varsayılan)
  USLUP  seslen üslubu (varsayılan haber)
"""
import asyncio
import base64
import glob
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

import numpy as np

MOTOR = os.environ.get("MOTOR", "edge")
SES = os.environ.get("SES") or {"gemini": "Algieba", "edge": "tr-TR-AhmetNeural"}.get(MOTOR, "hasan")
HIZ = os.environ.get("HIZ", "-5%")
USLUP = os.environ.get("USLUP", "haber")
ORAN = 24000
PARAGRAF_ARASI_MS = 550
KONU_ARASI_MS = 1100
# Gemini ücretsiz hakkı (Kasım 2026, AI Studio "Rate Limit" sayfası): dakikada 3, günde 10 istek.
# Bölümü birkaç büyük parçada okutuyoruz ki günlük hak yetsin ve yeniden denemeye pay kalsın.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash-tts")
GEMINI_USLUP = os.environ.get("GEMINI_USLUP", "warm, natural Turkish radio news host, native Istanbul accent, calm and clear pace")
GEMINI_PARCA_HARF = 3000  # ~3,5 dakikalık ses; daha uzun parçada ses kalitesi kayabiliyor
GEMINI_EN_COK_PARCA = 5
GEMINI_EN_COK_ISTEK = 8
GEMINI_ISTEK_ARASI_SN = 22
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def sessizlik(ms):
    return np.zeros(int(ORAN * ms / 1000), np.float32)


def temizle(metin):
    """Sesin takılacağı yazım işaretlerini ayıklar; sözcüklere dokunmaz."""
    metin = re.sub(r"[*_`#>|]+", " ", metin)
    metin = re.sub(r"\s+[–—-]\s+", ", ", metin)  # cümle içi uzun çizgi kısa bir durak olsun
    metin = metin.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", metin).strip()


def kirp(dalga, pay_ms=40):
    """Baştaki ve sondaki sessizliği atar; duraklar bizim eklediğimiz sürelerle belirlensin."""
    dolu = np.flatnonzero(np.abs(dalga) > 0.008)
    if not len(dolu):
        return dalga[:0]
    pay = int(ORAN * pay_ms / 1000)
    return dalga[max(0, dolu[0] - pay): dolu[-1] + pay]


def edge_oku(paragraf):
    """Bir paragrafı Edge sesiyle okur; ağ hatasında birkaç kez yeniden dener."""
    import edge_tts

    os.makedirs("cikti", exist_ok=True)
    gecici = "cikti/parca.mp3"
    son_hata = None
    for deneme in range(5):
        try:
            asyncio.run(edge_tts.Communicate(paragraf, SES, rate=HIZ).save(gecici))
            ham = subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-i", gecici, "-f", "s16le", "-ac", "1", "-ar", str(ORAN), "-"],
                check=True, capture_output=True,
            ).stdout
            dalga = kirp(np.frombuffer(ham, np.int16).astype(np.float32) / 32768)
            # Türkçe konuşma saniyede ~15 harf tutar; çok kısa geldiyse ses yarıda kesilmiştir.
            if len(dalga) / ORAN >= len(paragraf) / 40:
                os.remove(gecici)
                return dalga
            son_hata = f"ses eksik geldi ({len(dalga) / ORAN:.1f} sn, {len(paragraf)} harf)"
        except Exception as hata:  # ağ kesintisi, sunucu reddi, bozuk dosya
            son_hata = f"{type(hata).__name__}: {hata}"
        print(f"  yeniden deneniyor ({deneme + 1}/5): {son_hata}", flush=True)
        time.sleep(4 * (deneme + 1))
    sys.exit(f"Edge sesi alınamadı: {son_hata}")


def seslen_okuyucu():
    from seslen_tts import ORAN as seslen_orani, Seslen

    if seslen_orani != ORAN:
        sys.exit(f"Seslen örnekleme oranı {seslen_orani}, beklenen {ORAN}")
    s = Seslen()

    def oku(paragraf):
        parcalar = []
        for p in s.seslendir(paragraf, ses=SES, uslup=USLUP):
            parcalar += [np.asarray(p.ses, np.float32), sessizlik(p.sessizlik_ms)]
        return kirp(np.concatenate(parcalar)) if parcalar else np.zeros(0, np.float32)

    return oku

_gemini = {"istek": 0, "son": 0.0}


def gemini_iste(metin):
    """Metni Gemini TTS ile okur, 24 kHz float dalga döndürür. Günlük hak bittiyse çıkar (yedek ses devreye girer)."""
    anahtar = os.environ.get("GEMINI_API_KEY", "").strip()
    if not anahtar:
        sys.exit("GEMINI_API_KEY tanımlı değil")
    govde = json.dumps({
        "model": GEMINI_MODEL,
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": SES}]},
        "input": [{"type": "user_input", "content": [{
            "type": "text", "text": metin,
            "annotations": [{"type": "speech_metadata", "style": GEMINI_USLUP}],
        }]}],
    }).encode()
    son_hata = None
    for deneme in range(3):
        if _gemini["istek"] >= GEMINI_EN_COK_ISTEK:
            sys.exit(f"Gemini: istek sınırına gelindi ({GEMINI_EN_COK_ISTEK}); son hata: {son_hata}")
        bekle = GEMINI_ISTEK_ARASI_SN - (time.time() - _gemini["son"])
        if bekle > 0:
            time.sleep(bekle)
        _gemini["istek"] += 1
        _gemini["son"] = time.time()
        istek = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions", data=govde,
            headers={"x-goog-api-key": anahtar, "Content-Type": "application/json", "Api-Revision": "2026-05-20"},
        )
        try:
            with urllib.request.urlopen(istek, timeout=600) as y:
                yanit = json.load(y)
        except urllib.error.HTTPError as h:
            metin_hata = h.read().decode("utf-8", "replace")[:600]
            son_hata = f"HTTP {h.code}: {metin_hata}"
            if h.code == 429 and re.search(r"per.?day", metin_hata, re.I):
                sys.exit(f"Gemini günlük hakkı bitti: {son_hata}")
            if h.code not in (429, 500, 502, 503, 504):
                sys.exit(f"Gemini isteği reddedildi: {son_hata}")
            print(f"  yeniden deneniyor ({deneme + 1}/3): {son_hata}", flush=True)
            time.sleep(40 if h.code == 429 else 15)
            continue
        except Exception as hata:  # ağ kesintisi, zaman aşımı
            son_hata = f"{type(hata).__name__}: {hata}"
            print(f"  yeniden deneniyor ({deneme + 1}/3): {son_hata}", flush=True)
            time.sleep(15)
            continue
        veri = None
        for adim in yanit.get("steps", []):
            for icerik in adim.get("content", []) if isinstance(adim, dict) else []:
                if icerik.get("type") == "audio" and icerik.get("data"):
                    veri = icerik["data"]
        if not veri:
            son_hata = f"yanıtta ses yok (durum: {yanit.get('status')})"
        else:
            ham = base64.b64decode(veri)
            if ham[:4] == b"RIFF":
                with wave.open(io.BytesIO(ham)) as w:
                    if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (ORAN, 1, 2):
                        sys.exit(f"Gemini beklenmeyen ses biçimi: {w.getframerate()} Hz, {w.getnchannels()} kanal")
                    ham = w.readframes(w.getnframes())
            dalga = kirp(np.frombuffer(ham[: len(ham) // 2 * 2], np.int16).astype(np.float32) / 32768)
            # Türkçe konuşma saniyede ~14 harf tutar; çok kısa geldiyse ses yarıda kesilmiştir.
            if len(dalga) / ORAN >= len(metin) / 24:
                return dalga
            son_hata = f"ses eksik geldi ({len(dalga) / ORAN:.0f} sn, {len(metin)} harf)"
        print(f"  yeniden deneniyor ({deneme + 1}/3): {son_hata}", flush=True)
    sys.exit(f"Gemini sesi alınamadı: {son_hata}")


def parcalara_bol(uzunluklar, k):
    """Ardışık konuları k parçaya, en uzun parça en kısa olacak şekilde böler; parça başlangıç sıralarını döndürür."""
    n = len(uzunluklar)
    on = [0]
    for u in uzunluklar:
        on.append(on[-1] + u)
    en_iyi = {(0, 0): (0, [])}
    for j in range(1, k + 1):
        for i in range(j, n + 1):
            aday = None
            for b in range(j - 1, i):
                if (b, j - 1) not in en_iyi:
                    continue
                onceki, baslar = en_iyi[(b, j - 1)]
                deger = max(onceki, on[i] - on[b])
                if aday is None or deger < aday[0]:
                    aday = (deger, baslar + [b])
            if aday:
                en_iyi[(i, j)] = aday
    return en_iyi[(n, k)][1]


def sessiz_araliklar(dalga, en_az_sn=0.3):
    """Dalga içindeki sessiz aralıkları (başlangıç, bitiş) saniye olarak verir."""
    kare = int(ORAN * 0.02)
    adet = len(dalga) // kare
    rms = np.sqrt((dalga[: adet * kare].reshape(adet, kare) ** 2).mean(1))
    sessiz = rms < max(1e-4, np.percentile(rms, 90) * 0.05)
    araliklar, bas = [], None
    for i, s in enumerate(list(sessiz) + [False]):
        if s and bas is None:
            bas = i
        elif not s and bas is not None:
            if (i - bas) * 0.02 >= en_az_sn:
                araliklar.append((bas * 0.02, i * 0.02))
            bas = None
    return araliklar


def gemini_bolum(konular):
    """Bütün bölümü Gemini ile birkaç istekte okur; (dalga, bolumler) döndürür."""
    metinler = []
    for ad, govde in konular:
        paragraflar = [temizle(p).replace("<", " ") for p in re.split(r"\n\s*\n", govde)]
        metinler.append("\n\n".join(p for p in paragraflar if re.search(r"\w", p)))
    uzunluklar = [len(m) for m in metinler]
    k = max(1, min(GEMINI_EN_COK_PARCA, len(konular), math.ceil(sum(uzunluklar) / GEMINI_PARCA_HARF)))
    baslar = parcalara_bol(uzunluklar, k) + [len(konular)]
    print(f"Gemini: {len(konular)} konu, {k} istek, ses={SES}, model={GEMINI_MODEL}", flush=True)

    parcalar, bolumler, n = [], [], 0
    for p in range(k):
        sira = list(range(baslar[p], baslar[p + 1]))
        # Konular arasına uzun durak işareti koyuyoruz; sonra o durağı bulup "sonraki konu" yerini çıkarıyoruz.
        dalga = gemini_iste("\n\n<long pause>\n\n".join(metinler[i] for i in sira))
        etkin = float(np.sqrt((dalga ** 2).mean()))
        dalga = dalga * (0.08 / max(etkin, 1e-6))  # parçalar arası ses düzeyi eşit olsun
        if parcalar:
            parcalar.append(sessizlik(KONU_ARASI_MS))
            n += len(parcalar[-1])
        sure = len(dalga) / ORAN
        araliklar = sessiz_araliklar(dalga)
        toplam, gecen = sum(uzunluklar[i] for i in sira), 0
        for i in sira:
            yer = 0.0
            if gecen:
                beklenen = gecen / toplam * sure
                adaylar = [(b - a - 0.04 * abs((a + b) / 2 - beklenen), a, b) for a, b in araliklar
                           if abs((a + b) / 2 - beklenen) <= max(15.0, 0.1 * sure)]
                if adaylar:
                    _, a, b = max(adaylar)
                    yer = max(0.0, b - 0.12)
                    print(f"  {konular[i][0]}: beklenen {beklenen:.0f} sn, durak {a:.1f}-{b:.1f} sn ({b - a:.1f} sn)", flush=True)
                else:
                    yer = beklenen
                    print(f"  {konular[i][0]}: durak bulunamadı, tahmini yer {beklenen:.0f} sn", flush=True)
            bolumler.append({"baslik": konular[i][0], "saniye": round(n / ORAN + yer)})
            gecen += uzunluklar[i]
        parcalar.append(dalga)
        n += len(dalga)
        print(f"parça {p + 1}/{k}: {sure:.0f} sn, toplam {round(n / ORAN)} sn", flush=True)
    return np.concatenate(parcalar), bolumler


def parca_parca_oku(konular):
    """Edge ya da Seslen ile paragraf paragraf okur; (dalga, bolumler) döndürür."""
    if MOTOR == "gemini":
        return gemini_bolum(konular)
    oku = edge_oku if MOTOR == "edge" else seslen_okuyucu()
    parcalar, bolumler, n = [], [], 0

    def ekle(x):
        nonlocal n
        parcalar.append(x)
        n += len(x)

    for ad, govde in konular:
        if parcalar:
            ekle(sessizlik(KONU_ARASI_MS))
        bolumler.append({"baslik": ad, "saniye": round(n / ORAN)})
        ilk = True
        for paragraf in re.split(r"\n\s*\n", govde):
            paragraf = temizle(paragraf)
            if not re.search(r"\w", paragraf):
                continue
            if not ilk:
                ekle(sessizlik(PARAGRAF_ARASI_MS))
            ekle(oku(paragraf))
            ilk = False
        print(f"{ad}: {round(n / ORAN)} sn", flush=True)
    return np.concatenate(parcalar), bolumler


def main():
    dosyalar = sorted(f for f in glob.glob("metinler/*.txt") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.txt", os.path.basename(f)))
    if not dosyalar:
        sys.exit("metinler/ klasöründe YYYY-AA-GG.txt adlı metin yok")
    yol = dosyalar[-1]
    tarih = os.path.basename(yol)[:-4]
    metin = open(yol, encoding="utf-8").read()

    # "## Başlık" satırlarından konulara böl.
    konular, ad, govde = [], "Açılış", []
    for satir in metin.splitlines():
        if satir.startswith("##"):
            if "".join(govde).strip():
                konular.append((ad, "\n".join(govde)))
            ad, govde = satir.lstrip("# ").strip(), []
        else:
            govde.append(satir)
    if "".join(govde).strip():
        konular.append((ad, "\n".join(govde)))

    dalga, bolumler = parca_parca_oku(konular)
    if len(dalga) < ORAN * 60:
        sys.exit("üretilen ses bir dakikadan kısa; bir şey ters gitti")
    pcm = (np.clip(dalga / max(1e-6, float(np.abs(dalga).max())) * 0.9, -1, 1) * 32767).astype(np.int16)
    os.makedirs("cikti", exist_ok=True)
    with wave.open("cikti/ham.wav", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(ORAN)
        w.writeframes(pcm.tobytes())
    # Araba hoparlörü için: hafif sıkıştırma, ses düzeyi eşitleme, 44.1 kHz mono 64 kbps MP3.
    # Edge'in Ahmet sesi baslı ve boğuk geliyor; basları kısıp konuşma netliğini (3 kHz) ve tizleri açıyoruz.
    netlik = "equalizer=f=220:t=q:w=0.9:g=-5,equalizer=f=3200:t=q:w=0.8:g=5,highshelf=f=6000:g=4," if MOTOR == "edge" else ""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", "cikti/ham.wav",
         "-af", f"highpass=f={95 if netlik else 70},acompressor=threshold=-18dB:ratio=2.5:attack=8:release=160,{netlik}loudnorm=I=-16:TP=-1.5:LRA=9",
         "-ar", "44100", "-ac", "1", "-b:a", "64k", "cikti/bolum.mp3"],
        check=True,
    )
    os.remove("cikti/ham.wav")
    y, a, g = (int(x) for x in tarih.split("-"))
    bilgi = {
        "tarih": tarih,
        "baslik": f"{g} {AYLAR[a - 1]} {y}",
        "saniye": round(len(dalga) / ORAN),
        "ses": "bolum.mp3",
        "bolumler": bolumler,
    }
    json.dump(bilgi, open("cikti/bolum.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"tamam: {tarih}, {bilgi['saniye'] // 60} dk {bilgi['saniye'] % 60} sn, motor={MOTOR}, ses={SES}")


if __name__ == "__main__":
    main()
