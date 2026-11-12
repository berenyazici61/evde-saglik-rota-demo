"""
Gün içi dinamik rota revizyonu.

Kayıtlı (sabah onaylanan) plan, gün içinde bir olay olunca yeniden hesaplanır:
  - Acil hasta     : yeni (veya plandaki bir hasta öne alınarak) acil ziyaret
  - Ziyaret uzadı  : bir ziyaretin süresi beklenenden uzun
  - İptal          : hasta evde yok / ziyaret iptal

Adımlar:
  1. durum_cikar(): olay saatindeki durum sabitlenir. Her ekip için tamamlanan ve devam eden duraklar
     (değiştirilemez), ekibin konumu, hazır olacağı saat ve araçtaki teslim edilmemiş kan örnekleri.
  2. revize_coz(): kalan hastalar (+ acil hasta) ekiplerin o anki konumundan başlayarak yeniden atanır.
     Amaç = en geç bitiş + toplam yol + kan gecikmesi cezası (sabah modeliyle aynı)
            + acil hastanın bekleme süresi (ağırlıklı) + ekip değiştiren hasta başına değişiklik cezası.
     Sabah planının kalan kısmı başlangıç çözümü olarak verilir: yeni plan, olaylardan sonra
     "hiçbir şeyi değiştirmeden devam etmek"ten (amaç değerine göre) kötü olamaz.

Varsayım: olay anında yolda olan bir ekibin konumu, ayrıldığı durak ile gittiği durak arasında geçen
süre oranında (düz çizgi üzerinde) tahmin edilir; ekip oradan yeni rotasına devam eder.
"""

import copy
from dataclasses import dataclass, field

import pandas as pd
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

import ayarlar
import mesafe
from optimizasyon import ATLAMA_CEZASI, Durak, EkipRotasi, Sonuc
from ayarlar import saat

OLAY_TURLERI = {"acil": "🚨 Acil hasta", "uzama": "⏱️ Ziyaret uzadı", "iptal": "❌ İptal / hasta evde yok"}
ACIL_ON_EKI = "🚨 ACİL;"     # acil durağın işlem metninin başına eklenir (hemşire ekranında görünsün)
IPTAL_YAZISI = "❌ İPTAL (hasta evde yok / iptal)"


@dataclass
class Olay:
    tur: str                       # "acil", "uzama", "iptal"
    hasta_kodu: str
    ek_dk: int = 0                 # uzama
    islemler: str = ""             # acil: yapılacak işlemler (";" ile)
    sure_dk: int = 0               # acil: ziyaret süresi
    kan_alimi: bool = False        # acil
    enlem: float | None = None     # acil
    boylam: float | None = None

    def aciklama(self) -> str:
        if self.tur == "acil":
            return f"Acil hasta {self.hasta_kodu} ({self.sure_dk} dk" + (", kan alımı" if self.kan_alimi else "") + ")"
        if self.tur == "uzama":
            return f"{self.hasta_kodu} ziyareti {self.ek_dk} dk uzadı"
        return f"{self.hasta_kodu} ziyareti iptal / hasta evde yok"


@dataclass
class EkipDurumu:
    ekip_no: int                   # 1'den başlar
    sabit: list[Durak]             # tamamlanan + devam eden duraklar (ilki merkezden çıkış), değişmez
    kalan: list[Durak]             # henüz başlanmamış duraklar (sabah sırası; dönüş hariç)
    konum: tuple[float, float]
    hazir_dk: int                  # ekibin yeni işe başlayabileceği saat
    tasinan_kan: int               # araçta olup henüz teslim edilmemiş kan örneği sayısı
    dondu: bool = False            # ekip işini bitirip merkeze dönmüş
    ek_sure: dict = field(default_factory=dict)   # kalan hastalara eklenecek uzama (dk)
    yolda: str = ""                # olay anında yoldaysa gittiği durak (konum yol üzerinde tahmin edilir)
    _sonraki: Durak | None = None

    @property
    def tamamlanan(self) -> list[str]:
        return [d.ad for d in self.sabit if d.tur == "Hasta"]


@dataclass
class RevizyonSonucu:
    sonuc: Sonuc                   # yeni tam gün planı (sabit kısım + yeni kısım)
    durumlar: list[EkipDurumu]
    degisen: list[tuple[str, int | None, int]]  # (hasta, eski ekip, yeni ekip)
    acil_varis: dict               # {hasta: varış dk}
    uyarilar: list[str]
    atlanan_nedenleri: dict        # {hasta: neden}


# ---------------------------------------------------------------------------
# 1. Olay anındaki durum
# ---------------------------------------------------------------------------
def durum_cikar(plan: Sonuc, an_dk: int, tamamlanan: set[str], olaylar: list[Olay]):
    """(durumlar, uyarılar). tamamlanan: ziyaret kaydı girilmiş hastalar (sırası gelmeden girilmiş olabilir)."""
    durumlar, uyarilar = [], []
    for k, rota in enumerate(plan.rotalar, start=1):
        duraklar = [copy.copy(d) for d in rota.duraklar]
        p = 0  # sabit kısmın son indeksi
        for i in range(1, len(duraklar)):
            d = duraklar[i]
            if d.varis_dk <= an_dk or (d.tur == "Hasta" and d.ad in tamamlanan):
                p = i
        sabit, kalan = duraklar[:p + 1], duraklar[p + 1:]
        dondu = len(duraklar) > 1 and p == len(duraklar) - 1
        sonraki = None if dondu else duraklar[p + 1]
        if not dondu:
            kalan = kalan[:-1]  # merkeze dönüş yeniden hesaplanacak
        e = EkipDurumu(k, sabit, kalan, (0.0, 0.0), 0, 0, dondu)
        e._sonraki = sonraki
        durumlar.append(e)

    for o in olaylar:
        if o.tur == "acil":
            for e in durumlar:  # plandaki bir hasta acil olarak öne alındıysa eski yerinden çıkar
                e.kalan = [d for d in e.kalan if not (d.tur == "Hasta" and d.ad == o.hasta_kodu)]
            continue
        bulundu = False
        for e in durumlar:
            for i, d in enumerate(e.sabit):
                if d.tur != "Hasta" or d.ad != o.hasta_kodu:
                    continue
                bulundu = True
                if o.hasta_kodu in tamamlanan:
                    uyarilar.append(f"{o.hasta_kodu}: ziyaret kaydı zaten girilmiş, olay dikkate alınmadı.")
                elif o.tur == "uzama":  # devam eden (veya bitmiş sayılan) ziyaret uzar, sonrakiler kayar
                    d.ayrilis_dk += o.ek_dk
                    for s in e.sabit[i + 1:]:
                        s.varis_dk += o.ek_dk
                        s.ayrilis_dk += o.ek_dk
                else:  # iptal: ekip gitti ama ziyaret yapılmadı
                    d.ayrilis_dk = d.varis_dk
                    d.islemler, d.kan_alimi = IPTAL_YAZISI, False
            for d in list(e.kalan):
                if d.tur == "Hasta" and d.ad == o.hasta_kodu:
                    bulundu = True
                    if o.tur == "uzama":
                        e.ek_sure[d.ad] = e.ek_sure.get(d.ad, 0) + o.ek_dk
                    else:
                        e.kalan.remove(d)
        if not bulundu:
            uyarilar.append(f"{o.hasta_kodu} bu günün planında yok; '{OLAY_TURLERI[o.tur]}' olayı dikkate alınmadı.")

    for e in durumlar:
        son = e.sabit[-1]
        e.konum = (son.enlem, son.boylam)
        e.hazir_dk = max(an_dk, son.varis_dk if e.dondu else son.ayrilis_dk)
        hedef = e._sonraki
        if hedef is not None and son.ayrilis_dk < an_dk < hedef.varis_dk:
            # Ekip yolda: konumu iki durak arasında, geçen süre oranında (düz çizgi) tahmin edilir.
            oran = (an_dk - son.ayrilis_dk) / (hedef.varis_dk - son.ayrilis_dk)
            e.konum = (son.enlem + oran * (hedef.enlem - son.enlem), son.boylam + oran * (hedef.boylam - son.boylam))
            e.yolda = hedef.ad
        son_lab = max((i for i, d in enumerate(e.sabit) if d.tur == "7M Hastanesi"), default=-1)
        e.tasinan_kan = sum(d.tur == "Hasta" and d.kan_alimi for d in e.sabit[son_lab + 1:])
    return durumlar, uyarilar


def kalan_ziyaretler(durumlar: list[EkipDurumu], olaylar: list[Olay]) -> pd.DataFrame:
    """Yeniden atanacak hastalar: sabah planının kalanı + acil hastalar."""
    satirlar = []
    for e in durumlar:
        for d in e.kalan:
            if d.tur == "Hasta":
                satirlar.append(dict(hasta_kodu=d.ad, enlem=d.enlem, boylam=d.boylam,
                                     sure_dk=d.ayrilis_dk - d.varis_dk + e.ek_sure.get(d.ad, 0),
                                     kan_alimi=d.kan_alimi, islemler=d.islemler, eski_ekip=e.ekip_no, acil=False))
    for o in olaylar:
        if o.tur != "acil":
            continue
        eski = next((e.ekip_no for e in durumlar for d in e.kalan if d.ad == o.hasta_kodu), None)
        satirlar = [s for s in satirlar if s["hasta_kodu"] != o.hasta_kodu]
        satirlar.append(dict(hasta_kodu=o.hasta_kodu, enlem=o.enlem, boylam=o.boylam, sure_dk=o.sure_dk,
                             kan_alimi=o.kan_alimi, islemler=ACIL_ON_EKI + o.islemler, eski_ekip=eski, acil=True))
    return pd.DataFrame(satirlar, columns=["hasta_kodu", "enlem", "boylam", "sure_dk", "kan_alimi", "islemler",
                                           "eski_ekip", "acil"])


# ---------------------------------------------------------------------------
# 2. Yeniden çözüm
# ---------------------------------------------------------------------------
def revize_et(plan: Sonuc, an_dk: int, tamamlanan: set[str], olaylar: list[Olay],
              merkez, lab, sure_limiti_sn: int = 10) -> RevizyonSonucu:
    durumlar, uyarilar = durum_cikar(plan, an_dk, tamamlanan, olaylar)
    z = kalan_ziyaretler(durumlar, olaylar).reset_index(drop=True)
    E, n = len(durumlar), len(z)

    kan = [i for i in range(n) if bool(z.loc[i, "kan_alimi"])]
    tasiyan = [k for k, e in enumerate(durumlar) if e.tasinan_kan]
    # Düğümler: 0 merkez (dönüş) | 1..E ekip başlangıçları | hastalar | yeni kanların 7M kopyaları |
    #           araçtaki kanlar için ekibe özel 7M düğümleri
    ilk_hasta, ilk_kopya = 1 + E, 1 + E + n
    ilk_tasinan = ilk_kopya + len(kan)
    noktalar = ([merkez] + [e.konum for e in durumlar] + list(zip(z["enlem"], z["boylam"]))
                + [lab] * (len(kan) + len(tasiyan)))
    tur = ["Merkez"] + ["Başlangıç"] * E + ["Hasta"] * n + ["7M Hastanesi"] * (len(kan) + len(tasiyan))
    hizmet = [0] * (1 + E) + [int(s) for s in z["sure_dk"]] + [0] * (len(kan) + len(tasiyan))
    eski_ekip = [None] * (1 + E) + [None if pd.isna(x) else int(x) - 1 for x in z["eski_ekip"]] \
        + [None] * (len(kan) + len(tasiyan))
    tup = [0] * ilk_kopya + [1] * len(kan) + [durumlar[k].tasinan_kan for k in tasiyan]
    yol = mesafe.sure_matrisi(noktalar)

    lab_suresi = ayarlar.KAN_TESLIM_SURESI_DK
    hedef = ayarlar.dakika(ayarlar.KAN_TESLIM_SON_SAAT) - lab_suresi
    son = hedef + ayarlar.KAN_TESLIM_ESNEKLIK_DK

    def model_kur():
        manager = pywrapcp.RoutingIndexManager(len(noktalar), E, [1 + k for k in range(E)], [0] * E)
        routing = pywrapcp.RoutingModel(manager)
        solver = routing.solver()
        geri_cagrilar = []

        for k in range(E):  # yol + ekip değiştiren hasta için değişiklik cezası
            def maliyet(fi, ti, k=k):
                i, j = manager.IndexToNode(fi), manager.IndexToNode(ti)
                ceza = (ayarlar.DEGISIKLIK_CEZASI_DK
                        if tur[j] == "Hasta" and eski_ekip[j] is not None and eski_ekip[j] != k else 0)
                return ayarlar.AGIRLIK_TOPLAM_YOL * yol[i][j] + ceza
            geri_cagrilar.append(maliyet)
            routing.SetArcCostEvaluatorOfVehicle(routing.RegisterTransitCallback(maliyet), k)

        def zaman_cb(fi, ti):
            i, j = manager.IndexToNode(fi), manager.IndexToNode(ti)
            ek = lab_suresi if tur[i] == "7M Hastanesi" and tur[j] != "7M Hastanesi" else 0
            return hizmet[i] + yol[i][j] + ek
        geri_cagrilar.append(zaman_cb)

        routing.AddDimension(routing.RegisterTransitCallback(zaman_cb), 0, 24 * 60, False, "Zaman")
        zaman = routing.GetDimensionOrDie("Zaman")
        for k, e in enumerate(durumlar):
            zaman.CumulVar(routing.Start(k)).SetRange(e.hazir_dk, e.hazir_dk)
        zaman.SetGlobalSpanCostCoefficient(ayarlar.AGIRLIK_EN_GEC_BITIS)

        for i in range(n):
            idx = manager.NodeToIndex(ilk_hasta + i)
            routing.AddDisjunction([idx], ATLAMA_CEZASI)
            if bool(z.loc[i, "acil"]):  # acil hastanın olaydan varışa kadar beklediği her dakika cezalı
                zaman.SetCumulVarSoftUpperBound(idx, an_dk, ayarlar.ACIL_BEKLEME_AGIRLIGI)

        for t, i in enumerate(kan):  # yeni kan alımları: alım-teslim çifti (sabah modeliyle aynı)
            alim, teslim = manager.NodeToIndex(ilk_hasta + i), manager.NodeToIndex(ilk_kopya + t)
            routing.AddDisjunction([teslim], 0)
            routing.AddPickupAndDelivery(alim, teslim)
            solver.Add(routing.ActiveVar(alim) == routing.ActiveVar(teslim))
            solver.Add(routing.VehicleVar(alim) == routing.VehicleVar(teslim))
            solver.Add(zaman.CumulVar(alim) <= zaman.CumulVar(teslim))
            if not bool(z.loc[i, "acil"]):  # acil hasta kan sınırı yüzünden atlanmasın: yalnızca cezalı
                zaman.CumulVar(teslim).SetMax(son)
            zaman.SetCumulVarSoftUpperBound(teslim, hedef, ayarlar.KAN_GECIKME_CEZASI)

        for s, k in enumerate(tasiyan):  # araçtaki kanlar: aynı ekip mutlaka teslim eder
            idx = manager.NodeToIndex(ilk_tasinan + s)
            routing.VehicleVar(idx).SetValue(k)
            en_erken = durumlar[k].hazir_dk + yol[1 + k][ilk_tasinan + s]
            zaman.CumulVar(idx).SetMax(max(son, en_erken))  # yetişmiyorsa en erken varış (uyarı verilir)
            zaman.SetCumulVarSoftUpperBound(idx, hedef, ayarlar.KAN_GECIKME_CEZASI * durumlar[k].tasinan_kan)
        return manager, routing, zaman, geri_cagrilar

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(max(2, sure_limiti_sn // 2))

    adaylar = []
    for baslangictan in (False, True):
        manager, routing, zaman, _cb = model_kur()
        if baslangictan:  # sabah planının kalan sırası (acil hasta hariç) başlangıç çözümü
            ilk = routing.ReadAssignmentFromRoutes(_eski_sira(durumlar, z, kan, tasiyan, ilk_hasta, ilk_kopya,
                                                              ilk_tasinan, manager), True)
            cozum = routing.SolveFromAssignmentWithParameters(ilk, params) if ilk is not None else None
        else:
            cozum = routing.SolveWithParameters(params)
        if cozum is not None:
            adaylar.append((cozum.ObjectiveValue(),
                            _oku(cozum, manager, routing, zaman, durumlar, z, noktalar, tur, hizmet, tup,
                                 ilk_hasta, lab_suresi)))
    if not adaylar:
        raise RuntimeError("Yeni rota bulunamadı (kısıtlar sağlanamıyor).")
    yeni_rotalar, atlanan = min(adaylar, key=lambda a: a[0])[1]

    sonuc = Sonuc(yeni_rotalar, list(plan.atlanan) + atlanan, True)
    degisen, acil_varis = [], {}
    for k, r in enumerate(yeni_rotalar, start=1):
        sabit_sayisi = len(durumlar[k - 1].sabit)
        for d in r.duraklar[sabit_sayisi:]:
            if d.tur != "Hasta":
                continue
            satir = z[z["hasta_kodu"] == d.ad].iloc[0]
            if satir["acil"]:
                acil_varis[d.ad] = d.varis_dk
            eski = None if pd.isna(satir["eski_ekip"]) else int(satir["eski_ekip"])
            if eski != k:
                degisen.append((d.ad, eski, k))

    for e in durumlar:
        if e.tasinan_kan:
            r = yeni_rotalar[e.ekip_no - 1]
            teslim = r.kan_teslim_dk
            if teslim and teslim > son + lab_suresi:
                uyarilar.append(f"Ekip {e.ekip_no}: araçtaki {e.tasinan_kan} kan örneği en erken {saat(teslim)}'te "
                                f"teslim edilebiliyor ({ayarlar.KAN_TESLIM_SON_SAAT} + "
                                f"{ayarlar.KAN_TESLIM_ESNEKLIK_DK} dk sınırı aşılıyor).")
    for kod, varis in acil_varis.items():
        bekleme = varis - an_dk
        if bekleme > ayarlar.ACIL_HEDEF_DK:
            uyarilar.append(f"Acil hasta {kod}: varış {saat(varis)}, olaydan {bekleme} dk sonra "
                            f"(hedef en fazla {ayarlar.ACIL_HEDEF_DK} dk).")
    nedenler = {}
    for kod in atlanan:
        satir = z[z["hasta_kodu"] == kod].iloc[0]
        nedenler[kod] = ("Kan teslimi artık en geç saate yetişmiyor; bugün başka bir ekip de alamıyor."
                         if satir["kan_alimi"] else "Kalan sürede hiçbir rotaya sığdırılamadı.")
    return RevizyonSonucu(sonuc, durumlar, degisen, acil_varis, uyarilar, nedenler)


def _eski_sira(durumlar, z, kan, tasiyan, ilk_hasta, ilk_kopya, ilk_tasinan, manager):
    """Sabah planının kalan sırasını başlangıç rotalarına çevirir (acil hastalar dahil edilmez)."""
    dugum = {z.loc[i, "hasta_kodu"]: ilk_hasta + i for i in range(len(z)) if not z.loc[i, "acil"]}
    kopya = {ilk_hasta + i: ilk_kopya + t for t, i in enumerate(kan)}
    rotalar = []
    for k, e in enumerate(durumlar):
        sira, bekleyen = [], []
        tasinan = ilk_tasinan + tasiyan.index(k) if k in tasiyan else None
        for d in e.kalan:
            if d.tur == "Hasta" and d.ad in dugum:
                sira.append(dugum[d.ad])
                if dugum[d.ad] in kopya:
                    bekleyen.append(kopya[dugum[d.ad]])
            elif d.tur == "7M Hastanesi":
                if tasinan is not None:
                    sira.append(tasinan)
                    tasinan = None
                sira += bekleyen
                bekleyen = []
        if tasinan is not None:
            sira.append(tasinan)
        sira += bekleyen
        rotalar.append([manager.NodeToIndex(x) for x in sira])
    return rotalar


def _oku(cozum, manager, routing, zaman, durumlar, z, noktalar, tur, hizmet, tup, ilk_hasta, lab_suresi):
    rotalar = []
    for k, e in enumerate(durumlar):
        duraklar = [copy.copy(d) for d in e.sabit]
        km = sum(mesafe.yol_km((a.enlem, a.boylam), (b.enlem, b.boylam)) for a, b in zip(duraklar, duraklar[1:]))
        km += mesafe.yol_km((duraklar[-1].enlem, duraklar[-1].boylam), e.konum)  # yoldaysa alınan yol
        yeni = []
        idx = routing.Start(k)
        onceki = manager.IndexToNode(idx)
        idx = cozum.Value(routing.NextVar(idx))
        while True:
            node = manager.IndexToNode(idx)
            varis = cozum.Value(zaman.CumulVar(idx))
            km += mesafe.yol_km(noktalar[onceki], noktalar[node])
            if tur[node] == "Merkez":
                yeni.append(Durak("Merkez", ayarlar.MERKEZ["ad"], *noktalar[node], varis,
                                  varis + ayarlar.MERKEZ_DONUS_SURESI_DK))
            elif tur[node] == "Hasta":
                h = z.loc[node - ilk_hasta]
                yeni.append(Durak("Hasta", h["hasta_kodu"], *noktalar[node], varis, varis + hizmet[node],
                                  h["islemler"], bool(h["kan_alimi"])))
            else:
                if yeni and yeni[-1].tur == "7M Hastanesi":
                    yeni[-1].tup_sayisi += tup[node]
                else:
                    yeni.append(Durak("7M Hastanesi", ayarlar.KAN_TESLIM_YERI["ad"], *noktalar[node], varis,
                                      varis + lab_suresi, tup_sayisi=tup[node]))
            if routing.IsEnd(idx):
                break
            onceki = node
            idx = cozum.Value(routing.NextVar(idx))

        if e.dondu:
            if len(yeni) == 1:  # yeni iş yok: ekip zaten merkezde, plan aynen kalır
                yeni = []
            else:  # merkeze dönmüş ekip yeniden çıkıyor: önceki dönüş durağı ara durak olur
                duraklar[-1].ayrilis_dk = duraklar[-1].varis_dk
        duraklar += yeni
        r = EkipRotasi(f"Ekip {e.ekip_no}", duraklar, round(km, 2), duraklar[-1].ayrilis_dk)
        rotalar.append(r)

    atlanan = [z.loc[i, "hasta_kodu"] for i in range(len(z))
               if cozum.Value(routing.NextVar(manager.NodeToIndex(ilk_hasta + i))) == manager.NodeToIndex(ilk_hasta + i)]
    return rotalar, atlanan


# ---------------------------------------------------------------------------
# Yardımcılar (ekranlar için)
# ---------------------------------------------------------------------------
def durum_tablosu(durumlar: list[EkipDurumu], an_dk: int) -> pd.DataFrame:
    satirlar = []
    for e in durumlar:
        son = e.sabit[-1]
        if e.dondu:
            nerede = "Merkeze döndü"
        elif son.tur == "Merkez":
            nerede = "Merkezde (henüz çıkmadı)"
        elif son.ayrilis_dk > an_dk:
            nerede = f"{son.ad} · devam ediyor ({saat(son.ayrilis_dk)}'e kadar)"
        elif e.yolda:
            nerede = f"Yolda: {son.ad} → {e.yolda}"
        else:
            nerede = f"{son.ad} (bitti)"
        satirlar.append({
            "Ekip": f"Ekip {e.ekip_no}",
            "Konum (son durak)": nerede,
            "Yeni işe hazır": saat(e.hazir_dk),
            "Tamamlanan": ", ".join(e.tamamlanan) or "–",
            "Kalan hasta": sum(d.tur == "Hasta" for d in e.kalan),
            "Araçtaki kan": e.tasinan_kan or "–",
        })
    return pd.DataFrame(satirlar)
