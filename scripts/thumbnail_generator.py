#!/usr/bin/env python3
"""
🎨 Thumbnail Generator via ChatGPT
Gera thumbnails usando ChatGPT com login automático via Gmail
"""

import os
import re
import time
import pickle
import base64
import requests
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class ThumbnailGenerator:
    """Gerador de thumbnails usando ChatGPT"""
    
    def __init__(self, gmail_token_path: str = "gmail_token.pkl", headless: bool = True):
        self.gmail_token_path = gmail_token_path
        self.headless = headless
        self.email_address = self._get_email_from_token()
        self.timeout = 60000
        
    def _get_email_from_token(self) -> str:
        """Obtém o email do token do Gmail"""
        # Email padrão - ajuste conforme necessário
        return "expulsion-flip-elk@duck.com"
    
    def _get_gmail_service(self):
        """Carrega as credenciais do pickle e retorna o serviço Gmail"""
        if not os.path.exists(self.gmail_token_path):
            raise FileNotFoundError(f"❌ Arquivo '{self.gmail_token_path}' não encontrado!")
        
        with open(self.gmail_token_path, 'rb') as token:
            creds = pickle.load(token)
        
        if creds and creds.expired and creds.refresh_token:
            logger.info("🔄 Renovando token do Gmail...")
            creds.refresh(Request())
            with open(self.gmail_token_path, 'wb') as token:
                pickle.dump(creds, token)
        
        return build('gmail', 'v1', credentials=creds)
    
    def _get_chatgpt_code(self, service, max_attempts: int = 30, interval: int = 2) -> str:
        """Aguarda e extrai o código de verificação do ChatGPT do email"""
        logger.info("📧 Aguardando email com código do ChatGPT...")
        
        start_time = datetime.now(timezone.utc)
        
        for attempt in range(max_attempts):
            query = "from:noreply@tm.openai.com subject:Your ChatGPT code is"
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=5
            ).execute()
            
            messages = results.get('messages', [])
            
            for msg in messages:
                message = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()
                
                internal_date = int(message.get('internalDate', 0)) / 1000
                email_time = datetime.fromtimestamp(internal_date, tz=timezone.utc)
                
                if email_time < start_time:
                    continue
                
                headers = message['payload'].get('headers', [])
                subject = next(
                    (h['value'] for h in headers if h['name'].lower() == 'subject'),
                    ''
                )
                
                match = re.search(r'Your ChatGPT code is (\d{6})', subject)
                if match:
                    code = match.group(1)
                    logger.info(f"✅ Código encontrado: {code}")
                    return code
            
            time.sleep(interval)
        
        raise TimeoutError("❌ Tempo esgotado aguardando o email com o código.")
    
    def _download_image_direct(self, url: str, cookies: list, user_agent: str, output_path: str) -> bool:
        """Baixa a imagem usando as cookies da sessão"""
        cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        
        headers = {
            "Cookie": cookie_str,
            "User-Agent": user_agent,
            "Referer": "https://chatgpt.com/"
        }
        
        response = requests.get(url, headers=headers, stream=True)
        
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        return False
    
    def generate(self, image_path: str, prompt: str, output_path: str) -> bool:
        """
        Gera uma thumbnail usando ChatGPT
        
        Args:
            image_path: Caminho da imagem base
            prompt: Prompt para o ChatGPT
            output_path: Caminho para salvar a thumbnail gerada
            
        Returns:
            True se sucesso, False caso contrário
        """
        from playwright.sync_api import sync_playwright
        
        if not os.path.exists(image_path):
            logger.error(f"❌ Imagem não encontrada: {image_path}")
            return False
        
        logger.info("🌐 Iniciando geração de thumbnail via ChatGPT...")
        
        # Inicializa Gmail
        try:
            gmail_service = self._get_gmail_service()
            logger.info("✅ Gmail conectado!")
        except Exception as e:
            logger.error(f"❌ Erro ao conectar Gmail: {e}")
            return False
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )
            
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                accept_downloads=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                locale='en-US',
            )
            
            page = context.new_page()
            page.set_default_timeout(self.timeout)
            
            try:
                # ============================================
                # ETAPA 1: LOGIN
                # ============================================
                logger.info("🔐 Fazendo login no ChatGPT...")
                
                page.goto("https://chatgpt.com/", wait_until='networkidle')
                
                # Clica em Log in
                login_button = page.locator('[data-testid="login-button"]')
                login_button.wait_for(state='visible', timeout=10000)
                login_button.click()
                
                # Insere email
                email_input = page.locator('input[name="email"]')
                email_input.wait_for(state='visible')
                email_input.fill(self.email_address)
                
                # Continue
                continue_button = page.locator('button[type="submit"]:has-text("Continue")')
                continue_button.wait_for(state='visible')
                time.sleep(0.5)
                continue_button.click()
                
                # Obtém código do email
                code = self._get_chatgpt_code(gmail_service)
                
                # Insere código
                code_input = page.locator('input[name="code"]')
                code_input.wait_for(state='visible')
                code_input.fill(code)
                
                # Valida
                validate_button = page.locator('button[name="intent"][value="validate"]')
                validate_button.wait_for(state='visible')
                validate_button.click()
                
                # Aguarda login
                page.wait_for_url("**/", timeout=30000)
                time.sleep(3)
                
                logger.info("✅ Login realizado!")
                
                # ============================================
                # ETAPA 2: CRIAR IMAGEM
                # ============================================
                page.goto("https://chatgpt.com/", wait_until='domcontentloaded')
                time.sleep(3)
                
                # Clica no botão +
                plus_btn = page.locator('[data-testid="composer-plus-btn"]')
                plus_btn.wait_for(state="visible", timeout=15000)
                plus_btn.click()
                time.sleep(1)
                
                # Seleciona "Create image"
                create_image_btn = page.locator('div[role="menuitemradio"]:has-text("Create image")')
                create_image_btn.wait_for(state="visible", timeout=5000)
                create_image_btn.click()
                time.sleep(2)
                
                # ============================================
                # ETAPA 3: ADICIONAR IMAGEM
                # ============================================
                logger.info("📎 Adicionando imagem...")
                
                # Tenta via input file
                try:
                    file_input = page.locator('input[type="file"]').first
                    file_input.set_input_files(image_path)
                    time.sleep(2)
                    logger.info("   ✅ Imagem adicionada!")
                except Exception as e:
                    # Fallback: drag and drop
                    logger.info("   Tentando drag and drop...")
                    with open(image_path, 'rb') as f:
                        file_content = base64.b64encode(f.read()).decode()
                    
                    file_name = os.path.basename(image_path)
                    page.evaluate(f'''
                        () => {{
                            const base64 = "{file_content}";
                            const binaryString = atob(base64);
                            const bytes = new Uint8Array(binaryString.length);
                            for (let i = 0; i < binaryString.length; i++) {{
                                bytes[i] = binaryString.charCodeAt(i);
                            }}
                            const blob = new Blob([bytes], {{ type: 'image/png' }});
                            const file = new File([blob], '{file_name}', {{ type: 'image/png' }});
                            
                            const target = document.querySelector('#prompt-textarea') || document.querySelector('[contenteditable="true"]');
                            if (!target) return false;
                            
                            const dataTransfer = new DataTransfer();
                            dataTransfer.items.add(file);
                            
                            ['dragenter', 'dragover', 'drop'].forEach(eventType => {{
                                const event = new DragEvent(eventType, {{
                                    bubbles: true,
                                    cancelable: true,
                                    dataTransfer: dataTransfer
                                }});
                                target.dispatchEvent(event);
                            }});
                            return true;
                        }}
                    ''')
                    time.sleep(3)
                
                # ============================================
                # ETAPA 4: INSERIR PROMPT
                # ============================================
                logger.info("📝 Inserindo prompt...")
                
                # Limita o tamanho do prompt para evitar problemas
                prompt_truncated = prompt[:2000] if len(prompt) > 2000 else prompt
                prompt_escaped = prompt_truncated.replace('"', '\\"').replace('\n', '\\n')
                
                textarea = page.locator('#prompt-textarea')
                textarea.wait_for(state="visible", timeout=5000)
                textarea.click()
                time.sleep(0.5)
                
                page.evaluate(f'''
                    () => {{
                        const textarea = document.querySelector('#prompt-textarea');
                        if (!textarea) return;
                        const p = textarea.querySelector('p');
                        if (p) {{
                            p.innerHTML = "{prompt_escaped}";
                        }} else {{
                            textarea.innerHTML = "<p>{prompt_escaped}</p>";
                        }}
                        textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }}
                ''')
                time.sleep(1)
                
                # ============================================
                # ETAPA 5: ENVIAR
                # ============================================
                logger.info("📤 Enviando...")
                
                send_btn = page.locator('#composer-submit-button')
                send_btn.wait_for(state="visible", timeout=5000)
                send_btn.click()
                
                # ============================================
                # ETAPA 6: AGUARDAR GERAÇÃO (4 minutos)
                # ============================================
                logger.info("⏳ Aguardando geração (4 minutos)...")
                
                for remaining in range(240, 0, -30):
                    mins = remaining // 60
                    secs = remaining % 60
                    logger.info(f"   Tempo restante: {mins:02d}:{secs:02d}")
                    time.sleep(30)
                
                # ============================================
                # ETAPA 7: BAIXAR IMAGEM
                # ============================================
                logger.info("⬇️ Baixando imagem gerada...")
                
                time.sleep(5)
                
                image_containers = page.locator('div[class*="group/imagegen-image"]').all()
                
                if len(image_containers) > 0:
                    last_container = image_containers[-1]
                    last_container.hover()
                    time.sleep(1)
                    
                    download_btn = last_container.locator('button[aria-label="Download this image"]')
                    
                    try:
                        download_btn.wait_for(state="visible", timeout=5000)
                        
                        with page.expect_download(timeout=60000) as download_info:
                            download_btn.click()
                        
                        download = download_info.value
                        download.save_as(output_path)
                        
                        logger.info(f"✅ Thumbnail salva: {output_path}")
                        return True
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Erro no download via botão: {e}")
                        
                        # Tenta download direto
                        img_url = page.evaluate('''
                            () => {
                                const containers = document.querySelectorAll('div[class*="group/imagegen-image"]');
                                if (containers.length > 0) {
                                    const lastContainer = containers[containers.length - 1];
                                    const img = lastContainer.querySelector('img[alt="Generated image"]');
                                    return img ? img.src : null;
                                }
                                return null;
                            }
                        ''')
                        
                        if img_url:
                            cookies = context.cookies()
                            user_agent = page.evaluate("navigator.userAgent")
                            
                            if self._download_image_direct(img_url, cookies, user_agent, output_path):
                                logger.info(f"✅ Thumbnail salva via download direto: {output_path}")
                                return True
                
                logger.error("❌ Não foi possível baixar a imagem")
                return False
                
            except Exception as e:
                logger.error(f"❌ Erro durante geração: {e}")
                page.screenshot(path=f"error_screenshots/chatgpt_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                return False
                
            finally:
                browser.close()


if __name__ == "__main__":
    # Teste
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 3:
        print("Uso: python thumbnail_generator.py <imagem_base> <output>")
        sys.exit(1)
    
    generator = ThumbnailGenerator(headless=False)
    success = generator.generate(
        image_path=sys.argv[1],
        prompt="transforme em uma thumbnail para youtube(1280x720)",
        output_path=sys.argv[2]
    )
    
    sys.exit(0 if success else 1)
