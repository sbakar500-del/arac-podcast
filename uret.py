#!/usr/bin/env python3
"""metinler/ klasöründeki en yeni metni seslendirir -> cikti/bolum.mp3 + cikti/bolum.json

Metin biçimi: düz Türkçe metin. "## Başlık" satırı yeni konuyu başlatır (okunmaz; launcher'daki
"sonraki konu" düğmesi buraya atlar). Boş satır paragraf arasıdır.

Ortam değişkenleri:
  MOTOR  edge (varsayılan; Microsoft'un ana dili Türkçe olan sinir ağı sesi) ya da seslen (yedek, çevrimdışı)
  SES    edge için tr-TR-AhmetNeural (varsayılan), seslen için hasan
  HIZ    edge konuşma hızı, örn. -5% (varsayılan)
  USLUP  seslen üslubu (varsayılan haber)
"""
import asyncio
import glob
import json
import os
import re
import subprocess
import sys
import time
import wave

import numpy as np

MOTOR = os.environ.get("MOTOR", "edge")
SES = os.environ.get("SES") or ("tr-TR-AhmetNeural" if MOTOR == "edge" else "hasan")
HIZ = os.environ.get("HIZ", "-5%")
USLUP = os.environ.get("USLUP", "haber")
ORAN = 24000
PARAGRAF_ARASI_MS = 550
KONU_ARASI_MS = 1100
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

    dalga = np.concatenate(parcalar)
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
    # Ahmet sesi baslı ve boğuk geliyor; basları kısıp konuşma netliğini (3 kHz) ve tizleri açıyoruz.
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
