"""Hesap silme — veri gerçekten gidiyor mu, ve SIRA doğru mu.

Bu özellik geri alınamaz bir şey yapıyor, o yüzden iki soru testin merkezinde:
  1. HİÇBİR koleksiyon atlanıyor mu?  (drift testi — asıl koruma)
  2. Yarıda kalırsa kullanıcı kurtarılabilir durumda mı? (sıra testi)
"""
import ast
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parent.parent


# ── Sahte Firestore ──────────────────────────────────────
# MagicMock anlamlı davranış üretmiyor (Faz 16/17'de aynı gerekçeyle sahte
# doküman yazılmıştı): silinen doküman sayısını, batch sınırını ve pantry'nin
# dokümanının tamamen gitmesini ancak gerçek davranışla test edebiliriz.
class FakeSnap:
    def __init__(self, ref, exists=True):
        self.reference = ref
        self.exists = exists


class FakeDocRef:
    def __init__(self, db, collection, doc_id):
        self._db, self.collection, self.id = db, collection, doc_id

    def get(self):
        return FakeSnap(self, self.id in self._db.data.get(self.collection, {}))

    def delete(self):
        self._db.events.append(("delete_doc", self.collection, self.id))
        self._db.data.get(self.collection, {}).pop(self.id, None)


class FakeQuery:
    def __init__(self, db, collection, field, value):
        self._db, self.collection, self.field, self.value = db, collection, field, value

    def stream(self):
        self._db.queries.append((self.collection, self.field, self.value))
        for doc_id, doc in list(self._db.data.get(self.collection, {}).items()):
            if doc.get(self.field) == self.value:
                yield FakeSnap(FakeDocRef(self._db, self.collection, doc_id))


class FakeCollection:
    def __init__(self, db, name):
        self._db, self.name = db, name

    def where(self, filter=None):
        field, _op, value = filter          # account.FieldFilter tuple'a yamalandı
        return FakeQuery(self._db, self.name, field, value)

    def document(self, doc_id):
        return FakeDocRef(self._db, self.name, doc_id)


class FakeBatch:
    def __init__(self, db):
        self._db, self._pending = db, []

    def delete(self, ref):
        self._pending.append(ref)

    def commit(self):
        self._db.events.append(("commit", len(self._pending)))
        for ref in self._pending:
            self._db.data.get(ref.collection, {}).pop(ref.id, None)
        self._pending = []


class FakeDb:
    def __init__(self, data=None):
        self.data = data or {}
        self.events = []
        self.queries = []

    def collection(self, name):
        return FakeCollection(self, name)

    def batch(self):
        return FakeBatch(self)


class FakeUserNotFound(Exception):
    pass


class FakeAuth:
    """Kaydı silinen kullanıcıyı ve SIRAYI izleyen sahte Firebase Auth."""

    UserNotFoundError = FakeUserNotFound

    def __init__(self, db, exists=True):
        self._db, self._exists = db, exists
        self.deleted_uid = None

    def get_user_by_email(self, email):
        if not self._exists:
            raise FakeUserNotFound(email)
        return type("U", (), {"uid": "uid-" + email})()

    def delete_user(self, uid):
        self.deleted_uid = uid
        self._db.events.append(("delete_auth_user", uid))


EMAIL = "test@example.com"
OTHER = "someone.else@example.com"


def _seed():
    """İki kullanıcılı gerçekçi bir veri kümesi — komşunun verisine dokunulmamalı."""
    return {
        "favorites": {
            f"{EMAIL}_17450": {"user_email": EMAIL},
            f"{EMAIL}_37913": {"user_email": EMAIL},
            f"{OTHER}_17450": {"user_email": OTHER},
        },
        "collections": {
            "auto1": {"owner_email": EMAIL, "name": "Breakfast"},
            "auto2": {"owner_email": OTHER, "name": "Breakfast"},
        },
        "meal_plans": {
            f"{EMAIL}_2026-07-27": {"owner_email": EMAIL},
            f"{OTHER}_2026-07-27": {"owner_email": OTHER},
        },
        "shopping_lists": {
            f"{EMAIL}_2026-07-27": {"owner_email": EMAIL},
        },
        "pantry": {
            EMAIL: {"items": [{"name": "chicken"}]},
            OTHER: {"items": [{"name": "rice"}]},
        },
    }


@pytest.fixture
def account(api, monkeypatch):
    """(account modülü, sahte db, sahte auth) — gerçek silme mantığı çalışıyor."""
    import account as account_module

    db = FakeDb(_seed())
    fake_auth = FakeAuth(db)
    monkeypatch.setattr(account_module, "_db", db)
    monkeypatch.setattr(account_module, "firebase_auth", fake_auth)
    # Gerçek FieldFilter conftest'te MagicMock; sahte db'nin okuyabilmesi için
    # tuple üreten bir sürümle değiştiriliyor. Yan fayda: hangi ALANIN
    # sorgulandığını doğrulayabiliyoruz.
    monkeypatch.setattr(
        account_module, "FieldFilter", lambda field, op, value: (field, op, value)
    )
    return account_module, db, fake_auth


# ── 1. DRIFT: hiçbir koleksiyon atlanmasın ───────────────
class TestNoCollectionIsForgotten:
    """Bu özelliğin en olası ve en sinsi bozulma biçimi.

    Biri altıncı bir Firestore koleksiyonu eklediğinde silme listesine yazmayı
    unutursa hiçbir şey patlamaz: kullanıcı "hesabım silindi" mesajını görür,
    verisi Firestore'da durmaya devam eder. Sessiz, geri alınamaz ve tam da
    verdiğimiz sözün ihlali. O yüzden kaynak koddan doğrulanıyor.
    """

    def _collections_used_by_the_app(self) -> set[str]:
        """`x.collection("ad")` çağrılarını KAYNAK AĞACINDAN toplar.

        Metin araması denendi ve kendi belgesine takıldı: bu testi anlatan
        yorumun içindeki örnek de eşleşiyordu. `ast` yorumları ve docstring'leri
        hiç görmüyor, ayrıca `get_collection("recipes")` (ChromaDB) ile
        karışma ihtimalini de tamamen ortadan kaldırıyor — çağrılan
        özniteliğin adına bakıyor, dizgiye değil.
        """
        found = set()
        for path in API_DIR.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "collection"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    found.add(node.args[0].value)
        return found

    def test_the_scan_actually_finds_the_known_collections(self):
        """Önce aracın kendisi: tarama bozulursa test sessizce boş küme
        karşılaştırıp HER ZAMAN geçerdi — yani koruma varmış gibi görünüp
        hiçbir şey korumazdı."""
        found = self._collections_used_by_the_app()
        assert {"favorites", "collections", "pantry", "meal_plans", "shopping_lists"} <= found

    def test_every_firestore_collection_is_covered_by_account_deletion(self, api):
        import account

        covered = {name for name, _field in account._OWNED_BY_FIELD}
        covered |= set(account._OWNED_BY_DOC_ID)
        missing = self._collections_used_by_the_app() - covered

        assert not missing, (
            f"Bu Firestore koleksiyonlari hesap silmede kapsanmiyor: {sorted(missing)}. "
            "account.py'deki _OWNED_BY_FIELD ya da _OWNED_BY_DOC_ID listesine ekleyin."
        )

    def test_chromadb_recipes_are_not_in_the_deletion_list(self, api):
        """Tarifler salt-okunur ve image'a gömülü, kullanıcı verisi değil."""
        import account

        names = {n for n, _f in account._OWNED_BY_FIELD} | set(account._OWNED_BY_DOC_ID)
        assert "recipes" not in names


# ── 2. SIRA: yarıda kalırsa kurtarılabilir olsun ─────────
class TestDeletionOrder:
    def test_firestore_data_is_deleted_before_the_auth_user(self, account):
        """Tersi olsaydı ve Firestore yarıda kalsaydı kullanıcı bir daha giriş
        YAPAMAYACAĞI için kalan verisine ulaşamaz, tekrar de deneyemezdi."""
        account_module, db, _auth = account
        account_module.delete_account(EMAIL)

        kinds = [e[0] for e in db.events]
        assert "delete_auth_user" in kinds
        assert kinds.index("delete_auth_user") == len(kinds) - 1

    def test_auth_deletion_failure_leaves_the_user_able_to_retry(self, account, monkeypatch):
        """Auth silme patlarsa istisna yukarı çıkmalı — sessizce "silindi"
        demek, hesabı duran kullanıcıya silindi demek olurdu."""
        account_module, _db, fake_auth = account
        monkeypatch.setattr(
            fake_auth, "delete_user",
            lambda uid: (_ for _ in ()).throw(RuntimeError("firebase down")),
        )

        with pytest.raises(RuntimeError):
            account_module.delete_account(EMAIL)

    def test_a_second_attempt_succeeds_when_the_auth_user_is_already_gone(self, api, monkeypatch):
        """Yarıda kalmış bir silmenin ikinci denemesi. İstenen son durum zaten
        sağlanmış; hata vermek kullanıcıyı sıkışmış hissettirirdi."""
        import account as account_module

        db = FakeDb(_seed())
        monkeypatch.setattr(account_module, "_db", db)
        monkeypatch.setattr(account_module, "firebase_auth", FakeAuth(db, exists=False))
        monkeypatch.setattr(
            account_module, "FieldFilter", lambda f, o, v: (f, o, v)
        )

        assert account_module.delete_account(EMAIL)["auth_user"] is True


# ── 3. Verinin GERÇEKTEN gitmesi ─────────────────────────
class TestDataIsActuallyRemoved:
    def test_every_owned_document_is_gone(self, account):
        account_module, db, _ = account
        account_module.delete_account(EMAIL)

        for collection, docs in db.data.items():
            for doc_id in docs:
                assert EMAIL not in doc_id, f"{collection}/{doc_id} kaldi"

    def test_another_users_data_is_untouched(self, account):
        """En pahalı hata bu olurdu: bir kullanıcının silinmesi başkasının
        verisini götürürse geri dönüşü yok."""
        account_module, db, _ = account
        account_module.delete_account(EMAIL)

        assert db.data["favorites"] == {f"{OTHER}_17450": {"user_email": OTHER}}
        assert list(db.data["collections"]) == ["auto2"]
        assert list(db.data["meal_plans"]) == [f"{OTHER}_2026-07-27"]
        assert OTHER in db.data["pantry"]

    def test_the_pantry_document_is_deleted_not_just_emptied(self, account):
        """`clear_pantry` dokümanı bırakıp `items` dizisini boşaltıyor —
        hesap silmede bu YETMEZ, doküman ID'si e-postanın kendisi."""
        account_module, db, _ = account
        account_module.delete_account(EMAIL)

        assert EMAIL not in db.data["pantry"]

    def test_counts_are_reported_per_collection(self, account):
        account_module, _db, _ = account
        removed = account_module.delete_account(EMAIL)

        assert removed["favorites"] == 2
        assert removed["collections"] == 1
        assert removed["meal_plans"] == 1
        assert removed["shopping_lists"] == 1
        assert removed["pantry"] == 1

    def test_each_collection_is_queried_by_its_own_owner_field(self, account):
        """`favorites` alanı `user_email`, diğerleri `owner_email`. Karışırsa
        sorgu boş döner ve silme SESSİZCE hiçbir şey yapmaz."""
        account_module, db, _ = account
        account_module.delete_account(EMAIL)

        assert set(db.queries) == {
            ("favorites", "user_email", EMAIL),
            ("collections", "owner_email", EMAIL),
            ("meal_plans", "owner_email", EMAIL),
            ("shopping_lists", "owner_email", EMAIL),
        }

    def test_deleting_an_account_with_no_data_is_harmless(self, api, monkeypatch):
        import account as account_module

        db = FakeDb({})
        monkeypatch.setattr(account_module, "_db", db)
        monkeypatch.setattr(account_module, "firebase_auth", FakeAuth(db))
        monkeypatch.setattr(account_module, "FieldFilter", lambda f, o, v: (f, o, v))

        removed = account_module.delete_account("nobody@example.com")
        assert removed["favorites"] == 0 and removed["pantry"] == 0
        assert removed["auth_user"] is True


class TestBatching:
    def test_large_collections_are_deleted_in_batches(self, api, monkeypatch):
        """Firestore batch'i en fazla 500 işlem alıyor. Tek batch'e yığmak,
        çok favorisi olan bir kullanıcıda silmeyi patlatırdı."""
        import account as account_module

        db = FakeDb({"favorites": {f"{EMAIL}_{i}": {"user_email": EMAIL} for i in range(900)}})
        monkeypatch.setattr(account_module, "_db", db)
        monkeypatch.setattr(account_module, "firebase_auth", FakeAuth(db))
        monkeypatch.setattr(account_module, "FieldFilter", lambda f, o, v: (f, o, v))

        removed = account_module.delete_account(EMAIL)

        assert removed["favorites"] == 900
        commits = [n for kind, n in db.events if kind == "commit"]
        assert max(commits) <= 500          # Firestore sınırı
        assert sum(commits) == 900          # hiçbiri düşmedi

    def test_no_empty_batch_is_committed(self, account):
        account_module, db, _ = account
        account_module.delete_account(EMAIL)
        assert all(e[1] > 0 for e in db.events if e[0] == "commit")


# ── 4. Endpoint sözleşmesi ───────────────────────────────
class TestDeleteAccountEndpoint:
    def test_authentication_is_required(self, client):
        r = client.post("/api/account/delete", json={"confirm": "DELETE"})
        assert r.status_code == 422        # Header zorunlu

    def test_the_confirmation_is_enforced_server_side(self, auth_client, api, monkeypatch):
        """Onay bir güvenlik kontrolü değil, kazara tetiklenmeye karşı bir
        kapı — ama gerçekten kapı olmalı: yanlış onayda HİÇBİR ŞEY silinmemeli."""
        main, _ = api
        called = []
        monkeypatch.setattr(main, "delete_account", lambda e: called.append(e))

        r = auth_client.post(
            "/api/account/delete",
            json={"confirm": "delete"},     # küçük harf — kabul edilmemeli
            headers={"authorization": "Bearer x"},
        )
        assert r.status_code == 200
        assert "error" in r.json()
        assert called == []

    def test_a_confirmed_request_deletes_the_signed_in_user(self, auth_client, api, monkeypatch):
        """Silinen e-posta İSTEMCİDEN değil token'dan geliyor — aksi hâlde
        bir kullanıcı başkasının hesabını sildirebilirdi."""
        main, _ = api
        called = []
        monkeypatch.setattr(
            main, "delete_account",
            lambda e: (called.append(e), {"favorites": 2, "auth_user": True})[1],
        )

        r = auth_client.post(
            "/api/account/delete",
            json={"confirm": "DELETE"},
            headers={"authorization": "Bearer x"},
        )
        assert r.status_code == 200
        assert called == ["test@example.com"]
        assert r.json()["removed"]["auth_user"] is True

    def test_the_recipe_database_is_never_touched(self, auth_client, api, collection, monkeypatch):
        """Tarifler salt-okunur ve tüm kullanıcılarca paylaşılıyor."""
        main, _ = api
        monkeypatch.setattr(main, "delete_account", lambda e: {"auth_user": True})

        auth_client.post(
            "/api/account/delete",
            json={"confirm": "DELETE"},
            headers={"authorization": "Bearer x"},
        )
        assert not collection.get.called and not collection.query.called
        assert not collection.delete.called

    def test_a_missing_confirmation_field_is_rejected_by_pydantic(self, auth_client):
        r = auth_client.post(
            "/api/account/delete", json={}, headers={"authorization": "Bearer x"}
        )
        assert r.status_code == 422
