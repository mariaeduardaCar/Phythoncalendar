import os
import psycopg2
from flask import Flask, request, jsonify, redirect, url_for, render_template
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from config import DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, GOOGLE_CALENDAR_CREDENTIALS
from calendar import monthrange
from datetime import datetime

app = Flask(__name__)

# Conectar ao banco de dados PostgreSQL
def obter_conexao_banco():
    conexao = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD)
    return conexao


@app.route('/')
def index():
    return render_template('index.html')  # Renderiza o front-end HTML

def obter_eventos_publicos():
    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
    credenciais = None
    
    # O arquivo token.json armazena o token de acesso e atualização do usuário
    if os.path.exists('token.json'):
        credenciais = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # Se não houver credenciais válidas, solicite ao usuário que faça login
    if not credenciais or not credenciais.valid:
        if credenciais and credenciais.expired and credenciais.refresh_token:
            credenciais.refresh(Request())
        else:
            fluxo = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CALENDAR_CREDENTIALS, SCOPES)
            credenciais = fluxo.run_local_server(port=0)
        # Salve as credenciais para a próxima execução
        with open('token.json', 'w') as token:
            token.write(credenciais.to_json())

    servico = build('calendar', 'v3', credentials=credenciais)

    # Obter eventos do calendário principal (pessoal)
    eventos_pessoais = servico.events().list(
        calendarId='primary',
        singleEvents=True,
        orderBy='startTime'
    ).execute().get('items', [])

    # Obter eventos do calendário de feriados
    feriados = servico.events().list(
        calendarId='pt.brazilian#holiday@group.v.calendar.google.com',
        singleEvents=True,
        orderBy='startTime'
    ).execute().get('items', [])

    # Combinar os eventos pessoais e os feriados
    eventos = eventos_pessoais + feriados
    
    return eventos


# Rota para listar eventos públicos
@app.route('/eventos_publicos', methods=['GET'])
def eventos_publicos():
    eventos = obter_eventos_publicos()
    return jsonify(eventos)


# Rota para adicionar eventos pessoais
@app.route('/adicionar_evento', methods=['POST'])
def adicionar_evento():
    try:
        # Obter dados da requisição
        dados = request.get_json()
        titulo = dados.get('titulo')
        descricao = dados.get('descricao')
        data_inicio = dados.get('data_inicio')
        data_fim = dados.get('data_fim')

        # Validar os campos
        if not titulo or not data_inicio or not data_fim:
            return jsonify({'erro': 'Título, data de início e data de fim são obrigatórios!'}), 400

        # Conectar ao banco e inserir os dados
        conexao = obter_conexao_banco()
        cursor = conexao.cursor()
        cursor.execute(
            'INSERT INTO eventos_pessoais (titulo, descricao, data_inicio, data_fim) VALUES (%s, %s, %s, %s)',
            (titulo, descricao, data_inicio, data_fim)
        )
        conexao.commit()
        cursor.close()
        conexao.close()

        return jsonify({'mensagem': 'Evento pessoal adicionado com sucesso!'}), 201

    except Exception as e:
        # Tratar erros
        return jsonify({'erro': f'Ocorreu um erro: {str(e)}'}), 500


@app.route("/calendario", methods=["GET"])
def calendario():
    ano = int(request.args.get("ano", datetime.now().year))
    mes = int(request.args.get("mes", datetime.now().month))
    primeiro_dia, dias_no_mes = monthrange(ano, mes)

    # Criar a estrutura do calendário
    calendario = [{"dia": dia, "mes": mes, "ano": ano} for dia in range(1, dias_no_mes + 1)]

    # Obter eventos públicos
    eventos_publicos = obter_eventos_publicos()

    # Obter eventos pessoais do banco de dados
    conexao = obter_conexao_banco()
    cursor = conexao.cursor()
    cursor.execute('SELECT titulo, descricao, data_inicio, data_fim FROM eventos_pessoais WHERE EXTRACT(MONTH FROM data_inicio) = %s AND EXTRACT(YEAR FROM data_inicio) = %s', (mes, ano))
    eventos_pessoais = cursor.fetchall()
    cursor.close()
    conexao.close()

    # Processar eventos públicos e pessoais para adicionar ao calendário
    eventos = []
    for evento in eventos_publicos:
        data_inicio = evento['start'].get('date') or evento['start'].get('dateTime')
        if data_inicio:
            data_inicio = datetime.strptime(data_inicio[:10], "%Y-%m-%d")
            if data_inicio.month == mes and data_inicio.year == ano:
                eventos.append({
                    "titulo": evento['summary'],
                    "descricao": evento.get('description', ''),
                    "data_inicio": data_inicio.day
                })

    for evento in eventos_pessoais:
        data_inicio = evento[2]
        if data_inicio.month == mes and data_inicio.year == ano:
            eventos.append({
                "titulo": evento[0],
                "descricao": evento[1],
                "data_inicio": data_inicio.day
            })

    # Adicionar eventos ao calendário
    for dia in calendario:
        dia["eventos"] = [evento for evento in eventos if evento["data_inicio"] == dia["dia"]]

    return jsonify({
        "calendario": calendario,
        "mes": mes,
        "ano": ano,
        "primeiro_dia": primeiro_dia
    })


# Rodar o servidor
if __name__ == '__main__':
    app.run(debug=True)
