#!/usr/bin/env python3
"""metinler/ klasöründeki en yeni metni Seslen ile seslendirir -> cikti/bolum.mp3 + cikti/bolum.json

Metin biçimi: düz Türkçe metin. "## Başlık" satırı yeni konuyu başlatır (okunmaz; launcher'daki
"sonraki konu" düğmesi buraya atlar). Boş satır paragraf arasıdır.
Ortam değişkenleri: SES (varsayılan hasan), USLUP (varsayılan haber).
"""
import glob
import json
import os
import re
import subprocess
import sys
import wave

import numpy as np
from seslen_tts import ORAN, Seslen

SES = os.environ.get("SES", "hasan")
USLUP = os.environ.get("USLUP", "haber")
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def sessizlik(ms):
    return np.zeros(int(ORAN * ms / 1000), np.float32)


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

    s = Seslen()
    parcalar, bolumler, n = [], [], 0
    for ad, govde in konular:
        if parcalar:
            parcalar.append(sessizlik(700))
            n += len(parcalar[-1])
        bolumler.append({"baslik": ad, "saniye": round(n / ORAN)})
        for p in s.seslendir(govde, ses=SES, uslup=USLUP):
            for x in (np.asarray(p.ses, np.float32), sessizlik(p.sessizlik_ms)):
                parcalar.append(x)
                n += len(x)
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
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", "cikti/ham.wav",
         "-af", "highpass=f=70,acompressor=threshold=-18dB:ratio=2.5:attack=8:release=160,loudnorm=I=-16:TP=-1.5:LRA=9",
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
    print(f"tamam: {tarih}, {bilgi['saniye'] // 60} dk {bilgi['saniye'] % 60} sn, ses={SES}")


if __name__ == "__main__":
    main()
