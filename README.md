# Evde Sağlık Rota – DEMO

Evde sağlık ekipleri için günlük rota planlama ve veri giriş uygulamasının **demo** sürümüdür.

> ⚠️ Bu depodaki **bütün hasta ve personel bilgileri uydurmadır.** Gerçek hasta verisi içermez.

## Demo hesapları
Parola hepsi için: `demo1234`

| Kullanıcı adı | Rol |
|---|---|
| `yonetici` | Yönetici: rota planlama, raporlar, hastalar, personel, yedekler |
| `doktor1` | Doktor: hasta takibi, muayene notu, hemşire talimatı |
| `hemsire1` / `hemsire4` / `hemsire7` | Hemşire (Ekip 1 / 2 / 3): günlük rota, ziyaret kaydı |

## Çalıştırma
```
pip install -r requirements.txt
streamlit run app.py
```

## Neler var?
- Google OR-Tools ile 3 ekip için günlük rota optimizasyonu (kan teslim saati, ziyaret süreleri, merkeze dönüş)
- Mevcut sabit bölge sistemiyle karşılaştırma ve raporlar
- Rol bazlı ekranlar (yönetici / doktor / hemşire), telefona uygun hemşire ekranları
