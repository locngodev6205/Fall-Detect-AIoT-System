"""Short-lived TTS preview using the same Vietnamese voice as saved reminders."""
from pathlib import Path
import shutil
import subprocess
import tempfile
from fastapi import HTTPException

def preview_audio(text: str) -> bytes:
    binary=shutil.which('espeak-ng')
    if not binary:
        raise HTTPException(503,'Chức năng tạo giọng nói đang chưa sẵn sàng.')
    try:
        with tempfile.TemporaryDirectory(prefix='annha-preview-') as directory:
            path=Path(directory)/'preview.wav'
            subprocess.run([binary,'-v','vi','-s','150','-w',str(path),'--stdin'],input=text.encode(),timeout=30,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            return path.read_bytes()
    except (subprocess.SubprocessError,OSError):
        raise HTTPException(503,'Chưa thể tạo bản nghe thử. Vui lòng thử lại.') from None
