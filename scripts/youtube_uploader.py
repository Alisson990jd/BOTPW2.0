#!/usr/bin/env python3
"""
📤 YouTube Uploader
Upload de vídeos para o YouTube usando a API
"""

import os
import pickle
import logging
import time
import random
import httplib2
from pathlib import Path
from typing import Optional, List, Dict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Categorias do YouTube
YOUTUBE_CATEGORIES = {
    "gaming": "20",
    "entertainment": "24",
    "people": "22",
    "comedy": "23",
    "howto": "26",
    "education": "27",
    "science": "28",
    "travel": "19",
    "IRL": "22",  # People & Blogs
    "react": "24",  # Entertainment
    "music": "10",
}

# Retry config
MAX_RETRIES = 5
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError)
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]


class YouTubeUploader:
    """Uploader para YouTube"""
    
    def __init__(self, credentials: Dict):
        """
        Inicializa o uploader
        
        Args:
            credentials: Dict com json_data, json_file e pkl_file
        """
        self.credentials = credentials
        self.service = self._build_service()
    
    def _build_service(self):
        """Constrói o serviço da API do YouTube"""
        pkl_file = self.credentials.get("pkl_file")
        
        if not pkl_file or not Path(pkl_file).exists():
            # Tenta encontrar o pkl na pasta analisar
            analisar_dir = Path("analisar")
            pkl_files = list(analisar_dir.glob("*.pkl"))
            if pkl_files:
                pkl_file = pkl_files[0]
            else:
                raise FileNotFoundError("Arquivo .pkl de credenciais não encontrado!")
        
        logger.info(f"🔑 Carregando credenciais de: {pkl_file}")
        
        with open(pkl_file, 'rb') as f:
            creds = pickle.load(f)
        
        # Renova se necessário
        if creds and creds.expired and creds.refresh_token:
            logger.info("🔄 Renovando token...")
            creds.refresh(Request())
            with open(pkl_file, 'wb') as f:
                pickle.dump(creds, f)
        
        return build('youtube', 'v3', credentials=creds)
    
    def _get_category_id(self, category: str) -> str:
        """Obtém o ID da categoria do YouTube"""
        return YOUTUBE_CATEGORIES.get(category.lower(), "22")  # Default: People & Blogs
    
    def _resumable_upload(self, insert_request) -> Optional[str]:
        """Executa upload resumível com retry"""
        response = None
        error = None
        retry = 0
        
        while response is None:
            try:
                logger.info("   Enviando...")
                status, response = insert_request.next_chunk()
                
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"   Progresso: {progress}%")
                    
            except HttpError as e:
                if e.resp.status in RETRIABLE_STATUS_CODES:
                    error = f"HTTP {e.resp.status}: {e.content}"
                else:
                    raise
                    
            except RETRIABLE_EXCEPTIONS as e:
                error = str(e)
            
            if error:
                retry += 1
                if retry > MAX_RETRIES:
                    logger.error(f"❌ Máximo de retries atingido")
                    return None
                
                sleep_seconds = random.random() * (2 ** retry)
                logger.warning(f"   ⚠️ Erro: {error}. Retry em {sleep_seconds:.1f}s...")
                time.sleep(sleep_seconds)
                error = None
        
        if 'id' in response:
            return response['id']
        
        return None
    
    def upload(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: List[str] = None,
        category: str = "entertainment",
        thumbnail_path: str = None,
        privacy_status: str = "private"
    ) -> Optional[str]:
        """
        Faz upload de um vídeo para o YouTube
        
        Args:
            video_path: Caminho do arquivo de vídeo
            title: Título do vídeo
            description: Descrição
            tags: Lista de tags
            category: Categoria do vídeo
            thumbnail_path: Caminho da thumbnail (opcional)
            privacy_status: 'private', 'public' ou 'unlisted'
            
        Returns:
            ID do vídeo se sucesso, None caso contrário
        """
        if not Path(video_path).exists():
            logger.error(f"❌ Vídeo não encontrado: {video_path}")
            return None
        
        # Prepara tags
        if tags is None:
            tags = []
        
        # Limita título e descrição
        title = title[:100] if len(title) > 100 else title
        description = description[:5000] if len(description) > 5000 else description
        
        # Obtém ID da categoria
        category_id = self._get_category_id(category)
        
        # Corpo da requisição
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags[:500],  # Max 500 tags
                'categoryId': category_id,
                'defaultLanguage': 'pt-BR',
                'defaultAudioLanguage': 'pt-BR'
            },
            'status': {
                'privacyStatus': privacy_status,
                'selfDeclaredMadeForKids': False,
            }
        }
        
        logger.info(f"📤 Iniciando upload: {title}")
        logger.info(f"   Arquivo: {video_path}")
        logger.info(f"   Privacidade: {privacy_status}")
        
        # Prepara o upload
        media = MediaFileUpload(
            video_path,
            chunksize=1024*1024,  # 1MB chunks
            resumable=True,
            mimetype='video/mp4'
        )
        
        try:
            insert_request = self.service.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            video_id = self._resumable_upload(insert_request)
            
            if video_id:
                logger.info(f"✅ Upload concluído! ID: {video_id}")
                logger.info(f"   URL: https://youtube.com/watch?v={video_id}")
                
                # Upload da thumbnail
                if thumbnail_path and Path(thumbnail_path).exists():
                    self._set_thumbnail(video_id, thumbnail_path)
                
                return video_id
            else:
                logger.error("❌ Falha no upload")
                return None
                
        except HttpError as e:
            logger.error(f"❌ Erro HTTP: {e.resp.status} - {e.content}")
            return None
        except Exception as e:
            logger.error(f"❌ Erro: {e}")
            return None
    
    def _set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """Define a thumbnail do vídeo"""
        logger.info(f"🖼️ Configurando thumbnail...")
        
        try:
            media = MediaFileUpload(
                thumbnail_path,
                mimetype='image/png',
                resumable=True
            )
            
            self.service.thumbnails().set(
                videoId=video_id,
                media_body=media
            ).execute()
            
            logger.info("   ✅ Thumbnail configurada!")
            return True
            
        except HttpError as e:
            # Erro 403 geralmente significa que o canal não tem permissão para thumbnails customizadas
            if e.resp.status == 403:
                logger.warning("   ⚠️ Canal não tem permissão para thumbnails customizadas")
            else:
                logger.warning(f"   ⚠️ Erro ao definir thumbnail: {e.resp.status}")
            return False
        except Exception as e:
            logger.warning(f"   ⚠️ Erro: {e}")
            return False
    
    def get_channel_info(self) -> Dict:
        """Obtém informações do canal autenticado"""
        try:
            response = self.service.channels().list(
                part='snippet,statistics',
                mine=True
            ).execute()
            
            if 'items' in response and len(response['items']) > 0:
                channel = response['items'][0]
                return {
                    'id': channel['id'],
                    'title': channel['snippet']['title'],
                    'subscribers': channel['statistics'].get('subscriberCount', 'N/A'),
                    'videos': channel['statistics'].get('videoCount', 'N/A'),
                    'views': channel['statistics'].get('viewCount', 'N/A')
                }
            
            return {}
            
        except Exception as e:
            logger.error(f"Erro ao obter info do canal: {e}")
            return {}


if __name__ == "__main__":
    # Teste
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 3:
        print("Uso: python youtube_uploader.py <pkl_file> <video_path>")
        sys.exit(1)
    
    creds = {
        "pkl_file": Path(sys.argv[1])
    }
    
    uploader = YouTubeUploader(creds)
    
    # Mostra info do canal
    info = uploader.get_channel_info()
    print(f"Canal: {info.get('title')}")
    print(f"Inscritos: {info.get('subscribers')}")
    
    # Faz upload de teste
    video_id = uploader.upload(
        video_path=sys.argv[2],
        title="Teste de Upload",
        description="Vídeo de teste",
        tags=["teste"],
        privacy_status="private"
    )
    
    sys.exit(0 if video_id else 1)
