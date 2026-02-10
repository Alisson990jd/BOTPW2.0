#!/usr/bin/env python3
"""
🎬 YouTube Clip Creator
Processa clipes do VOD da Twitch e faz upload para o YouTube
"""

import os
import sys
import json
import subprocess
import pickle
import time
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('clip_creator.log')
    ]
)
logger = logging.getLogger(__name__)

# ==================== CONSTANTES ====================
TEMP_DIR = Path("temp_clips")
ERROR_SCREENSHOTS_DIR = Path("error_screenshots")
PROCESSING_LOG = "processing_log.json"


def setup_directories():
    """Cria diretórios necessários"""
    TEMP_DIR.mkdir(exist_ok=True)
    ERROR_SCREENSHOTS_DIR.mkdir(exist_ok=True)


def time_to_seconds(time_str: str) -> int:
    """Converte HH:MM:SS para segundos"""
    parts = time_str.split(':')
    if len(parts) == 3:
        h, m, s = map(int, parts)
        return h * 3600 + m * 60 + s
    elif len(parts) == 2:
        m, s = map(int, parts)
        return m * 60 + s
    return int(parts[0])


def seconds_to_time(seconds: int) -> str:
    """Converte segundos para HH:MM:SS"""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def load_clips_config() -> List[Dict]:
    """Carrega e filtra clipes do YouTube do JSON"""
    logger.info("📂 Carregando configuração de clipes...")
    
    with open("analise_resultado.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    clips = data.get("clips", [])
    youtube_clips = [c for c in clips if c.get("platform") == "youtube"]
    
    logger.info(f"   Total de clipes: {len(clips)}")
    logger.info(f"   Clipes YouTube: {len(youtube_clips)}")
    
    return youtube_clips


def load_youtube_credentials() -> Dict:
    """Carrega credenciais do YouTube da pasta analisar"""
    logger.info("🔑 Carregando credenciais do YouTube...")
    
    analisar_dir = Path("analisar")
    json_files = list(analisar_dir.glob("*.json"))
    
    if not json_files:
        raise FileNotFoundError("Nenhum arquivo de credenciais encontrado em 'analisar/'")
    
    # Usa o primeiro arquivo encontrado
    cred_file = json_files[0]
    logger.info(f"   Usando: {cred_file.name}")
    
    with open(cred_file, "r", encoding="utf-8") as f:
        cred_data = json.load(f)
    
    # Carrega o pickle com o token
    pkl_file = analisar_dir / cred_data.get("pkl_file", "")
    
    # Se o pkl não estiver na pasta analisar, procura na raiz
    if not pkl_file.exists():
        pkl_file = Path(cred_data.get("pkl_file", ""))
    
    # Tenta baixar o pkl do repositório se não existir
    if not pkl_file.exists():
        logger.info(f"   ⚠️ Arquivo pkl não encontrado localmente, tentando baixar...")
        pkl_name = cred_data.get("pkl_file", "")
        if pkl_name:
            download_pkl_from_repo(pkl_name)
            pkl_file = Path(pkl_name)
    
    return {
        "json_data": cred_data,
        "json_file": cred_file,
        "pkl_file": pkl_file
    }


def download_pkl_from_repo(pkl_name: str):
    """Baixa arquivo pkl do repositório externo"""
    import requests
    
    token = os.environ.get("GH_PAT", "")
    if not token:
        logger.warning("   GH_PAT não encontrado, tentando sem autenticação...")
    
    url = f"https://api.github.com/repos/Alisson990jd/apiss/contents/analisar/{pkl_name}"
    headers = {
        "Accept": "application/vnd.github.v3.raw"
    }
    if token:
        headers["Authorization"] = f"token {token}"
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        # Salva na pasta analisar
        pkl_path = Path("analisar") / pkl_name
        with open(pkl_path, "wb") as f:
            f.write(response.content)
        logger.info(f"   ✅ {pkl_name} baixado com sucesso!")
    else:
        logger.error(f"   ❌ Erro ao baixar {pkl_name}: {response.status_code}")


def get_vod_info(vod_url: str) -> Dict:
    """Obtém informações do VOD"""
    logger.info(f"📹 Obtendo informações do VOD...")
    
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-download", vod_url],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        raise Exception(f"Erro ao obter info do VOD: {result.stderr}")
    
    info = json.loads(result.stdout)
    logger.info(f"   Título: {info.get('title', 'N/A')}")
    logger.info(f"   Duração: {info.get('duration', 0)} segundos")
    
    return info


def download_clip_segment(vod_url: str, start_time: str, end_time: str, output_path: Path) -> bool:
    """Baixa um segmento específico do VOD na melhor qualidade"""
    logger.info(f"⬇️  Baixando segmento: {start_time} -> {end_time}")
    
    start_sec = time_to_seconds(start_time)
    end_sec = time_to_seconds(end_time)
    duration = end_sec - start_sec
    
    # Comando yt-dlp para baixar segmento específico
    cmd = [
        "yt-dlp",
        "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--download-sections", f"*{start_time}-{end_time}",
        "--force-keyframes-at-cuts",
        "--concurrent-fragments", "8",
        "--output", str(output_path),
        "--no-playlist",
        "--no-part",
        vod_url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode == 0 and output_path.exists():
            file_size = output_path.stat().st_size / (1024 * 1024)
            logger.info(f"   ✅ Segmento baixado: {file_size:.2f} MB")
            return True
        else:
            logger.error(f"   ❌ Erro no download: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("   ❌ Timeout no download")
        return False
    except Exception as e:
        logger.error(f"   ❌ Erro: {e}")
        return False


def capture_thumbnail_frame(video_path: Path, timestamp: str, output_path: Path) -> bool:
    """Captura um frame do vídeo para usar como base da thumbnail"""
    logger.info(f"📸 Capturando frame em {timestamp}...")
    
    # Calcula o offset relativo (timestamp é absoluto no VOD, precisamos relativo ao clipe)
    cmd = [
        "ffmpeg",
        "-ss", timestamp,
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        "-y",
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0 and output_path.exists():
            logger.info(f"   ✅ Frame capturado!")
            return True
        else:
            logger.error(f"   ❌ Erro na captura: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"   ❌ Erro: {e}")
        return False


def capture_thumbnail_from_vod(vod_url: str, timestamp: str, output_path: Path) -> bool:
    """Captura frame diretamente do VOD usando yt-dlp + ffmpeg"""
    logger.info(f"📸 Capturando thumbnail do VOD em {timestamp}...")
    
    # Primeiro, obtém a URL do stream
    cmd_url = [
        "yt-dlp",
        "--format", "bestvideo[ext=mp4]/best[ext=mp4]/best",
        "--get-url",
        vod_url
    ]
    
    try:
        result = subprocess.run(cmd_url, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.error(f"   ❌ Erro ao obter URL: {result.stderr}")
            return False
        
        stream_url = result.stdout.strip().split('\n')[0]
        
        # Usa ffmpeg para capturar o frame
        cmd_ffmpeg = [
            "ffmpeg",
            "-ss", timestamp,
            "-i", stream_url,
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            str(output_path)
        ]
        
        result = subprocess.run(cmd_ffmpeg, capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0 and output_path.exists():
            logger.info(f"   ✅ Thumbnail capturada!")
            return True
        else:
            logger.error(f"   ❌ Erro no ffmpeg: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"   ❌ Erro: {e}")
        return False


def generate_thumbnail_chatgpt(clip_data: Dict, image_path: Path, output_path: Path) -> bool:
    """Gera thumbnail usando ChatGPT"""
    from thumbnail_generator import ThumbnailGenerator
    
    logger.info("🎨 Gerando thumbnail via ChatGPT...")
    
    try:
        generator = ThumbnailGenerator(
            gmail_token_path="gmail_token.pkl",
            headless=True
        )
        
        # Monta o prompt com os dados do clipe
        prompt = f"""transforme em uma thumbnail para youtube(1280x720), esse é o clipe:
{json.dumps(clip_data, indent=2, ensure_ascii=False)}"""
        
        success = generator.generate(
            image_path=str(image_path),
            prompt=prompt,
            output_path=str(output_path)
        )
        
        if success and output_path.exists():
            logger.info(f"   ✅ Thumbnail gerada!")
            return True
        else:
            logger.warning("   ⚠️ Falha na geração, usando frame original")
            # Copia o frame original como thumbnail
            import shutil
            shutil.copy(image_path, output_path)
            return True
            
    except Exception as e:
        logger.error(f"   ❌ Erro no ChatGPT: {e}")
        # Usa frame original como fallback
        import shutil
        shutil.copy(image_path, output_path)
        return True


def upload_to_youtube(
    video_path: Path,
    thumbnail_path: Path,
    clip_data: Dict,
    credentials: Dict
) -> Optional[str]:
    """Faz upload do vídeo para o YouTube"""
    from youtube_uploader import YouTubeUploader
    
    logger.info("📤 Fazendo upload para o YouTube...")
    
    try:
        uploader = YouTubeUploader(credentials)
        
        video_id = uploader.upload(
            video_path=str(video_path),
            title=clip_data.get("title", "Clip"),
            description=clip_data.get("recommended_description", ""),
            tags=clip_data.get("tags", []),
            thumbnail_path=str(thumbnail_path) if thumbnail_path.exists() else None,
            privacy_status="private"  # Sempre privado
        )
        
        if video_id:
            logger.info(f"   ✅ Upload concluído! ID: {video_id}")
            return video_id
        else:
            logger.error("   ❌ Falha no upload")
            return None
            
    except Exception as e:
        logger.error(f"   ❌ Erro no upload: {e}")
        return None


def cleanup_temp_files(*paths):
    """Remove arquivos temporários"""
    for path in paths:
        try:
            if isinstance(path, Path) and path.exists():
                path.unlink()
                logger.debug(f"   🗑️ Removido: {path}")
        except Exception as e:
            logger.warning(f"   ⚠️ Erro ao remover {path}: {e}")


def process_clip(clip_data: Dict, vod_url: str, credentials: Dict, clip_index: int, total_clips: int) -> Dict:
    """Processa um único clipe"""
    clip_id = clip_data.get("clip_id", f"clip_{clip_index}")
    
    logger.info("=" * 60)
    logger.info(f"🎬 Processando clipe {clip_index + 1}/{total_clips}: {clip_id}")
    logger.info(f"   Título: {clip_data.get('title', 'N/A')}")
    logger.info(f"   Duração: {clip_data.get('duration_seconds', 0)}s")
    logger.info("=" * 60)
    
    result = {
        "clip_id": clip_id,
        "title": clip_data.get("title"),
        "status": "pending",
        "video_id": None,
        "error": None
    }
    
    # Paths temporários
    video_path = TEMP_DIR / f"{clip_id}.mp4"
    frame_path = TEMP_DIR / f"{clip_id}_frame.png"
    thumbnail_path = TEMP_DIR / f"{clip_id}_thumbnail.png"
    
    try:
        # 1. Baixar segmento do VOD
        if not download_clip_segment(
            vod_url,
            clip_data.get("start_time", "00:00:00"),
            clip_data.get("end_time", "00:01:00"),
            video_path
        ):
            result["status"] = "failed"
            result["error"] = "Falha no download do segmento"
            return result
        
        # 2. Capturar frame para thumbnail
        thumbnail_timestamp = clip_data.get("thumbnail_timestamp", clip_data.get("start_time", "00:00:00"))
        
        # Calcula o timestamp relativo ao início do clipe
        start_sec = time_to_seconds(clip_data.get("start_time", "00:00:00"))
        thumb_sec = time_to_seconds(thumbnail_timestamp)
        relative_thumb = seconds_to_time(max(0, thumb_sec - start_sec))
        
        capture_thumbnail_frame(video_path, relative_thumb, frame_path)
        
        # 3. Gerar thumbnail via ChatGPT (ou usar frame original como fallback)
        if frame_path.exists():
            try:
                generate_thumbnail_chatgpt(clip_data, frame_path, thumbnail_path)
            except Exception as e:
                logger.warning(f"   ⚠️ ChatGPT falhou, usando frame original: {e}")
                import shutil
                shutil.copy(frame_path, thumbnail_path)
        
        # 4. Upload para YouTube
        video_id = upload_to_youtube(
            video_path,
            thumbnail_path if thumbnail_path.exists() else frame_path,
            clip_data,
            credentials
        )
        
        if video_id:
            result["status"] = "success"
            result["video_id"] = video_id
        else:
            result["status"] = "failed"
            result["error"] = "Falha no upload"
        
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.error(f"   ❌ Erro ao processar clipe: {e}")
        
    finally:
        # Limpar arquivos temporários
        cleanup_temp_files(video_path, frame_path, thumbnail_path)
    
    return result


def save_processing_log(results: List[Dict]):
    """Salva log de processamento"""
    summary = {
        "processed_at": datetime.now().isoformat(),
        "total_clips": len(results),
        "successful": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] in ["failed", "error"]]),
        "clips": results
    }
    
    with open(PROCESSING_LOG, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    logger.info(f"📝 Log salvo em {PROCESSING_LOG}")
    return summary


def main():
    """Função principal"""
    logger.info("=" * 60)
    logger.info("   🎬 YOUTUBE CLIP CREATOR - INICIANDO")
    logger.info("=" * 60)
    
    if len(sys.argv) < 2:
        logger.error("❌ Uso: python clip_creator.py <VOD_URL>")
        sys.exit(1)
    
    vod_url = sys.argv[1]
    logger.info(f"📹 VOD URL: {vod_url}")
    
    # Setup
    setup_directories()
    
    # Carregar configurações
    try:
        youtube_clips = load_clips_config()
        credentials = load_youtube_credentials()
    except Exception as e:
        logger.error(f"❌ Erro ao carregar configurações: {e}")
        sys.exit(1)
    
    if not youtube_clips:
        logger.warning("⚠️ Nenhum clipe do YouTube encontrado para processar!")
        sys.exit(0)
    
    # Obter info do VOD
    try:
        vod_info = get_vod_info(vod_url)
    except Exception as e:
        logger.error(f"❌ Erro ao obter info do VOD: {e}")
        sys.exit(1)
    
    # Processar cada clipe
    results = []
    total = len(youtube_clips)
    
    for i, clip in enumerate(youtube_clips):
        result = process_clip(clip, vod_url, credentials, i, total)
        results.append(result)
        
        # Pequena pausa entre uploads para evitar rate limiting
        if result["status"] == "success" and i < total - 1:
            logger.info("⏳ Aguardando 5 segundos antes do próximo clipe...")
            time.sleep(5)
    
    # Salvar resumo
    summary = save_processing_log(results)
    
    # Relatório final
    logger.info("")
    logger.info("=" * 60)
    logger.info("   📊 RESUMO FINAL")
    logger.info("=" * 60)
    logger.info(f"   Total processado: {summary['total_clips']}")
    logger.info(f"   ✅ Sucesso: {summary['successful']}")
    logger.info(f"   ❌ Falhas: {summary['failed']}")
    logger.info("=" * 60)
    
    # Exit code baseado no resultado
    if summary['failed'] > 0:
        sys.exit(1)
    
    logger.info("🎉 Processamento concluído com sucesso!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\n⚠️ Operação cancelada pelo usuário")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Erro fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
