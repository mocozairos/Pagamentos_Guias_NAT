import streamlit as st
import pandas as pd
import mysql.connector
import decimal
from babel.numbers import format_currency
from google.oauth2 import service_account
import gspread 
import requests
from datetime import time

def gerar_df_phoenix(vw_name, base_luck):

    # Parametros de Login AWS
    config = {
    'user': 'user_automation_jpa',
    'password': 'luck_jpa_2024',
    'host': 'comeia.cixat7j68g0n.us-east-1.rds.amazonaws.com',
    'database': base_luck
    }
    # Conexão as Views
    conexao = mysql.connector.connect(**config)
    cursor = conexao.cursor()

    request_name = f'SELECT * FROM {vw_name}'

    # Script MySql para requests
    cursor.execute(
        request_name
    )
    # Coloca o request em uma variavel
    resultado = cursor.fetchall()
    # Busca apenas o cabecalhos do Banco
    cabecalho = [desc[0] for desc in cursor.description]

    # Fecha a conexão
    cursor.close()
    conexao.close()

    # Coloca em um dataframe e muda o tipo de decimal para float
    df = pd.DataFrame(resultado, columns=cabecalho)
    df = df.applymap(lambda x: float(x) if isinstance(x, decimal.Decimal) else x)
    return df

def puxar_dados_phoenix():

    st.session_state.df_escalas = gerar_df_phoenix('vw_payment_guide', 'test_phoenix_natal')

    st.session_state.df_escalas = st.session_state.df_escalas[~(st.session_state.df_escalas['Status da Reserva'].isin(['CANCELADO', 'PENDENCIA DE IMPORTAÇÃO'])) & 
                                                              ~(pd.isna(st.session_state.df_escalas['Status da Reserva'])) & ~(pd.isna(st.session_state.df_escalas['Escala'])) & 
                                                              ~(pd.isna(st.session_state.df_escalas['Guia']))].reset_index(drop=True)

def puxar_aba_simples(id_gsheet, nome_aba, nome_df):

    nome_credencial = st.secrets["CREDENCIAL_SHEETS"]
    credentials = service_account.Credentials.from_service_account_info(nome_credencial)
    scope = ['https://www.googleapis.com/auth/spreadsheets']
    credentials = credentials.with_scopes(scope)
    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(id_gsheet)
    
    sheet = spreadsheet.worksheet(nome_aba)

    sheet_data = sheet.get_all_values()

    st.session_state[nome_df] = pd.DataFrame(sheet_data[1:], columns=sheet_data[0])

def inserir_info_sheets(df_pag_final, nome_aba, id_gsheet):

    nome_credencial = st.secrets["CREDENCIAL_SHEETS"]
    credentials = service_account.Credentials.from_service_account_info(nome_credencial)
    scope = ['https://www.googleapis.com/auth/spreadsheets']
    credentials = credentials.with_scopes(scope)
    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(id_gsheet)
    
    sheet = spreadsheet.worksheet(nome_aba)

    sheet.batch_clear(["2:100000"])

    df_pag_final = df_pag_final.fillna("").astype(str)

    data_to_insert = df_pag_final.values.tolist()

    sheet.update("A2", data_to_insert)
    
    st.success('Informações de Pagamentos inseridas na planilha!')

def transformar_em_listas(idiomas):

    return list(set(idiomas))

def tratar_colunas_idioma(df_escalas_group):
    
    df_idiomas = df_escalas_group[df_escalas_group['Idioma'].apply(lambda idiomas: idiomas != ['pt-br'])].reset_index()

    df_idiomas['Idioma'] = df_idiomas['Idioma'].apply(lambda idiomas: ', '.join([idioma for idioma in idiomas if idioma != 'pt-br']))

    df_escalas_group['Idioma'] = ''

    for index, index_principal in df_idiomas['index'].items():

        df_escalas_group.at[index_principal, 'Idioma'] = df_idiomas.at[index, 'Idioma']

    df_escalas_group['Idioma'] = df_escalas_group['Idioma'].replace({'all': 'en-us', 'it-ele': 'en-us'})

    return df_escalas_group

def verificar_tarifarios(df_escalas_group, id_gsheet):

    lista_passeios = df_escalas_group['Servico'].unique().tolist()

    lista_passeios_tarifario = st.session_state.df_tarifario['Servico'].unique().tolist()

    lista_passeios_sem_tarifario = [item for item in lista_passeios if not item in lista_passeios_tarifario]

    if len(lista_passeios_sem_tarifario)>0:

        df_itens_faltantes = pd.DataFrame(lista_passeios_sem_tarifario, columns=['Serviços'])

        st.dataframe(df_itens_faltantes, hide_index=True)

        nome_credencial = st.secrets["CREDENCIAL_SHEETS"]
        credentials = service_account.Credentials.from_service_account_info(nome_credencial)
        scope = ['https://www.googleapis.com/auth/spreadsheets']
        credentials = credentials.with_scopes(scope)
        client = gspread.authorize(credentials)
        
        spreadsheet = client.open_by_key(id_gsheet)

        sheet = spreadsheet.worksheet('Tarifário Robô')
        sheet_data = sheet.get_all_values()
        last_filled_row = len(sheet_data)
        data = df_itens_faltantes.values.tolist()
        start_row = last_filled_row + 1
        start_cell = f"A{start_row}"
        
        sheet.update(start_cell, data)

        st.error('Os serviços acima não estão tarifados. Eles foram inseridos no final da planilha de tarifários. Por favor, tarife os serviços e tente novamente')

    else:

        st.success('Todos os serviços estão tarifados!')

def retirar_idioma_tour_reg_8_paxs(df_escalas_group):

    df_tour_regular_idioma = df_escalas_group[(df_escalas_group['Tipo de Servico']=='TOUR') & (df_escalas_group['Modo']=='REGULAR') & (df_escalas_group['Idioma']!='') & 
                                              (df_escalas_group['Total ADT | CHD']<8)].reset_index()
    
    for index, index_principal in df_tour_regular_idioma['index'].items():

        df_escalas_group.at[index_principal, 'Idioma'] = ''

    return df_escalas_group

def calcular_adicional_motoguia_tour(df_escalas_pag):

    df_escalas_pag['Adicional Passeio Motoguia'] = 0

    df_escalas_pag.loc[(df_escalas_pag['Motorista']==df_escalas_pag['Guia']) & (df_escalas_pag['Tipo de Servico']=='TOUR'), 'Adicional Passeio Motoguia'] = 50

    return df_escalas_pag

def calcular_adicional_20h_pipatour(df_escalas_pag):

    df_escalas_pag['Adicional Motoguia Após 20:00'] = 0

    df_escalas_pag.loc[(df_escalas_pag['Servico']=='Pipatour ') & (df_escalas_pag['Motorista']==df_escalas_pag['Guia']), 'Adicional Motoguia Após 20:00'] = 25

    return df_escalas_pag

def criar_colunas_escala_veiculo_mot_guia(df_apoios):

    df_apoios[['Escala Apoio', 'Veiculo Apoio', 'Motorista Apoio', 'Guia Apoio']] = ''

    df_apoios['Apoio'] = df_apoios['Apoio'].str.replace('Escala Auxiliar: ', '', regex=False)

    df_apoios['Apoio'] = df_apoios['Apoio'].str.replace(' Veículo: ', '', regex=False)

    df_apoios['Apoio'] = df_apoios['Apoio'].str.replace(' Motorista: ', '', regex=False)

    df_apoios['Apoio'] = df_apoios['Apoio'].str.replace(' Guia: ', '', regex=False)

    df_apoios[['Escala Apoio', 'Veiculo Apoio', 'Motorista Apoio', 'Guia Apoio']] = \
        df_apoios['Apoio'].str.split(',', expand=True)
    
    return df_apoios

def preencher_colunas_df(df_apoios_group):

    df_apoios_group['Modo']='REGULAR'

    df_apoios_group['Tipo de Servico']='TOUR'

    df_apoios_group['Servico']='APOIO'

    df_apoios_group['Est. Origem']=''

    df_apoios_group[['Valor']]=28

    return df_apoios_group

def adicionar_apoios_em_dataframe(df_escalas_pag):

    df_escalas_com_apoio = df_escalas_pag[~pd.isna(df_escalas_pag['Apoio'])].reset_index(drop=True)

    df_escalas_com_apoio = criar_colunas_escala_veiculo_mot_guia(df_escalas_com_apoio)

    df_apoios_group = df_escalas_com_apoio.groupby(['Escala Apoio', 'Veiculo Apoio', 'Motorista Apoio', 'Guia Apoio']).agg({'Data da Escala': 'first', 'Data | Horario Apresentacao': 'first'}).reset_index()

    df_apoios_group = df_apoios_group.rename(columns={'Veiculo Apoio': 'Veiculo', 'Motorista Apoio': 'Motorista', 'Guia Apoio': 'Guia', 'Escala Apoio': 'Escala'})

    df_apoios_group = df_apoios_group[['Data da Escala', 'Escala', 'Veiculo', 'Motorista', 'Guia', 'Data | Horario Apresentacao']]

    df_apoios_group[['Servico', 'Tipo de Servico', 'Modo', 'Apoio', 'Idioma', 'Total ADT | CHD', 'Horario Voo', 'Valor Padrão', 'Valor Espanhol', 'Valor Inglês', 
                     'Adicional Passeio Motoguia', 'Adicional Motoguia Após 20:00']] = ['APOIO', 'TRANSFER', 'REGULAR', None, '', 0, time(0,0), 28, 28, 28, 0, 0]

    df_escalas_pag = pd.concat([df_escalas_pag, df_apoios_group], ignore_index=True)

    return df_escalas_pag

def calcular_adicional_motoguia_ref_apoio(df_escalas_pag):

    df_escalas_pag['Adicional Diária Motoguia TRF|APOIO'] = 0

    df_motoguias_trf = df_escalas_pag[(df_escalas_pag['Motorista']==df_escalas_pag['Guia']) & (df_escalas_pag['Tipo de Servico'].isin(['TRANSFER', 'IN', 'OUT']))].reset_index()

    df_data_motoguia = df_motoguias_trf[['Data da Escala', 'Guia']].drop_duplicates().reset_index(drop=True)

    for index in range(len(df_data_motoguia)):

        data_ref = df_data_motoguia.at[index, 'Data da Escala']

        guia_ref = df_data_motoguia.at[index, 'Guia']

        df_ref = df_motoguias_trf[(df_motoguias_trf['Data da Escala']==data_ref) & (df_motoguias_trf['Guia']==guia_ref)].reset_index(drop=True)

        if len(df_ref)==1:

            df_escalas_pag.at[df_ref.at[0, 'index'], 'Adicional Diária Motoguia TRF|APOIO'] = 60

        else:

            df_escalas_pag.at[df_ref.at[0, 'index'], 'Adicional Diária Motoguia TRF|APOIO'] = 90

    
    return df_escalas_pag

def calcular_adicional_apos_20h_trf(df_escalas_pag):

    df_trf_motoguia = df_escalas_pag[(df_escalas_pag['Tipo de Servico']!='TOUR') & (df_escalas_pag['Servico']!='APOIO') & (df_escalas_pag['Horario Voo']!='None') & 
                                     ((df_escalas_pag['Motorista']==df_escalas_pag['Guia']))].reset_index()

    df_trf_motoguia['Horario Voo'] = df_trf_motoguia['Horario Voo'].apply(lambda x: pd.to_datetime(x).time() if isinstance(x, str) else x)

    dict_masks = {'Natal|Camurupim': time(19,0), 'Pipa|Touros': time(17,0), 'Gostoso': time(16,30)}

    for mascara in dict_masks:

        df_trf_ref = df_trf_motoguia[(df_trf_motoguia['Servico'].str.contains(mascara, case=False, na=False)) & (df_trf_motoguia['Horario Voo']>=dict_masks[mascara])]\
            .reset_index(drop=True)

        df_data_guia = df_trf_ref[['Data da Escala', 'Guia']].drop_duplicates().reset_index(drop=True)

        for index in range(len(df_data_guia)):

            data_ref = df_data_guia.at[index, 'Data da Escala']

            guia_ref = df_data_guia.at[index, 'Guia']

            df_ref = df_escalas_pag[(df_escalas_pag['Data da Escala']==data_ref) & (df_escalas_pag['Guia']==guia_ref)].reset_index()

            df_ref['Data | Horario Apresentacao'] = pd.to_datetime(df_ref['Data | Horario Apresentacao']).dt.time

            df_ref['Horario Voo'] = df_ref['Horario Voo'].fillna('00:00:00')

            df_ref['Horario Voo'] = df_ref['Horario Voo'].apply(lambda x: pd.to_datetime(x).time() if isinstance(x, str) else x)

            hora_inicio = df_ref['Data | Horario Apresentacao'].min()

            hora_final = df_ref['Horario Voo'].max()

            if hora_inicio<=time(16,0) and hora_final>=dict_masks[mascara]:

                df_escalas_pag.at[df_ref.at[0, 'index'], 'Adicional Motoguia Após 20:00'] = 25

    return df_escalas_pag

def definir_valor_diaria(df_escalas_pag):

    df_escalas_pag['Valor Serviço'] = 0

    df_escalas_pag.loc[df_escalas_pag['Idioma']=='', 'Valor Serviço'] = df_escalas_pag['Valor Padrão']

    df_escalas_pag.loc[df_escalas_pag['Idioma']=='en-us', 'Valor Serviço'] = df_escalas_pag['Valor Inglês']

    df_escalas_pag.loc[df_escalas_pag['Idioma']=='es-es', 'Valor Serviço'] = df_escalas_pag['Valor Espanhol']

    lista_escalas_sem_diaria = df_escalas_pag[df_escalas_pag['Valor Serviço']==0]['Escala'].unique().tolist()

    if len(lista_escalas_sem_diaria):

        nomes_escalas = ', '.join(lista_escalas_sem_diaria)

        st.error(f'As escalas {nomes_escalas} estão com idioma não identificado. Entre em contato com Marcelo pra resolver isso aqui, por favor')

        st.stop()

    return df_escalas_pag

def definir_html(df_ref):

    html=df_ref.to_html(index=False, escape=False)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                text-align: center;  /* Centraliza o texto */
            }}
            table {{
                margin: 0 auto;  /* Centraliza a tabela */
                border-collapse: collapse;  /* Remove espaço entre as bordas da tabela */
            }}
            th, td {{
                padding: 8px;  /* Adiciona espaço ao redor do texto nas células */
                border: 1px solid black;  /* Adiciona bordas às células */
                text-align: center;
            }}
        </style>
    </head>
    <body>
        {html}
    </body>
    </html>
    """

    return html

def criar_output_html(nome_html, html, guia, soma_servicos):

    with open(nome_html, "w", encoding="utf-8") as file:

        file.write(f'<p style="font-size:40px;">{guia}</p><br><br>')

        file.write(html)

        file.write(f'<br><br><p style="font-size:40px;">O valor total dos serviços é {soma_servicos}</p>')

def verificar_guia_sem_telefone(id_gsheet, guia, lista_guias_com_telefone):

    if not guia in lista_guias_com_telefone:

        lista_guias = []

        lista_guias.append(guia)

        df_itens_faltantes = pd.DataFrame(lista_guias, columns=['Guias'])

        st.dataframe(df_itens_faltantes, hide_index=True)

        nome_credencial = st.secrets["CREDENCIAL_SHEETS"]
        credentials = service_account.Credentials.from_service_account_info(nome_credencial)
        scope = ['https://www.googleapis.com/auth/spreadsheets']
        credentials = credentials.with_scopes(scope)
        client = gspread.authorize(credentials)
        
        spreadsheet = client.open_by_key(id_gsheet)

        sheet = spreadsheet.worksheet('Telefones Guias')
        sheet_data = sheet.get_all_values()
        last_filled_row = len(sheet_data)
        data = df_itens_faltantes.values.tolist()
        start_row = last_filled_row + 1
        start_cell = f"A{start_row}"
        
        sheet.update(start_cell, data)

        st.error(f'O guia {guia} não tem número de telefone cadastrado na planilha. Ele foi inserido no final da lista de guias. Por favor, cadastre o telefone dele e tente novamente')

        st.stop()

    else:

        telefone_guia = st.session_state.df_telefones.loc[st.session_state.df_telefones['Guias']==guia, 'Telefone'].values[0]

    return telefone_guia

st.set_page_config(layout='wide')

with st.spinner('Puxando dados do Phoenix...'):

    if not 'df_escalas' in st.session_state:

        puxar_dados_phoenix()

st.title('Mapa de Pagamento - Guias')

st.divider()

row1 = st.columns(2)

with row1[0]:

    container_datas = st.container(border=True)

    container_datas.subheader('Período')

    data_inicial = container_datas.date_input('Data Inicial', value=None ,format='DD/MM/YYYY', key='data_inicial')

    data_final = container_datas.date_input('Data Inicial', value=None ,format='DD/MM/YYYY', key='data_final')

    gerar_mapa = container_datas.button('Gerar Mapa de Pagamentos')

    inserir = container_datas.button('Inserir infos no Drive')

with row1[1]:

    atualizar_phoenix = st.button('Atualizar Dados Phoenix')

if atualizar_phoenix:

    puxar_dados_phoenix()

if gerar_mapa:

    # Puxando tarifários e tratando colunas de números

    # puxar_aba_simples('1tsaBFwE3KS84r_I5-g3YGP7tTROe1lyuCw_UjtxofYI', 'Tarifário Robô', 'df_tarifario')

    # st.session_state.df_tarifario[['Valor Padrão', 'Valor Espanhol', 'Valor Inglês']] = st.session_state.df_tarifario[['Valor Padrão', 'Valor Espanhol', 'Valor Inglês']]\
    #     .apply(pd.to_numeric, errors='coerce')

    # Filtrando período solicitado pelo usuário

    df_escalas = st.session_state.df_escalas[(st.session_state.df_escalas['Data da Escala'] >= data_inicial) & (st.session_state.df_escalas['Data da Escala'] <= data_final)].reset_index(drop=True)

    # Adicionando somatório de ADT e CHD

    df_escalas['Total ADT | CHD'] = df_escalas['Total ADT'] + df_escalas['Total CHD']

    # Agrupando escalas

    df_escalas_group = df_escalas.groupby(['Data da Escala', 'Escala', 'Veiculo', 'Motorista', 'Guia', 'Servico', 'Tipo de Servico', 'Modo'])\
        .agg({'Apoio': 'first',  'Idioma': transformar_em_listas, 'Total ADT | CHD': 'sum', 'Horario Voo': transformar_em_listas, 'Data | Horario Apresentacao': 'min'}).reset_index()
    
    # Tratando coluna Idioma

    df_escalas_group = tratar_colunas_idioma(df_escalas_group)

    # Verificando se todos os serviços estão tarifados

    verificar_tarifarios(df_escalas_group, '1tsaBFwE3KS84r_I5-g3YGP7tTROe1lyuCw_UjtxofYI')

    # Colocando valores tarifarios
    
    df_escalas_pag = pd.merge(df_escalas_group, st.session_state.df_tarifario, on='Servico', how='left')

    # Retirando informação da coluna Idioma para TOUR REGULAR com menos de 8 paxs

    df_escalas_pag = retirar_idioma_tour_reg_8_paxs(df_escalas_pag)

    # Calculando adicional p/ tours como motoguia

    df_escalas_pag = calcular_adicional_motoguia_tour(df_escalas_pag)

    # Calculando adicional motoguia após 20:00 p/ Pipatour

    df_escalas_pag = calcular_adicional_20h_pipatour(df_escalas_pag)

    # Pegando horário de último voo de cada escala

    df_escalas_pag['Horario Voo'] = df_escalas_pag['Horario Voo'].apply(lambda lista: max(lista) if isinstance(lista, list) and lista else None)

    # Adicionando Apoios no dataframe de pagamentos

    df_escalas_pag = adicionar_apoios_em_dataframe(df_escalas_pag)

    # Calculando adicional p/ motoguias em diversos TRF/APOIO

    df_escalas_pag = calcular_adicional_motoguia_ref_apoio(df_escalas_pag)

    # Calculando adicional motoguia após 20:00 p/ Transfers Natal, Camurupim, Pipa, Touros ou São Miguel do Gostoso

    df_escalas_pag = calcular_adicional_apos_20h_trf(df_escalas_pag)

    # Definindo valores de diárias

    df_escalas_pag = definir_valor_diaria(df_escalas_pag)

    # Somando valores pra calcular o valor total de cada linha

    df_escalas_pag['Valor Total'] = df_escalas_pag[['Adicional Passeio Motoguia', 'Adicional Motoguia Após 20:00', 'Adicional Diária Motoguia TRF|APOIO', 'Valor Serviço']].sum(axis=1)

    # Ajustando pagamentos de DIDI e RODRIGO SALES

    df_escalas_pag.loc[(df_escalas_pag['Guia']=='DIDI') | (df_escalas_pag['Guia']=='RODRIGO SALES'), 'Valor Total'] = df_escalas_pag['Valor Serviço'] * 0.5

    st.session_state.df_pag_final = df_escalas_pag[['Data da Escala', 'Modo', 'Tipo de Servico', 'Servico', 'Veiculo', 'Motorista', 'Guia', 'Idioma', 'Adicional Passeio Motoguia', 
                                                      'Adicional Motoguia Após 20:00', 'Adicional Diária Motoguia TRF|APOIO', 'Valor Serviço', 'Valor Total']]

if 'df_pag_final' in st.session_state:

    st.header('Gerar Mapas')

    row2 = st.columns(2)

    with row2[0]:

        lista_guias = st.session_state.df_pag_final['Guia'].dropna().unique().tolist()

        guia = st.selectbox('Guia', sorted(lista_guias), index=None)

    if guia:

        row2_1 = st.columns(4)

        df_pag_guia = st.session_state.df_pag_final[st.session_state.df_pag_final['Guia']==guia].sort_values(by=['Data da Escala', 'Veiculo', 'Motorista']).reset_index(drop=True)

        df_data_correta = df_pag_guia.reset_index(drop=True)

        df_data_correta['Data da Escala'] = pd.to_datetime(df_data_correta['Data da Escala'])

        df_data_correta['Data da Escala'] = df_data_correta['Data da Escala'].dt.strftime('%d/%m/%Y')

        container_dataframe = st.container()

        container_dataframe.dataframe(df_data_correta, hide_index=True, use_container_width = True)

        with row2_1[0]:

            total_a_pagar = df_pag_guia['Valor Total'].sum()

            st.subheader(f'Valor Total: R${int(total_a_pagar)}')

        df_pag_guia['Data da Escala'] = pd.to_datetime(df_pag_guia['Data da Escala'])

        df_pag_guia['Data da Escala'] = df_pag_guia['Data da Escala'].dt.strftime('%d/%m/%Y')

        soma_servicos = df_pag_guia['Valor Total'].sum()

        soma_servicos = format_currency(soma_servicos, 'BRL', locale='pt_BR')

        for item in ['Adicional Passeio Motoguia', 'Adicional Motoguia Após 20:00', 'Adicional Diária Motoguia TRF|APOIO', 'Valor Serviço', 'Valor Total']:

            df_pag_guia[item] = df_pag_guia[item].apply(lambda x: format_currency(x, 'BRL', locale='pt_BR'))

        html = definir_html(df_pag_guia)

        nome_html = f'{guia}.html'

        criar_output_html(nome_html, html, guia, soma_servicos)

        with open(nome_html, "r", encoding="utf-8") as file:

            html_content = file.read()

        with row2_1[1]:

            st.download_button(
                label="Baixar Arquivo HTML",
                data=html_content,
                file_name=nome_html,
                mime="text/html"
            )

        st.session_state.html_content = html_content

    else:

        row2_1 = st.columns(4)

        with row2_1[0]:

            enviar_informes = st.button(f'Enviar Informes Gerais')

            if enviar_informes:

                puxar_aba_simples('1tsaBFwE3KS84r_I5-g3YGP7tTROe1lyuCw_UjtxofYI', 'Telefones Guias', 'df_telefones')

                lista_htmls = []

                lista_telefones = []

                for guia_ref in lista_guias:

                    telefone_guia = verificar_guia_sem_telefone('1tsaBFwE3KS84r_I5-g3YGP7tTROe1lyuCw_UjtxofYI', guia_ref, st.session_state.df_telefones['Guias'].unique().tolist())

                    df_pag_guia = st.session_state.df_pag_final[st.session_state.df_pag_final['Guia']==guia_ref].sort_values(by=['Data da Escala', 'Veiculo', 'Motorista']).reset_index(drop=True)

                    df_pag_guia['Data da Escala'] = pd.to_datetime(df_pag_guia['Data da Escala'])

                    df_pag_guia['Data da Escala'] = df_pag_guia['Data da Escala'].dt.strftime('%d/%m/%Y')

                    soma_servicos = df_pag_guia['Valor Total'].sum()

                    soma_servicos = format_currency(soma_servicos, 'BRL', locale='pt_BR')

                    for item in ['Adicional Passeio Motoguia', 'Adicional Motoguia Após 20:00', 'Adicional Diária Motoguia TRF|APOIO', 'Valor Serviço', 'Valor Total']:

                        df_pag_guia[item] = df_pag_guia[item].apply(lambda x: format_currency(x, 'BRL', locale='pt_BR'))

                    html = definir_html(df_pag_guia)

                    nome_html = f'{guia_ref}.html'

                    criar_output_html(nome_html, html, guia_ref, soma_servicos)

                    with open(nome_html, "r", encoding="utf-8") as file:

                        html_content_guia_ref = file.read()

                    lista_htmls.append([html_content_guia_ref, telefone_guia])

                webhook_thiago = "https://conexao.multiatend.com.br/webhook/pagamentolucknatal"

                payload = {"informe_html": lista_htmls}
                
                response = requests.post(webhook_thiago, json=payload)
                    
                if response.status_code == 200:
                    
                    st.success(f"Mapas de Pagamentos enviados com sucesso!")
                    
                else:
                    
                    st.error(f"Erro. Favor contactar o suporte")

                    st.error(f"{response}")

if 'html_content' in st.session_state and guia:

    with row2_1[2]:

        enviar_informes = st.button(f'Enviar Informes | {guia}')

    if enviar_informes:

        puxar_aba_simples('1tsaBFwE3KS84r_I5-g3YGP7tTROe1lyuCw_UjtxofYI', 'Telefones Guias', 'df_telefones')

        telefone_guia = verificar_guia_sem_telefone('1tsaBFwE3KS84r_I5-g3YGP7tTROe1lyuCw_UjtxofYI', guia, st.session_state.df_telefones['Guias'].unique().tolist())

        webhook_thiago = "https://conexao.multiatend.com.br/webhook/pagamentolucknatal"
        
        payload = {"informe_html": st.session_state.html_content, 
                    "telefone": telefone_guia}
        
        response = requests.post(webhook_thiago, json=payload)
            
        if response.status_code == 200:
            
            st.success(f"Mapas de Pagamento enviados com sucesso!")
            
        else:
            
            st.error(f"Erro. Favor contactar o suporte")

            st.error(f"{response}")

if inserir:

    df_escalas = st.session_state.df_escalas[(st.session_state.df_escalas['Data da Escala'] >= data_inicial) & (st.session_state.df_escalas['Data da Escala'] <= data_final)].reset_index(drop=True)

    lista_servicos = df_escalas['Guia'].dropna().unique().tolist()

    df_insercao = pd.DataFrame(columns=['Servico'], data=lista_servicos)

    inserir_info_sheets(df_insercao, 'Telefones Guias', '1tsaBFwE3KS84r_I5-g3YGP7tTROe1lyuCw_UjtxofYI')
