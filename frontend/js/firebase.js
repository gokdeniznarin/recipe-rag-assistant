/**
 * Firebase başlatma. Her sayfa, Firebase compat SDK script'lerinden HEMEN SONRA,
 * diğer js dosyalarından ÖNCE bu dosyayı yükler.
 *
 * firebaseConfig değerlerini Firebase Console > Project settings > Your apps (Web)
 * bölümünden alın. Bu değerlerin public olması normaldir — güvenlik, backend'in
 * ID token doğrulaması ve Firebase kurallarıyla sağlanır.
 */

const firebaseConfig = {
  apiKey: "AIzaSyBRqjiiyobEKHsPRFQp_eyeLKkT82WhTZg",
  authDomain: "rag-assistant-2b6a4.firebaseapp.com",
  projectId: "rag-assistant-2b6a4",
  appId: "1:662307994725:web:9aa1d492154a11b72ada8c",
};

firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();
// Not: Web'de varsayılan kalıcılık zaten LOCAL — setPersistence çağrısı gereksiz
// olduğu gibi, asenkron olarak onAuthStateChanged'i önce null tetikleyip
// yönlendirme döngüsüne yol açıyordu; bu yüzden çağrılmıyor.

// Auth durumu KESİNLEŞENE kadar beklemek için promise.
// authStateReady(), oturum kalıcılıktan geri yüklendikten sonra çözülür — böylece
// onAuthStateChanged'in restore öncesi tetikleyebildiği "geçici null" durumunu
// yakalamayız (bu, giriş↔search arasında sonsuz yönlendirme döngüsüne yol açıyordu).
const authReady = auth.authStateReady
  ? auth.authStateReady().then(() => auth.currentUser)
  : new Promise((resolve) => {
      // Eski SDK için yedek: null-then-user yarışına karşı, ilk kullanıcı gelene
      // ya da state ikinci kez tetiklenene kadar bekle.
      let settled = false;
      const unsubscribe = auth.onAuthStateChanged((user) => {
        if (settled) return;
        settled = true;
        unsubscribe();
        resolve(user);
      });
    });
