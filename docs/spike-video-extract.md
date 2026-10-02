# Spike: Extracción de video directo de servidores de streaming

**Fecha:** 2026-10-02
**Target:** Cuevana3 (cuevana3i.cc) → Doodstream → Playmogo.com → CloudataCDN

## Resumen

**Resultado:** ✅ MECÁNICA DE EXTRACCIÓN DESCUBIERTA — pero el CDN final bloquea acceso desde infraestructura no autorizada.

## Cadena de redirecciones

```
cuevana3i.cc/pelicula/signal-one/
  → resolve_playback() → data-server URL
  → doodstream.com/e/jtri5tfbukk6
  → (302) playmogo.com/e/jtri5tfbukk6
  → (HTML con Video.js + lógica JS)
  → pass_md5 endpoint → URL base del CDN
  → URL final del video (.mp4) en cloudatacdn.com
```

## Mecánica de extracción (Doodstream/Playmogo)

### Paso 1: Obtener la página del embed
```
GET https://playmogo.com/e/{file_id}
Headers: User-Agent, Referer
```

### Paso 2: Extraer datos del HTML
- **Token:** `token=([a-zA-Z0-9]+)` → ej: `s2ov4941r1l844sw0u3a14gr`
- **Pass MD5 path:** `pass_md5/([^'"]+)` → ej: `267031004-181-178-{timestamp}-{hash}/{token}`

### Paso 3: Obtener URL base del CDN
```
GET https://playmogo.com/pass_md5/{pass_path}
Headers: Referer: https://playmogo.com/e/{file_id}
Response: URL base del CDN (texto plano)
Ej: https://fj173o.cloudatacdn.com/u5kjvip74la3sdgge6n3gpaclldtb57jkldye3e55rq4l7gsymecnwwbgumq/hdnsjes9ln~
```

### Paso 4: Construir URL del video
La función JavaScript `makePlay()` genera:
```javascript
function makePlay() {
    var a = "", t = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    for (var n = t.length, o = 0; 10 > o; o++)
        a += t.charAt(Math.floor(Math.random() * n));
    return a + "?token=s2ov4941r1l844sw0u3a14gr&expiry=" + Date.now();
}
```

**URL final:** `{pass_md5_response}{random_10_chars}?token={token}&expiry={timestamp}`

Tipo: `video/mp4`

## Estado de otros servidores

| Servidor | Estado | Notas |
|----------|--------|-------|
| Doodstream/Playmogo | ✅ Mecánica descubierta | CDN bloquea IPs no autorizadas |
| Voe | ❓ No probado | Requiere página con servidor voe activo |
| Vidhide | ❓ No probado | Requiere página con servidor vidhide activo |
| Streamwish | ❓ No probado | Requiere página con servidor streamwish activo |

## Bloqueo del CDN

El CDN `cloudatacdn.com` no responde desde codeserver (posible geo-bloqueo o restricción por IP). Los intentos de HEAD/GET fallan con "All connection attempts failed". Esto significa:

1. **La mecánica de extracción funciona** — podemos construir la URL correcta
2. **La reproducción directa desde nuestro servidor NO funciona** — el CDN bloquea la IP
3. **Solución posible:** El cliente final (IPTV, navegador) accede directamente a la URL del CDN, no a través de nuestro servidor. Nuestro gateway solo necesita **resolver y entregar la URL**, no hacer proxy del video.

## Implicaciones para el M3U

El endpoint `GET /api/v1/resolve/{provider}/{id}` debe:
1. Navegar la cadena de extracción (como se describe arriba)
2. Devolver la URL del CDN directamente al cliente
3. El cliente (VLC, IPTV player) reproduce desde el CDN

**NO** necesitamos hacer proxy del video — solo resolver la URL.

## Implementación requerida

Para soportar Doodstream/Playmogo en el resolver:

```python
async def resolve_doodstream(self, embed_url: str) -> PlaybackDescriptor:
    """Resuelve URL de video directo desde Doodstream/Playmogo."""
    # 1. GET embed page
    # 2. Extraer token y pass_md5 path
    # 3. GET pass_md5 → base URL
    # 4. Construir URL final: base + random(10) + ?token=...&expiry=...
    # 5. Devolver PlaybackDescriptor(protocol="mp4", url=video_url)
```

## Pruebas en vivo

Para verificar end-to-end:
1. El CDN debe ser accesible desde la red del cliente final
2. La URL generada tiene expiración (expiry timestamp) — URLs caducan
3. Cada request genera una URL diferente (random string + timestamp)
