// Ortak kamera modülü — fotoğraf çekme / yükleme akışı.
//
// NEDEN AYRI DOSYA: iki sayfa aynı akışı kullanıyor ve soruları farklı —
// search.html "bununla ne pişirebilirim", nutrition.html "bunda ne var".
// getUserMedia + canvas + retake mantığını ikisine kopyalamak, projedeki
// "aynı kuralı iki yere yazma" ilkesinin (Faz 15d/19) ihlali olurdu: biri
// düzeltilip diğeri unutulur.
//
// Sayfaya özel HİÇBİR ŞEY bilmiyor: hangi butonların gösterileceğini,
// fotoğrafla ne yapılacağını çağıran karar veriyor (onCapture/onReset).
// Logger deseniyle aynı: klasik <script>, global sabit, modül sistemi yok.
const Camera = (function () {
  const cameraLog = Logger.get('camera');

  const CONSTRAINTS = { video: { facingMode: 'environment' } };   // varsa arka kamera

  // Yüklenen fotoğraf için uzun kenar sınırı. Telefon fotoğrafı 12MP olabiliyor
  // ve base64'e çevrilince ~8MB'lık bir gövde çıkıyor — hem yükleme yavaşlar hem
  // Gemini'ye gereksiz veri gider. Kameradan gelen kare zaten 640-1280 civarı.
  const MAX_EDGE = 1280;
  const JPEG_QUALITY = 0.85;

  function attach(el) {
    // el: { preview, canvas, startBtn, captureBtn, retakeBtn }
    //     + onCapture(dataUrl) / onReset() / onError(mesaj)
    let stream = null;
    let photo = null;
    // Fotoğrafın KAYNAĞI: 'camera' | 'file'. reset() buna bakıyor — çekilen bir
    // fotoğrafı "yeniden çek" demek kamerayı açmak demek, ama yüklenen bir
    // dosyada aynı şeyi yapmak kullanıcının hiç istemediği bir izin istemi ve
    // yanan bir kamera ışığı üretiyor.
    let source = null;

    function stop() {
      if (stream) {
        stream.getTracks().forEach(t => t.stop());
        stream = null;
      }
    }

    async function open() {
      try {
        stream = await navigator.mediaDevices.getUserMedia(CONSTRAINTS);
        el.preview.srcObject = stream;
        el.startBtn.classList.add('hidden');
        el.captureBtn.classList.remove('hidden');
        return true;
      } catch (err) {
        cameraLog.warn(`Could not open camera: ${err.message || err}`);
        if (el.onError) el.onError('Could not access the camera. Check browser permissions.');
        return false;
      }
    }

    // Çekilen ya da yüklenen fotoğraf artık canvas'ta — tek gösterim yolu var,
    // dolayısıyla iki kaynak da aynı UI durumuna düşüyor.
    function showPhoto(from) {
      source = from;
      photo = el.canvas.toDataURL('image/jpeg', JPEG_QUALITY);
      stop();
      el.preview.classList.add('hidden');
      el.canvas.classList.remove('hidden');
      el.startBtn.classList.add('hidden');
      el.captureBtn.classList.add('hidden');
      el.retakeBtn.classList.remove('hidden');
      if (el.onCapture) el.onCapture(photo);
    }

    function capture() {
      el.canvas.width = el.preview.videoWidth;
      el.canvas.height = el.preview.videoHeight;
      el.canvas.getContext('2d').drawImage(el.preview, 0, 0);
      showPhoto('camera');
    }

    async function reset() {
      const fromCamera = source === 'camera';
      photo = null;
      source = null;
      el.canvas.classList.add('hidden');
      el.preview.classList.remove('hidden');
      el.retakeBtn.classList.add('hidden');
      if (el.onReset) el.onReset();

      // DOSYADAN gelen bir fotoğrafta kamerayı açmak yanlış olurdu: kullanıcı
      // kamerayı hiç istemedi, "başka bir fotoğraf kullan" dedi. Başlangıç
      // durumuna dönüyoruz — "Start camera" ve "Upload a photo" yeniden yan
      // yana, kullanıcı hangisini isterse onu seçiyor.
      if (!fromCamera) {
        el.startBtn.classList.remove('hidden');
        return;
      }

      // Kameradan çekildiyse "yeniden çek" beklenen davranış: doğrudan aç.
      // Açılamazsa (izin reddi, cihazda kamera yok) kullanıcı kilitli kalmasın
      // diye "Start camera" geri gelir.
      if (!(await open())) el.startBtn.classList.remove('hidden');
    }

    // Dosyadan fotoğraf: kamerası olmayan masaüstü kullanıcısı ve demo için.
    function loadFile(file) {
      if (!file) return;
      if (!/^image\//.test(file.type)) {
        if (el.onError) el.onError('That file is not an image.');
        return;
      }

      const reader = new FileReader();
      reader.onload = () => {
        const img = new Image();
        img.onload = () => {
          // Uzun kenarı MAX_EDGE'e indir (oran korunarak)
          const scale = Math.min(1, MAX_EDGE / Math.max(img.width, img.height));
          el.canvas.width = Math.round(img.width * scale);
          el.canvas.height = Math.round(img.height * scale);
          el.canvas.getContext('2d').drawImage(img, 0, 0, el.canvas.width, el.canvas.height);
          showPhoto('file');
        };
        img.onerror = () => {
          if (el.onError) el.onError('That image could not be read.');
        };
        img.src = reader.result;
      };
      reader.onerror = () => {
        if (el.onError) el.onError('That file could not be read.');
      };
      reader.readAsDataURL(file);
    }

    el.startBtn.addEventListener('click', open);
    el.captureBtn.addEventListener('click', capture);
    el.retakeBtn.addEventListener('click', reset);
    // Sayfa kapanırken kamerayı serbest bırak (yoksa kamera ışığı yanık kalır)
    window.addEventListener('beforeunload', stop);

    return {
      stop,
      reset,
      loadFile,
      getPhoto: () => photo,
    };
  }

  return { attach };
})();
