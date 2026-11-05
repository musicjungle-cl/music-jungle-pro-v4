from types import SimpleNamespace as NS
import mj_logic as mj


def test_formato_y_categoria():
    assert mj.build_formato_simplificado({"name": "Vinyl", "descriptions": ["LP", "Album"], "qty": "1"}) == "LP, Album"
    assert mj.build_formato_simplificado({"name": "Vinyl", "descriptions": ["LP", "Compilation"], "qty": "2"}) == "2xLP, Compilation"
    assert mj.build_formato_simplificado({"name": "Vinyl", "descriptions": ['12"', "EP"], "qty": "1"}) == '12", EP'
    assert mj.build_formato_simplificado({"name": "CD", "descriptions": ["Album"], "qty": "3"}) == "3xCD, Album"
    assert mj.build_formato_simplificado({"name": "Cassette", "descriptions": []}) == "Cassette, Album"
    assert mj.categoria_from_format("Vinyl", ["LP"]) == "Vinilo"
    assert mj.categoria_from_format("CD", ["Album"]) == "CD"
    assert mj.categoria_from_format("Cassette", []) == "Cassette"
    assert mj.categoria_from_format("DVD", []) == "DVD"


def test_pais():
    assert mj.normalize_country("Europe") == "Europe"
    assert mj.normalize_country("US & Canada") == "US"
    assert mj.normalize_country("UK, Europe & US") == "Europe"
    assert mj.normalize_country("Japan") == "Japan"
    assert mj.normalize_country("Chile") == "Chile"
    assert mj.normalize_country("") == ""


def test_nombre_ficha():
    f = mj.build_product_name
    assert f("John Coltrane", "My Favorite Things", "Vinilo", "LP, Album", "Europe", "2018") == \
        "John Coltrane - My Favorite Things (Vinilo, Ed. Europe, 2018)"
    assert f("A", "B", "Vinilo", "2xLP, Album", "Europe", "2021") == "A - B (Vinilo, 2LP, Ed. Europe, 2021)"
    assert f("A", "B", "CD", "2xCD, Album", "US", "2009") == "A - B (2 CD, Ed. US, 2009)"
    assert f("A", "B", "CD", "CD, Album", "", "") == "A - B (CD)"
    assert f("A", "B", "Vinilo", '12", EP', "UK", 1999) == 'A - B (Vinilo, 12", Ed. UK, 1999)'


def test_precio_encargo():
    assert mj.precio_encargo(13900) == 28900        # ejemplo real de la skill
    assert mj.precio_encargo(0) is None
    assert mj.precio_encargo(None) is None
    assert mj.precio_encargo(float("nan")) is None
    # siempre termina en 900 y nunca queda bajo costo*1,7*1,19
    for c in range(1000, 90000, 777):
        p = mj.precio_encargo(c)
        assert p % 1000 == 900 and p >= c * 1.7 * 1.19 and p - c * 1.7 * 1.19 < 1000


def test_condiciones_y_comentarios():
    assert mj.condiciones_para("Nuevo", "Very Good (VG)") == ("Mint (M)", "Mint (M)")
    assert mj.condiciones_para("Usado", "Very Good Plus (VG+)") == ("Very Good Plus (VG+)",) * 2
    assert mj.build_comentario("Nuevo", "MusicJungleCL", "Vinilo") == "Vinilo nuevo, sellado. COPIAS LIMITADAS"
    assert mj.build_comentario("Nuevo", "PMS", "CD") == "[code_snippet id=42]\nCD nuevo, sellado. DISPONIBLE EN 5 DÍAS HÁBILES"
    assert mj.build_comentario("Nuevo", "DAAM", "Vinilo").startswith("[code_snippet id=42]")
    assert mj.build_comentario("Usado", "Vintage Jungle", "CD") == "[code_snippet id=28] Disco en excelente estado. COPIA ÚNICA."


def test_parse_inputs():
    assert mj.parse_inputs("123\n456, 789;123  ABC 1") == ["123", "456", "789", "ABC", "1"]
    assert mj.is_barcode("602557340846") and not mj.is_barcode("CAD2821") and not mj.is_barcode("12345")


def rel(country, year, have=0, catno="X"):
    return NS(country=country, year=year, labels=[NS(catno=catno)], images=[1], formats=[1],
              data={"community": {"have": have}})


def test_mejor_release():
    us, eu, cl = rel("US", 2020), rel("Europe", 2018), rel("Chile", 2018)
    assert mj.pick_best_release([us, eu, cl]) is eu          # Europe > Chile > otros
    assert mj.pick_best_release([us, cl]) is cl
    assert mj.pick_best_release([eu, us], origin="USA/Canadá") is us   # el origen pedido manda
    assert mj.pick_best_release([]) is None


def test_fetch_discogs_429_y_exito():
    class Rel(NS): pass
    r = Rel(id=1, title="T", artists=[NS(name="Artista (2)")], year=2018, country="Europe",
            labels=[NS(name="Sello (3)", catno="C1")], images=[{"uri": "http://img/full.jpg"}], thumb="t",
            formats=[{"name": "Vinyl", "descriptions": ["LP", "Album"], "qty": "1"}], styles=["Hard Bop"], genres=["Jazz"],
            tracklist=[NS(position="A1", title="Uno"), NS(position="A2", title="")], data={})
    calls = {"n": 0}
    class C:
        def search(self, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Exception("429 Too Many Requests")
            assert kw == {"barcode": "5060397601469", "type": "release"}
            return [r]
    waits = []
    out = mj.fetch_discogs(C(), "5060397601469", sleep=waits.append)
    assert 61 in waits
    assert out["Artista"] == "Artista" and out["Discográfica"] == "Sello" and out["Formato"] == "LP, Album"
    assert out["Categoría"] == "Vinilo" and out["País"] == "Europe" and out["Año"] == "2018"
    assert out["Link fotos"] == "http://img/full.jpg" and out["Tags"] == "Hard Bop"
    assert out["Tracklist"] == "<table><tr><td>A1</td><td>Uno</td></tr></table>"

    class Always429:
        def search(self, **kw): raise Exception("429")
    assert mj.fetch_discogs(Always429(), "5060397601469", sleep=lambda s: None) == mj.RATE_LIMIT
    assert mj.fetch_discogs(None, "1") is None


def test_catno_desde_data():
    r = NS(id=2, title="T", artists=[NS(name="A")], year=2018, country="Europe",
           labels=[NS(name="Sello", data={"catno": "CATLP146"})], images=[], thumb="t",
           formats=[{"name": "Vinyl", "descriptions": ["LP"], "qty": "1"}], styles=[], genres=["Jazz"],
           tracklist=[], data={"catno": "OTRO"})
    assert mj.release_to_row(r, "5060397601469")["Cat No"] == "CATLP146"
    r.labels = [NS(name="Sello", data={})]
    assert mj.release_to_row(r, "5060397601469")["Cat No"] == "OTRO"
    assert mj.release_to_row(r, "ABC1")["Cat No"] == "OTRO"


def test_fila_final_y_enriquecimiento():
    mb = {"Barcode": "602557340846", "Cat No": "", "Artista": "Aqua", "Título": "Aquarium", "Categoría": "", "Formato": "",
          "País": "", "Año": "1997", "Fuente": "MusicBrainz", "Needs_Enrichment": True}
    row = mj.finalize_row(mb, item="602557340846", vendedor="DAAM", estado="Nuevo", condicion_usado="Mint (M)",
                          shipping_class="por-encargo", costo=13900)
    assert row["Vendedor ID"] == 6086 and row["Precio"] == 28900 and row["PDC"] == 13900
    assert row["Condición Disco"] == "Mint (M)"
    enr = {"Categoría": "Vinilo", "Formato": "LP, Album", "País": "Europe", "Año": "2017", "Needs_Enrichment": False}
    mj.apply_enrichment(row, enr)
    assert row["Nombre ficha"] == "Aqua - Aquarium (Vinilo, Ed. Europe, 2017)" and row["Categoría WC"] == 83
    assert "Vinilo nuevo, sellado. DISPONIBLE EN 5 DÍAS HÁBILES" in row["Comentario"]


def test_duplicados():
    class R:
        def __init__(self, code, body): self.status_code, self._b = code, body
        def json(self): return self._b
    ok = lambda body, code=200: (lambda *a, **k: R(code, body))
    prod = {"id": 7, "status": "publish", "name": "X", "global_unique_id": "111"}
    assert mj.check_duplicate("111", "https://x", "k", "s", http_get=ok([prod]))[0] == "existe"
    assert mj.check_duplicate("222", "https://x", "k", "s", http_get=ok([prod]))[0] == "libre"   # search difuso != barcode exacto
    assert mj.check_duplicate("111", "https://x", "k", "s", http_get=ok([], 403)) == ("error", "HTTP 403")
    def boom(*a, **k): raise TimeoutError()
    assert mj.check_duplicate("111", "https://x", "k", "s", http_get=boom) == ("error", "TimeoutError")


def test_avisos_vendedor():
    assert mj.vendor_warnings("MusicJungleCL", "Usado")
    assert mj.vendor_warnings("Vintage Jungle", "Nuevo")
    assert not mj.vendor_warnings("MusicJungleCL", "Nuevo")
