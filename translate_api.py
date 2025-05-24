from flask import Flask, request, jsonify, send_from_directory
import os
import requests
import logging
import sys
from datetime import datetime
import uuid
from threading import Thread
import time
import re

# Configuração da API DeepL
DEEPL_API_KEY = os.environ.get('DEEPL_API_KEY', 'API_KEY')
DEEPL_API_URL = 'https://api.deepl.com/v2'
# Use api-free.deepl.com para contas gratuitas
# DEEPL_API_URL = 'https://api-free.deepl.com/v2'

# Mapeamento de idiomas
LANGUAGE_MAP = {
    'pt': 'PT',  # Português
    'en': 'EN-US'  # Inglês (EUA)
} 

# Configuração de diretórios
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public_uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configuração de logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('translate_api.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class TranslationTask:
    def __init__(self, task_id, filename, target_lang):
        self.task_id = task_id
        self.filename = filename
        self.target_lang = target_lang
        self.status = 'pending'  # pending, processing, completed, error
        self.progress = 0
        self.result_file = None
        self.error = None
        self.created_at = datetime.now()

# Dicionário global para armazenar as tasks
translation_tasks = {}

def upload_document_to_deepl(file_path: str, target_lang: str = 'EN-US', source_lang: str = 'PT') -> tuple:
    """
    Envia um documento para tradução na API DeepL
    Retorna: (document_id, document_key)
    """
    try:
        with open(file_path, 'rb') as f:
            files = {
                'file': (os.path.basename(file_path), f)
            }
            data = {
                'target_lang': target_lang,
                'source_lang': source_lang
            }
            
            response = requests.post(
                f'{DEEPL_API_URL}/document',
                headers={'Authorization': f'DeepL-Auth-Key {DEEPL_API_KEY}'},
                files=files,
                data=data
            )
            
            response.raise_for_status()
            result = response.json()
            
            return result['document_id'], result['document_key']
            
    except Exception as e:
        logger.error(f"Erro ao enviar documento para DeepL: {e}")
        raise

def check_document_status(document_id: str, document_key: str) -> dict:
    """
    Verifica o status da tradução do documento
    Retorna: dict com status e informações adicionais
    """
    try:
        response = requests.post(
            f'{DEEPL_API_URL}/document/{document_id}',
            headers={
                'Authorization': f'DeepL-Auth-Key {DEEPL_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={'document_key': document_key}
        )
        
        response.raise_for_status()
        return response.json()
        
    except Exception as e:
        logger.error(f"Erro ao verificar status do documento: {e}")
        raise

def download_translated_document(document_id: str, document_key: str, output_path: str) -> str:
    """
    Baixa o documento traduzido
    Retorna: caminho do arquivo baixado
    """
    try:
        response = requests.post(
            f'{DEEPL_API_URL}/document/{document_id}/result',
            headers={
                'Authorization': f'DeepL-Auth-Key {DEEPL_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={'document_key': document_key},
            stream=True  # Importante para arquivos grandes
        )
        
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
            
        return output_path
        
    except Exception as e:
        logger.error(f"Erro ao baixar documento traduzido: {e}")
        raise

def cleanup_file(file_path: str):
    """Função auxiliar para remover arquivos temporários"""
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.debug(f"Arquivo removido: {file_path}")
        except Exception as e:
            logger.warning(f"Erro ao remover arquivo {file_path}: {e}")

def process_translation_task(task_id: str, uploaded_file_path: str):
    """Processa uma tarefa de tradução"""
    task = translation_tasks.get(task_id)
    if not task:
        logger.error(f"Task {task_id} não encontrada.")
        cleanup_file(uploaded_file_path)
        return

    logger.info(f"Iniciando processamento para Task ID {task_id}")
    task.status = 'processing'
    task.progress = 0

    try:
        # Simulação inicial de progresso (0-10%)
        for i in range(1, 11):
            time.sleep(0.5)  # 5 segundos total
            task.progress = i
        
        # Upload do documento para DeepL
        document_id, document_key = upload_document_to_deepl(
            uploaded_file_path,
            target_lang=LANGUAGE_MAP.get(task.target_lang, 'EN-US'),
            source_lang='PT'
        )
        
        # Progresso após upload (10-20%)
        for i in range(11, 21):
            time.sleep(0.5)  # 5 segundos total
            task.progress = i
        
        # Loop de verificação de status
        max_wait_time = 3600  # 1 hora
        start_time = time.time()
        min_processing_time = 20  # Tempo mínimo de processamento em segundos
        
        while True:
            status_info = check_document_status(document_id, document_key)
            current_status = status_info.get('status', '')
            elapsed_time = time.time() - start_time
            
            if current_status == 'done':
                if elapsed_time < min_processing_time:
                    # Se terminou muito rápido, simula progresso até o tempo mínimo
                    remaining_time = min_processing_time - elapsed_time
                    steps = int((90 - task.progress) * (remaining_time / min_processing_time))
                    
                    for _ in range(steps):
                        task.progress = min(90, task.progress + 1)
                        time.sleep(remaining_time / steps)
                
                # Sanitiza o nome do arquivo para evitar problemas com URLs
                base_name = os.path.splitext(task.filename)[0]
                ext = os.path.splitext(task.filename)[1]
                
                # Remove caracteres especiais e espaços
                safe_base_name = re.sub(r'[^\w\-]', '_', base_name)
                safe_base_name = safe_base_name.strip('_')
                
                # Cria nome do arquivo traduzido
                output_filename = f"{safe_base_name}_translated_{task.target_lang}{ext}"
                output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
                
                # Simulação final (90-100%)
                for i in range(91, 101):
                    time.sleep(0.2)  # 2 segundos total
                    task.progress = i
                
                task.result_file = download_translated_document(
                    document_id, 
                    document_key,
                    output_path
                )
                task.status = 'completed'
                break
                
            elif current_status == 'error':
                error_msg = status_info.get('message', 'Erro desconhecido na tradução')
                raise Exception(f"Erro na API DeepL: {error_msg}")
                
            elif current_status in ['translating', 'queued']:
                # Calcula progresso baseado no tempo estimado
                seconds_remaining = status_info.get('seconds_remaining', 120)
                
                if seconds_remaining > 0:
                    # Estima progresso entre 20% e 90%
                    progress = min(90, max(20, 
                        20 + (elapsed_time / max(elapsed_time + seconds_remaining, min_processing_time)) * 70
                    ))
                    task.progress = int(progress)
                
                if elapsed_time > max_wait_time:
                    raise Exception("Tempo máximo de tradução excedido")
                    
                time.sleep(2)  # Verifica a cada 2 segundos
                
            else:
                raise Exception(f"Status desconhecido: {current_status}")

    except Exception as e:
        logger.error(f"Erro ao processar documento: {e}", exc_info=True)
        task.status = 'error'
        task.error = str(e)
        task.progress = 0
        
    finally:
        cleanup_file(uploaded_file_path)

@app.route('/translate', methods=['POST'])
def translate_document_route():
    """Endpoint para iniciar uma tradução"""
    logger.info(f"Nova requisição /translate recebida de {request.remote_addr}")
    
    if 'file' not in request.files:
        logger.warning("Nenhum arquivo na requisição.")
        return jsonify({'status': 'nok', 'message': 'Nenhum arquivo enviado'}), 400
    
    file = request.files['file']
    target_lang = request.form.get('target_lang', 'en')
    
    if not file.filename:
        logger.warning("Nome de arquivo vazio na requisição.")
        return jsonify({'status': 'nok', 'message': 'Nenhum arquivo selecionado'}), 400
    
    # Verifica extensão do arquivo
    allowed_extensions = {'.docx', '.doc', '.pdf', '.pptx', '.xlsx', '.txt', '.html', '.htm'}
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        return jsonify({
            'status': 'nok', 
            'message': f'Formato de arquivo não suportado. Use: {", ".join(allowed_extensions)}'
        }), 400
    
    original_filename = file.filename
    logger.info(f"Arquivo recebido: '{original_filename}', Idioma alvo: '{target_lang}'")
    
    task_id = str(uuid.uuid4())
    task = TranslationTask(task_id, original_filename, target_lang)
    translation_tasks[task_id] = task
    
    safe_original_basename = re.sub(r'[^\w\s.-]', '', os.path.splitext(original_filename)[0])
    temp_filename = f"upload_{task_id}_{safe_original_basename[:50]}{file_ext}"
    uploaded_temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
    
    try:
        file.save(uploaded_temp_path)
        logger.info(f"Arquivo salvo temporariamente como: {uploaded_temp_path}")
        
        thread = Thread(
            target=process_translation_task,
            args=(task_id, uploaded_temp_path),
            name=f"TaskThread-{task_id[:8]}"
        )
        thread.start()
        
        return jsonify({
            'status': 'ok',
            'message': 'Tradução iniciada. Verifique o status da tarefa periodicamente.',
            'task_id': task_id,
            'check_status_url': f'/task/{task_id}'
        }), 202
        
    except Exception as e:
        logger.critical(f"Erro ao iniciar tradução: {e}", exc_info=True)
        task.status = 'error'
        task.error = str(e)
        cleanup_file(uploaded_temp_path)
        return jsonify({
            'status': 'nok',
            'message': f"Erro interno do servidor: {str(e)}"
        }), 500

@app.route('/task/<task_id>', methods=['GET'])
def check_task_status_route(task_id: str):
    """Endpoint para verificar status de uma tradução"""
    logger.debug(f"Requisição de status para Task ID: {task_id}")
    task = translation_tasks.get(task_id)
    
    if not task:
        logger.warning(f"Task ID {task_id} não encontrada.")
        return jsonify({
            'status': 'nok',
            'message': 'Tarefa de tradução não encontrada.'
        }), 404
        
    response_data = {
        'task_id': task.task_id,
        'filename': task.filename,
        'target_lang': task.target_lang,
        'status': task.status,
        'progress': task.progress,
        'created_at': task.created_at.isoformat()
    }
    
    if task.status == 'completed' and task.result_file:
        response_data['download_url'] = f"/download/{os.path.basename(task.result_file)}"
        response_data['message'] = "Tradução concluída com sucesso."
    elif task.status == 'error':
        response_data['error_message'] = task.error
        response_data['message'] = "Tradução falhou."
    elif task.status == 'processing':
        response_data['message'] = f"Tradução em progresso... {task.progress}%"
    else:
        response_data['message'] = "Tradução pendente, aguardando início."

    return jsonify(response_data)

@app.route('/download/<filename>')
def download_file_route(filename: str):
    """Endpoint para download do arquivo traduzido"""
    logger.info(f"Requisição de download para: {filename}")
    
    # Sanitiza o nome do arquivo
    safe_filename = re.sub(r'[^\w\-\.]', '_', filename)
    safe_filename = safe_filename.strip('_')
    
    if safe_filename != filename:
        logger.warning(f"Nome do arquivo sanitizado de '{filename}' para '{safe_filename}'")
    
    if ".." in safe_filename or safe_filename.startswith(("/", "\\")):
        logger.warning(f"Tentativa de download com nome de arquivo inválido: {filename}")
        return jsonify({
            'status': 'nok',
            'message': 'Nome de arquivo inválido.'
        }), 400

    try:
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            safe_filename,
            as_attachment=True,
            # Adiciona o nome original como fallback para o download
            download_name=filename
        )
    except FileNotFoundError:
        logger.error(f"Arquivo não encontrado: {safe_filename}")
        return jsonify({
            'status': 'nok',
            'message': 'Arquivo não encontrado.'
        }), 404
    except Exception as e:
        logger.error(f"Erro ao servir arquivo '{safe_filename}': {e}", exc_info=True)
        return jsonify({
            'status': 'nok',
            'message': 'Erro interno ao processar download.'
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get("FLASK_PORT", os.environ.get("PORT", 5003)))
    host = os.environ.get("FLASK_HOST", '0.0.0.0')
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    logger.info(f"Iniciando servidor Flask em {host}:{port} (Debug: {debug_mode})")
    logger.info(f"Pasta de uploads configurada: {UPLOAD_FOLDER}")
    
    app.run(host=host, port=port, debug=debug_mode) 