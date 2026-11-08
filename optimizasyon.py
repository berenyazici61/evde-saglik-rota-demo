"""
Günlük rota optimizasyonu (Google OR-Tools).

Model (ayrıntılar masaüstündeki kısıtlar belgesinde, K1–K16):
  - Her ekip 09:00'da merkezden çıkar, işi bitince merkeze döner (+30 dk teslim).
  - Her hasta tam bir kez, tek bir ekip tarafından ziyaret edilir.
  - Ziyaret süresi = yapılan işlemlerin planlama sürelerinin toplamı.
  - Her ekip kendi aldığı kanı 7M Hastanesi'ne teslim eder. Hedef varış 12:00;
    gerekirse en fazla 15 dk esneyebilir (12:15 kesin sınır), her geç dakika cezalıdır.
  - Amaç (eşit ağırlık): en geç biten ekibin süresi + tüm ekiplerin toplam yol süresi.

Kan teslimi nasıl modellendi?
  Kanı alınan her hasta için 7M Hastanesi'nde bir "teslim düğümü" kopyası
  oluşturulur. Hasta (alım) ile teslim düğümü bir "alım-teslim çifti"dir:
  aynı ekip tarafından, önce alım sonra teslim yapılmalıdır. Kopyalar aynı
  yerde olduğu için ekip genelde hastaneye bir kez gidip hepsini birden teslim eder.
  Teslim süresi (15-20 dk -> 18 dk) hastaneden ayrılırken bir kez eklenir.
"""

from dataclasses import dataclass, field

import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

import ayarlar
import mesafe

ATLAMA_CEZASI = 1_000_000  # bir hastayı atlamak çok pahalı: yalnızca imkânsızsa atlanır


@dataclass
class Durak:
    tur: str                 # "Merkez", "Hasta", "7M Hastanesi"
    ad: str
    enlem: float
    boylam: float
    varis_dk: int
    ayrilis_dk: int
    islemler: str = ""
    kan_alimi: bool = False
    tup_sayisi: int = 0


@dataclass
class EkipRotasi:
    ekip: str
    duraklar: list[Durak] = field(default_factory=list)
    km: float = 0.0
    bitis_dk: int = 0        # merkezde teslim dahil işin bittiği an

    @property
    def hasta_sayisi(self) -> int:
        return sum(d.tur == "Hasta" for d in self.duraklar)

    @property
    def kan_teslim_dk(self):
        """Ekibin 7M Hastanesi'nde kan teslimini son bitirdiği saat (birden fazla gidiş olabilir)."""
        bitisler = [d.ayrilis_dk for d in self.duraklar if d.tur == "7M Hastanesi"]
        return max(bitisler) if bitisler else None


@dataclass
class Sonuc:
    rotalar: list[EkipRotasi]
    atlanan: list[str]
    cozum_bulundu: bool

    @property
    def en_gec_bitis(self) -> int:
        dolu = [r.bitis_dk for r in self.rotalar if r.hasta_sayisi]
        return max(dolu) if dolu else 0

    @property
    def toplam_km(self) -> float:
        return sum(r.km for r in self.rotalar)

    @property
    def toplam_calisma_dk(self) -> int:
        cikis = ayarlar.dakika(ayarlar.CIKIS_SAATI)
        return sum(r.bitis_dk - cikis for r in self.rotalar if r.hasta_sayisi)

    @property
    def kan_gecikmesi_dk(self) -> int:
        """Teslim bitişinin 12:00'yi geçtiği toplam süre (dk)."""
        son = ayarlar.dakika(ayarlar.KAN_TESLIM_SON_SAAT)
        return sum(max(0, d.ayrilis_dk - son) for r in self.rotalar for d in r.duraklar
                   if d.tur == "7M Hastanesi")


def rota_coz(
    ziyaretler: pd.DataFrame,
    merkez: tuple[float, float],
    lab: tuple[float, float],
    ekip_sayisi: int = ayarlar.EKIP_SAYISI,
    ekip_adlari: list[str] | None = None,
    sure_limiti_sn: int = 10,
    baslangic: "Sonuc | None" = None,
) -> Sonuc:
    """
    ziyaretler: hasta_kodu, enlem, boylam, sure_dk, kan_alimi, islemler sütunları olmalı
                (konumu olmayan satırlar önceden çıkarılmalı).
    baslangic:  isteğe bağlı başlangıç çözümü (ör. mevcut bölge sistemi). Verilirse
                sonuç, amaç fonksiyonuna göre bu çözümden kötü olamaz.
    """
    ekip_adlari = ekip_adlari or [f"Ekip {k + 1}" for k in range(ekip_sayisi)]
    z = ziyaretler.reset_index(drop=True)
    n = len(z)
    if n == 0:
        return Sonuc([EkipRotasi(a) for a in ekip_adlari], [], True)

    kan_hastalari = [i for i in range(n) if bool(z.loc[i, "kan_alimi"])]
    b = len(kan_hastalari)

    # Düğümler: 0 = merkez, 1..n = hastalar, n+1..n+b = 7M teslim kopyaları
    noktalar = [merkez] + list(zip(z["enlem"], z["boylam"])) + [lab] * b
    tur = ["Merkez"] + ["Hasta"] * n + ["7M Hastanesi"] * b
    hizmet = [0] + [int(s) for s in z["sure_dk"]] + [0] * b
    yol = mesafe.sure_matrisi(noktalar)

    cikis = ayarlar.dakika(ayarlar.CIKIS_SAATI)
    lab_suresi = ayarlar.KAN_TESLIM_SURESI_DK
    # Sınırlar teslimin BİTİŞİNE uygulanır (bitiş = 7M'ye varış + teslim süresi).
    # Modelde teslim düğümünün zamanı varış olduğu için sınırlar teslim süresi kadar öne çekilir.
    hedef_teslim = ayarlar.dakika(ayarlar.KAN_TESLIM_SON_SAAT) - lab_suresi                # 12:00 bitiş -> 11:42 varış
    son_teslim = hedef_teslim + ayarlar.KAN_TESLIM_ESNEKLIK_DK                              # 12:15 bitiş -> 11:57 varış

    def model_kur():
        """Modeli sıfırdan kurar. (OR-Tools çözülmüş bir modele başlangıç rotası okuyamadığı
        için her başlangıç denemesi kendi modelini kullanır.)"""
        manager = pywrapcp.RoutingIndexManager(len(noktalar), ekip_sayisi, 0)
        routing = pywrapcp.RoutingModel(manager)
        solver = routing.solver()

        # Amacın 1. parçası: toplam yol süresi (ağırlık AGIRLIK_TOPLAM_YOL)
        def yol_cb(fi, ti):
            return ayarlar.AGIRLIK_TOPLAM_YOL * yol[manager.IndexToNode(fi)][manager.IndexToNode(ti)]

        routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(yol_cb))

        # Zaman boyutu: i'den j'ye geçiş = i'deki hizmet + yol (+ hastaneden ayrılırken teslim süresi)
        def zaman_cb(fi, ti):
            i, j = manager.IndexToNode(fi), manager.IndexToNode(ti)
            ek = lab_suresi if tur[i] == "7M Hastanesi" and tur[j] != "7M Hastanesi" else 0
            return hizmet[i] + yol[i][j] + ek

        routing.AddDimension(routing.RegisterTransitCallback(zaman_cb), 0, 24 * 60, False, "Zaman")
        zaman = routing.GetDimensionOrDie("Zaman")
        for k in range(ekip_sayisi):
            zaman.CumulVar(routing.Start(k)).SetRange(cikis, cikis)       # K5: 09:00 çıkış
        # Amacın 2. parçası: en geç biten ekibin süresi, C_max − 09:00 (ağırlık AGIRLIK_EN_GEC_BITIS)
        zaman.SetGlobalSpanCostCoefficient(ayarlar.AGIRLIK_EN_GEC_BITIS)

        # K1: her hasta bir kez (imkânsızsa çok yüksek cezayla atlanabilir -> raporlanır)
        for i in range(1, n + 1):
            routing.AddDisjunction([manager.NodeToIndex(i)], ATLAMA_CEZASI)

        # K9-K11: kan alım-teslim çiftleri
        for t, i in enumerate(kan_hastalari):
            alim = manager.NodeToIndex(1 + i)
            teslim = manager.NodeToIndex(1 + n + t)
            routing.AddDisjunction([teslim], 0)
            routing.AddPickupAndDelivery(alim, teslim)
            solver.Add(routing.ActiveVar(alim) == routing.ActiveVar(teslim))
            solver.Add(routing.VehicleVar(alim) == routing.VehicleVar(teslim))
            solver.Add(zaman.CumulVar(alim) <= zaman.CumulVar(teslim))
            zaman.CumulVar(teslim).SetMax(son_teslim)                                  # kesin: bitiş 12:15
            zaman.SetCumulVarSoftUpperBound(teslim, hedef_teslim, ayarlar.KAN_GECIKME_CEZASI)  # esnek: bitiş 12:00
        return manager, routing, zaman

    # İki başlangıçtan çöz, iyisini al:
    #   1) sıfırdan (en ucuz ekleme sezgiseli)
    #   2) verilmişse "baslangic" çözümünden (ör. mevcut bölge sistemi) -> sonuç ondan kötü olamaz
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(max(2, sure_limiti_sn // 2) if baslangic else sure_limiti_sn)

    def oku(cozum, manager, routing, zaman) -> Sonuc:
        return _cozumu_oku(cozum, routing, manager, zaman, ekip_sayisi, ekip_adlari,
                           noktalar, tur, hizmet, z, n, lab_suresi)

    adaylar = []  # (amaç değeri, Sonuc)
    manager, routing, zaman = model_kur()
    cozum = routing.SolveWithParameters(params)
    if cozum is not None:
        adaylar.append((cozum.ObjectiveValue(), oku(cozum, manager, routing, zaman)))

    if baslangic is not None:
        manager, routing, zaman = model_kur()
        ilk_rotalar = _baslangic_rotalari(baslangic, z, n, kan_hastalari, manager, ekip_sayisi)
        ilk = routing.ReadAssignmentFromRoutes(ilk_rotalar, True)
        if ilk is not None:
            cozum2 = routing.SolveFromAssignmentWithParameters(ilk, params)
            if cozum2 is not None:
                adaylar.append((cozum2.ObjectiveValue(), oku(cozum2, manager, routing, zaman)))

    if not adaylar:
        return Sonuc([EkipRotasi(a) for a in ekip_adlari], list(z["hasta_kodu"]), False)
    return min(adaylar, key=lambda a: a[0])[1]


def _baslangic_rotalari(baslangic: "Sonuc", z, n, kan_hastalari, manager, ekip_sayisi):
    """Başka bir çözümü (ör. bölge sistemi) OR-Tools başlangıç rotalarına çevirir."""
    kod_dugum = {z.loc[i, "hasta_kodu"]: 1 + i for i in range(n)}
    kopya = {1 + i: 1 + n + t for t, i in enumerate(kan_hastalari)}
    rotalar = []
    for rota in baslangic.rotalar[:ekip_sayisi]:
        sira, teslim_bekleyen = [], []
        for d in rota.duraklar:
            if d.tur == "Hasta" and d.ad in kod_dugum:
                dugum = kod_dugum[d.ad]
                sira.append(dugum)
                if dugum in kopya:
                    teslim_bekleyen.append(kopya[dugum])
            elif d.tur == "7M Hastanesi":
                sira += teslim_bekleyen
                teslim_bekleyen = []
        sira += teslim_bekleyen
        rotalar.append([manager.NodeToIndex(x) for x in sira])
    while len(rotalar) < ekip_sayisi:
        rotalar.append([])
    return rotalar


def _cozumu_oku(cozum, routing, manager, zaman, ekip_sayisi, ekip_adlari,
                noktalar, tur, hizmet, z, n, lab_suresi) -> "Sonuc":
    """OR-Tools çözümünü okunabilir Sonuc nesnesine çevirir."""
    rotalar = []
    for k in range(ekip_sayisi):
        rota = EkipRotasi(ekip_adlari[k])
        idx = routing.Start(k)
        onceki = None
        while True:
            node = manager.IndexToNode(idx)
            varis = cozum.Value(zaman.CumulVar(idx))
            if onceki is not None:
                rota.km += mesafe.yol_km(noktalar[onceki], noktalar[node])
            if tur[node] == "Merkez":
                ad = ayarlar.MERKEZ["ad"]
                rota.duraklar.append(Durak("Merkez", ad, *noktalar[node], varis, varis))
            elif tur[node] == "Hasta":
                h = z.loc[node - 1]
                rota.duraklar.append(Durak("Hasta", h["hasta_kodu"], *noktalar[node], varis,
                                           varis + hizmet[node], h["islemler"], bool(h["kan_alimi"])))
            else:  # 7M teslim kopyası: ardışık kopyaları tek durakta birleştir
                son = rota.duraklar[-1] if rota.duraklar else None
                if son and son.tur == "7M Hastanesi":
                    son.tup_sayisi += 1
                else:
                    rota.duraklar.append(Durak("7M Hastanesi", ayarlar.KAN_TESLIM_YERI["ad"],
                                               *noktalar[node], varis, varis + lab_suresi, tup_sayisi=1))
            if routing.IsEnd(idx):
                break
            onceki = node
            idx = cozum.Value(routing.NextVar(idx))
        rota.bitis_dk = rota.duraklar[-1].varis_dk + ayarlar.MERKEZ_DONUS_SURESI_DK
        rota.duraklar[-1].ayrilis_dk = rota.bitis_dk
        rotalar.append(rota)

    atlanan = [z.loc[i - 1, "hasta_kodu"] for i in range(1, n + 1)
               if cozum.Value(routing.NextVar(manager.NodeToIndex(i))) == manager.NodeToIndex(i)]
    return Sonuc(rotalar, atlanan, True)


def atlama_nedeni(ziyaret: pd.Series, merkez, lab) -> str:
    """Rotaya alınamayan bir hasta için anlaşılır bir açıklama üretir."""
    cikis = ayarlar.dakika(ayarlar.CIKIS_SAATI)
    hasta = (ziyaret["enlem"], ziyaret["boylam"])
    bitis = cikis + mesafe.yol_suresi_dk(merkez, hasta) + int(ziyaret["sure_dk"])
    if bool(ziyaret["kan_alimi"]):
        lab_varis = bitis + mesafe.yol_suresi_dk(hasta, lab)
        teslim_bitis = lab_varis + ayarlar.KAN_TESLIM_SURESI_DK
        son = ayarlar.dakika(ayarlar.KAN_TESLIM_SON_SAAT) + ayarlar.KAN_TESLIM_ESNEKLIK_DK
        if teslim_bitis > son:
            return (f"Kan teslimi en geç {ayarlar.saat(son)}'te (esneklik dahil) bitemiyor: ekip 09:00'da "
                    f"doğrudan bu hastaya gitse bile ziyaret {ayarlar.saat(bitis)}'te biter, 7M'ye "
                    f"{ayarlar.saat(lab_varis)}'te varılır ve teslim {ayarlar.saat(teslim_bitis)}'te biter "
                    f"({teslim_bitis - son} dk geç).")
        return "Kan teslim saati nedeniyle diğer kan alımlarıyla birlikte sığdırılamadı."
    return "Çözüm süresi içinde rotaya yerleştirilemedi (çözüm süresini artırmayı deneyin)."


# ---------------------------------------------------------------------------
# Mevcut sistemle karşılaştırma: sabit doğu / orta / batı bölgeleri
# ---------------------------------------------------------------------------
# Boylama göre bölge sınırları. Kullanıcı gerçek sınırlara çok yakın olduğunu teyit etti (07.11.2026).
BATI_SINIRI = 39.705    # bunun batısı (Akçaabat, Beşirli, Ayasofya...) -> Batı
DOGU_SINIRI = 39.770    # bunun doğusu (Pelitli, Kaşüstü, Arsin, Of...) -> Doğu


def bolge_bul(boylam: float) -> str:
    if boylam < BATI_SINIRI:
        return "Batı"
    if boylam > DOGU_SINIRI:
        return "Doğu"
    return "Orta"


def mevcut_sistem_coz(ziyaretler, merkez, lab, sure_limiti_sn: int = 5) -> Sonuc:
    """Her bölgeye tek ekip: hastalar bölgelere sabit, her ekip kendi sırasını optimize eder."""
    z = ziyaretler.copy()
    z["bolge"] = z["boylam"].map(bolge_bul)
    rotalar, atlanan = [], []
    for bolge in ["Batı", "Orta", "Doğu"]:
        alt = z[z["bolge"] == bolge]
        s = rota_coz(alt, merkez, lab, ekip_sayisi=1, ekip_adlari=[f"{bolge} ekibi"],
                     sure_limiti_sn=sure_limiti_sn)
        rotalar += s.rotalar
        atlanan += s.atlanan
    return Sonuc(rotalar, atlanan, True)
