# Importações necessárias
from flask import (
    Flask, render_template, request, redirect, url_for, flash, Response
)
from flask_sqlalchemy import SQLAlchemy
import os
import csv  # Para Request 3: Importação CSV
import io   # Para ler o ficheiro CSV em memória

# Importação para Request 5: PDF
# Certifique-se de ter feito: pip install WeasyPrint

# --- PDF DESATIVADO TEMPORARIAMENTE PARA A NUVEM ---
# try:
#     import weasyprint
# except ImportError:
#     weasyprint = None
#     print("AVISO: WeasyPrint não instalado. Geração de PDF não irá funcionar.")
#     print("Execute: pip install WeasyPrint")
weasyprint = None # Garante que a variável existe como None
# --- FIM DA DESATIVAÇÃO ---

# --- 1. Configuração Inicial ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-segura-mude-depois'
db = SQLAlchemy(app)


# --- 2. Modelos do Banco de Dados (Request 2 ATUALIZADA) ---

class Veiculo(db.Model):
    """
    Modelo Veículo ATUALIZADO com potências AC e DC.
    """
    __tablename__ = 'veiculo'
    id = db.Column(db.Integer, primary_key=True)
    marca = db.Column(db.String(100), nullable=False)
    modelo = db.Column(db.String(100), nullable=False)
    capacidade_bateria_kwh = db.Column(db.Float, nullable=False)
    
    # Request 2: Potências AC e DC separadas
    potencia_max_carga_ac_kw = db.Column(db.Float, nullable=False, default=7.4)
    potencia_max_carga_dc_kw = db.Column(db.Float, nullable=False, default=0.0) # 0 se não suporta DC
    
    @property
    def nome_completo(self):
        dc_info = f"DC: {self.potencia_max_carga_dc_kw}kW" if self.potencia_max_carga_dc_kw > 0 else "DC: Não"
        return f"{self.marca} {self.modelo} ({self.capacidade_bateria_kwh} kWh | AC: {self.potencia_max_carga_ac_kw}kW | {dc_info})"

class Carregador(db.Model):
    """
    Modelo Carregador (Request 4 será implementada no form).
    """
    __tablename__ = 'carregador'
    id = db.Column(db.Integer, primary_key=True)
    marca = db.Column(db.String(100), nullable=False)
    modelo = db.Column(db.String(100), nullable=False)
    potencia_saida_kw = db.Column(db.Float, nullable=False)
    tipo_corrente = db.Column(db.String(20), default='AC', nullable=False) # AC ou DC
    preco = db.Column(db.Float, default=0.0)
    
    @property
    def nome_completo(self):
        return f"{self.marca} {self.modelo} ({self.potencia_saida_kw} kW {self.tipo_corrente})"

# --- CRIA AS TABELAS (SE NÃO EXISTIREM) ---
# Isto é seguro de executar; não apaga dados.
# Movido para aqui para funcionar na nuvem (produção).
with app.app_context():
    db.create_all()
# --- FIM DO BLOCO DE CRIAÇÃO ---

# --- 3. Lógica de Cálculo Central (Helper Function) ---

def calcular_relatorio_comparativo(veiculo_id, custo_kwh, recargas_mes):
    """
    Função central que executa toda a lógica de cálculo.
    Isso evita repetição de código entre a simulação web e o PDF.
    """
    
    veiculo = Veiculo.query.get(veiculo_id)
    carregadores_db = Carregador.query.all()
    
    # Cálculos de Custo (independentes do carregador)
    kwh_para_recarga = veiculo.capacidade_bateria_kwh * 0.60 # 20% a 80%
    custo_por_recarga = kwh_para_recarga * custo_kwh
    custo_mensal = custo_por_recarga * recargas_mes
    
    custos_gerais = {
        "custo_por_recarga": custo_por_recarga,
        "custo_mensal": custo_mensal,
        "custo_diario": custo_mensal / 30.0,
        "custo_anual": custo_mensal * 12.0
    }
    
    lista_de_resultados = []
    
    for carregador in carregadores_db:
        potencia_efetiva_kw = 0.0
        
        # --- A NOVA LÓGICA (Request 2) ---
        # Verifica o tipo de corrente e usa o limite correto do carro
        if carregador.tipo_corrente == 'AC':
            potencia_efetiva_kw = min(veiculo.potencia_max_carga_ac_kw, carregador.potencia_saida_kw)
        elif carregador.tipo_corrente == 'DC':
            potencia_efetiva_kw = min(veiculo.potencia_max_carga_dc_kw, carregador.potencia_saida_kw)
        
        # Se a potência efetiva for 0, o carregador é INCOMPATÍVEL (ex: DC em carro só AC).
        # Não o adicionamos ao relatório.
        if potencia_efetiva_kw <= 0:
            continue

        # Cálculo de Tempo
        tempo_recarga_horas = kwh_para_recarga / potencia_efetiva_kw
        
        # Cálculo de Custo-Benefício (R$ por kW efetivo)
        if carregador.preco > 0:
            custo_beneficio_reais_por_kw = carregador.preco / potencia_efetiva_kw
        else:
            custo_beneficio_reais_por_kw = float('inf') # Joga para o fim da lista
        
        lista_de_resultados.append({
            "carregador": carregador,
            "potencia_efetiva_kw": potencia_efetiva_kw,
            "tempo_recarga_horas": tempo_recarga_horas,
            "custo_beneficio_reais_por_kw": custo_beneficio_reais_por_kw
        })
            
    # Ordena a lista pelo custo-benefício (menor é melhor)
    resultados_comparativos = sorted(
        lista_de_resultados, 
        key=lambda x: x['custo_beneficio_reais_por_kw']
    )
    
    return veiculo, custos_gerais, resultados_comparativos


# --- 4. Rotas do Simulador (Request 5 ATUALIZADA) ---

@app.route('/')
def index():
    """ Página inicial agora é o simulador. """
    return redirect(url_for('simulador'))

@app.route('/simular', methods=['GET', 'POST'])
def simulador():
    """
    Página principal do simulador.
    GET: Mostra os formulários.
    POST: Calcula e mostra resultados OU gera PDF.
    """
    
    veiculos_db = Veiculo.query.order_by(Veiculo.marca, Veiculo.modelo).all()
    
    resultados_comparativos = None
    veiculo_selecionado = None
    custos_gerais = None
    custos_info = request.form # Mantém os valores do form

            
        # Se 'action' for 'simular', ele continua e renderiza a página normal
        # com os resultados (abaixo).

    return render_template(
        'simulador.html', 
        veiculos=veiculos_db, 
        veiculo_selecionado=veiculo_selecionado,
        custos_info=custos_info,
        custos_gerais=custos_gerais,
        resultados_comparativos=resultados_comparativos
    )


# --- 5. Rotas de Admin (Request 1, 3, 4 ATUALIZADAS) ---

@app.route('/admin')
def admin_dashboard():
    """ Request 1: Nova página principal do Admin """
    return render_template('admin_dashboard.html')

@app.route('/admin/veiculos')
def admin_veiculos():
    """ Request 1: Página dedicada para Veículos (AGORA COM LISTA) """
    veiculos = Veiculo.query.order_by(Veiculo.marca, Veiculo.modelo).all()
    return render_template('admin_veiculos.html', veiculos=veiculos)

@app.route('/admin/carregadores')
def admin_carregadores():
    """ Request 1: Página dedicada para Carregadores (AGORA COM LISTA) """
    carregadores = Carregador.query.order_by(Carregador.marca, Carregador.modelo).all()
    return render_template('admin_carregadores.html', carregadores=carregadores)

@app.route('/add_veiculo', methods=['POST'])
def add_veiculo():
    """ Adiciona um veículo (manual) e redireciona para a pág. de veículos """
    try:
        novo_veiculo = Veiculo(
            marca=request.form['marca'],
            modelo=request.form['modelo'],
            capacidade_bateria_kwh=float(request.form['capacidade_bateria_kwh']),
            # Request 2: Campos AC/DC
            potencia_max_carga_ac_kw=float(request.form['potencia_max_carga_ac_kw']),
            potencia_max_carga_dc_kw=float(request.form['potencia_max_carga_dc_kw'])
        )
        db.session.add(novo_veiculo)
        db.session.commit()
        flash(f"Veículo {novo_veiculo.marca} {novo_veiculo.modelo} cadastrado com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao cadastrar veículo: {e}", "error")
    
    return redirect(url_for('admin_veiculos'))

@app.route('/add_carregador', methods=['POST'])
def add_carregador():
    """ Adiciona um carregador (manual) e redireciona para a pág. de carregadores """
    try:
        novo_carregador = Carregador(
            marca=request.form['marca'],
            modelo=request.form['modelo'],
            potencia_saida_kw=float(request.form['potencia_saida_kw']),
            tipo_corrente=request.form['tipo_corrente'], # Request 4: Vem do <select>
            preco=float(request.form['preco'])
        )
        db.session.add(novo_carregador)
        db.session.commit()
        flash(f"Carregador {novo_carregador.marca} {novo_carregador.modelo} cadastrado com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao cadastrar carregador: {e}", "error")
    
    return redirect(url_for('admin_carregadores'))


# --- 6. Rotas de Importação CSV (Request 3) ---

@app.route('/admin/importar_veiculos', methods=['POST'])
def importar_veiculos():
    """ Request 3: Lógica de importação de CSV de Veículos """
    if 'csv_file' not in request.files:
        flash("Nenhum ficheiro enviado.", "error")
        return redirect(url_for('admin_veiculos'))
    
    file = request.files['csv_file']
    
    if file.filename == '':
        flash("Nenhum ficheiro selecionado.", "error")
        return redirect(url_for('admin_veiculos'))

    if file and file.filename.endswith('.csv'):
        try:
            # CORREÇÃO: 'latin-1' para Excel (PT) e delimiter=';'
            stream = io.TextIOWrapper(file.stream._file, 'latin-1')
            csv_reader = csv.DictReader(stream, delimiter=';')
            
            count = 0
            for row in csv_reader:
                veiculo = Veiculo(
                    marca=row['marca'],
                    modelo=row['modelo'],
                    capacidade_bateria_kwh=float(row['capacidade_bateria_kwh']),
                    potencia_max_carga_ac_kw=float(row['potencia_max_carga_ac_kw']),
                    potencia_max_carga_dc_kw=float(row['potencia_max_carga_dc_kw'])
                )
                db.session.add(veiculo)
                count += 1
            
            db.session.commit()
            flash(f"{count} veículos importados com sucesso!", "success")
        except Exception as e: # <-- O bloco 'except' está aqui, com a indentação correta
            db.session.rollback()
            flash(f"Erro ao processar o CSV: {e}. Verifique se as colunas estão corretas.", "error")
    else:
        flash("Ficheiro inválido. Por favor, envie um .csv.", "error")

    return redirect(url_for('admin_veiculos'))

@app.route('/admin/importar_carregadores', methods=['POST'])
def importar_carregadores():
    """ Request 3: Lógica de importação de CSV de Carregadores """
    if 'csv_file' not in request.files:
        flash("Nenhum ficheiro enviado.", "error")
        return redirect(url_for('admin_carregadores'))
    
    file = request.files['csv_file']
    
    if file.filename == '':
        flash("Nenhum ficheiro selecionado.", "error")
        return redirect(url_for('admin_carregadores'))

    if file and file.filename.endswith('.csv'):
        try:
            # CORREÇÃO: 'latin-1' para Excel (PT) e delimiter=';'
            stream = io.TextIOWrapper(file.stream._file, 'latin-1')
            csv_reader = csv.DictReader(stream, delimiter=';')
            
            count = 0
            for row in csv_reader:
                carregador = Carregador(
                    marca=row['marca'],
                    modelo=row['modelo'],
                    potencia_saida_kw=float(row['potencia_saida_kw']),
                    tipo_corrente=row['tipo_corrente'], # Deve ser 'AC' ou 'DC'
                    preco=float(row['preco'])
                )
                db.session.add(carregador)
                count += 1
            
            db.session.commit()
            flash(f"{count} carregadores importados com sucesso!", "success")
        except Exception as e: # <-- O bloco 'except' está aqui, com a indentação correta
            db.session.rollback()
            flash(f"Erro ao processar o CSV: {e}. Verifique as colunas (tipo_corrente deve ser AC ou DC).", "error")
    else:
        flash("Ficheiro inválido. Por favor, envie um .csv.", "error")

    return redirect(url_for('admin_carregadores'))
# --- 7. Rotas de Edição (NOVA FUNCIONALIDADE) ---

@app.route('/admin/veiculo/<int:veiculo_id>/editar', methods=['GET', 'POST'])
def editar_veiculo(veiculo_id):
    """
    Página de Edição de um Veículo específico.
    GET: Mostra o formulário com os dados atuais.
    POST: Salva as alterações no banco de dados.
    """
    # 1. Busca o veículo no BD ou retorna um erro 404 (Não Encontrado)
    veiculo = Veiculo.query.get_or_404(veiculo_id)
    
    # 2. Se o formulário foi ENVIADO (POST)
    if request.method == 'POST':
        try:
            # 3. Atualiza os dados do objeto 'veiculo' com os dados do formulário
            veiculo.marca = request.form['marca']
            veiculo.modelo = request.form['modelo']
            veiculo.capacidade_bateria_kwh = float(request.form['capacidade_bateria_kwh'])
            veiculo.potencia_max_carga_ac_kw = float(request.form['potencia_max_carga_ac_kw'])
            veiculo.potencia_max_carga_dc_kw = float(request.form['potencia_max_carga_dc_kw'])
            
            # 4. Salva (commit) as alterações na sessão do BD
            db.session.commit()
            flash(f"Veículo '{veiculo.nome_completo}' atualizado com sucesso!", "success")
        except Exception as e:
            db.session.rollback() # Desfaz em caso de erro
            flash(f"Erro ao atualizar veículo: {e}", "error")
            
        # 5. Redireciona de volta para a lista principal
        return redirect(url_for('admin_veiculos'))
    
    # 6. Se o formulário foi apenas REQUISITADO (GET)
    # Mostra o template de edição, passando o veículo que queremos editar
    return render_template('editar_veiculo.html', veiculo=veiculo)


@app.route('/admin/carregador/<int:carregador_id>/editar', methods=['GET', 'POST'])
def editar_carregador(carregador_id):
    """
    Página de Edição de um Carregador específico. (Sua Solicitação)
    """
    carregador = Carregador.query.get_or_404(carregador_id)
    
    if request.method == 'POST':
        try:
            # Atualiza os dados (especialmente o preço!)
            carregador.marca = request.form['marca']
            carregador.modelo = request.form['modelo']
            carregador.potencia_saida_kw = float(request.form['potencia_saida_kw'])
            carregador.tipo_corrente = request.form['tipo_corrente'] # Vem do <select>
            carregador.preco = float(request.form['preco']) # O campo que você queria editar!
            
            db.session.commit()
            flash(f"Carregador '{carregador.nome_completo}' atualizado com sucesso!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao atualizar carregador: {e}", "error")
            
        return redirect(url_for('admin_carregadores'))
    
    # GET: Mostra o formulário de edição com os dados atuais
    return render_template('editar_carregador.html', carregador=carregador)

# --- 7. Execução da Aplicação ---
if __name__ == '__main__':
                
    app.run(debug=True, port=5000)
