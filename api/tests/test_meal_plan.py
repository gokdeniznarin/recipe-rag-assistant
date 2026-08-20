"""Meal Planner testleri.

Katman 1 — saf fonksiyonlar. Ağırlık `week_start_for`'da: doküman ID'sini o
belirliyor, yani okuma ve yazma aynı sonucu vermezse veri iki ayrı dokümana
bölünür ve kullanıcı planını kaybetmiş gibi görünür. Off-by-one'a en açık yer.

Katman 1.5 — slot yazma mantığı (sahte Firestore dokümanı): dolu slota yazmanın
ÜZERİNE YAZDIĞI ve komşu slotları bozmadığı burada doğrulanıyor.

Katman 2 — endpoint sözleşmesi (auth, include_details kart eşleme, hafta
normalizasyonu, yıkıcı yolun ayrı olması).

    python -m pytest api/tests/test_meal_plan.py -v
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from meal_plan import (
    SLOTS,
    week_start_for,
    validate_date,
    validate_slot,
    validate_week,
    upsert_entry,
    sort_entries,
    MAX_YEARS_AHEAD,
)


def _iso(days_from_today: int = 0) -> str:
    """Bugüne göre bir tarih — aralık sınırına takılmayan test verisi için."""
    return (datetime.now(timezone.utc).date() + timedelta(days=days_from_today)).isoformat()


# ── Katman 1: hafta hesabı ────────────────────────────────
# Doküman ID'si buna bağlı; okuma ile yazma ayrışırsa plan kaybolur.

class TestWeekStartFor:
    def test_monday_maps_to_itself(self):
        # 2026-07-27 bir pazartesi
        assert week_start_for("2026-07-27") == "2026-07-27"

    def test_midweek_maps_back_to_monday(self):
        assert week_start_for("2026-07-30") == "2026-07-27"   # perşembe

    def test_sunday_belongs_to_the_week_that_started_monday(self):
        # ISO 8601: pazar haftanın SON günü, bir sonrakinin ilki değil.
        # En klasik off-by-one burada.
        assert week_start_for("2026-08-02") == "2026-07-27"

    def test_next_monday_starts_a_new_week(self):
        assert week_start_for("2026-08-03") == "2026-08-03"

    def test_crosses_month_boundary(self):
        assert week_start_for("2026-08-01") == "2026-07-27"   # cumartesi

    def test_crosses_year_boundary(self):
        # 2027-01-01 bir cuma → haftası 2026'da başlıyor
        assert week_start_for("2027-01-01") == "2026-12-28"

    def test_leap_day(self):
        # 2028-02-29 bir salı
        assert week_start_for("2028-02-29") == "2028-02-28"

    def test_all_days_of_a_week_give_the_same_answer(self):
        # Asıl güvence: aynı haftanın 7 günü TEK bir dokümana yönelmeli.
        # (27-31 Temmuz + 1-2 Ağustos = pazartesiden pazara)
        week = [f"2026-07-{d}" for d in range(27, 32)] + ["2026-08-01", "2026-08-02"]
        assert {week_start_for(d) for d in week} == {"2026-07-27"}

    def test_idempotent(self):
        # Hafta başını tekrar geçirmek aynı sonucu vermeli (validate_week
        # bunu zincirliyor).
        once = week_start_for("2026-07-30")
        assert week_start_for(once) == once

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            week_start_for("not-a-date")


# ── Katman 1: tarih doğrulama ─────────────────────────────

class TestValidateDate:
    def test_accepts_iso_date(self):
        assert validate_date(_iso(3)) == _iso(3)

    def test_rejects_unpadded_parts(self):
        # `2026-7-4` REDDEDİLİYOR: date.fromisoformat sıfır dolgusu istiyor.
        # Kabul edilebilir bir katılık — frontend her zaman dolgulu üretiyor
        # (plan.js `padStart`), ve belirsiz biçimi sessizce kabul etmektense
        # net bir mesaj vermek doğru.
        with pytest.raises(ValueError):
            validate_date("2026-7-4")

    def test_trims_whitespace(self):
        assert validate_date(f"  {_iso()}  ") == _iso()

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            validate_date("tomorrow")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_date("")

    def test_rejects_none(self):
        with pytest.raises(ValueError):
            validate_date(None)

    def test_rejects_impossible_calendar_date(self):
        with pytest.raises(ValueError):
            validate_date("2026-02-30")

    def test_rejects_far_future(self):
        # `year=9999` gibi çöp dokümanlar açılmasın
        with pytest.raises(ValueError):
            validate_date("9999-01-01")

    def test_rejects_far_past(self):
        with pytest.raises(ValueError):
            validate_date("1990-01-01")

    def test_accepts_months_ahead(self):
        assert MAX_YEARS_AHEAD >= 1
        ahead = _iso(300)                 # sınırın rahatça içinde
        assert validate_date(ahead) == ahead

    def test_unbounded_accepts_far_dates(self):
        # Sınırın amacı ÇÖP DOKÜMAN açılmasını engellemek — yani yalnızca yazma
        # ile ilgili. Okuma/silme yollarında uygulansaydı bir yıldan eski
        # planlar zamanla ne görüntülenebilir ne silinebilir olurdu.
        assert validate_date("2001-05-06", bounded=False) == "2001-05-06"
        assert validate_date("2099-05-06", bounded=False) == "2099-05-06"

    def test_unbounded_still_rejects_garbage(self):
        with pytest.raises(ValueError):
            validate_date("whenever", bounded=False)

    def test_bounds_use_day_arithmetic_not_replace_year(self, monkeypatch):
        # REGRESYON: sınır `today.replace(year=...)` ile hesaplanıyordu ve
        # 29 ŞUBAT'ta ValueError fırlatırdı — o gün HİÇBİR tarih kabul
        # edilmezdi. Bugünü artık güne sabitleyip normal bir tarihin hâlâ
        # geçtiğini doğruluyoruz.
        import meal_plan as mp

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2028, 2, 29, 12, 0, tzinfo=tz)

        monkeypatch.setattr(mp, "datetime", _FrozenDatetime)
        assert validate_date("2028-03-05") == "2028-03-05"


class TestValidateSlot:
    @pytest.mark.parametrize("slot", SLOTS)
    def test_accepts_known_slots(self, slot):
        assert validate_slot(slot) == slot

    def test_case_insensitive(self):
        assert validate_slot("Dinner") == "dinner"

    def test_trims(self):
        assert validate_slot("  lunch ") == "lunch"

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            validate_slot("brunch")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_slot("")

    def test_slots_match_the_frontend_copy(self):
        # DRIFT KORUMASI: frontend/js/plan.js aynı listeyi SABİT olarak taşıyor
        # (3 elemanlı bir sabit için her sayfa açılışına ağ turu bindirmemek
        # üzere bilinçli kopya). Burası değişirse bu test kırılır ve plan.js'in
        # de güncellenmesini zorlar.
        assert SLOTS == ("breakfast", "lunch", "dinner")


class TestValidateWeek:
    def test_normalizes_to_monday(self):
        # İstemci haftanın ortasından bir tarih gönderirse aynı haftanın
        # dokümanına yönelmeli — yoksa aynı hafta iki yere bölünür.
        assert validate_week("2026-07-30") == "2026-07-27"

    def test_monday_passes_through(self):
        assert validate_week("2026-07-27") == "2026-07-27"

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            validate_week("week-31")

    def test_accepts_weeks_outside_the_write_bound(self):
        # Hafta parametresi hiç doküman AÇMIYOR (okuma / temizleme) — kullanıcı
        # istediği kadar geriye gidebilmeli.
        assert validate_week("2001-05-06") == "2001-04-30"


# ── Katman 1: slot yazma / sıralama ───────────────────────

class TestUpsertEntry:
    def test_adds_to_empty(self):
        out = upsert_entry([], "2026-07-27", "dinner", "17450")
        assert len(out) == 1
        assert out[0]["recipe_id"] == "17450"

    def test_replaces_occupied_slot(self):
        entries = upsert_entry([], "2026-07-27", "dinner", "17450")
        entries = upsert_entry(entries, "2026-07-27", "dinner", "37913")
        assert len(entries) == 1                       # eskisi kalmadı
        assert entries[0]["recipe_id"] == "37913"

    def test_does_not_touch_other_slots(self):
        entries = upsert_entry([], "2026-07-27", "dinner", "17450")
        entries = upsert_entry(entries, "2026-07-27", "lunch", "37913")
        by_slot = {e["slot"]: e["recipe_id"] for e in entries}
        assert by_slot == {"dinner": "17450", "lunch": "37913"}

    def test_does_not_touch_other_days(self):
        entries = upsert_entry([], "2026-07-27", "dinner", "17450")
        entries = upsert_entry(entries, "2026-07-28", "dinner", "37913")
        assert len(entries) == 2

    def test_recipe_id_is_stringified(self):
        # ChromaDB ID'leri metin; sayı gelirse eşleştirme sessizce kaçardı.
        out = upsert_entry([], "2026-07-27", "dinner", 17450)
        assert out[0]["recipe_id"] == "17450"

    def test_same_recipe_can_appear_twice_in_the_week(self):
        entries = upsert_entry([], "2026-07-27", "dinner", "17450")
        entries = upsert_entry(entries, "2026-07-29", "lunch", "17450")
        assert len(entries) == 2

    def test_pure_does_not_mutate_input(self):
        original = upsert_entry([], "2026-07-27", "dinner", "17450")
        snapshot = list(original)
        upsert_entry(original, "2026-07-27", "dinner", "37913")
        assert original == snapshot


class TestSortEntries:
    def test_sorts_by_day_then_meal_order(self):
        entries = [
            {"date": "2026-07-28", "slot": "breakfast"},
            {"date": "2026-07-27", "slot": "dinner"},
            {"date": "2026-07-27", "slot": "breakfast"},
            {"date": "2026-07-27", "slot": "lunch"},
        ]
        out = [(e["date"], e["slot"]) for e in sort_entries(entries)]
        assert out == [
            ("2026-07-27", "breakfast"),
            ("2026-07-27", "lunch"),
            ("2026-07-27", "dinner"),      # alfabetik değil, ÖĞÜN sırası
            ("2026-07-28", "breakfast"),
        ]

    def test_unknown_slot_goes_last_instead_of_crashing(self):
        entries = [
            {"date": "2026-07-27", "slot": "supper"},
            {"date": "2026-07-27", "slot": "lunch"},
        ]
        assert sort_entries(entries)[0]["slot"] == "lunch"

    def test_empty(self):
        assert sort_entries([]) == []


# ── Katman 1.5: Firestore yazma mantığı (sahte doküman) ───
# MagicMock Firestore anlamlı davranış üretmediği için bu mantık aksi hâlde
# test edilemezdi (pantry'deki toplu ekleme testleriyle aynı desen).

class _FakeSnap:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return self._data


class _FakeRef:
    def __init__(self, data=None):
        self._data = data
        self.written = None

    def get(self):
        return _FakeSnap(self._data)

    def set(self, payload, merge=False):
        self.written = payload
        # Yazılanı geri okunabilir yap ki ardışık çağrılar gerçekçi olsun
        self._data = {**(self._data or {}), **payload}


class TestSetEntryStorage:
    def _fake_doc(self, monkeypatch, existing=None):
        import meal_plan as mp
        ref = _FakeRef({"entries": existing} if existing is not None else None)
        captured = {}
        monkeypatch.setattr(
            mp._plans, "document",
            lambda doc_id: (captured.update(doc_id=doc_id), ref)[1],
        )
        return ref, captured

    def test_doc_id_is_email_plus_week_monday(self, monkeypatch):
        import meal_plan as mp
        _, captured = self._fake_doc(monkeypatch)
        mp.set_entry("u@e.com", "2026-07-30", "dinner", "17450")   # perşembe
        assert captured["doc_id"] == "u@e.com_2026-07-27"          # pazartesi

    def test_writes_owner_and_week(self, monkeypatch):
        import meal_plan as mp
        ref, _ = self._fake_doc(monkeypatch)
        mp.set_entry("u@e.com", "2026-07-27", "lunch", "17450")
        assert ref.written["owner_email"] == "u@e.com"
        assert ref.written["week_start"] == "2026-07-27"

    def test_replacing_keeps_a_single_entry(self, monkeypatch):
        import meal_plan as mp
        ref, _ = self._fake_doc(
            monkeypatch, existing=[{"date": "2026-07-27", "slot": "dinner", "recipe_id": "17450"}]
        )
        result = mp.set_entry("u@e.com", "2026-07-27", "dinner", "37913")
        assert len(ref.written["entries"]) == 1
        assert result["entries"][0]["recipe_id"] == "37913"

    def test_returns_sorted_entries(self, monkeypatch):
        import meal_plan as mp
        self._fake_doc(
            monkeypatch, existing=[{"date": "2026-07-27", "slot": "dinner", "recipe_id": "1"}]
        )
        result = mp.set_entry("u@e.com", "2026-07-27", "breakfast", "2")
        assert [e["slot"] for e in result["entries"]] == ["breakfast", "dinner"]


class TestRemoveEntryStorage:
    def _fake_doc(self, monkeypatch, existing=None):
        import meal_plan as mp
        ref = _FakeRef({"entries": existing} if existing is not None else None)
        monkeypatch.setattr(mp._plans, "document", lambda doc_id: ref)
        return ref

    def test_removes_only_the_target_slot(self, monkeypatch):
        import meal_plan as mp
        ref = self._fake_doc(monkeypatch, existing=[
            {"date": "2026-07-27", "slot": "dinner", "recipe_id": "1"},
            {"date": "2026-07-27", "slot": "lunch", "recipe_id": "2"},
        ])
        mp.remove_entry("u@e.com", "2026-07-27", "dinner")
        assert [e["slot"] for e in ref.written["entries"]] == ["lunch"]

    def test_missing_slot_raises(self, monkeypatch):
        import meal_plan as mp
        self._fake_doc(monkeypatch, existing=[
            {"date": "2026-07-27", "slot": "lunch", "recipe_id": "2"},
        ])
        with pytest.raises(ValueError):
            mp.remove_entry("u@e.com", "2026-07-27", "dinner")

    def test_missing_document_raises(self, monkeypatch):
        import meal_plan as mp
        self._fake_doc(monkeypatch)
        with pytest.raises(ValueError):
            mp.remove_entry("u@e.com", "2026-07-27", "dinner")


class TestClearWeekStorage:
    def _fake_doc(self, monkeypatch, existing=None):
        import meal_plan as mp
        ref = _FakeRef({"entries": existing} if existing is not None else None)
        monkeypatch.setattr(mp._plans, "document", lambda doc_id: ref)
        return ref

    def test_returns_removed_count(self, monkeypatch):
        import meal_plan as mp
        self._fake_doc(monkeypatch, existing=[
            {"date": "2026-07-27", "slot": "lunch", "recipe_id": "1"},
            {"date": "2026-07-28", "slot": "dinner", "recipe_id": "2"},
        ])
        assert mp.clear_week("u@e.com", "2026-07-27") == 2

    def test_missing_document_returns_zero_without_writing(self, monkeypatch):
        import meal_plan as mp
        ref = self._fake_doc(monkeypatch)
        assert mp.clear_week("u@e.com", "2026-07-27") == 0
        assert ref.written is None


# ── Katman 2: auth sözleşmesi ─────────────────────────────

class TestMealPlanAuthContract:
    def test_get_requires_auth(self, client):
        assert client.get("/api/meal-plan?week=2026-07-27").status_code == 422

    def test_post_requires_auth(self, client):
        r = client.post("/api/meal-plan", json={
            "date": "2026-07-27", "slot": "dinner", "recipe_id": "17450",
        })
        assert r.status_code == 422

    def test_delete_requires_auth(self, client):
        r = client.delete("/api/meal-plan?date=2026-07-27&slot=dinner")
        assert r.status_code == 422

    def test_clear_week_requires_auth(self, client):
        assert client.delete("/api/meal-plan/week?week=2026-07-27").status_code == 422


# ── Katman 2: endpoint davranışı ──────────────────────────

class TestGetMealPlanEndpoint:
    def test_empty_week_skips_chromadb(self, auth_client, api, collection, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[]))
        r = auth_client.get("/api/meal-plan?week=2026-07-27&include_details=true")
        assert r.status_code == 200
        assert r.json()["entries"] == []
        assert not collection.get.called          # boş hafta → ChromaDB'ye gidilmiyor

    def test_include_details_attaches_recipe_card(self, auth_client, api, collection, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[
            {"date": "2026-07-27", "slot": "dinner", "recipe_id": "17450"},
        ]))
        r = auth_client.get("/api/meal-plan?week=2026-07-27&include_details=true")
        entry = r.json()["entries"][0]
        assert entry["recipe"]["name"] == "Test Recipe"
        assert entry["recipe"]["ingredients"] == [
            "chicken breast", "tomatoes", "olive oil", "garlic",
        ]

    def test_card_carries_every_macro_the_daily_total_needs(
        self, auth_client, api, collection, monkeypatch,
    ):
        """Plan sayfası her günün altına o günün besin toplamını yazıyor ve o
        toplamı KARTTAN hesaplıyor (ayrı bir istek yok).

        Bu dört alandan biri karttan düşerse hiçbir şey patlamaz — istek 200
        döner, ızgara çizilir, yalnızca ekrandaki toplam sessizce eksik ya da
        sıfır görünür. Tam da görülmesi zor olan bozulma bu.
        """
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[
            {"date": "2026-07-27", "slot": "dinner", "recipe_id": "17450"},
        ]))
        r = auth_client.get("/api/meal-plan?week=2026-07-27&include_details=true")
        card = r.json()["entries"][0]["recipe"]
        assert card["calories"] == 300.0
        assert card["protein_content"] == 25.0
        assert card["carbohydrate_content"] == 10.0
        assert card["fat_content"] == 5.0

    def test_without_details_no_chromadb_call(self, auth_client, api, collection, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[
            {"date": "2026-07-27", "slot": "dinner", "recipe_id": "17450"},
        ]))
        r = auth_client.get("/api/meal-plan?week=2026-07-27")
        assert not collection.get.called
        assert "recipe" not in r.json()["entries"][0]

    def test_deleted_recipe_becomes_none(self, auth_client, api, collection, monkeypatch):
        # Tarif veri setinden kalkmışsa slot None döner (favoriler/koleksiyonlarla
        # aynı davranış) — istek patlamaz.
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[
            {"date": "2026-07-27", "slot": "dinner", "recipe_id": "99999"},
        ]))
        collection.get.return_value = {"documents": [], "metadatas": [], "ids": []}
        r = auth_client.get("/api/meal-plan?week=2026-07-27&include_details=true")
        assert r.json()["entries"][0]["recipe"] is None

    def test_same_recipe_in_two_slots_is_fetched_once(self, auth_client, api, collection, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "get_week", MagicMock(return_value=[
            {"date": "2026-07-27", "slot": "lunch", "recipe_id": "17450"},
            {"date": "2026-07-29", "slot": "dinner", "recipe_id": "17450"},
        ]))
        r = auth_client.get("/api/meal-plan?week=2026-07-27&include_details=true")
        assert collection.get.call_args.kwargs["ids"] == ["17450"]   # tekilleştirilmiş
        assert all(e["recipe"]["name"] == "Test Recipe" for e in r.json()["entries"])

    def test_midweek_date_is_normalized_to_monday(self, auth_client, api, monkeypatch):
        main, _ = api
        get_week = MagicMock(return_value=[])
        monkeypatch.setattr(main, "get_week", get_week)
        r = auth_client.get("/api/meal-plan?week=2026-07-30")
        assert get_week.call_args.args[1] == "2026-07-27"
        assert r.json()["week_start"] == "2026-07-27"

    def test_invalid_week_returns_error_not_500(self, auth_client, api, monkeypatch):
        main, _ = api
        get_week = MagicMock()
        monkeypatch.setattr(main, "get_week", get_week)
        r = auth_client.get("/api/meal-plan?week=next-monday")
        assert r.status_code == 200
        assert "error" in r.json()
        assert not get_week.called          # Firestore'a HİÇ gidilmiyor

    def test_missing_week_param_is_422(self, auth_client):
        assert auth_client.get("/api/meal-plan").status_code == 422


class TestSetMealPlanEntryEndpoint:
    def test_happy_path(self, auth_client, api, monkeypatch):
        main, _ = api
        set_entry = MagicMock(return_value={"week_start": "2026-07-27", "entries": []})
        monkeypatch.setattr(main, "set_entry", set_entry)
        r = auth_client.post("/api/meal-plan", json={
            "date": "2026-07-30", "slot": "Dinner", "recipe_id": "17450",
        })
        assert r.status_code == 200
        # Slot normalize edilmiş halde katmana geçiyor
        assert set_entry.call_args.args[1:] == ("2026-07-30", "dinner", "17450")

    def test_invalid_slot_returns_error_without_writing(self, auth_client, api, monkeypatch):
        main, _ = api
        set_entry = MagicMock()
        monkeypatch.setattr(main, "set_entry", set_entry)
        r = auth_client.post("/api/meal-plan", json={
            "date": "2026-07-27", "slot": "brunch", "recipe_id": "17450",
        })
        assert r.status_code == 200
        assert "error" in r.json()
        assert not set_entry.called

    def test_invalid_date_returns_error_without_writing(self, auth_client, api, monkeypatch):
        main, _ = api
        set_entry = MagicMock()
        monkeypatch.setattr(main, "set_entry", set_entry)
        r = auth_client.post("/api/meal-plan", json={
            "date": "9999-01-01", "slot": "dinner", "recipe_id": "17450",
        })
        assert "error" in r.json()
        assert not set_entry.called

    def test_does_not_touch_favorites(self, auth_client, api, monkeypatch):
        # KOLEKSİYONLARDAN FARKI: plana eklemek favoriye EKLEMEZ. Koleksiyonlarda
        # add_favorite çağrılıyor; burada çağrılmamalı.
        main, _ = api
        add_favorite = MagicMock()
        monkeypatch.setattr(main, "add_favorite", add_favorite)
        monkeypatch.setattr(main, "set_entry", MagicMock(return_value={
            "week_start": "2026-07-27", "entries": [],
        }))
        auth_client.post("/api/meal-plan", json={
            "date": "2026-07-27", "slot": "dinner", "recipe_id": "17450",
        })
        assert not add_favorite.called

    def test_missing_field_is_422(self, auth_client):
        r = auth_client.post("/api/meal-plan", json={"date": "2026-07-27"})
        assert r.status_code == 422

    def test_overlong_recipe_id_is_422(self, auth_client):
        r = auth_client.post("/api/meal-plan", json={
            "date": "2026-07-27", "slot": "dinner", "recipe_id": "x" * 51,
        })
        assert r.status_code == 422


class TestRemoveMealPlanEntryEndpoint:
    def test_happy_path(self, auth_client, api, monkeypatch):
        main, _ = api
        remove = MagicMock()
        monkeypatch.setattr(main, "remove_entry", remove)
        r = auth_client.delete("/api/meal-plan?date=2026-07-27&slot=dinner")
        assert r.status_code == 200
        assert remove.call_args.args[1:] == ("2026-07-27", "dinner")

    def test_missing_slot_returns_error_not_500(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "remove_entry", MagicMock(
            side_effect=ValueError("There is nothing planned for that slot.")
        ))
        r = auth_client.delete("/api/meal-plan?date=2026-07-27&slot=dinner")
        assert r.status_code == 200
        assert "nothing planned" in r.json()["error"]

    def test_missing_params_is_422(self, auth_client):
        assert auth_client.delete("/api/meal-plan?date=2026-07-27").status_code == 422

    def test_old_entry_can_still_be_deleted(self, auth_client, api, monkeypatch):
        # REGRESYON: silme yolu da yazma sınırını uyguluyordu, yani bir yıldan
        # eski bir plan girdisi SİLİNEMEZ hale geliyordu.
        main, _ = api
        remove = MagicMock()
        monkeypatch.setattr(main, "remove_entry", remove)
        r = auth_client.delete("/api/meal-plan?date=2001-05-06&slot=dinner")
        assert r.status_code == 200
        assert remove.called

    def test_old_week_can_still_be_cleared(self, auth_client, api, monkeypatch):
        main, _ = api
        clear = MagicMock(return_value=2)
        monkeypatch.setattr(main, "clear_week", clear)
        r = auth_client.delete("/api/meal-plan/week?week=2001-05-06")
        assert r.json()["removed"] == 2


class TestClearWeekEndpoint:
    def test_returns_removed_count(self, auth_client, api, monkeypatch):
        main, _ = api
        monkeypatch.setattr(main, "clear_week", MagicMock(return_value=7))
        r = auth_client.delete("/api/meal-plan/week?week=2026-07-27")
        assert r.status_code == 200
        assert r.json()["removed"] == 7

    def test_week_route_does_not_fall_through_to_slot_delete(self, auth_client, api, monkeypatch):
        # "/api/meal-plan/week" LİTERAL yol; tekil silme yoluna düşmemeli
        # (pantry'deki /all ile aynı koruma).
        main, _ = api
        remove = MagicMock()
        monkeypatch.setattr(main, "remove_entry", remove)
        monkeypatch.setattr(main, "clear_week", MagicMock(return_value=0))
        auth_client.delete("/api/meal-plan/week?week=2026-07-27")
        assert not remove.called

    def test_normalizes_week_before_clearing(self, auth_client, api, monkeypatch):
        main, _ = api
        clear = MagicMock(return_value=0)
        monkeypatch.setattr(main, "clear_week", clear)
        auth_client.delete("/api/meal-plan/week?week=2026-08-02")   # pazar
        assert clear.call_args.args[1] == "2026-07-27"

    def test_invalid_week_returns_error_without_clearing(self, auth_client, api, monkeypatch):
        main, _ = api
        clear = MagicMock()
        monkeypatch.setattr(main, "clear_week", clear)
        r = auth_client.delete("/api/meal-plan/week?week=oops")
        assert "error" in r.json()
        assert not clear.called
