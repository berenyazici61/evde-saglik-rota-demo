"""
Anlık trafik bilgisi (TomTom Traffic Flow) – YALNIZCA DEMO'da kullanılır (kullanıcı kararı, 12.11.2026).

Gizlilik: servise hasta ya da ekip konumu GÖNDERİLMEZ. Yalnızca yol ağından seçilmiş sabit örnek noktalar
(ana yollar üzerinde, yaklaşık 5 km'de bir; yol_guzergahi.trafik_ornek_noktalari) sorgulanır. Her örnek nokta
için "şu anki yol süresi / serbest akış süresi" oranı alınır ve o noktanın çevresindeki yol parçalarının süresi
bu oranla çarpılır (yol_guzergahi: trafik çarpanı). Yani trafik, bölge bölge bir "yavaşlama katsayısı"dır.

API anahtarı: Streamlit Cloud'da "Secrets" bölümüne  TOMTOM_API_KEY = "..."  ya da ortam değişkeni
TOMTOM_API_KEY. Anahtar yoksa trafik kullanılamaz, uygulama trafiksiz çalışmaya devam eder.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

import ayarlar
import yol_guzergahi

URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
ONBELLEK_SN = 10 * 60          # aynı trafik bilgisi 10 dk boyunca yeniden kullanılır (istek sayısı az kalsın)
EN_FAZLA_CARPAN = 5.0          # yol kapalı / çok yoğun trafik üst sınırı
KAPALI_YOL_CARPANI = 5.0

_onbellek: dict = {"zaman": 0.0, "durum": None}


@dataclass
class TrafikDurumu:
    zaman: float                                   # sorgu zamanı (time.time())
    carpanlar: tuple                               # örnek nokta başına süre çarpanı (≥ 1)
    noktalar: list = field(default_factory=list)   # örnek noktalar (enlem, boylam)
    hiz_orani: list = field(default_factory=list)  # şu anki hız / serbest akış hızı (gösterim için), None = veri yok
    kapali: list = field(default_factory=list)
    hata: int = 0                                  # yanıt alınamayan nokta sayısı

    @property
    def ortalama_yavaslama(self) -> float:
        return sum(self.carpanlar) / len(self.carpanlar) if self.carpanlar else 1.0


def kullanilabilir() -> bool:
    """Bu kurulumda anlık trafik açılabilir mi? (Yalnızca demo + anahtar + yol ağı.)"""
    return ayarlar.TRAFIK_KULLANILABILIR and bool(api_anahtari()) and yol_guzergahi.hazir()


def api_anahtari() -> str:
    try:
        import streamlit as st
        anahtar = st.secrets.get("TOMTOM_API_KEY", "")
    except Exception:  # secrets dosyası yok vb.
        anahtar = ""
    return anahtar or os.environ.get("TOMTOM_API_KEY", "")


def _sorgula(nokta, anahtar):
    """(süre çarpanı, hız oranı, kapalı mı) ya da veri yoksa None."""
    try:
        r = requests.get(URL, params={"point": f"{nokta[0]:.5f},{nokta[1]:.5f}", "unit": "KMPH", "key": anahtar},
                         timeout=8)
        if r.status_code != 200:
            return None
        v = r.json()["flowSegmentData"]
        if v.get("roadClosure"):
            return KAPALI_YOL_CARPANI, 0.0, True
        simdi, serbest = float(v["currentTravelTime"]), float(v["freeFlowTravelTime"])
        if simdi <= 0 or serbest <= 0:
            return None
        carpan = min(EN_FAZLA_CARPAN, max(1.0, simdi / serbest))
        return carpan, float(v["currentSpeed"]) / max(1.0, float(v["freeFlowSpeed"])), False
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def guncel_durum(yenile: bool = False) -> TrafikDurumu | None:
    """Anlık trafik (10 dk önbellekli). Kullanılamıyorsa ya da hiç yanıt gelmezse None."""
    if not kullanilabilir():
        return None
    if not yenile and _onbellek["durum"] and time.time() - _onbellek["zaman"] < ONBELLEK_SN:
        return _onbellek["durum"]
    anahtar = api_anahtari()
    noktalar = yol_guzergahi.trafik_ornek_noktalari()
    with ThreadPoolExecutor(max_workers=6) as havuz:
        yanitlar = list(havuz.map(lambda p: _sorgula(p, anahtar), noktalar))
    if all(y is None for y in yanitlar):
        return None
    durum = TrafikDurumu(
        zaman=time.time(),
        carpanlar=tuple(round(y[0], 3) if y else 1.0 for y in yanitlar),
        noktalar=noktalar,
        hiz_orani=[y[1] if y else None for y in yanitlar],
        kapali=[bool(y and y[2]) for y in yanitlar],
        hata=sum(y is None for y in yanitlar),
    )
    _onbellek.update(zaman=durum.zaman, durum=durum)
    return durum
