"""Aynı kısa metni açık kaynak XTTS v2 modeliyle (işlemcide) okur -> ornekler/xtts-*.wav"""
import os, re, time
os.environ["COQUI_TOS_AGREED"] = "1"
from TTS.api import TTS

metin = re.sub(r"\s*\n\s*\n\s*", " ", open("deneme/ornek.txt", encoding="utf-8").read()).strip()
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
print("konuşmacılar:", tts.speakers)
os.makedirs("ornekler", exist_ok=True)
for kisi in ["Damien Black", "Aaron Dreschner", "Viktor Eka"]:
    if kisi not in (tts.speakers or []):
        print("yok:", kisi); continue
    t = time.time()
    tts.tts_to_file(text=metin, speaker=kisi, language="tr", file_path=f"ornekler/xtts-{kisi.replace(' ', '-')}.wav")
    print(f"tamam: {kisi}, {time.time() - t:.0f} sn sürdü", flush=True)
