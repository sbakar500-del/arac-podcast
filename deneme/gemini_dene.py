"""Aynı kısa metni Gemini TTS ile birkaç erkek sesle okur -> ornekler/gemini-*.wav

Anahtar GEMINI_API_KEY ortam değişkeninden okunur ve yalnızca istek başlığında gönderilir; hiçbir yere yazılmaz.
"""
import base64, json, os, sys, time, urllib.error, urllib.request, wave

ANAHTAR = os.environ.get("GEMINI_API_KEY", "").strip()
if not ANAHTAR:
    sys.exit("GEMINI_API_KEY tanımlı değil")
MODELLER = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview"]
SESLER = sys.argv[1:] or ["Charon", "Algieba", "Achird"]
USLUP = "warm, natural Turkish radio news host, native Istanbul accent, calm and clear pace"
metin = open("deneme/ornek.txt", encoding="utf-8").read().strip()


def iste(govde):
    istek = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps(govde).encode(),
        headers={"x-goog-api-key": ANAHTAR, "Content-Type": "application/json", "Api-Revision": "2026-05-20"},
    )
    try:
        with urllib.request.urlopen(istek, timeout=300) as y:
            return y.status, json.load(y)
    except urllib.error.HTTPError as h:
        return h.code, h.read().decode("utf-8", "replace")[:1500]


def iskelet(x, d=0):
    """Yanıtın yapısını, uzun değerleri kısaltarak gösterir."""
    if isinstance(x, dict):
        return {k: iskelet(v, d + 1) for k, v in x.items()}
    if isinstance(x, list):
        return [iskelet(v, d + 1) for v in x[:3]]
    if isinstance(x, str) and len(x) > 80:
        return f"<{len(x)} karakter>"
    return x


def ses_bul(x):
    """Yanıttaki en uzun base64 ses verisini ve türünü bulur."""
    en = (None, None)
    if isinstance(x, dict):
        v = x.get("data")
        if isinstance(v, str) and len(v) > 2000:
            en = (v, x.get("mime_type") or x.get("mimeType"))
        for a in x.values():
            b = ses_bul(a)
            if b[0] and (not en[0] or len(b[0]) > len(en[0])):
                en = b
    elif isinstance(x, list):
        for a in x:
            b = ses_bul(a)
            if b[0] and (not en[0] or len(b[0]) > len(en[0])):
                en = b
    return en


def govdeler(model, ses):
    yapili = {"model": model, "response_format": {"type": "audio"},
              "generation_config": {"speech_config": [{"voice": ses}]},
              "input": [{"type": "user_input", "content": [{"type": "text", "text": metin,
                         "annotations": [{"type": "speech_metadata", "style": USLUP}]}]}]}
    duz = dict(yapili, input=metin)
    return [("üsluplu", yapili), ("düz", duz)]


os.makedirs("ornekler", exist_ok=True)
model_sirasi = list(MODELLER)
ilk = True
for ses in SESLER:
    tamam = False
    for model in list(model_sirasi):
        for ad, govde in govdeler(model, ses):
            t = time.time()
            kod, yanit = iste(govde)
            if kod == 200:
                if ilk:
                    print("yanıt yapısı:", json.dumps(iskelet(yanit), ensure_ascii=False)[:1500]); ilk = False
                veri, tur = ses_bul(yanit)
                if not veri:
                    print(f"{ses}/{model}/{ad}: yanıtta ses yok"); continue
                ham = base64.b64decode(veri)
                yol = f"ornekler/gemini-{ses}.wav"
                if ham[:4] == b"RIFF":
                    open(yol, "wb").write(ham)
                else:
                    with wave.open(yol, "wb") as w:
                        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(ham)
                print(f"tamam: {ses}, model={model}, biçim={ad}, tür={tur}, {len(ham)} bayt, {time.time() - t:.0f} sn", flush=True)
                model_sirasi = [model]  # çalışan modelde kal, kotayı boşa harcama
                tamam = True
                break
            print(f"hata: {ses}/{model}/{ad}: HTTP {kod}: {str(yanit)[:900]}", flush=True)
            if kod in (429, 403, 404):
                break  # kota/izin/model yok: bu modelde öbür biçimi deneme
        if tamam:
            break
    time.sleep(3)
