#!/usr/bin/env python3
import asyncio
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
import time
import argparse
import sys
import os
import subprocess
import venv

# ---------------------------
# Helper: Ensure VirtualEnv
# ---------------------------
def ensure_virtualenv(required_packages):
    venv_path = Path(".venv")
    python_exe = sys.executable

    if not venv_path.exists():
        print("🔧 Creating virtual environment...")
        venv.create(venv_path, with_pip=True)
        python_exe = str(venv_path / ("Scripts" if os.name == "nt" else "bin") / "python")
    else:
        python_exe = str(venv_path / ("Scripts" if os.name == "nt" else "bin") / "python")

    # Install missing packages
    for pkg, ver in required_packages.items():
        try:
            subprocess.run([python_exe, "-m", "pip", "install", f"{pkg}=={ver}"], check=True)
        except subprocess.CalledProcessError:
            print(f"❌ Failed to install {pkg}")
    
    return python_exe

# ---------------------------
# Downloader Class
# ---------------------------
class HighTechWebtoonDownloader:
    def _init_(self):
        self.dl = []
        self.sp = []
        self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        self.session_stats = {'images_downloaded':0,'images_skipped':0,'failed_downloads':0,'start_time':time.time()}

    async def fetch_url(self, client, url):
        try:
            resp = await client.get(url, headers=self.headers, timeout=15)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            print(f"❌ Error fetching {url}: {e}")
        return None

    async def fetch_download_image(self, client, url, fp):
        file_path = Path(fp)
        if file_path.exists() and file_path.stat().st_size > 1024:
            self.session_stats['images_downloaded'] += 1
            print(f"⏭️  Skipped (exists): {file_path.name}")
            return True

        attempt, max_retries = 0, 5
        while attempt < max_retries:
            try:
                async with client.get(url, headers=self.headers) as resp:
                    if resp.status == 200:
                        img = await resp.read()
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        tmp_path = file_path.with_suffix('.tmp')
                        with open(tmp_path, 'wb') as f:
                            f.write(img)
                        if tmp_path.stat().st_size > 1024:
                            tmp_path.rename(file_path)
                            self.session_stats['images_downloaded'] += 1
                            print(f"✅ Downloaded: {file_path.name}")
                            return True
                        else:
                            tmp_path.unlink()
            except Exception as e:
                print(f"❌ Error downloading {url}: {e}")
            attempt += 1
            await asyncio.sleep(2 ** attempt)
        self.session_stats['failed_downloads'] += 1
        print(f"💥 Failed to download {url} after {max_retries} attempts")
        return False

    async def download_all_images(self, batch_size=20):
        import aiohttp
        async with aiohttp.ClientSession() as client:
            for i in range(0, len(self.dl), batch_size):
                batch_urls = self.dl[i:i+batch_size]
                batch_paths = self.sp[i:i+batch_size]
                tasks = [self.fetch_download_image(client, u, p) for u, p in zip(batch_urls, batch_paths)]
                await asyncio.gather(*tasks)

    async def extract_episode_data(self, comic_id, start, end, full_path):
        async with httpx.AsyncClient() as client:
            for cur in range(start, end):
                url = f"https://comic.naver.com/webtoon/detail?titleId={comic_id}&no={cur}"
                content = await self.fetch_url(client, url)
                if content:
                    soup = BeautifulSoup(content, 'html.parser')
                    div = soup.select_one('div.viewer_img')
                    if div:
                        img_tags = div.find_all('img')
                        img_links = []
                        for img in img_tags:
                            if 'data-src' in img.attrs:
                                img_links.append(img['data-src'])
                            elif 'src' in img.attrs:
                                img_links.append(img['src'])
                        self.dl.extend(img_links)
                        img_folder = Path(full_path) / str(cur)
                        img_folder.mkdir(exist_ok=True)
                        save_paths = [str(img_folder / f'{i}.jpg') for i in range(len(img_links))]
                        self.sp.extend(save_paths)
                        print(f"📄 Episode {cur}: {len(img_links)} images found")
                    else:
                        print(f"⚠️ No images found in episode {cur}")
                else:
                    print(f"❌ Failed to fetch episode {cur}")

    def get_comic_title(self, comic_id):
        import requests, re
        try:
            url = f"https://comic.naver.com/webtoon/list?titleId={comic_id}"
            r = requests.get(url, headers=self.headers)
            if r.status_code == 200:
                soup = BeautifulSoup(r.content, 'html.parser')
                meta_tag = soup.find('meta', attrs={'property':'og:title'})
                if meta_tag:
                    return re.sub(r'[<>:"/\\|?*]', '-', meta_tag['content'])
        except:
            pass
        return f"comic_{comic_id}"

    def print_stats(self):
        elapsed = time.time() - self.session_stats['start_time']
        total_processed = self.session_stats['images_downloaded'] + self.session_stats['failed_downloads']
        print(f"\n📊 Download Statistics:")
        print(f"✅ Successfully downloaded: {self.session_stats['images_downloaded']}")
        print(f"❌ Failed downloads: {self.session_stats['failed_downloads']}")
        print(f"📁 Total processed: {total_processed}")
        print(f"⏱️ Total time: {elapsed:.2f} sec")
        if self.session_stats['images_downloaded'] > 0:
            print(f"⚡ Speed: {self.session_stats['images_downloaded']/elapsed:.2f} images/sec")

# ---------------------------
# Main Process
# ---------------------------
async def main_download_process(comic_id, start, end, outpath):
    downloader = HighTechWebtoonDownloader()
    title = downloader.get_comic_title(comic_id)
    full_path = Path(outpath) / title
    full_path.mkdir(parents=True, exist_ok=True)

    print(f"📚 Comic: {title}")
    print(f"📁 Output: {full_path}")

    await downloader.extract_episode_data(comic_id, start, end + 1, full_path)
    await downloader.download_all_images()
    downloader.print_stats()
    print("🎉 FINISHED!")

def main():
    parser = argparse.ArgumentParser(description="High-tech Naver Webtoon Downloader with VENV")
    parser.add_argument("comic_id", type=int)
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    parser.add_argument("outpath", type=str)
    args = parser.parse_args()

    # ---------------------------
    # Ensure VirtualEnv
    # ---------------------------
    required_packages = {
        'aiohttp':'3.11.11',
        'httpx':'0.28.1',
        'beautifulsoup4':'4.13.4',
        'requests':'2.32.3'
    }

    python_exe = ensure_virtualenv(required_packages)
    if python_exe != sys.executable:
        print("🔄 Re-running script inside virtual environment...")
        subprocess.run([python_exe, _file_, str(args.comic_id), str(args.start), str(args.end), args.outpath])
        return

    # Run main download
    try:
        asyncio.run(main_download_process(args.comic_id, args.start, args.end, args.outpath))
    except KeyboardInterrupt:
        print("\n⚠️  Download interrupted by user")
    except Exception as e:
        print(f"💥 Error: {e}")

if _name_ == "_main_":
    main()