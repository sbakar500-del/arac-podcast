# Araç podcast'i

Her sabah `metinler/` klasörüne o günün Türkçe haber metni eklenir. GitHub Actions bu metni Microsoft Edge'in
ana dili Türkçe olan sesiyle (`tr-TR-AhmetNeural`, ücretsiz [edge-tts](https://github.com/rany2/edge-tts) ile)
seslendirir ve `yayin` sürümüne `bolum.mp3` ile `bolum.json` olarak yükler. Arabadaki launcher bu iki dosyayı
indirip çalar.

Edge ses hizmeti o sabah yanıt vermezse bölüm, yedek olarak çevrimdışı çalışan
[Seslen](https://github.com/seslen-tr/seslen-tts) ile (ses: `hasan`) üretilir.

Ses ve hız `.github/workflows/podcast.yml` içindeki `SES` ve `HIZ` değerleriyle değişir.

Metin ve ses yapay zekâ ile üretilir. Yedek ses modeli Seslen, CC BY-SA 4.0 lisanslıdır.
