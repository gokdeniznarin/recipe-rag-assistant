FROM nginx:alpine

# nginx'in mime.types'ı `.webmanifest` uzantısını BİLMİYOR ve dosyayı
# application/octet-stream olarak gönderiyor. Vercel doğru tipi gönderdiği için,
# bu satır olmadan yerel ile canlı davranışı ayrışır — projedeki "yerelde
# çalışan = canlıya giden" ilkesinin frontend tarafındaki karşılığı.
# Ayrı bir conf DOSYASI kullanılmadı: build context ./frontend ve aynı klasör
# nginx'in html kökü, yani oraya konan her dosya herkese açık servis edilirdi.
# `grep` bilerek zincire bağlı: sed dosya biçimine dayanıyor, temel image
# gelecekte mime.types'ı değiştirirse sed SESSİZCE hiçbir şey yapmaz ve MIME
# tipi fark edilmeden geriler. Böyle bir durumda build kasten çöksün.
RUN sed -i '/^}/i\    application/manifest+json  webmanifest;' /etc/nginx/mime.types \
    && grep -q 'application/manifest+json' /etc/nginx/mime.types

COPY . /usr/share/nginx/html

EXPOSE 80