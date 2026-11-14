"""Aynı kısa metni birkaç Edge sesiyle okur -> ornekler/*.mp3 (ham, işlenmemiş)."""
import asyncio, os
import edge_tts

ISTENEN = ["en-US-AndrewMultilingualNeural", "en-US-BrianMultilingualNeural",
           "de-DE-FlorianMultilingualNeural", "fr-FR-RemyMultilingualNeural"]

async def main():
    metin = open("deneme/ornek.txt", encoding="utf-8").read()
    var = {v["ShortName"] for v in await edge_tts.list_voices()}
    print("Çok dilli sesler:", sorted(k for k in var if "Multilingual" in k))
    os.makedirs("ornekler", exist_ok=True)
    for ses in ISTENEN:
        if ses not in var:
            print("yok:", ses); continue
        try:
            await edge_tts.Communicate(metin, ses).save(f"ornekler/edge-{ses}.mp3")
            print("tamam:", ses)
        except Exception as h:
            print("hata:", ses, type(h).__name__, h)

asyncio.run(main())
