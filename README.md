# Araç podcast'i

Her sabah `metinler/` klasörüne o günün Türkçe haber metni eklenir. GitHub Actions bu metni Google Gemini'nin
ses modeliyle (`gemini-3.8-flash-tts`, ses: `Algieba`) seslendirir ve `yayin` sürümüne `bolum.mp3` ile
`bolum.json` olarak yükler. Arabadaki launcher bu iki dosyayı indirip çalar.

Gemini ücretsiz kullanılıyor: günde 10, dakikada 3 istek hakkı var. Bölüm en çok 5 istekte okunur.
Anahtar, deponun `GEMINI_API_KEY` adlı gizli değişkeninde durur.

Yedekler sırayla:
1. Gemini yanıt vermezse ya da günlük hak biterse: Microsoft Edge'in Türkçe sesi (`tr-TR-AhmetNeural`,
   ücretsiz [edge-tts](https://github.com/rany2/edge-tts) ile).
2. O da yanıt vermezse: çevrimdışı çalışan [Seslen](https://github.com/seslen-tr/seslen-tts) (ses: `hasan`).

Ses `.github/workflows/podcast.yml` içindeki `SES` değeriyle değişir.

Metin ve ses yapay zekâ ile üretilir. Son yedek ses modeli Seslen, CC BY-SA 4.0 lisanslıdır.
