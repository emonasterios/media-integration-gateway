import asyncio
import re
from curl_cffi.requests import AsyncSession


async def test_vidhidepro():
    url = 'https://vidhidepro.com/v/mm13p1xnf3s3'
    async with AsyncSession() as s:
        r = await s.get(url, impersonate='chrome', headers={'Referer': 'https://vidhidepro.com/'}, timeout=20)
        print(f'=== vidhidepro.com ===')
        print(f'Status: {r.status_code}')
        print(f'Final URL: {r.url}')
        print(f'HTML length: {len(r.text)}')
        print(f'HTML (first 2000):')
        print(r.text[:2000])
        print()
        
        # Si es redirección o página corta, buscar meta refresh o location
        refresh = re.search(r'<meta[^>]+url=([^"\']+)', r.text, re.IGNORECASE)
        if refresh:
            print(f'Meta refresh: {refresh.group(1)}')
        
        # Buscar cualquier enlace
        links = re.findall(r'href=["\']([^"\']+)["\']', r.text)
        if links:
            print(f'Links found: {links[:5]}')


async def test_waaw_iframe():
    url = 'https://waaw.to/e/MAtjuehID7dA?http_referer=https%3A%2F%2Fwaaw.to%2F&autoplay=no&embed_from=embed_from'
    async with AsyncSession() as s:
        r = await s.get(url, impersonate='chrome', headers={'Referer': 'https://waaw.to/'}, timeout=20)
        print(f'\n=== waaw.to iframe ===')
        print(f'Status: {r.status_code}')
        print(f'HTML length: {len(r.text)}')
        
        # Buscar video URLs
        for pattern in ['file', 'm3u8', 'mp4', 'source', 'videoUrl', 'hls']:
            matches = re.findall(r'.{0,100}' + pattern + r'.{0,100}', r.text[:10000], re.IGNORECASE)
            if matches:
                print(f'  [{pattern}]: {matches[:2]}')
        
        # Buscar scripts con eval
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', r.text, re.DOTALL)
        for i, script in enumerate(scripts):
            if 'eval(function(p,a,c,k,e,d)' in script:
                print(f'Script {i}: eval packed ({len(script)} chars)')
            if 'jwplayer' in script.lower() or 'player' in script.lower():
                print(f'Script {i}: player-related ({len(script)} chars)')
                if 'file' in script.lower():
                    file_match = re.search(r'file["\']?\s*[:=]\s*["\']([^"\']+)["\']', script)
                    if file_match:
                        print(f'  file: {file_match.group(1)[:120]}')


async def main():
    await test_vidhidepro()
    await test_waaw_iframe()


asyncio.run(main())
