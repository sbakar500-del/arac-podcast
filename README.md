# Araç podcast'i

Her sabah `metinler/` klasörüne o günün Türkçe haber metni eklenir. GitHub Actions bu metni
[Seslen](https://github.com/seslen-tr/seslen-tts) ile (ses: `hasan`) seslendirir ve `yayin` sürümüne
`bolum.mp3` ile `bolum.json` olarak yükler. Arabadaki launcher bu iki dosyayı indirip çalar.

Metin ve ses yapay zekâ ile üretilir. Ses modeli Seslen, CC BY-SA 4.0 lisanslıdır.
