# kepçe: Instagram videolarını toplu indirme sitesi

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/formxweb/kepce)

Kullanıcı en fazla 20 Instagram linkini (Reels, gönderi, IGTV) tek seferde yapıştırır, site hepsini aynı anda hazırlar. "Hepsini indir" düğmesi her videoyu ayrı bir MP4 dosyası olarak cihaza indirir; her satırda tek tek indirme düğmesi de var. Arayüz Türkçe ve telefona göre tasarlandı.

Tarayıcılar art arda birden çok indirme gördüğünde bir kez izin ister (Chrome'da "Birden fazla dosya indirmeye izin ver"). Kullanıcı İzin ver'e dokununca kalan videolar da iner.

## Neler var

- Karışık metinden link ayıklama: alt alta, virgüllü ya da mesajın içinde olsa da bulur, tekrar edenleri bir kez sayar. 20'den fazla link varsa ilk 20'yi alır, kalanlar için "Kalan linklere geç" düğmesi çıkar.
- 20 kutuluk şerit: her kutu bir videoyu gösterir; sırada, iniyor, hazır, hata durumları renkle görünür.
- Aynı anda birden çok indirme (varsayılan 4), her video için ilerleme yüzdesi ve küçük resim.
- Çoklu (kaydırmalı) gönderilerde içindeki bütün videolar iner.
- Hatalar anlaşılır Türkçe mesajla gösterilir (gizli hesap, silinmiş gönderi, fotoğraf gönderisi, Instagram engeli) ve "Tekrar dene" düğmesi çıkar.
- Sayfa yenilense de liste kaybolmaz.
- Dosyalar 30 dakika sonra sunucudan silinir. IP başına saatte 15 liste sınırı var.

## Bilgisayarda çalıştırma

Python 3.10+ ve ffmpeg gerekir.

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Tarayıcıda `http://localhost:8000` adresini aç.

Instagram'a bağlanmadan denemek için demo modu:

```bash
DOWNLOADER=fake uvicorn app.main:app
```

Demo modunda her link sahte bir video üretir. Linkin kodunda `gizli`, `silindi`, `foto` geçerse ilgili hata, `coklu` geçerse iki videolu gönderi taklit edilir.

Testler: `python -m unittest discover -s tests -v`

## Yayına alma (Render)

1. Yukarıdaki **Deploy to Render** düğmesine bas, Render'a GitHub ile giriş yap ve **Apply**'a dokun. `render.yaml` her şeyi ayarlar (Docker ile kurulur, ffmpeg ve yt-dlp dahil). İlk kurulum 5-10 dakika sürer.
2. Kurulum bitince Render sana `kepce-xxxx.onrender.com` gibi bir link verir; site hazırdır.
3. Kendi alan adını Render panelinden **Custom Domains** kısmına ekle.

Ücretsiz planda site 15 dakika kullanılmayınca uyur, sonraki ilk açılış yaklaşık 1 dakika sürer. Müşteriye açacaksan panelden **Starter** plana geç.

Railway, Fly.io ya da kendi VPS'in de olur: Dockerfile her yerde çalışır. Proxy arkasındaysan `TRUST_PROXY=1` yap.

**Vercel ya da Netlify olmaz.** Oralarda işlemler birkaç saniyede kesiliyor, ffmpeg yok ve dosya saklanamıyor. Bu sitenin sürekli çalışan bir sunucuya ihtiyacı var.

Liste durumu bellekte tutulduğu için tek işçiyle (`--workers 1`) çalışmalı. Daha fazla yük için `MAX_CONCURRENT` değerini artır ya da sunucuyu büyüt.

## Instagram engellerse

Instagram, sunucu firmalarının IP adreslerinden gelen istekleri sık sık sınırlıyor. Kullanıcılar "Instagram bu isteği şimdilik engelledi" mesajını çok görmeye başlarsa:

1. Ana hesabın olmayan, yedek bir Instagram hesabıyla tarayıcıdan giriş yap.
2. "Get cookies.txt LOCALLY" gibi bir eklentiyle instagram.com çerezlerini `cookies.txt` olarak dışa aktar.
3. Render'da **Secret Files** kısmına `cookies.txt` adıyla yükle ve `IG_COOKIES_FILE=/etc/secrets/cookies.txt` ortam değişkenini ekle.

Bu hesap zamanla kısıtlanabilir; ana hesabını kullanma.

Instagram sitesini değiştirdiğinde yt-dlp birkaç gün içinde güncellenir. İndirmeler toptan bozulursa Render'da **Manual Deploy > Clear build cache & deploy** yapman yeterli; en güncel yt-dlp kurulur.

## Ayarlar (ortam değişkenleri)

| Değişken | Varsayılan | Ne işe yarar |
|---|---|---|
| `MAX_CONCURRENT` | 4 | Aynı anda kaç video indirilir (tüm kullanıcılar toplamı) |
| `JOBS_PER_HOUR` | 15 | Bir IP saatte kaç liste başlatabilir |
| `JOB_TTL_MINUTES` | 30 | Dosyalar kaç dakika sonra silinir |
| `MAX_FILESIZE_MB` | 300 | Tek video için boyut sınırı |
| `MAX_ATTEMPTS` | 3 | Bir link en fazla kaç kez denenir |
| `IG_COOKIES_FILE` | yok | Instagram çerez dosyasının yolu |
| `TRUST_PROXY` | 0 | Proxy arkasında gerçek IP'yi okumak için 1 |
| `DATA_DIR` | /tmp/kepce-data | Geçici dosyaların klasörü |
| `DOWNLOADER` | ytdlp | `fake` yaparsan demo modu |

## Dosyalar

```
app/main.py        HTTP uçları, hız sınırı, uygulama kurulumu
app/jobs.py        İndirme kuyruğu, küçük resim, temizlik
app/downloader.py  yt-dlp ile indirme, Türkçe hata mesajları, demo indirici
app/links.py       Metinden Instagram linki ayıklama
static/            Arayüz (index.html, style.css, app.js)
tests/             Testler
```

İsmi değiştirmek için `static/index.html` içindeki "kepçe" yazılarını ve başlığı düzenle.

## Hukuki not

Videoları indirmek Instagram'ın kullanım koşullarına aykırı olabilir ve videoların telif hakkı sahiplerine aittir. Site, kullanıcılara yalnızca kendi videolarını ya da izin aldıkları videoları indirmelerini söylüyor. Instagram'ın logosunu ya da marka görselini sitede kullanma; "Instagram" kelimesini yalnızca ne işe yaradığını anlatmak için kullan.
