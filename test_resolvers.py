import asyncio
import re
from curl_cffi.requests import AsyncSession


def unpack_js(p, a, c, k):
    """Desofuscar JS packed con eval(p,a,c,k,e,d)."""
    c = int(c)
    k = k.split('|')
    
    def replace(match):
        idx = int(match.group(0), a) if a > 10 else int(match.group(0))
        if idx < len(k) and k[idx]:
            return k[idx]
        return match.group(0)
    
    if a <= 10:
        pattern = r'\b\d+\b'
    else:
        pattern = r'\b\w+\b'
    
    result = re.sub(pattern, replace, p)
    return result


async def test_vimeos():
    url = 'https://vimeos.net/embed-kfoithrzjnbi.html'
    async with AsyncSession() as s:
        r = await s.get(url, impersonate='chrome', headers={'Referer': 'https://vimeos.net/'}, timeout=20)
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', r.text, re.DOTALL)
        for i, script in enumerate(scripts):
            if 'eval(function(p,a,c,k,e,d)' in script:
                print(f'=== vimeos.net Script {i} (eval packed, {len(script)} chars) ===')
                m = re.search(r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\((.*?),(\d+),(\d+),'(.*?)'\.split\('\|'\)", script, re.DOTALL)
                if m:
                    e_val = m.group(1)
                    a_val = int(m.group(2))
                    c_val = int(m.group(3))
                    k_str = m.group(4)
                    print(f'a={a_val}, c={c_val}, k_parts={len(k_str.split("|"))}')
                    
                    unpacked = unpack_js(e_val, a_val, c_val, k_str)
                    print(f'Unpacked length: {len(unpacked)}')
                    
                    m3u8 = re.findall(r'(https?://[^\'"\s]+\.m3u8[^\'"\s]*)', unpacked)
                    if m3u8:
                        print(f'm3u8 URLs found: {len(m3u8)}')
                        for u in m3u8[:3]:
                            print(f'  {u[:120]}')
                    else:
                        file_matches = re.findall(r'file["\']?\s*[:=]\s*["\']([^"\']+)["\']', unpacked)
                        if file_matches:
                            print(f'file URLs: {file_matches[:3]}')
                        else:
                            print('No m3u8 or file URLs found in unpacked')
                            print(f'First 800 chars of unpacked:')
                            print(unpacked[:800])
                break


async def test_vidhidepro():
    url = 'https://vidhidepro.com/v/mm13p1xnf3s3'
    async with AsyncSession() as s:
        r = await s.get(url, impersonate='chrome', headers={'Referer': 'https://vidhidepro.com/'}, timeout=20)
        print(f'\n=== vidhidepro.com ===')
        print(f'Status: {r.status_code}, HTML length: {len(r.text)}')
        
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', r.text, re.DOTALL)
        for i, script in enumerate(scripts):
            if 'eval(function(p,a,c,k,e,d)' in script:
                print(f'Script {i}: eval packed ({len(script)} chars)')
                m = re.search(r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\((.*?),(\d+),(\d+),'(.*?)'\.split\('\|'\)", script, re.DOTALL)
                if m:
                    e_val = m.group(1)
                    a_val = int(m.group(2))
                    c_val = int(m.group(3))
                    k_str = m.group(4)
                    print(f'a={a_val}, c={c_val}, k_parts={len(k_str.split("|"))}')
                    unpacked = unpack_js(e_val, a_val, c_val, k_str)
                    m3u8 = re.findall(r'(https?://[^\'"\s]+\.m3u8[^\'"\s]*)', unpacked)
                    if m3u8:
                        print(f'm3u8 URLs: {len(m3u8)}')
                        for u in m3u8[:3]:
                            print(f'  {u[:120]}')
                    else:
                        print('No m3u8 found')
                        print(f'Unpacked[:500]: {unpacked[:500]}')
                break


async def test_waaw():
    url = 'https://waaw.to/f/MAtjuehID7dA'
    async with AsyncSession() as s:
        r = await s.get(url, impersonate='chrome', headers={'Referer': 'https://waaw.to/'}, timeout=20)
        print(f'\n=== waaw.to ===')
        print(f'Status: {r.status_code}, HTML length: {len(r.text)}')
        
        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', r.text)
        if iframe_match:
            iframe_url = iframe_match.group(1)
            print(f'iframe src: {iframe_url}')
            full_url = f'https://waaw.to{iframe_url}' if iframe_url.startswith('/') else iframe_url
            r2 = await s.get(full_url, impersonate='chrome', headers={'Referer': 'https://waaw.to/'}, timeout=20)
            print(f'iframe status: {r2.status_code}, length: {len(r2.text)}')
            
            for pattern in ['file', 'm3u8', 'mp4', 'source']:
                matches = re.findall(r'.{0,80}' + pattern + r'.{0,80}', r2.text[:5000], re.IGNORECASE)
                if matches:
                    print(f'  [{pattern}]: {matches[:1]}')
        else:
            print('No iframe found')
            for pattern in ['file', 'm3u8', 'mp4', 'source']:
                matches = re.findall(r'.{0,80}' + pattern + r'.{0,80}', r.text[:5000], re.IGNORECASE)
                if matches:
                    print(f'  [{pattern}]: {matches[:1]}')


async def main():
    await test_vimeos()
    await test_vidhidepro()
    await test_waaw()


asyncio.run(main())
